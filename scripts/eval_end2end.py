"""End-to-end (text): extract -> match against the SEED knowledge base.

Reports correct / wrong / not_sure rates per language. A low WRONG rate matters more than a high correct rate.
"correct" includes correctly abstaining on cases whose expected condition is not_sure.
Writes eval/end2end_results.csv.
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.languages import profiles  # noqa: E402
from scripts._csv import lang_filter, write_merged  # noqa: E402
from app.pipeline.extract import ExtractionError, extract_parameters  # noqa: E402
from app.pipeline.match import NOT_SURE, match  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cases = yaml.safe_load((ROOT / "eval" / "extract_testset.yaml").read_text(encoding="utf-8"))["cases"]
    kb = list(profiles().items())
    s = get_settings()
    model = s.together_model if s.llm_provider == "together" else s.ollama_model
    rows = []
    for lang, items in lang_filter(cases).items():
        correct = wrong = not_sure = 0
        for it in items:
            try:
                got = match(extract_parameters(it["text"], lang), kb).result
            except ExtractionError:
                got = NOT_SURE
            if got == it["condition"]:
                correct += 1
            elif got == NOT_SURE:
                not_sure += 1
            else:
                wrong += 1
                print(f"  WRONG [{lang}] expected={it['condition']} got={got}: {it['text']}")
        n = len(items)
        row = {"provider": s.llm_provider, "model": model, "lang": lang, "n": n,
               "correct": round(correct / n, 3), "wrong": round(wrong / n, 3), "not_sure": round(not_sure / n, 3)}
        rows.append(row)
        print(row)
    write_merged(ROOT / "eval" / "end2end_results.csv", rows)


if __name__ == "__main__":
    main()
