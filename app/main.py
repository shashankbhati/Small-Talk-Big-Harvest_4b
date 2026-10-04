"""FastAPI server: Twilio voice webhooks + test API + officer dashboard.

Run:  uvicorn app.main:app --port 8000
Then expose with ngrok and set the Twilio number's voice webhook to  <BASE_URL>/voice  (HTTP POST).
"""
import html
import json
import threading
import traceback
import uuid
from pathlib import Path

import requests
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from twilio.twiml.voice_response import Gather, VoiceResponse

from . import config, db
from .classifier import load_kb
from .pipeline import run_pipeline
from .prompts import PROMPTS

app = FastAPI(title="Coffee voice advisor")
app.mount("/static", StaticFiles(directory=config.ROOT / "static"), name="static")

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
MAX_POLLS = 30  # ~60 seconds of waiting before giving up


@app.on_event("startup")
def startup() -> None:
    db.init_db()

    def _warm():
        try:
            from .asr import warm_up
            warm_up()
            print("[startup] Whisper model loaded")
        except Exception as e:  # server still works for /api/text
            print(f"[startup] Whisper not loaded: {e}")

    threading.Thread(target=_warm, daemon=True).start()


# ---------------- helpers ----------------
def say_or_play(vr, key: str) -> None:
    """Play the recorded clip for `key` if it exists, otherwise read the text."""
    clip = config.AUDIO_DIR / f"{key}.mp3"
    if clip.exists():
        vr.play(f"{config.BASE_URL}/static/audio/{key}.mp3")
        return
    text = PROMPTS.get(key) or load_kb()["advice"].get(key, key)
    vr.say(text)


def twiml(vr: VoiceResponse) -> Response:
    return Response(content=str(vr), media_type="application/xml")


def _process_recording(call_sid: str, recording_url: str, recording_sid: str, phone: str) -> None:
    from .asr import transcribe

    tmp = config.TMP_DIR / f"{uuid.uuid4().hex}.wav"
    try:
        r = requests.get(
            f"{recording_url}.wav",
            auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
            timeout=30,
        )
        r.raise_for_status()
        tmp.write_bytes(r.content)
        asr = transcribe(str(tmp))
        farmer = db.get_or_create_farmer(phone)
        out = run_pipeline(asr["text"], farmer)
        out["asr"] = asr
        print(f"[call {call_sid}] {json.dumps(out, default=str)[:1500]}")
        with JOBS_LOCK:
            JOBS[call_sid] = {"status": "done", "output": out}
    except Exception:
        traceback.print_exc()
        with JOBS_LOCK:
            JOBS[call_sid] = {"status": "error"}
    finally:
        # Privacy: no voice is kept, locally or at Twilio.
        tmp.unlink(missing_ok=True)
        if config.DELETE_RECORDINGS and recording_sid:
            try:
                requests.delete(
                    f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}"
                    f"/Recordings/{recording_sid}.json",
                    auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN),
                    timeout=15,
                )
            except Exception:
                traceback.print_exc()


# ---------------- Twilio voice flow ----------------
@app.post("/voice")
def voice(From: str = Form("")):
    farmer = db.get_or_create_farmer(From)
    vr = VoiceResponse()
    if farmer.get("consent_service"):
        vr.redirect("/describe", method="POST")
        return twiml(vr)
    g = Gather(num_digits=1, action="/consent", method="POST", timeout=8)
    say_or_play(g, "welcome_consent")
    vr.append(g)
    say_or_play(vr, "no_consent")
    vr.hangup()
    return twiml(vr)


@app.post("/consent")
def consent(From: str = Form(""), Digits: str = Form("")):
    vr = VoiceResponse()
    if Digits == "1":
        db.set_consent(From, service=True)
        g = Gather(num_digits=1, action="/consent-improve", method="POST", timeout=8)
        say_or_play(g, "consent_improve")
        vr.append(g)
        vr.redirect("/describe", method="POST")  # no answer = no data sharing
    elif Digits == "9":
        db.delete_farmer_data(From)
        say_or_play(vr, "deleted")
        vr.hangup()
    else:
        say_or_play(vr, "no_consent")
        vr.hangup()
    return twiml(vr)


@app.post("/consent-improve")
def consent_improve(From: str = Form(""), Digits: str = Form("")):
    db.set_consent(From, improve=(Digits == "1"))
    vr = VoiceResponse()
    vr.redirect("/describe", method="POST")
    return twiml(vr)


@app.post("/describe")
def describe():
    vr = VoiceResponse()
    say_or_play(vr, "describe")
    vr.record(
        max_length=30,
        timeout=4,
        play_beep=True,
        trim="trim-silence",
        finish_on_key="#",
        action="/recorded",
        method="POST",
    )
    say_or_play(vr, "no_input")
    vr.hangup()
    return twiml(vr)


