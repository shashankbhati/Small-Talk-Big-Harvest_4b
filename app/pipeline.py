"""The whole flow: transcript -> features -> context -> classifier -> response."""
import time

from . import db
from .classifier import classify, load_kb
from .extractor import extract_features
from .weather import get_recent_weather, weather_flags


def run_pipeline(transcript: str, farmer: dict) -> dict:
    t0 = time.time()
    kb = load_kb()

    features, method = extract_features(transcript)
    weather = get_recent_weather(farmer["lat"], farmer["lon"])
    flags = weather_flags(weather)
    nearby = db.nearby_confirmed_counts(farmer["lat"], farmer["lon"])

    if all(v == "unknown" for v in features.values()):
        result = {
            "ranking": [], "top": None, "confidence": 0.0, "decision": "no_input",
            "unsure_reasons": ["no symptoms understood"], "known_features": {}, "explain": {},
        }
        response_key = "no_input"
    else:
        result = classify(features, flags, nearby)
        response_key = result["top"] if result["decision"] == "confident" else "unsure"

    case_id = None
    if result["decision"] != "no_input":
        case_id = db.save_case(
            farmer, transcript, features, result,
            store_transcript=bool(farmer.get("consent_improve")),
        )

    return {
        "case_id": case_id,
        "transcript": transcript,
        "extraction_method": method,
        "features": features,
        "weather": weather,
        "weather_flags": flags,
        "nearby_confirmed": nearby,
        "result": result,
        "response_key": response_key,
        "response_text": kb["advice"][response_key],
        "seconds": round(time.time() - t0, 2),
    }
