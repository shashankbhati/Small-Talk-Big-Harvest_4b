"""Build eval/RESULTS.md from all test and eval outputs, and refresh the results tables in README.md.

    python scripts/report.py

Inputs (each optional): eval/pytest_summary.txt, eval/scenarios.json, eval/speech_e2e_results.csv,
eval/speech_e2e_details.csv, eval/end2end_results.csv, eval/extract_results.csv, eval/asr_results.csv,
eval/findings.md.
"""
import csv
import json
import platform
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "eval"
sys.path.insert(0, str(ROOT))

SPEECH = ("speech_e2e_results.csv", "Speech end to end: synthetic audio of the 36 test sentences → speech-to-text → "
          "extraction → diagnosis. Low `wrong` matters more than high `correct`.")
TEXT = ("end2end_results.csv", "Text end to end: test sentence → extraction → diagnosis (also what SMS does).")
EXTRACT = ("extract_results.csv", "Symptom extraction: how many of the 24 symptom flags the LLM got right.")
ASR = ("asr_results.csv", "Speech recognition on FLEURS (25 real read-speech clips per language): word error rate "
       "(lower is better).")


def rows(name: str) -> list[dict]:
    p = EVAL / name
    return list(csv.DictReader(p.open(encoding="utf-8"))) if p.exists() else []


def table(data: list[dict], cols: list[str] | None = None) -> str:
    if not data:
        return "*(not run yet)*"
    cols = cols or list(data[0])
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in data]
    return "\n".join(lines)


def pct(v) -> str:
    try:
        return f"{float(v) * 100:.0f}%"
    except (TypeError, ValueError):
        return str(v)


def as_pct(data: list[dict], cols=("correct", "wrong", "not_sure", "exact_match", "symptom_accuracy")) -> list[dict]:
    return [{k: (pct(v) if k in cols else v) for k, v in r.items()} for r in data]


def wrong_cases() -> list[dict]:
    out = []
    for r in rows("speech_e2e_details.csv"):
        if r["got"] != r["expected"] and r["got"] != "not_sure":
            out.append({"test": "speech", "stack": r["stack"], "lang": r["lang"], "expected": r["expected"],
                        "got": r["got"], "transcript": r["transcript"]})
    return out


def wrong_count(data: list[dict]) -> int:
    return sum(round(float(r["wrong"]) * int(r["n"])) for r in data)


def total(data: list[dict]) -> int:
    return sum(int(r["n"]) for r in data)


