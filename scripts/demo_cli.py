"""Run the pipeline on a local audio file or text.

    python scripts/demo_cli.py --lang sw --text "Majani yana unga wa machungwa chini..."
    python scripts/demo_cli.py --lang sw --audio sample.wav [--consent answer_only]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cases import create_case  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.pipeline.answer import render_answer  # noqa: E402
from app.pipeline.run import run_case  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="sw")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--audio")
    ap.add_argument("--consent", default="answer_only", choices=["keep_for_training", "answer_only"])
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    init_db()
    session = SessionLocal()
    if args.text:
        case = create_case(session, "demo", args.lang, transcript=args.text)
    else:
        from app.audio import save_upload

        key = save_upload(Path(args.audio).read_bytes(), Path(args.audio).suffix)
        case = create_case(session, "demo", args.lang, audio_consent=args.consent, audio_path=key)

    case = run_case(case.id, session)
    ans = render_answer(case.result, case.language)
    print(json.dumps({
        "case_id": case.id,
        "language": case.language,
        "detected_language": case.detected_language,
        "asr_confidence": case.asr_confidence,
        "transcript": case.transcript,
        "parameters": {k: v for k, v in (case.parameters or {}).items() if v != 0},
        "top2": case.top2,
        "result": case.result,
        "score": case.score,
        "not_sure_reason": case.not_sure_reason,
        "status": case.status,
        "audio_path_after": case.audio_path,
        "answer_text": ans.text,
        "answer_audio": ans.audio_url,
    }, ensure_ascii=False, indent=2))
    session.close()


if __name__ == "__main__":
    main()
