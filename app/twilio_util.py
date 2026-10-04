"""Twilio helpers: signature validation and TwiML prompt rendering."""
import logging

from fastapi import HTTPException, Request
from fastapi.responses import Response

from app.config import get_settings
from app.languages import languages
from app.pipeline.answer import render_answer

log = logging.getLogger(__name__)


async def validate_twilio(request: Request) -> dict:
    """Dependency: returns the form params; rejects requests with a bad X-Twilio-Signature."""
    form = dict(await request.form())
    s = get_settings()
    if not s.twilio_validate:
        return form
    from twilio.request_validator import RequestValidator

    # Behind ngrok the request arrives as http://localhost — validate against the public URL Twilio used.
    url = f"{s.public_base_url.rstrip('/')}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    sig = request.headers.get("X-Twilio-Signature", "")
    if not RequestValidator(s.twilio_auth_token).validate(url, form, sig):
        log.warning("rejected webhook with invalid Twilio signature: %s", request.url.path)
        raise HTTPException(403, "invalid signature")
    return form


def speak(verb, key: str, lang: str) -> None:
    """Add <Play> for the pre-recorded prompt, or <Say> fallback, to a VoiceResponse/Gather."""
    ans = render_answer(key, lang)
    if ans.audio_url:
        verb.play(ans.audio_url)
    else:
        voice = languages().get(lang, {}).get("twilio_say_voice")
        if voice:
            verb.say(ans.text, voice=voice)
        else:
            verb.say(ans.text)


def twiml(resp) -> Response:
    return Response(str(resp), media_type="application/xml")
