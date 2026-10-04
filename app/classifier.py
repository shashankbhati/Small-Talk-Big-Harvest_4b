"""Small probabilistic classifier (naive Bayes style).

score(problem) = base_prior
               x weather multiplier   (recent rain / temperature at her farm)
               x nearby multiplier    (CONFIRMED cases near her in the last 30 days)
               x product of P(symptom | problem) for every symptom she mentioned

Scores are normalised to probabilities. 'unknown' symptoms are skipped,
so missing answers do not break it. Priors start from the expert table in
data/knowledge_base.json and are meant to be re-estimated from confirmed cases.
"""
import json
from functools import lru_cache

from . import config

UNIFORM_FLOOR = 0.02  # avoids zero probabilities


@lru_cache(maxsize=1)
def load_kb() -> dict:
    return json.loads(config.KB_PATH.read_text(encoding="utf-8"))


def _likelihood(problem: dict, feature: str, value: str, n_values: int) -> float:
    lk = problem["likelihood"]
    if lk == "uniform":
        return 1.0 / n_values
    return max(lk.get(feature, {}).get(value, UNIFORM_FLOOR), UNIFORM_FLOOR)


def classify(features: dict, weather_flags: dict, nearby_counts: dict) -> dict:
    kb = load_kb()
    feat_defs = kb["features"]
    known = {k: v for k, v in features.items() if v != "unknown"}

    scores, explain = {}, {}
    for name, p in kb["problems"].items():
        score = p["base_prior"]
        w_mult = 1.0
        for cond, active in weather_flags.items():
            if active:
                w_mult *= p["weather"].get(cond, 1.0)
        n = nearby_counts.get(name, 0)
        n_mult = min(1.0 + 0.15 * n, 2.5)
        lik = 1.0
        for k, v in known.items():
            n_vals = len([x for x in feat_defs[k] if x != "unknown"])
            lik *= _likelihood(p, k, v, n_vals)
        scores[name] = score * w_mult * n_mult * lik
        explain[name] = {"prior": score, "weather_x": round(w_mult, 2), "nearby_x": round(n_mult, 2), "nearby_cases": n}

    total = sum(scores.values()) or 1.0
    probs = {k: v / total for k, v in scores.items()}
    ranking = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)

    top, top_p = ranking[0]
    second_p = ranking[1][1] if len(ranking) > 1 else 0.0

    # Decision rule: confident only with enough evidence AND a clear winner.
    reasons = []
    if len(known) < config.MIN_KNOWN_FEATURES:
        reasons.append(f"only {len(known)} symptom(s) described")
    if top_p < config.CONFIDENCE_THRESHOLD:
        reasons.append(f"top probability {top_p:.2f} below {config.CONFIDENCE_THRESHOLD}")
    if top_p - second_p < config.MARGIN_THRESHOLD:
        reasons.append(f"too close to second option ({second_p:.2f})")
    if top == "other":
        reasons.append("best match is 'something else'")

    decision = "confident" if not reasons else "unsure"
    return {
        "ranking": [{"problem": k, "label": kb["problems"][k]["label"], "p": round(v, 3)} for k, v in ranking],
        "top": top,
        "confidence": round(top_p, 3),
        "decision": decision,
        "unsure_reasons": reasons,
        "known_features": known,
        "explain": explain,
    }
