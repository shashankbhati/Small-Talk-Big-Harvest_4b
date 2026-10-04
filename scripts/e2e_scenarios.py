"""Live end-to-end scenarios against the real configured models (Together primary, local fallback).

    python scripts/e2e_scenarios.py

Runs the FastAPI app in-process with a throwaway database and checks every user-facing flow:
demo text/voice, SMS, the phone (IVR) flow, the expert feedback loop, privacy, and a simulated
Together outage. Writes eval/scenarios.json (read by scripts/report.py).
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = f"sqlite:///{(ROOT / 'data' / 'e2e_scenarios.db').as_posix()}"
os.environ["AUDIO_DIR"] = str(ROOT / "data" / "e2e_audio")
os.environ["TWILIO_VALIDATE"] = "false"
os.environ["REVIEW_USER"] = "expert"
os.environ["REVIEW_PASSWORD"] = "e2e"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.models import Case, KnowledgeProfile  # noqa: E402
from scripts.seed_db import seed  # noqa: E402

CLIPS = ROOT / "eval" / "clips"
AUTH = ("expert", "e2e")
PHONE = "+254700123456"
RUST = {
    "sw": "Majani yangu yana madoa madogo ya njano juu, na chini kuna unga wa rangi ya machungwa.",
    "ar": "على أوراق البن بقع صفراء صغيرة من الأعلى، ومسحوق برتقالي تحت الورقة.",
    "hi": "पत्तियों के ऊपर छोटे पीले धब्बे हैं और नीचे नारंगी पाउडर है।",
}
RUST_WORD = {"sw": "kutu", "ar": "صدأ", "hi": "रतुआ"}

results: list[dict] = []


def scenario(name: str):
    def deco(fn):
        def run(client):
            t0 = time.time()
            try:
                detail = fn(client)
                status = "PASS"
            except AssertionError as e:
                status, detail = "FAIL", str(e) or "assertion failed"
            except Exception as e:  # noqa: BLE001
                status, detail = "ERROR", f"{type(e).__name__}: {e}"
                traceback.print_exc()
            results.append({"scenario": name, "status": status, "seconds": round(time.time() - t0, 1),
                            "detail": detail})
            print(f"[{status}] {name} ({time.time() - t0:.1f}s): {detail}")
        return run
    return deco


def last_case() -> Case:
    with SessionLocal() as s:
        return s.scalars(select(Case).order_by(Case.created_at.desc())).first()


def post_demo(client, **data) -> Case:
    files = None
    if "audio" in data:
        p = data.pop("audio")
        files = {"audio": (p.name, p.read_bytes(), "audio/mpeg")}
    r = client.post("/demo", data=data, files=files)
    assert r.status_code == 200, f"HTTP {r.status_code}"
    return last_case()


@scenario("Health check: all model backends reachable")
def s_health(client):
    h = client.get("/health?deep=true").json()
    t, o, w = h["stt"]["together"]["ok"], h["llm"]["ollama"]["ok"], h["stt"]["local"]["ok"]
    assert t and o and w, f"together={t} ollama={o} local_whisper={w}"
    return "Together, Ollama (gemma3:4b) and local Whisper all available"


def make_text_scenario(lang):
    @scenario(f"Demo text ({lang}): leaf rust description → leaf rust answer in {lang}")
    def s(client):
        c = post_demo(client, lang=lang, text=RUST[lang], consent="answer_only")
        assert c.result == "leaf_rust", f"got {c.result} ({c.not_sure_reason})"
        from app.pipeline.answer import render_answer

        assert RUST_WORD[lang] in render_answer(c.result, lang).text
        return f"leaf_rust, score {c.score}, LLM={c.llm_provider}"
    return s


@scenario("Demo voice (sw, consent=answer_only): audio → leaf rust, audio deleted")
def s_voice_sw(client):
    c = post_demo(client, lang="sw", consent="answer_only", audio=CLIPS / "sw_rust.mp3")
    assert c.result == "leaf_rust", f"got {c.result} ({c.not_sure_reason})"
    assert c.audio_path is None, "audio was not deleted"
    return f"leaf_rust, ASR conf {c.asr_confidence}, STT={c.stt_provider}, LLM={c.llm_provider}, audio deleted"


@scenario("Demo voice (ar, consent=keep): audio → leaf rust, audio kept")
def s_voice_ar(client):
    c = post_demo(client, lang="ar", consent="keep_for_training", audio=CLIPS / "ar_rust.mp3")
    assert c.result == "leaf_rust", f"got {c.result} ({c.not_sure_reason})"
    assert c.audio_path, "audio should be kept"
    return f"leaf_rust, ASR conf {c.asr_confidence}, audio stored"


@scenario("SMS (Arabic): Arabic reply, privacy line only on first contact")
def s_sms(client):
    body = "أوراق البن عليها بقع صفراء ومسحوق برتقالي تحت الورقة"
    r1 = client.post("/sms/incoming", data={"From": PHONE, "Body": body}).text
    r2 = client.post("/sms/incoming", data={"From": PHONE, "Body": body}).text
    assert "صدأ" in r1, "no Arabic rust answer"
    assert "رقمك محمي" in r1 and "رقمك محمي" not in r2, "privacy line rule broken"
    return "Arabic leaf-rust reply; privacy notice on first SMS only"


@scenario("Phone (IVR): call → Arabic → consent → recording → answer played")
def s_ivr(client):
    from app.audio import save_upload
    from app.routes import voice

    def fake_download(case_id, url, sid):  # stands in for downloading the Twilio recording
        key = save_upload((CLIPS / "ar_rust.mp3").read_bytes(), ".mp3")
        with SessionLocal() as s:
            s.get(Case, case_id).audio_path = key
            s.commit()

    orig = voice._download_and_store
    voice._download_and_store = fake_download
    try:
        assert "<Gather" in client.post("/voice/incoming", data={"From": PHONE}).text
        cid = last_case().id
        client.post(f"/voice/language?case_id={cid}", data={"Digits": "2"})
        assert "<Record" in client.post(f"/voice/consent?case_id={cid}", data={"Digits": "2"}).text
        client.post(f"/voice/recorded?case_id={cid}", data={"RecordingUrl": "https://x/rec", "RecordingSid": "RE1"})
        twiml = ""
        for n in range(1, get_settings().voice_max_tries + 1):
            twiml = client.post(f"/voice/result?case_id={cid}&try={n}").text
            if "<Hangup" in twiml:
                break
    finally:
        voice._download_and_store = orig
    with SessionLocal() as s:
        c = s.get(Case, cid)
    assert "leaf_rust.mp3" in twiml or "صدأ" in twiml, f"answer not played (result={c.result})"
    assert c.audio_path is None, "answer_only audio not deleted"
    return f"leaf_rust played in Arabic, consent=answer_only → audio deleted"


@scenario("Feedback loop: not-sure case labeled by expert → same input now answered")
def s_feedback(client):
    text = "Kuna unga wa rangi ya machungwa chini ya majani, na kuna matundu madogo kwenye buni."
    c = post_demo(client, lang="sw", text=text)
    assert c.result == "not_sure", f"expected not_sure first, got {c.result}"
    assert c.id in client.get("/review", auth=AUTH).text, "case not in review queue"
    form = {"expert_label": "berry_borer", "reviewed_by": "e2e officer"}
    form.update({f"p_{k}": str(v) for k, v in (c.parameters or {}).items()})
    assert client.post(f"/review/{c.id}", data=form, auth=AUTH, follow_redirects=False).status_code == 303
    c2 = post_demo(client, lang="sw", text=text)
    assert c2.result == "berry_borer", f"after labeling got {c2.result}"
    with SessionLocal() as s:
        n = len(s.scalars(select(KnowledgeProfile).where(KnowledgeProfile.source == "verified_case")).all())
    return f"not_sure ({c.not_sure_reason}) → labeled berry_borer → answered berry_borer; {n} verified case in KB"


@scenario("Review page requires login")
def s_auth(client):
    assert client.get("/review").status_code == 401
    assert client.get("/review", auth=("expert", "wrong")).status_code == 401
    return "401 without / with wrong credentials"


@scenario("Privacy: phone number never stored in plain text; key 9 deletes caller data")
def s_privacy(client):
    with SessionLocal() as s:
        rows = s.scalars(select(Case).where(Case.phone_hash.is_not(None))).all()
        assert rows and all(PHONE not in (r.phone_encrypted or "") and PHONE != r.phone_hash for r in rows)
        n_before = len(rows)
    client.post("/voice/incoming", data={"From": PHONE})
    client.post(f"/voice/language?case_id={last_case().id}", data={"Digits": "9"})
    with SessionLocal() as s:
        left = s.scalars(select(Case).where(Case.phone_hash.is_not(None))).all()
    assert not left, f"{len(left)} cases left after delete-my-data"
    return f"{n_before} cases with hashed/encrypted numbers; all deleted via key 9"


def make_outage_scenario(kind):
    @scenario(f"Together outage → local fallback ({kind})")
    def s(client):
        st = get_settings()
        orig = st.together_url
        st.together_url = "http://127.0.0.1:9/v1"  # unreachable, like Wi-Fi off
        try:
            if kind == "text":
                c = post_demo(client, lang="sw", text=RUST["sw"])
            else:
                c = post_demo(client, lang="sw", consent="answer_only", audio=CLIPS / "sw_rust.mp3")
        finally:
            st.together_url = orig
        assert c.result == "leaf_rust", f"got {c.result} ({c.not_sure_reason})"
        assert c.llm_provider == "ollama", f"LLM={c.llm_provider}"
        if kind == "voice":
            assert c.stt_provider == "local", f"STT={c.stt_provider}"
        return f"leaf_rust via STT={c.stt_provider}, LLM={c.llm_provider}"
    return s


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    Base.metadata.drop_all(engine)
    init_db()
    seed()
    from app.main import app

    steps = [s_health] + [make_text_scenario(lang) for lang in RUST] + [
        s_voice_sw, s_voice_ar, s_sms, s_ivr, s_feedback, s_auth, s_privacy,
        make_outage_scenario("text"), make_outage_scenario("voice")]
    with TestClient(app) as client:
        for step in steps:
            step(client)
    Base.metadata.drop_all(engine)
    engine.dispose()
    (ROOT / "data" / "e2e_scenarios.db").unlink(missing_ok=True)

    out = {"run_at": time.strftime("%Y-%m-%d %H:%M"), "scenarios": results}
    (ROOT / "eval" / "scenarios.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(r["status"] == "PASS" for r in results)
    print(f"{passed}/{len(results)} scenarios passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
