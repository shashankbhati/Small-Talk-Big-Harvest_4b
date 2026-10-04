"""Shared helpers for the eval scripts."""
import argparse
import csv
from pathlib import Path


def write_merged(path: Path, rows: list[dict], keys: tuple[str, ...] = ("model", "lang")) -> None:
    """Write rows, keeping existing rows whose (model, lang) is not being replaced."""
    current = {tuple(r[k] for k in keys) for r in rows}
    old = []
    if path.exists():
        for r in csv.DictReader(path.open(encoding="utf-8")):
            if all(r.get(k) for k in keys) and tuple(r[k] for k in keys) not in current:
                old.append(r)
    fields = list(rows[0])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(old + rows)


def lang_filter(cases: dict) -> dict:
    """--lang sw [--lang ar ...] limits the run to those languages."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", action="append")
    a, _ = ap.parse_known_args()
    return {k: v for k, v in cases.items() if not a.lang or k in a.lang}
