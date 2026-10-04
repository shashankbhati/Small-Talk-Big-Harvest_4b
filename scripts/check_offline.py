"""Simulate a Together AI outage and check that the full pipeline still answers using local models.

    python scripts/check_offline.py

Points TOGETHER_URL at an unreachable address (like Wi-Fi off), then runs a Swahili text case and
Swahili/Arabic voice clips through run_case(). Uses a throwaway database.
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["TOGETHER_URL"] = "http://127.0.0.1:9/v1"  # nothing listens here -> connection refused
os.environ["DATABASE_URL"] = f"sqlite:///{(ROOT / 'data' / 'offline_check.db').as_posix()}"
os.environ["AUDIO_DIR"] = str(ROOT / "data" / "offline_check_audio")

from app.cases import create_case  # noqa: E402
from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.pipeline.answer import render_answer  # noqa: E402
from app.pipeline.run import run_case  # noqa: E402
from scripts.seed_db import seed  # noqa: E402

CASES = [
    ("text", "sw", "Majani ya kahawa yana unga wa rangi ya machungwa upande wa chini na madoa ya njano juu.",
     "leaf_rust"),
    ("audio", "sw", ROOT / "eval" / "clips" / "sw_rust.mp3", "leaf_rust"),
    ("audio", "ar", ROOT / "eval" / "clips" / "ar_rust.mp3", "leaf_rust"),
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    Base.metadata.drop_all(engine)
    init_db()
    seed()
    ok = True
    with SessionLocal() as session:
        for kind, lang, payload, expected in CASES:
            t = time.time()
            if kind == "text":
                case = create_case(session, "demo", lang, transcript=payload)
            else:
                from app.audio import save_upload

                key = save_upload(Path(payload).read_bytes(), Path(payload).suffix)
                case = create_case(session, "demo", lang, audio_consent="answer_only", audio_path=key)
            case = run_case(case.id, session)
            passed = case.result == expected and case.llm_provider == "ollama" and \
                (kind == "text" or case.stt_provider == "local")
            ok &= passed
            print(f"[{'PASS' if passed else 'FAIL'}] {kind}/{lang} {time.time() - t:.1f}s "
                  f"stt={case.stt_provider} llm={case.llm_provider} result={case.result} "
                  f"reason={case.not_sure_reason} asr_conf={case.asr_confidence}")
            print("       ", render_answer(case.result, case.language).text[:90])
    Base.metadata.drop_all(engine)
    engine.dispose()
    (ROOT / "data" / "offline_check.db").unlink(missing_ok=True)
    print("ALL PASS" if ok else "SOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
