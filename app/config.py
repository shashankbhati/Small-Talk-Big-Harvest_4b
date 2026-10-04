"""Central configuration, read from .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
AUDIO_DIR = ROOT / "static" / "audio"
TMP_DIR = DATA_DIR / "tmp"
DB_PATH = DATA_DIR / "app.db"
KB_PATH = DATA_DIR / "knowledge_base.json"
WEATHER_CACHE = DATA_DIR / "weather_cache.json"

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
DELETE_RECORDINGS = os.getenv("DELETE_RECORDINGS", "true").lower() == "true"
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
ASR_LANGUAGE = os.getenv("ASR_LANGUAGE", "") or None

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")

DEMO_LAT = float(os.getenv("DEMO_LAT", "12.42"))
DEMO_LON = float(os.getenv("DEMO_LON", "75.74"))
DEMO_VILLAGE = os.getenv("DEMO_VILLAGE", "Demo village")

CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.60"))
MARGIN_THRESHOLD = float(os.getenv("MARGIN_THRESHOLD", "0.20"))
MIN_KNOWN_FEATURES = int(os.getenv("MIN_KNOWN_FEATURES", "2"))

PHONE_HASH_SALT = os.getenv("PHONE_HASH_SALT", "change-me")

for d in (DATA_DIR, AUDIO_DIR, TMP_DIR):
    d.mkdir(parents=True, exist_ok=True)