def results_md() -> str:
    from app.config import get_settings

    s = get_settings()
    pytest_line = (EVAL / "pytest_summary.txt").read_text(encoding="utf-8").strip() \
        if (EVAL / "pytest_summary.txt").exists() else "not run"
    sc = json.loads((EVAL / "scenarios.json").read_text(encoding="utf-8")) if (EVAL / "scenarios.json").exists() \
        else {"scenarios": [], "run_at": "-"}
    scen = sc["scenarios"]
    n_pass = sum(x["status"] == "PASS" for x in scen)
    speech, text = rows(SPEECH[0]), rows(TEXT[0])

    md = [
        "# Shamba Call: End-to-End Test Results",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `scripts/report.py`. "
        f"Machine: {platform.system()} {platform.release()}, NVIDIA RTX 3050 Ti Laptop (4 GB), 14 GB RAM.",
        "",
        "## Summary",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Unit tests (`pytest`) | {pytest_line.split(' in ')[0]} |",
        f"| Live scenarios (real models) | {n_pass}/{len(scen)} passed |",
        f"| Speech end to end: wrong diagnoses | {wrong_count(speech)} of {total(speech)} cases |",
        f"| Text end to end: wrong diagnoses | {wrong_count(text)} of {total(text)} cases |",
        "",
        "**Model stacks tested**",
        "",
        "| Stack | Speech-to-text | Symptom extraction |",
        "|---|---|---|",
        f"| Hosted (default) | Together `{s.together_stt_model}` | Together `{s.together_model}` |",
        f"| Local (fallback) | faster-whisper `{s.whisper_model}` on GPU | Ollama `{s.ollama_model}` + keyword check |",
        "",
        f"Decision thresholds: `MIN_KNOWN={s.min_known}`, `SCORE_MIN={s.score_min}`, `MARGIN_MIN={s.margin_min}`, "
        f"`ASR_MIN_CONF={s.asr_min_conf}`, `LEXICON_CHECK={s.lexicon_check}`.",
        "",
        "## 1. Unit tests",
        "",
        f"`pytest`: **{pytest_line}**. Covers config, database, matching rules, answers in every language, "
        "extraction validation and retries, storage and audio deletion, demo/review/voice/SMS routes, Twilio "
        "signature check, privacy (hashing, encryption, retention, logs), retry + local fallback, keyword check.",
        "",
        f"## 2. Live scenarios (run {sc.get('run_at', '-')})",
        "",
        "The app runs in-process against the real models (`python scripts/e2e_scenarios.py`).",
        "",
        table([{"#": i + 1, "Scenario": x["scenario"],
                "Result": ("✅ " if x["status"] == "PASS" else "❌ ") + x["status"],
                "Time": f"{x['seconds']} s", "Details": x["detail"]} for i, x in enumerate(scen)]),
        "",
        "## 3. Speech end to end",
        "",
        SPEECH[1] + " The audio is clean synthetic speech (edge-tts), easier than a real phone line.",
        "",
        table(as_pct(speech)),
        "",
        "## 4. Text end to end",
        "",
        TEXT[1],
        "",
        table(as_pct(text)),
        "",
        "## 5. Symptom extraction",
        "",
        EXTRACT[1] + " `exact_match` = all 24 flags right for a sentence; many misses are harmless (e.g. reading "
        "\"the plant is healthy\" as \"no\" to every symptom).",
        "",
        table(as_pct(rows(EXTRACT[0]))),
        "",
        "## 6. Speech recognition (FLEURS)",
        "",
        ASR[1],
        "",
        table(rows(ASR[0])),
        "",
        "## 7. Wrong diagnoses",
        "",
    ]
    wc = wrong_cases()
    md += [table(wc) if wc else "None.", ""]
    if (EVAL / "findings.md").exists():
        md += ["## 8. Findings", "", (EVAL / "findings.md").read_text(encoding="utf-8").strip(), ""]
    md += [
        "## 9. Test data and caveats",
        "",
        "- Test set: `eval/extract_testset.yaml`, 12 **synthetic** sentences per language (8 conditions, healthy, "
        "3 cases that should get \"not sure\"), written by the team from the knowledge base. Some were written after "
        "the Swahili keyword list, so real-world accuracy will be lower.",
        "- Speech tests use clean synthetic audio and FLEURS read speech, not real farmers on a phone line.",
        "- Knowledge base: `knowledge/coffee_disease_knowledge_base.xlsx` (team-provided, no citations yet).",
        "",
        "## 10. How to reproduce",
        "",
        "```bash",
        "pytest -q | tail -1 > eval/pytest_summary.txt",
        "python scripts/e2e_scenarios.py                                         # live scenarios",
        "python scripts/e2e_speech.py                                            # speech e2e, hosted stack",
        "STT_PROVIDER=local LLM_PROVIDER=ollama python scripts/e2e_speech.py --lang sw   # local stack, per language",
        "LLM_FALLBACK= python scripts/eval_extract.py                             # text e2e + extraction, hosted",
        "LLM_PROVIDER=ollama LLM_FALLBACK= python scripts/eval_extract.py --lang sw      # local, per language",
        "python scripts/eval_asr.py; STT_PROVIDER=local STT_FALLBACK= python scripts/eval_asr.py",
        "python scripts/report.py                                                # rebuild this file",
        "```",
        "",
    ]
    return "\n".join(md)


def readme_block() -> str:
    parts = [f"**{SPEECH[1]}**\n\n" + table(as_pct(rows(SPEECH[0]))),
             f"**{TEXT[1]}**\n\n" + table(as_pct(rows(TEXT[0]))),
             f"**{EXTRACT[1]}**\n\n" + table(as_pct(rows(EXTRACT[0]))),
             f"**{ASR[1]}**\n\n" + table(rows(ASR[0])),
             "Full report, including live scenarios and findings: [`eval/RESULTS.md`](eval/RESULTS.md)."]
    return "<!-- RESULTS:START -->\n" + "\n\n".join(parts) + "\n<!-- RESULTS:END -->"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    (EVAL / "RESULTS.md").write_text(results_md(), encoding="utf-8")
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    readme.write_text(re.sub(r"<!-- RESULTS:START -->.*?<!-- RESULTS:END -->", lambda _: readme_block(), text,
                             flags=re.S), encoding="utf-8")
    print(f"wrote {EVAL / 'RESULTS.md'} and updated README.md")


if __name__ == "__main__":
    main()
