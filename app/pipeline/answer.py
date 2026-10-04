"""Answers come ONLY from human-written answers/<lang>.json. Nothing is generated."""
import logging
from dataclasses import dataclass

from app.config import STATIC_DIR, get_settings
from app.languages import answers, default_language, languages

log = logging.getLogger(__name__)


@dataclass
class Answer:
    key: str
    lang: str
    text: str
    audio_url: str | None

    @property
    def audio_rel(self) -> str | None:
        """Same-origin path (for the browser demo page)."""
        return f"/static/audio/{self.lang}/{self.audio_url.rsplit('/', 1)[-1]}" if self.audio_url else None


def render_answer(key: str, lang: str) -> Answer:
    if lang not in languages():
        lang = default_language()
    table = answers(lang)
    if key not in table:
        log.warning("answer key %r missing for %s, using not_sure", key, lang)
        key = "not_sure"
    entry = table[key]
    audio_url = None
    fname = entry.get("audio")
    if fname and (STATIC_DIR / "audio" / lang / fname).exists():
        audio_url = f"{get_settings().public_base_url.rstrip('/')}/static/audio/{lang}/{fname}"
    elif fname:
        log.warning("audio file missing: static/audio/%s/%s (falling back to <Say>)", lang, fname)
    return Answer(key=key, lang=lang, text=entry["text"], audio_url=audio_url)
