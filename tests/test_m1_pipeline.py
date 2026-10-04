import json

import pytest

from app.languages import answers, conditions, languages, symptoms
from app.pipeline import extract
from app.pipeline.answer import render_answer
from app.pipeline.match import match


def flags(**kw):
    return {k: kw.get(k, 0) for k in symptoms()}


def seed_profiles():
    from app.languages import profiles

    return list(profiles().items())


# ---------- match (required unit tests) ----------

def test_rust():
    r = match(flags(orange_powder_under_leaf=1, yellow_spots_on_leaf=1), seed_profiles())
    assert r.result == "leaf_rust"
    assert r.score == 1.0


def test_all_no_is_healthy():
    r = match({k: -1 for k in symptoms()}, seed_profiles())
    assert r.result == "healthy"


def test_too_few_symptoms():
    r = match(flags(orange_powder_under_leaf=1), seed_profiles())
    assert (r.result, r.not_sure_reason) == ("not_sure", "too_few_symptoms")


def test_ambiguous():
    r = match(flags(orange_powder_under_leaf=1, small_hole_in_berry=1), seed_profiles())
    assert r.result == "not_sure"
    assert r.not_sure_reason in ("too_close", "weak_match")
    assert len(r.top2) == 2


def test_verified_case_resolves_ambiguity():
    vec = flags(orange_powder_under_leaf=1, small_hole_in_berry=1)
    kb = seed_profiles() + [("berry_borer", vec)]
    r = match(vec, kb)
    assert r.result == "berry_borer"


# ---------- answers ----------

@pytest.mark.parametrize("lang", list(languages()))
def test_every_condition_has_answer(lang):
    table = answers(lang)
    for key in conditions() + ["not_sure", "prompt_welcome", "prompt_consent", "prompt_describe",
                               "prompt_wait", "goodbye", "sms_privacy", "prompt_invalid"]:
        assert key in table and table[key]["text"].strip(), f"{lang}:{key}"


@pytest.mark.parametrize("lang", list(languages()))
def test_no_percentages_in_answers(lang):
    assert "%" not in json.dumps(answers(lang), ensure_ascii=False)


def test_render_answer():
    a = render_answer("leaf_rust", "sw")
    assert "kutu" in a.text
    assert render_answer("bogus", "sw").key == "not_sure"


# ---------- extraction (LLM mocked) ----------

def test_schema_requires_all_keys():
    s = extract.json_schema()
    assert set(s["required"]) == set(symptoms())
    assert all(p["enum"] == [-1, 0, 1] for p in s["properties"].values())


def test_extract_parses_and_strips_think(monkeypatch):
    out = flags(orange_powder_under_leaf=1)
    monkeypatch.setattr(extract, "_chat", lambda m, s, p=None: "<think>hmm</think>" + json.dumps(out))
    assert extract.extract_parameters("x", "sw") == out


def test_extract_retries_then_fails(monkeypatch):
    calls = []

    def bad(m, s, p=None):
        calls.append(1)
        return '{"orange_powder_under_leaf": 5}'

    monkeypatch.setattr(extract, "_chat", bad)
    with pytest.raises(extract.ExtractionError):
        extract.extract_parameters("x", "sw")
    assert len(calls) == 2


def test_fewshot_in_prompt():
    msgs = extract.build_messages("hello")
    assert msgs[0]["role"] == "system" and "orange_powder_under_leaf" in msgs[0]["content"]
    from app.languages import fewshot

    n_examples = sum(len(v) for v in fewshot().values())
    assert len(msgs) == 1 + 2 * n_examples + 1


# ---------- run_case ----------

def test_run_case_text_rust(db, monkeypatch):
    from app.cases import create_case
    from app.pipeline.run import run_case

    monkeypatch.setattr(extract, "_chat",
                        lambda m, s, p=None: json.dumps(flags(orange_powder_under_leaf=1, yellow_spots_on_leaf=1)))
    case = create_case(db, "demo", "sw", transcript="Majani yana unga wa machungwa chini na madoa ya njano.")
    case = run_case(case.id, db)
    assert (case.result, case.status) == ("leaf_rust", "answered")


def test_run_case_extraction_failed(db, monkeypatch):
    from app.cases import create_case
    from app.pipeline.run import run_case

    monkeypatch.setattr(extract, "_chat", lambda m, s, p=None: "not json")
    case = run_case(create_case(db, "demo", "sw", transcript="abc").id, db)
    assert (case.result, case.status, case.not_sure_reason) == ("not_sure", "in_review", "extraction_failed")
