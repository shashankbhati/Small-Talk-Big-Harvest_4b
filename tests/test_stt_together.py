import httpx
import pytest

from app.config import get_settings
from app.pipeline import stt


@pytest.fixture()
def together(monkeypatch, tmp_path):
    s = get_settings()
    monkeypatch.setattr(s, "stt_provider", "together")
    monkeypatch.setattr(s, "together_api_key", "k")
    f = tmp_path / "a.ogg"
    f.write_bytes(b"OggS")
    return str(f)


def fake_post(body, seen):
    def _post(url, headers=None, data=None, files=None, timeout=None):
        seen.update(url=url, data=data, auth=headers["Authorization"])
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))
    return _post


def test_together_with_logprobs(together, monkeypatch):
    seen = {}
    body = {"text": " Majani yana unga ", "language": "swahili",
            "segments": [{"text": "a", "avg_logprob": -0.5}, {"text": "b", "avg_logprob": -0.3}]}
    monkeypatch.setattr(stt.httpx, "post", fake_post(body, seen))
    text, lang, conf = stt.transcribe(together, "sw")
    assert (text, lang, conf) == ("Majani yana unga", "sw", 0.67)
    assert seen["url"].endswith("/audio/transcriptions")
    assert seen["data"]["language"] == "sw" and seen["data"]["model"] == "openai/whisper-large-v3"
    assert seen["auth"] == "Bearer k"


def test_together_without_logprobs_gives_none(together, monkeypatch):
    monkeypatch.setattr(stt.httpx, "post", fake_post({"text": "hello", "segments": [{"text": "hello"}]}, {}))
    assert stt.transcribe(together, "sw")[2] is None


def test_together_empty_text(together, monkeypatch):
    monkeypatch.setattr(stt.httpx, "post", fake_post({"text": ""}, {}))
    assert stt.transcribe(together, "ar") == ("", None, 0.0)
