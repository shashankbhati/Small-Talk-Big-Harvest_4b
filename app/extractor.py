"""Turn a farmer's free description into a FIXED set of symptom features.

The small LLM (via Ollama) is only allowed to fill this form. Its output is
forced to a JSON schema with fixed allowed values, so it cannot write advice.
If Ollama is not running, a simple keyword fallback is used (English only).
"""
import json
import re

import requests

from . import config
from .classifier import load_kb

SYSTEM_PROMPT = """You extract crop symptoms from a coffee farmer's description.
Fill every field using ONLY the allowed values.
Use "unknown" when the farmer did not mention it. Never guess.
Do not give advice. Do not explain. Output JSON only.

Field meanings:
- spot_colour: colour of spots/patches on leaves (orange_yellow, brown, black, none)
- spot_location: where spots are on the leaf (underside = below/under/back of leaf, top = upper surface, both)
- powder: is there powder or dust on the spots (yes/no)
- leaf_drop: are leaves falling off (yes/no)
- leaf_yellowing: old_leaves = older/lower leaves turning yellow, all_leaves = whole plant yellow, no
- leaf_trails: tunnels, trails, or blisters inside the leaf (yes/no)
- wilting: plants drooping or wilting (yes/no)
- berry_damage: small_hole = small hole in the berry, dark_sunken = dark sunken patches on green berries, none
"""


def _schema(features: dict) -> dict:
    return {
        "type": "object",
        "properties": {k: {"type": "string", "enum": v} for k, v in features.items()},
        "required": list(features.keys()),
    }


def _clean(raw: dict, features: dict) -> dict:
    """Keep only allowed values; anything else becomes 'unknown'."""
    out = {}
    for k, allowed in features.items():
        v = str(raw.get(k, "unknown")).strip().lower()
        out[k] = v if v in allowed else "unknown"
    return out


def extract_with_llm(text: str, features: dict) -> dict | None:
    try:
        resp = requests.post(
            f"{config.OLLAMA_URL}/api/chat",
            json={
                "model": config.OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Farmer said: {text}"},
                ],
                "format": _schema(features),
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        return _clean(json.loads(content), features)
    except Exception:
        return None


# --- Fallback: simple English keyword rules (used only if the LLM is unavailable) ---
def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{w}", text) for w in words)


def extract_with_keywords(text: str, features: dict) -> dict:
    t = text.lower()
    f = {k: "unknown" for k in features}
    if _has(t, "orange", "yellow spot", "rust"):
        f["spot_colour"] = "orange_yellow"
    elif _has(t, "brown"):
        f["spot_colour"] = "brown"
    elif _has(t, "black"):
        f["spot_colour"] = "black"
    if _has(t, "under", "below", "back of the lea", "underside"):
        f["spot_location"] = "underside"
    elif _has(t, "on top", "upper", "top of the lea"):
        f["spot_location"] = "top"
    if _has(t, "powder", "dust"):
        f["powder"] = "yes"
    if _has(t, "falling", "fall off", "dropping", "drop off", "leaves fall"):
        f["leaf_drop"] = "yes"
    if _has(t, "old leaves", "older leaves", "lower leaves") and _has(t, "yellow"):
        f["leaf_yellowing"] = "old_leaves"
    elif _has(t, "whole plant", "all leaves", "all the leaves") and _has(t, "yellow"):
        f["leaf_yellowing"] = "all_leaves"
    if _has(t, "tunnel", "trail", "mine", "blister"):
        f["leaf_trails"] = "yes"
    if _has(t, "wilt", "droop", "dry and hanging"):
        f["wilting"] = "yes"
    if _has(t, "hole") and _has(t, "berr", "cherr", "bean"):
        f["berry_damage"] = "small_hole"
    elif _has(t, "berr", "cherr") and _has(t, "black", "dark", "rotten", "sunken"):
        f["berry_damage"] = "dark_sunken"
    return f


def extract_features(text: str) -> tuple[dict, str]:
    """Returns (features, method)."""
    features = load_kb()["features"]
    if not text or not text.strip():
        return {k: "unknown" for k in features}, "empty"
    llm = extract_with_llm(text, features)
    if llm is not None:
        return llm, f"llm:{config.OLLAMA_MODEL}"
    return extract_with_keywords(text, features), "keyword-fallback"
