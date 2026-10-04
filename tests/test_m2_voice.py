import json
import shutil
import subprocess

import pytest

from app.languages import symptoms
from app.pipeline import extract

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def tone_wav(tmp_path) -> bytes:
    out = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    str(out)], check=True)
    return out.read_bytes()


def rust_flags(*_):
    f = {k: 0 for k in symptoms()}
    f.update(orange_powder_under_leaf=1, yellow_spots_on_leaf=1)
    return json.dumps(f)


def test_local_storage_roundtrip():
    from app.storage import get_storage

    st = get_storage()
    st.save("x/a.bin", b"hi")
    assert st.exists("x/a.bin") and st.read("x/a.bin") == b"hi"
    with st.local_path("x/a.bin") as p:
        assert open(p, "rb").read() == b"hi"
    st.delete("x/a.bin")
    assert not st.exists("x/a.bin")
    with pytest.raises(ValueError):
        st.save("../escape.bin", b"no")


@needs_ffmpeg
def test_convert_to_ogg(tmp_path):
    from app.audio import save_upload
    from app.storage import get_storage

    key = save_upload(tone_wav(tmp_path), ".wav")
    assert key.endswith(".ogg")
    assert get_storage().read(key)[:4] == b"OggS"


@needs_ffmpeg
@pytest.mark.parametrize("consent,kept", [("answer_only", False), ("keep_for_training", True)])
def test_voice_case_audio_retention(db, tmp_path, monkeypatch, consent, kept):
    from app.audio import save_upload
    from app.cases import create_case
    from app.pipeline import stt
    from app.pipeline.run import run_case
    from app.storage import get_storage

    monkeypatch.setattr(stt, "transcribe", lambda p, l: ("majani yana unga wa machungwa", "sw", 0.8))
    monkeypatch.setattr(extract, "_chat", lambda m, s, p=None: rust_flags())
    key = save_upload(tone_wav(tmp_path), ".wav")
    case = create_case(db, "demo", "sw", audio_consent=consent, audio_path=key)
    case = run_case(case.id, db)
    assert case.result == "leaf_rust"
    assert case.transcript and case.asr_confidence == 0.8
    assert get_storage().exists(key) is kept
    assert (case.audio_path is not None) is kept


@needs_ffmpeg
def test_low_asr_confidence(db, tmp_path, monkeypatch):
    from app.audio import save_upload
    from app.cases import create_case
    from app.pipeline import stt
    from app.pipeline.run import run_case

    monkeypatch.setattr(stt, "transcribe", lambda p, l: ("???", "sw", 0.2))
    case = create_case(db, "demo", "sw", audio_consent="answer_only", audio_path=save_upload(tone_wav(tmp_path)))
    case = run_case(case.id, db)
    assert (case.result, case.not_sure_reason, case.status) == ("not_sure", "low_asr_confidence", "in_review")
    assert case.audio_path is None


def test_pipeline_error_gives_not_sure(db, monkeypatch):
    from app.cases import create_case
    from app.pipeline import run

    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(run, "match", boom)
    monkeypatch.setattr(extract, "_chat", lambda m, s, p=None: rust_flags())
    case = run.run_case(create_case(db, "demo", "sw", transcript="abc").id, db)
    assert (case.status, case.result) == ("error", "not_sure")
