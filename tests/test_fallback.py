"""Retry + local fallback for hosted models."""
import json

import httpx
import pytest

from app.config import get_settings
from app.languages import symptoms
from app.pipeline import extract, resilience, stt

RUST_SW = "Majani yana madoa ya njano juu na unga wa rangi ya machungwa chini."
RUST = {k: 0 for k in symptoms()} | {"orange_powder_under_leaf": 1, "yellow_spots_on_leaf": 1}


def http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://api.together.xyz/v1/x")
    return httpx.HTTPStatusError("err", request=req, response=httpx.Response(status, request=req))


@pytest.fixture()
def chains(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_fallback", "ollama")
    monkeypatch.setattr(s, "stt_fallback", "local")
    monkeypatch.setattr(s, "together_retries", 1)
    monkeypatch.setattr(resilience.time, "sleep", lambda _s: None)
    return s


# ---------- retry policy ----------

def test_transient_classification():
    assert resilience.is_transient(httpx.ReadTimeout("t"))
    assert resilience.is_transient(httpx.ConnectError("c"))
    assert resilience.is_transient(http_error(429)) and resilience.is_transient(http_error(503))
    assert not resilience.is_transient(http_error(401)) and not resilience.is_transient(http_error(400))


def test_with_retry_recovers(monkeypatch):
    monkeypatch.setattr(resilience.time, "sleep", lambda _s: None)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("t")
        return "ok"

    assert resilience.with_retry(flaky, 1, "x") == "ok" and len(calls) == 2


def test_with_retry_does_not_retry_auth_errors():
    calls = []

    def unauthorized():
        calls.append(1)
        raise http_error(401)

    with pytest.raises(httpx.HTTPStatusError):
        resilience.with_retry(unauthorized, 3, "x")
    assert len(calls) == 1


# ---------- LLM ----------

def test_llm_retries_together_then_succeeds(chains, monkeypatch):
    calls = []

    def chat(m, s, p):
        calls.append(p)
        if len(calls) == 1:
            raise httpx.ReadTimeout("t")
        return json.dumps(RUST)

    monkeypatch.setattr(extract, "_chat", chat)
    flags = extract.extract_parameters("x")
    assert flags == RUST and flags.provider == "together" and calls == ["together", "together"]


def test_llm_falls_back_to_ollama(chains, monkeypatch):
    calls = []

    def chat(m, s, p):
        calls.append(p)
        if p == "together":
            raise http_error(503)
        return json.dumps(RUST)

    monkeypatch.setattr(extract, "_chat", chat)
    flags = extract.extract_parameters("x")
    assert flags.provider == "ollama"
    assert calls == ["together", "together", "ollama"]  # 1 retry, then fallback


def test_llm_missing_key_goes_straight_to_fallback(chains, monkeypatch):
    monkeypatch.setattr(chains, "together_api_key", "")
    seen = []
    monkeypatch.setattr(extract, "_chat_ollama", lambda m, s: seen.append(1) or json.dumps(RUST))
    monkeypatch.setitem(extract._PROVIDERS, "ollama", extract._chat_ollama)
    assert extract.extract_parameters("x").provider == "ollama" and seen == [1]


def test_llm_all_fail_raises(chains, monkeypatch):
    def chat(m, s, p):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(extract, "_chat", chat)
    with pytest.raises(extract.ExtractionError):
        extract.extract_parameters("x")


def test_run_case_records_llm_provider_and_not_sure_when_all_fail(db, chains, monkeypatch):
    from app.cases import create_case
    from app.pipeline.run import run_case

    monkeypatch.setattr(extract, "_chat", lambda m, s, p: (_ for _ in ()).throw(httpx.ConnectError("x"))
                        if p == "together" else json.dumps(RUST))
    case = run_case(create_case(db, "demo", "sw", transcript=RUST_SW).id, db)
    assert (case.result, case.llm_provider) == ("leaf_rust", "ollama")

    monkeypatch.setattr(extract, "_chat", lambda m, s, p: (_ for _ in ()).throw(httpx.ConnectError("x")))
    case = run_case(create_case(db, "demo", "sw", transcript="unga").id, db)
    assert (case.result, case.not_sure_reason) == ("not_sure", "extraction_failed")


# ---------- STT ----------

def test_stt_falls_back_to_local(chains, monkeypatch):
    calls = []

    def together(path, lang):
        calls.append("together")
        raise httpx.ConnectError("offline")

    def local(path, lang):
        calls.append("local")
        return "majani", "sw", 0.9

    monkeypatch.setitem(stt._PROVIDERS, "together", together)
    monkeypatch.setitem(stt._PROVIDERS, "local", local)
    res = stt.transcribe("a.ogg", "sw")
    text, lang, conf = res
    assert (text, conf, res.provider) == ("majani", 0.9, "local")
    assert calls == ["together", "together", "local"]


def test_stt_all_fail_raises(chains, monkeypatch):
    def down(path, lang):
        raise httpx.ConnectError("x")

    monkeypatch.setitem(stt._PROVIDERS, "together", down)
    monkeypatch.setitem(stt._PROVIDERS, "local", down)
    with pytest.raises(httpx.ConnectError):
        stt.transcribe("a.ogg", "sw")


def test_add_missing_columns_migration(tmp_path):
    """An old DB without the new provider columns is upgraded in place."""
    from sqlalchemy import create_engine, inspect, text

    from app import db as dbmod

    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE cases (id VARCHAR(36) PRIMARY KEY, channel VARCHAR(10))"))
    old = dbmod.engine
    dbmod.engine = eng
    try:
        dbmod._add_missing_columns()
    finally:
        dbmod.engine = old
    cols = {c["name"] for c in inspect(eng).get_columns("cases")}
    assert {"stt_provider", "llm_provider", "transcript"} <= cols
