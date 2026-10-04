"""ffmpeg conversion (any input -> Opus .ogg, mono, 16 kHz) and saving via Storage."""
import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone

from app.storage import get_storage


def to_ogg(data: bytes, suffix: str = ".wav") -> bytes:
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, f"in{suffix or '.bin'}")
        dst = os.path.join(d, "out.ogg")
        with open(src, "wb") as f:
            f.write(data)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", "16000",
             "-c:a", "libopus", "-b:a", "24k", dst],
            check=True, capture_output=True, timeout=120,
        )
        with open(dst, "rb") as f:
            return f.read()


def save_upload(data: bytes, suffix: str = ".wav") -> str:
    """Convert to .ogg and store. Returns the storage key."""
    now = datetime.now(timezone.utc)
    key = f"{now:%Y/%m}/{uuid.uuid4().hex}.ogg"
    return get_storage().save(key, to_ogg(data, suffix))
