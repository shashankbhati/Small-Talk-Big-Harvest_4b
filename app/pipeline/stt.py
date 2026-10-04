"""Speech-to-text.

STT_PROVIDER=together (Together AI Whisper large-v3) or local (faster-whisper). If the primary fails
(after TOGETHER_RETRIES on transient errors), STT_FALLBACK=local transcribes on this machine.
"""
import glob
import logging
import math
import os
import sys
import threading
from pathlib import Path

import httpx

from app.config import get_settings
from app.languages import languages
from app.pipeline import calllog
from app.pipeline.resilience import ProviderUnavailable, STTResult, mode_chain, with_retry

log = logging.getLogger(__name__)

_model = None
_lock = threading.Lock()


def _confidence(logprobs: list[float]) -> float | None:
    """asr_confidence = exp(mean(segment.avg_logprob)), rounded to 2 decimals."""
    return round(math.exp(sum(logprobs) / len(logprobs)), 2) if logprobs else None


# ---------- local: faster-whisper ----------

def _add_cuda_dll_dirs() -> None:
    """On Windows, make the pip-installed CUDA 12 / cuDNN 9 DLLs (nvidia-* wheels) loadable."""
    if os.name != "nt":
        return
    for d in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin")):
        try:
            os.add_dll_directory(d)
        except OSError:
            continue
        if d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def get_model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel

            s = get_settings()
            device = s.whisper_device
            if device == "cuda":
                _add_cuda_dll_dirs()
                try:
                    compute = s.whisper_compute or "int8_float16"
                    log.info("loading whisper %s on cuda (%s)", s.whisper_model, compute)
                    _model = WhisperModel(s.whisper_model, device="cuda", compute_type=compute)
                    return _model
                except Exception as e:
                    log.warning("whisper on cuda failed (%s); using cpu", e)
            compute = (s.whisper_compute if device == "cpu" else "") or "int8"
            log.info("loading whisper %s on cpu (%s)", s.whisper_model, compute)
            _model = WhisperModel(s.whisper_model, device="cpu", compute_type=compute)
        return _model


def decode_audio(path: str, sr: int = 16000):
    """Decode any audio file to mono float32 PCM with ffmpeg (avoids PyAV version issues)."""
    import subprocess

    import numpy as np

    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"],
        check=True, capture_output=True, timeout=120,
    ).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0


def _transcribe_local(path: str, whisper_lang: str | None) -> tuple[str, str | None, float | None]:
    model = get_model()
    audio = decode_audio(path)
    calllog.note(audio_seconds=round(len(audio) / 16000, 2))

    detected = None
    try:
        detected, _prob, _all = model.detect_language(audio)
    except Exception:  # detection is informational only
        log.warning("language detection failed", exc_info=True)

    segments, _info = model.transcribe(audio, language=whisper_lang, beam_size=5, vad_filter=True)
    segments = list(segments)
    text = " ".join(s.text.strip() for s in segments).strip()
    if not segments:
        return "", detected, 0.0
    return text, detected, _confidence([s.avg_logprob for s in segments])


# ---------- Together AI Whisper ----------

def _transcribe_together(path: str, whisper_lang: str | None) -> tuple[str, str | None, float | None]:
    s = get_settings()
    if not s.together_api_key:
        raise ProviderUnavailable("TOGETHER_API_KEY is not set")
    data = {"model": s.together_stt_model, "response_format": "verbose_json",
            "timestamp_granularities": "segment", "temperature": "0"}
    if whisper_lang:
        data["language"] = whisper_lang
    with open(path, "rb") as f:
        r = httpx.post(
            f"{s.together_url.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {s.together_api_key}"},
            data=data,
            files={"file": (Path(path).name, f, "application/octet-stream")},
            timeout=s.together_timeout,
        )
    r.raise_for_status()
    body = r.json()
    calllog.note(audio_seconds=body.get("duration"))
    text = (body.get("text") or "").strip()
    segments = body.get("segments") or []
    if not text:
        return "", body.get("language"), 0.0
    logprobs = [seg["avg_logprob"] for seg in segments if isinstance(seg.get("avg_logprob"), (int, float))]
    return text, _normalize_lang(body.get("language")), _confidence(logprobs)


_LANG_NAMES = {"swahili": "sw", "arabic": "ar", "hindi": "hi", "english": "en"}


def _normalize_lang(lang: str | None) -> str | None:
    if not lang:
        return None
    return _LANG_NAMES.get(lang.lower(), lang.lower())


_PROVIDERS = {"together": _transcribe_together, "local": _transcribe_local}


def _model_name(provider: str) -> str:
    s = get_settings()
    if provider == "together":
        return s.together_stt_model
    if provider == "local":
        return f"faster-whisper/{s.whisper_model} ({s.whisper_device})"
    return provider


def _logged(provider: str, fn, path: str, whisper_lang: str | None):
    size = os.path.getsize(path) if os.path.exists(path) else None
    return calllog.record(
        "stt", provider, _model_name(provider),
        {"audio": Path(path).name, "bytes": size, "language_hint": whisper_lang},
        lambda: fn(path, whisper_lang),
        lambda r: {"text": r[0], "detected_language": r[1], "asr_confidence": r[2]},
    )


def provider_chain() -> list[str]:
    s = get_settings()
    chain = [s.stt_provider.lower()]
    if s.stt_fallback and s.stt_fallback.lower() not in chain:
        chain.append(s.stt_fallback.lower())
    return mode_chain("stt", chain)


def transcribe(path: str, lang_hint: str | None) -> STTResult:
    """Return (text, detected_language, asr_confidence); `.provider` says which backend answered.

    Confidence is None if the backend doesn't report it. Raises the last error if every provider failed.
    """
    whisper_lang = languages().get(lang_hint, {}).get("whisper_code") if lang_hint else None
    retries = get_settings().together_retries
    last: Exception | None = None
    for provider in provider_chain():
        fn = _PROVIDERS.get(provider)
        if fn is None:
            last = ProviderUnavailable(f"unknown STT provider: {provider}")
            continue
        try:
            text, lang, conf = with_retry(lambda: _logged(provider, fn, path, whisper_lang),
                                          retries if provider == "together" else 0, f"stt/{provider}")
            return STTResult(text, lang, conf, provider)
        except Exception as e:
            last = e
            log.warning("stt/%s failed (%s), trying fallback", provider, type(e).__name__)
    raise last or RuntimeError("no STT provider configured")


def preload() -> None:
    """Load the local model now (WHISPER_PRELOAD=true) so the first fallback is fast."""
    if "local" in provider_chain():
        get_model()
