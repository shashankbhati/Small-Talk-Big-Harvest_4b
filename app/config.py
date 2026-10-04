from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
ANSWERS_DIR = ROOT / "answers"
STATIC_DIR = ROOT / "static"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str = "sqlite:///./data/shamba.db"
    storage_backend: str = "local"
    audio_dir: str = "./data/audio"
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "voices"

    # Speech-to-text: primary provider, then optional local fallback
    stt_provider: str = "together"  # together | local
    stt_fallback: str = "local"  # local | "" (none)
    together_stt_model: str = "openai/whisper-large-v3"
    whisper_model: str = "large-v3-turbo"
    whisper_device: str = "cuda"  # cuda | cpu (cuda falls back to cpu if it cannot load)
    whisper_compute: str = ""  # "" = auto (int8_float16 on cuda, int8 on cpu)
    whisper_preload: bool = False

    # LLM (symptom extraction only): primary provider, then optional local fallback
    llm_provider: str = "together"  # together | ollama
    llm_fallback: str = "ollama"  # ollama | "" (none)
    together_api_key: str = ""
    together_url: str = "https://api.together.xyz/v1"
    together_model: str = "Qwen/Qwen3.5-9B"
    together_timeout: float = 10.0
    together_retries: int = 1  # extra attempts on timeouts / 429 / 5xx before falling back
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:4b"
    ollama_think: str = ""  # "" = don't send; "false" for thinking models such as qwen3
    ollama_keep_alive: str = "30m"
    ollama_num_ctx: int = 8192  # the extraction prompt is ~4.3k tokens; Ollama's default 4096 truncates it
    llm_timeout: float = 120.0  # local models
    # Cross-check LLM flags with config/lexicon/<lang>.yaml: always | local (only the Ollama model) | off.
    # On the 8-disease test set it costs Qwen3.5-9B nothing and recovers Swahili words it misses ("matundu").
    # For the local model it is also strict: every "yes" needs keyword support.
    lexicon_check: str = "always"

    # Past weather at the farm (Open-Meteo, no API key) nudges the match; see config/weather.yaml
    weather_enabled: bool = True
    weather_url: str = "https://api.open-meteo.com/v1/forecast"
    geocode_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    weather_timeout: float = 8.0

    # One JSON line per model call + per case (input, output, latency): <dir>/model_calls-YYYY-MM-DD.jsonl
    model_log_dir: str = "./data/logs"  # "" = off

    voice_max_tries: int = 25  # /voice/result polls (3 s each, ~75 s) before "not sure"; local fallback needs ~40-70 s

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_validate: bool = True
    # public https URL of this server (ngrok: `ngrok http 8000`); BASE_URL also accepted, as on main
    public_base_url: str = Field("http://localhost:8000", validation_alias=AliasChoices("PUBLIC_BASE_URL", "BASE_URL"))
    # set = open an ngrok tunnel at startup; its https URL replaces public_base_url (no separate `ngrok http`)
    ngrok_authtoken: str = ""
    ngrok_domain: str = ""  # optional static domain from the ngrok dashboard, keeps the Twilio webhook fixed

    phone_salt: str = "change-me"
    fernet_key: str = ""

    review_user: str = "expert"
    review_password: str = "change-me"

    asr_min_conf: float = 0.45
    min_known: int = 2
    score_min: float = 0.75
    margin_min: float = 0.15
    retention_days: int = 365


@lru_cache
def get_settings() -> Settings:
    return Settings()
