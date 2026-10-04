"""Create SYNTHETIC confirmed cases around the demo location, so the
'nearby farmers' signal has something to show. Every row is marked synthetic=1.

Usage:  python -m scripts.seed_synthetic --rust 6 --miner 1
"""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rust", type=int, default=6, help="confirmed leaf rust cases nearby")
    ap.add_argument("--miner", type=int, default=1, help="confirmed leaf miner cases nearby")
    ap.add_argument("--borer", type=int, default=0, help="confirmed berry borer cases nearby")
    ap.add_argument("--clear", action="store_true", help="delete previous synthetic rows first")
    args = ap.parse_args()

    db.init_db()
    with db.connect() as conn:
        if args.clear:
            conn.execute("DELETE FROM cases WHERE synthetic=1")
        plan = [("leaf_rust", args.rust), ("leaf_miner", args.miner), ("berry_borer", args.borer)]
        n = 0
        for label, count in plan:
            for i in range(count):
                lat = config.DEMO_LAT + random.uniform(-0.04, 0.04)  # roughly within ~5 km
                lon = config.DEMO_LON + random.uniform(-0.04, 0.04)
                conn.execute(
                    """INSERT INTO cases(phone_hash, village, lat, lon, created_at, transcript, features, ranking,
                                         predicted, confidence, decision, confirmed_label, confirmed_by, synthetic)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (f"synthetic-{label}-{i}", f"Synthetic farm {i+1}", lat, lon, db.now_iso(), None,
                     json.dumps({}), json.dumps([]), label, None, "confident", label, "synthetic-officer"),
                )
                n += 1
    print(f"Inserted {n} synthetic confirmed cases near ({config.DEMO_LAT}, {config.DEMO_LON}).")


if __name__ == "__main__":
    main()
