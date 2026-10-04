import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Isolated test environment — set before app modules are imported.
_TMP = ROOT / "data" / "test"
_TMP.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["AUDIO_DIR"] = str(_TMP / "audio")
os.environ["MODEL_LOG_DIR"] = str(_TMP / "logs")
os.environ["TWILIO_VALIDATE"] = "false"
os.environ["PHONE_SALT"] = "test-salt"
os.environ["FERNET_KEY"] = "P3qBLfZml22orTgIkNjU5jtvV4rilhlNiVJp4WpSEZM="
os.environ["REVIEW_USER"] = "expert"
os.environ["REVIEW_PASSWORD"] = "pw"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"
# Deterministic model config: never hit real APIs; fallback tests enable chains explicitly.
os.environ["TOGETHER_API_KEY"] = "test-key"
os.environ["STT_PROVIDER"] = "together"
os.environ["LLM_PROVIDER"] = "together"
os.environ["STT_FALLBACK"] = ""
os.environ["LLM_FALLBACK"] = ""
os.environ["TOGETHER_RETRIES"] = "0"
os.environ["WHISPER_PRELOAD"] = "false"

import pytest  # noqa: E402

from app.db import Base, SessionLocal, engine, init_db  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    init_db()
    from scripts.seed_db import seed

    session = SessionLocal()
    seed(session)
    yield session
    session.close()


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
