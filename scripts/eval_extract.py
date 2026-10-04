"""Extraction accuracy on the SYNTHETIC test set (eval/extract_testset.yaml), using the configured LLM.

Reports per-language exact match (all symptom flags right) and per-symptom accuracy.
Also runs the matcher on each extraction (end-to-end text -> diagnosis).
Writes eval/extract_results.csv, eval/end2end_results.csv and eval/extract_details.csv (per sentence).
"""
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.languages import symptoms  # noqa: E402
from app.languages import profiles  # noqa: E402
from app.pipeline.extract import ExtractionError, extract_parameters  # noqa: E402
from app.pipeline.match import NOT_SURE, match  # noqa: E402
from scripts._csv import lang_filter, write_merged  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cases = yaml.safe_load((ROOT / "eval" / "extract_testset.yaml").read_text(encoding="utf-8"))["cases"]
    keys = list(symptoms())
    s = get_settings()
    model = s.together_model if s.llm_provider == "together" else s.ollama_model
    kb = list(profiles().items())
    summary, e2e, details = [], [], []
    for lang, items in lang_filter(cases).items():
        exact = flag_ok = failed = correct = wrong_dx = not_sure = 0
        t0 = time.time()
        for it in items:
            gold = {k: it["flags"].get(k, 0) for k in keys}
            try:
                pred = extract_parameters(it["text"], lang)
            except ExtractionError:
                pred, failed = None, failed + 1
            ok = pred is not None and pred == gold
            exact += ok
            flag_ok += sum(pred[k] == gold[k] for k in keys) if pred else 0
            wrong = [] if pred is None else [f"{k}:{gold[k]}->{pred[k]}" for k in keys if pred[k] != gold[k]]
            # end-to-end with the same extraction (saves a second pass over the LLM)
            got = match(pred, kb).result if pred is not None else NOT_SURE
            if got == it["condition"]:
                correct += 1
            elif got == NOT_SURE:
                not_sure += 1
            else:
                wrong_dx += 1
                print(f"  WRONG [{lang}] expected={it['condition']} got={got}: {it['text']}")
            details.append({"lang": lang, "text": it["text"], "exact": int(ok), "failed": int(pred is None),
                            "expected": it["condition"], "got": got, "errors": " ".join(wrong)})
        n = len(items)
        row = {"provider": s.llm_provider, "model": model, "lang": lang, "n": n,
               "exact_match": round(exact / n, 3), "symptom_accuracy": round(flag_ok / (n * len(keys)), 3),
               "failed": failed, "sec_per_case": round((time.time() - t0) / n, 2)}
        summary.append(row)
        e2e.append({"provider": s.llm_provider, "model": model, "lang": lang, "n": n,
                    "correct": round(correct / n, 3), "wrong": round(wrong_dx / n, 3),
                    "not_sure": round(not_sure / n, 3)})
        print(row)
        print(e2e[-1])

    out = ROOT / "eval"
    write_merged(out / "extract_results.csv", summary)
    write_merged(out / "end2end_results.csv", e2e)
    with open(out / "extract_details.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(details[0]))
        w.writeheader()
        w.writerows(details)
    print(f"wrote {out / 'extract_results.csv'}")


if __name__ == "__main__":
    main()
