"""Twilio SMS: text in -> extract -> match -> fixed answer text back."""
import re

from fastapi import APIRouter, Depends
from sqlalchemy import select
from twilio.twiml.messaging_response import MessagingResponse

from app.cases import create_case
from app.db import SessionLocal
from app.languages import answers, default_language, languages
from app.models import Case
from app.pipeline.answer import render_answer
from app.pipeline.run import run_case
from app.privacy import hash_phone
from app.twilio_util import twiml, validate_twilio

router = APIRouter(prefix="/sms")

_SCRIPTS = {
    "arabic": re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]"),
    "devanagari": re.compile(r"[ऀ-ॿ]"),
}


def detect_language(body: str) -> tuple[str, str]:
    """Return (lang, body_without_prefix). Explicit prefix (e.g. 'AR ...') wins, then script heuristic."""
    stripped = body.strip()
    for code, cfg in languages().items():
        prefix = str(cfg.get("sms_prefix", code)).upper()
        m = re.match(rf"^{re.escape(prefix)}\b[\s:,.-]*", stripped, flags=re.I)
        if m:
            return code, stripped[m.end():].strip()
    for code, cfg in languages().items():
        rx = _SCRIPTS.get(cfg.get("script", ""))
        if rx and rx.search(stripped):
            return code, stripped
    return default_language(), stripped


@router.post("/incoming")
def incoming(form: dict = Depends(validate_twilio)):
    phone = form.get("From") or None
    lang, text = detect_language(str(form.get("Body", "")))
    with SessionLocal() as session:
        first_contact = phone is None or session.scalar(
            select(Case.id).where(Case.phone_hash == hash_phone(phone)).limit(1)) is None
        case = create_case(session, "sms", lang, phone=phone, transcript=text, audio_consent="n/a")
        case = run_case(case.id, session)
        reply = render_answer(case.result, case.language).text
    if first_contact:
        reply += "\n" + answers(lang)["sms_privacy"]["text"]
    resp = MessagingResponse()
    resp.message(reply)
    return twiml(resp)
