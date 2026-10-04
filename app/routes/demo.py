"""Browser demo (no Twilio): upload / record from mic / type text -> full pipeline."""
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile

from app.cases import create_case
from app.config import get_settings
from app.db import SessionLocal
from app.languages import default_language, languages
from app.pipeline.answer import render_answer
from app.pipeline import weather
from app.pipeline.resilience import model_mode
from app.pipeline.run import run_case
from app.templating import templates

router = APIRouter()

MODES = {"together": "Together AI (local fallback)", "local": "Local only (faster-whisper + Ollama)"}


def _default_mode() -> str:
    return "local" if get_settings().llm_provider.lower() == "ollama" else "together"


def _lang(lang: str | None) -> str:
    """A configured language: the requested one, else default_language, else the first configured."""
    langs = languages()
    if lang in langs:
        return lang
    return default_language() if default_language() in langs else next(iter(langs))


def _float(v: str) -> float | None:
    try:
        return float(v) if v.strip() else None
    except ValueError:
        return None


def _page(request: Request, r, lang: str, mode: str | None = None, place: str = ""):
    return templates.TemplateResponse(request, "demo.html", {
        "languages": languages(), "modes": MODES, "lang": lang, "mode": mode or _default_mode(),
        "place": place, "r": r})


@router.get("/demo")
def demo_page(request: Request, lang: str = ""):
    return _page(request, None, _lang(lang))


@router.post("/demo")
async def demo_submit(
    request: Request,
    lang: str = Form(""),
    mode: str = Form(""),
    consent: str = Form("answer_only"),
    text: str = Form(""),
    place: str = Form(""),
    lat: str = Form(""),
    lon: str = Form(""),
    audio: UploadFile | None = File(None),
):
    lang = _lang(lang)
    if consent not in ("keep_for_training", "answer_only"):
        consent = "answer_only"
    if mode not in MODES:
        mode = ""  # no choice sent: use the .env provider chain
    data = await audio.read() if audio is not None and audio.filename else b""

    # farm location: browser GPS (lat/lon) wins, else geocode the typed place; rounded to ~1 km
    loc = {"lat": _float(lat), "lon": _float(lon), "place": place.strip() or None}
    if loc["lat"] is not None and loc["lon"] is not None:
        loc["lat"], loc["lon"] = weather.round_coord(loc["lat"]), weather.round_coord(loc["lon"])
        loc["place"] = loc["place"] or "GPS location"
    elif loc["place"]:
        loc = weather.geocode(loc["place"]) or {"lat": None, "lon": None, "place": loc["place"] + " (not found)"}

    with SessionLocal() as session:
        if data:
            from app.audio import save_upload

            key = save_upload(data, Path(audio.filename).suffix or ".webm")
            case = create_case(session, "demo", lang, audio_consent=consent, audio_path=key, **loc)
        else:
            case = create_case(session, "demo", lang, transcript=text.strip(), **loc)
        token = model_mode.set(mode)
        try:
            case = run_case(case.id, session)
        finally:
            model_mode.reset(token)
        ans = render_answer(case.result, case.language)
        r = {"case": case, "answer": ans,
             "known": {k: v for k, v in (case.parameters or {}).items() if v != 0}}
    return _page(request, r, lang, mode, place.strip())
