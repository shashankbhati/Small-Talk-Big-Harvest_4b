"""Speech end-to-end eval: test sentence → synthetic audio → STT → extraction → diagnosis.

    python scripts/e2e_speech.py [--lang sw]          # uses STT_PROVIDER / LLM_PROVIDER from .env
    STT_PROVIDER=local LLM_PROVIDER=ollama python scripts/e2e_speech.py --lang sw

Audio for eval/extract_testset.yaml is synthesised once with edge-tts (eval/clips/testset/, clean TTS speech,
easier than a real phone line). Fallbacks are disabled so each run measures one model stack.
Writes eval/speech_e2e_results.csv (summary) and eval/speech_e2e_details.csv.
"""
import asyncio
import csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = f"sqlite:///{(ROOT / 'data' / 'e2e_speech.db').as_posix()}"
os.environ["AUDIO_DIR"] = str(ROOT / "data" / "e2e_speech_audio")
os.environ["STT_FALLBACK"] = ""
os.environ["LLM_FALLBACK"] = ""

import yaml  # noqa: E402

from app.audio import save_upload  # noqa: E402
from app.cases import create_case  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.pipeline.run import run_case  # noqa: E402
from scripts._csv import lang_filter, write_merged  # noqa: E402
from scripts.generate_audio import VOICES, synth  # noqa: E402
from scripts.seed_db import seed  # noqa: E402

CLIP_DIR = ROOT / "eval" / "clips" / "testset"


def ensure_clips(cases: dict) -> None:
    async def run():
        for lang, items in cases.items():
            for i, it in enumerate(items):
                out = CLIP_DIR / f"{lang}_{i:02d}.mp3"
                if not out.exists():
                    await synth(it["text"], VOICES[lang], out)
    asyncio.run(run())


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cases = lang_filter(yaml.safe_load((ROOT / "eval" / "extract_testset.yaml").read_text(encoding="utf-8"))["cases"])
    ensure_clips(cases)
    s = get_settings()
    stt = s.together_stt_model if s.stt_provider == "together" else f"{s.whisper_model} (local)"
    llm = s.together_model if s.llm_provider == "together" else f"{s.ollama_model} (local)"
    stack = f"{stt} + {llm}"

    Base.metadata.drop_all(engine)
    init_db()
    seed()
    summary, details = [], []
    with SessionLocal() as session:
        for lang, items in cases.items():
            correct = wrong = not_sure = 0
            confs, t0 = [], time.time()
            for i, it in enumerate(items):
                key = save_upload((CLIP_DIR / f"{lang}_{i:02d}.mp3").read_bytes(), ".mp3")
                case = create_case(session, "demo", lang, audio_consent="answer_only", audio_path=key)
                case = run_case(case.id, session)
                got = case.result
                if got == it["condition"]:
                    correct += 1
                elif got == "not_sure":
                    not_sure += 1
                else:
                    wrong += 1
                    print(f"  WRONG [{lang}] expected={it['condition']} got={got}: {case.transcript}")
                if case.asr_confidence is not None:
                    confs.append(case.asr_confidence)
                details.append({"stack": stack, "lang": lang, "expected": it["condition"], "got": got,
                                "reason": case.not_sure_reason or "", "asr_conf": case.asr_confidence,
                                "text": it["text"], "transcript": case.transcript or ""})
            n = len(items)
            row = {"stack": stack, "lang": lang, "n": n, "correct": round(correct / n, 3),
                   "wrong": round(wrong / n, 3), "not_sure": round(not_sure / n, 3),
                   "mean_asr_conf": round(sum(confs) / len(confs), 2) if confs else "",
                   "sec_per_case": round((time.time() - t0) / n, 1)}
            summary.append(row)
            print(row)
    Base.metadata.drop_all(engine)
    engine.dispose()
    (ROOT / "data" / "e2e_speech.db").unlink(missing_ok=True)

    write_merged(ROOT / "eval" / "speech_e2e_results.csv", summary, keys=("stack", "lang"))
    det = ROOT / "eval" / "speech_e2e_details.csv"
    old = []
    if det.exists():
        done = {(d["stack"], d["lang"]) for d in details}
        old = [r for r in csv.DictReader(det.open(encoding="utf-8")) if (r["stack"], r["lang"]) not in done]
    with open(det, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(details[0]))
        w.writeheader()
        w.writerows(old + details)


if __name__ == "__main__":
    main()
