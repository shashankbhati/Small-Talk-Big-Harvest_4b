"""Retry policy for hosted model calls, and tagged results that remember which provider answered."""
import logging
import time
from contextvars import ContextVar
from typing import Callable, TypeVar

import httpx

log = logging.getLogger(__name__)
T = TypeVar("T")

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


# Per-request model choice (the demo page's switch): "" = use .env settings, "local" = this machine only
# (faster-whisper + Ollama), "together" = Together AI with the configured fallback.
model_mode: ContextVar[str] = ContextVar("model_mode", default="")

LOCAL_PROVIDERS = {"stt": "local", "llm": "ollama"}


def mode_chain(kind: str, default: list[str]) -> list[str]:
    """Provider chain for `kind` ("stt" | "llm") after applying the per-request model_mode."""
    mode = model_mode.get()
    if mode == "local":
        return [LOCAL_PROVIDERS[kind]]
    if mode == "together":
        return ["together"] + [p for p in default if p != "together"]
    return default


class ProviderUnavailable(Exception):
    """Provider can't be used (missing key, auth error, bad request). Don't retry; go to the fallback."""


def is_transient(e: Exception) -> bool:
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code in RETRY_STATUS
    return isinstance(e, (httpx.TimeoutException, httpx.TransportError))


def with_retry(fn: Callable[[], T], retries: int, what: str, backoff: float = 1.0) -> T:
    """Call fn; on transient errors retry up to `retries` more times. Other errors propagate immediately."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            if not is_transient(e) or attempt == retries:
                raise
            log.warning("%s: transient error (%s), retry %d/%d", what, type(e).__name__, attempt + 1, retries)
            time.sleep(backoff * (attempt + 1))
    raise AssertionError("unreachable")


class Flags(dict):
    """Symptom flags dict that also records which provider produced it."""
    provider: str | None = None


class STTResult(tuple):
    """(text, detected_language, asr_confidence) that also records which provider produced it."""
    provider: str | None = None

    def __new__(cls, text, lang, conf, provider=None):
        obj = super().__new__(cls, (text, lang, conf))
        obj.provider = provider
        return obj
