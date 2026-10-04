"""Recent weather for a location from NASA POWER (free, no key).

Offline-first: results are cached to disk. If there is no internet,
the last cached value is used; if none exists, the weather signal is neutral.
"""
import json
from datetime import date, timedelta

import requests

from . import config

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"


def _load_cache() -> dict:
    if config.WEATHER_CACHE.exists():
        try:
            return json.loads(config.WEATHER_CACHE.read_text())
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    config.WEATHER_CACHE.write_text(json.dumps(cache, indent=2))


def get_recent_weather(lat: float, lon: float, days: int = 14) -> dict:
    """Returns {'rain_mm': total rain, 'temp_c': mean temp, 'source': ...} for the last `days` days."""
    key = f"{round(lat, 2)},{round(lon, 2)}"
    cache = _load_cache()
    # NASA POWER lags a few days behind today, so look at the window ending 3 days ago.
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days - 1)
    try:
        resp = requests.get(
            POWER_URL,
            params={
                "parameters": "PRECTOTCORR,T2M",
                "community": "AG",
                "latitude": lat,
                "longitude": lon,
                "start": start.strftime("%Y%m%d"),
                "end": end.strftime("%Y%m%d"),
                "format": "JSON",
            },
            timeout=8,
        )
        resp.raise_for_status()
        p = resp.json()["properties"]["parameter"]
        rain = [v for v in p["PRECTOTCORR"].values() if v is not None and v > -900]
        temp = [v for v in p["T2M"].values() if v is not None and v > -900]
        if not rain or not temp:
            raise ValueError("no valid weather values")
        result = {
            "rain_mm": round(sum(rain), 1),
            "temp_c": round(sum(temp) / len(temp), 1),
            "window": f"{start} to {end}",
            "source": "NASA POWER",
        }
        cache[key] = result
        _save_cache(cache)
        return result
    except Exception:
        if key in cache:
            return {**cache[key], "source": cache[key].get("source", "cache") + " (cached, offline)"}
        return {"rain_mm": None, "temp_c": None, "window": None, "source": "unavailable (neutral)"}


def weather_flags(w: dict) -> dict:
    """Turn numbers into coarse conditions used by the classifier.
    Thresholds are rough starting values for a 14-day window; tune per region."""
    flags = {"wet": False, "dry": False, "warm": False, "cool": False}
    if w.get("rain_mm") is not None:
        flags["wet"] = w["rain_mm"] >= 50
        flags["dry"] = w["rain_mm"] < 10
    if w.get("temp_c") is not None:
        flags["warm"] = w["temp_c"] >= 21
        flags["cool"] = w["temp_c"] < 18
    return flags
