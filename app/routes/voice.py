"""Twilio voice IVR: language -> record -> background pipeline -> poll -> answer."""
import logging

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from twilio.twiml.voice_response import VoiceResponse

from app.cases import create_case
from app.config import get_settings
from app.db import SessionLocal
from app.farmers import delete_caller_data, find_farmer
from app.languages import default_language, language_for_key, languages
from app.models import Case
from app.pipeline.run import run_case
from app.twilio_util import speak, twiml, validate_twilio

log = logging.getLogger(__name__)
router = APIRouter(prefix="/voice")

DIGITS = "0123456789*#"
DONE = {"answered", "in_review", "labeled", "error"}


def _welcome_gather(resp: VoiceResponse, case_id: str, attempt: int) -> None:
    g = resp.gather(num_digits=1, action=f"/voice/language?case_id={case_id}&attempt={attempt}", timeout=6)
    for code in languages():  # "1 Swahili, 2 Arabic, 3 Hindi" — each in its own language
        speak(g, "prompt_welcome", code)
    # no key pressed -> treat as invalid digit
    resp.redirect(f"/voice/language?case_id={case_id}&attempt={attempt}")


@router.post("/incoming")
def incoming(form: dict = Depends(validate_twilio)):
    phone = form.get("From") or None
    resp = VoiceResponse()
    with SessionLocal() as session:
        farmer = find_farmer(session, phone)
        if farmer:  # registered: language and farm location are known, so skip the language menu
            case = create_case(session, "voice", farmer.language, phone=phone, audio_consent="answer_only",
                               lat=farmer.lat, lon=farmer.lon, place=farmer.place)
            _ask_describe(resp, case.id, case.language)
            return twiml(resp)
        case = create_case(session, "voice", default_language(), phone=phone, audio_consent="answer_only")
    _welcome_gather(resp, case.id, 0)
    return twiml(resp)


@router.post("/language")
def language(case_id: str, attempt: int = 0, form: dict = Depends(validate_twilio)):
    digit = str(form.get("Digits", ""))
    resp = VoiceResponse()
    with SessionLocal() as session:
        case = session.get(Case, case_id)
        if case is None:
            resp.hangup()
            return twiml(resp)
        if digit == "9" and case.phone_hash:  # delete-my-data
            delete_caller_data(session, case.phone_hash)
            speak(resp, "prompt_data_deleted", default_language())
            resp.hangup()
            return twiml(resp)
        lang = language_for_key(digit)
        if lang is None and attempt < 1:
            speak(resp, "prompt_invalid", default_language())
            _welcome_gather(resp, case_id, attempt + 1)
            return twiml(resp)
        case.language = lang or default_language()
        session.commit()
        lang = case.language
    # no consent question: straight to the recording; audio stays "answer_only" (deleted after the answer)
    _ask_describe(resp, case_id, lang)
    return twiml(resp)


def _ask_describe(resp: VoiceResponse, case_id: str, lang: str) -> None:
    speak(resp, "prompt_describe", lang)
    resp.record(max_length=30, finish_on_key=DIGITS, play_beep=True, timeout=5,
                action=f"/voice/recorded?case_id={case_id}")
    # Twilio continues here if nothing was recorded
    resp.redirect(f"/voice/result?case_id={case_id}&try={get_settings().voice_max_tries}")


@router.post("/consent")
def consent(case_id: str, form: dict = Depends(validate_twilio)):
    digit = str(form.get("Digits", ""))
    resp = VoiceResponse()
    with SessionLocal() as session:
        case = session.get(Case, case_id)
        if case is None:
            resp.hangup()
            return twiml(resp)
        if digit == "9" and case.phone_hash:  # registered callers skip the language menu, so 9 works here too
            lang = case.language
            delete_caller_data(session, case.phone_hash)
            speak(resp, "prompt_data_deleted", lang)
            resp.hangup()
            return twiml(resp)
        # Only an explicit "1" keeps audio. Anything else -> answer_only (privacy by default).
        case.audio_consent = "keep_for_training" if digit == "1" else "answer_only"
        session.commit()
        lang = case.language
    _ask_describe(resp, case_id, lang)
    return twiml(resp)


def _download_and_store(case_id: str, url: str, sid: str | None) -> None:
    s = get_settings()
    auth = (s.twilio_account_sid, s.twilio_auth_token) if s.twilio_account_sid else None
    r = httpx.get(url + ".wav", auth=auth, timeout=30, follow_redirects=True)
    r.raise_for_status()
    from app.audio import save_upload

    key = save_upload(r.content, ".wav")
    with SessionLocal() as session:
        case = session.get(Case, case_id)
        case.audio_path = key
        session.commit()
    if sid and s.twilio_account_sid:
        try:
            from twilio.rest import Client

            Client(s.twilio_account_sid, s.twilio_auth_token).recordings(sid).delete()
        except Exception:
            log.warning("could not delete Twilio recording for case %s", case_id, exc_info=True)


def process_recording(case_id: str, url: str, sid: str | None) -> None:
    try:
        _download_and_store(case_id, url, sid)
    except Exception:
        log.exception("case %s: recording download failed", case_id)
        with SessionLocal() as session:
            case = session.get(Case, case_id)
            case.status, case.result, case.not_sure_reason = "error", "not_sure", "extraction_failed"
            session.commit()
        return
    run_case(case_id)


@router.post("/recorded")
def recorded(case_id: str, background: BackgroundTasks, form: dict = Depends(validate_twilio)):
    url = form.get("RecordingUrl")
    resp = VoiceResponse()
    with SessionLocal() as session:
        case = session.get(Case, case_id)
        if case is None:
            resp.hangup()
            return twiml(resp)
        lang = case.language
    if not url:
        resp.redirect(f"/voice/result?case_id={case_id}&try={get_settings().voice_max_tries}")
        return twiml(resp)
    background.add_task(process_recording, case_id, url, form.get("RecordingSid"))
    speak(resp, "prompt_wait", lang)
    resp.redirect(f"/voice/result?case_id={case_id}&try=1")
    return twiml(resp)


@router.post("/result")
def result(case_id: str, n: int = Query(1, alias="try"), form: dict = Depends(validate_twilio)):
    resp = VoiceResponse()
    with SessionLocal() as session:
        case = session.get(Case, case_id)
        if case is None:
            resp.hangup()
            return twiml(resp)
        lang = case.language
        if case.status in DONE:
            speak(resp, case.result or "not_sure", lang)
        elif n < get_settings().voice_max_tries:
            resp.pause(length=3)
            resp.redirect(f"/voice/result?case_id={case_id}&try={n + 1}")
            return twiml(resp)
        else:
            case.status, case.result = "in_review", "not_sure"
            case.not_sure_reason = case.not_sure_reason or "timeout"
            session.commit()
            speak(resp, "not_sure", lang)
    speak(resp, "goodbye", lang)
    resp.hangup()
    return twiml(resp)
