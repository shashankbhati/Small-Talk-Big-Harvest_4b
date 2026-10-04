"""Run the pipeline on example descriptions (no phone, no audio).

Usage:  python -m scripts.test_pipeline
        python -m scripts.test_pipeline "the leaves have orange powder underneath and are falling"
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.pipeline import run_pipeline  # noqa: E402

EXAMPLES = [
    "The leaves on the upper rows have orange powder underneath and many leaves are falling.",
    "There are brown spots on top of the leaves, with a light centre.",
    "I see brown tunnels inside the leaves, like someone drew lines.",
    "The green berries have dark sunken patches and some are rotting.",
    "Many berries have a small hole at the tip.",
    "The plants are drooping and the leaves are yellow everywhere, it has not rained.",
    "The old leaves at the bottom are turning yellow.",
    "Something is wrong with my coffee.",
]


def main() -> None:
    db.init_db()
    farmer = db.get_or_create_farmer("test-user")
    texts = sys.argv[1:] or EXAMPLES
    for t in texts:
        out = run_pipeline(t, farmer)
        r = out["result"]
        print("=" * 90)
        print("SAID:     ", t)
        print("METHOD:   ", out["extraction_method"])
        print("FEATURES: ", {k: v for k, v in out["features"].items() if v != "unknown"})
        print("WEATHER:  ", out["weather"], out["weather_flags"])
        print("NEARBY:   ", out["nearby_confirmed"])
        print("TOP 3:    ", [(x["label"], x["p"]) for x in r["ranking"][:3]])
        print("DECISION: ", r["decision"], r["unsure_reasons"])
        print("REPLY:    ", out["response_text"])


if __name__ == "__main__":
    main()