@app.post("/recorded")
def recorded(
    CallSid: str = Form(""),
    From: str = Form(""),
    RecordingUrl: str = Form(""),
    RecordingSid: str = Form(""),
):
    with JOBS_LOCK:
        JOBS[CallSid] = {"status": "pending", "polls": 0}
    threading.Thread(
        target=_process_recording, args=(CallSid, RecordingUrl, RecordingSid, From), daemon=True
    ).start()
    vr = VoiceResponse()
    say_or_play(vr, "please_wait")
    vr.redirect("/result", method="POST")
    return twiml(vr)


@app.post("/result")
def result(CallSid: str = Form("")):
    vr = VoiceResponse()
    with JOBS_LOCK:
        job = JOBS.get(CallSid, {"status": "error"})
        if job["status"] == "pending":
            job["polls"] = job.get("polls", 0) + 1
            if job["polls"] > MAX_POLLS:
                job = {"status": "error"}
    if job["status"] == "pending":
        vr.pause(length=2)
        vr.redirect("/result", method="POST")
    elif job["status"] == "done":
        say_or_play(vr, job["output"]["response_key"])
        say_or_play(vr, "goodbye")
        vr.hangup()
    else:
        say_or_play(vr, "error")
        vr.hangup()
    return twiml(vr)


# ---------------- Test API (no phone needed) ----------------
@app.post("/api/text")
async def api_text(request: Request):
    """Body: {"text": "...", "phone": "+49..."} -> full pipeline output."""
    body = await request.json()
    farmer = db.get_or_create_farmer(body.get("phone", "test-user"))
    return JSONResponse(run_pipeline(body.get("text", ""), farmer))


@app.post("/api/audio")
async def api_audio(file: UploadFile = File(...), phone: str = Form("test-user")):
    """Upload an audio file (wav/mp3/m4a/ogg) -> transcript + pipeline output."""
    from .asr import transcribe

    tmp = config.TMP_DIR / f"{uuid.uuid4().hex}{Path(file.filename or '').suffix or '.wav'}"
    tmp.write_bytes(await file.read())
    try:
        asr = transcribe(str(tmp))
    finally:
        tmp.unlink(missing_ok=True)
    out = run_pipeline(asr["text"], db.get_or_create_farmer(phone))
    out["asr"] = asr
    return JSONResponse(out)


@app.post("/api/confirm/{case_id}")
def api_confirm(case_id: int, label: str = Form(...), by: str = Form("officer")):
    db.confirm_case(case_id, label, by)
    return HTMLResponse('<meta http-equiv="refresh" content="0; url=/dashboard">')


# ---------------- Extension officer dashboard ----------------
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    kb = load_kb()
    options = "".join(f'<option value="{k}">{html.escape(v["label"])}</option>' for k, v in kb["problems"].items())
    rows = []
    for c in db.list_cases(200):
        ranking = json.loads(c["ranking"] or "[]")[:3]
        top3 = "<br>".join(f'{html.escape(r["label"])}: {r["p"]:.0%}' for r in ranking)
        feats = json.loads(c["features"] or "{}")
        feats_s = ", ".join(f"{k}={v}" for k, v in feats.items() if v != "unknown")
        badge = "#1f7a4d" if c["decision"] == "confident" else "#b45309"
        confirm = (
            f'<b>{html.escape(c["confirmed_label"])}</b> ({html.escape(c["confirmed_by"] or "")})'
            if c["confirmed_label"]
            else f'<form method="post" action="/api/confirm/{c["id"]}"><select name="label">{options}</select>'
                 f'<button>Confirm</button></form>'
        )
        rows.append(
            f'<tr><td>{c["id"]}</td><td>{html.escape(c["created_at"] or "")}</td>'
            f'<td>{html.escape(c["village"] or "")}{" (synthetic)" if c["synthetic"] else ""}</td>'
            f'<td>{html.escape(feats_s)}</td><td>{top3}</td>'
            f'<td><span style="color:{badge};font-weight:600">{html.escape(c["decision"])}</span></td>'
            f'<td>{confirm}</td></tr>'
        )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Extension officer dashboard</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;background:#f7f7f4;color:#1c2321}}
table{{border-collapse:collapse;width:100%;background:#fff}}td,th{{border:1px solid #ddd;padding:8px;font-size:14px;vertical-align:top}}
th{{background:#eef0ec;text-align:left}}</style></head><body>
<h1>Extension officer dashboard</h1>
<p>Unsure cases need a call back. Confirming a case teaches the system: only confirmed cases count as nearby reports.</p>
<table><tr><th>#</th><th>Time (UTC)</th><th>Village</th><th>Symptoms</th><th>Top guesses</th><th>Decision</th><th>Confirmed problem</th></tr>
{''.join(rows) or '<tr><td colspan=7>No cases yet</td></tr>'}</table></body></html>"""


@app.get("/")
def index():
    return {"status": "ok", "voice_webhook": f"{config.BASE_URL}/voice", "dashboard": "/dashboard"}
