"""Speech-to-text with faster-whisper (runs locally on CPU, no internet needed
after the model is downloaded once)."""
from functools import lru_cache

from . import config


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel  # imported lazily so the server starts fast

    return WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")


def transcribe(audio_path: str) -> dict:
    segments, info = _model().transcribe(
        audio_path,
        language=config.ASR_LANGUAGE,
        beam_size=5,
        vad_filter=True,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "language": info.language, "language_prob": round(info.language_probability, 3)}


def warm_up() -> None:
    """Load the model at startup so the first call is not slow."""
    _model()
