import json
from datetime import date, timedelta

from app.languages import symptoms
from app.pipeline import calllog, extract


def _rows():
    rows = []
    for f in sorted(calllog.log_dir().glob("model_calls-*.jsonl")):
        rows += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()]
    return rows


def _clear():
    for f in calllog.log_dir().glob("model_calls-*.jsonl"):
        f.unlink()


def test_demo_logs_llm_call_and_case(client, monkeypatch):
    _clear()
    flags = {k: 0 for k in symptoms()}
    flags["orange_powder_under_leaf"] = 1
    monkeypatch.setattr(extract, "_chat", lambda m, s, p=None: json.dumps(flags))
    client.post("/demo", data={"lang": "hi", "mode": "local", "text": "पत्तियों के नीचे नारंगी पाउडर"})

    rows = _rows()
    llm = next(r for r in rows if r["event"] == "llm")
    assert llm["provider"] == "ollama" and llm["mode"] == "local" and llm["ok"] is True
    assert llm["input"]["text"] == "पत्तियों के नीचे नारंगी पाउडर" and llm["input"]["language"] == "hi"
    assert json.loads(llm["output"]["raw"])["orange_powder_under_leaf"] == 1
    assert isinstance(llm["latency_ms"], int)

    case = next(r for r in rows if r["event"] == "case")
    assert case["case_id"] == llm["case_id"] and case["language"] == "hi"
    assert case["llm_provider"] == "ollama" and case["input"] == "text" and "result" in case


def test_failed_call_is_logged(client, monkeypatch):
    _clear()

    def boom(m, s, p=None):
        raise extract.ProviderUnavailable("no key")

    monkeypatch.setattr(extract, "_chat", boom)
    client.post("/demo", data={"lang": "ar", "mode": "together", "text": "بقع على الأوراق"})
    llm = next(r for r in _rows() if r["event"] == "llm")
    assert llm["provider"] == "together" and llm["ok"] is False and "no key" in llm["error"]


def test_cleanup_removes_old_logs():
    d = calllog.log_dir()
    d.mkdir(parents=True, exist_ok=True)
    old = d / f"model_calls-{(date.today() - timedelta(days=400)).isoformat()}.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    assert calllog.cleanup(365) >= 1 and not old.exists()
