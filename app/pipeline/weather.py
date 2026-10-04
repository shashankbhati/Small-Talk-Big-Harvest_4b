"""Past weather at the farm -> per-condition weather risk with plain-language reasons.

Open-Meteo (free, no API key): geocoding for a typed place name, and the forecast API with past_days
for daily rain / temperature / humidity. Rules live in config/weather.yaml. Weather never decides on its
own: match() only adds a small bonus to the symptom score. Any failure here -> no weather, same answer flow.
Coordinates are rounded to 2 decimals (~1 km) before they are stored or sent anywhere.
"""
import logging
from datetime import date, datetime, timezone
from functools import lru_cache

import httpx
import yaml

from app.config import CONFIG_DIR, get_settings
from app.pipeline import calllog

log = logging.getLogger(__name__)

DAILY = ["precipitation_sum", "temperature_2m_max", "temperature_2m_mean", "relative_humidity_2m_mean"]
WINDOWS = (14, 21, 30, 42, 60)
RAIN_DAY_MM = 1.0
HUMID_RH = 85.0
HOT_MAX_C = 30.0

_cache: dict[tuple, dict] = {}


@lru_cache
def config() -> dict:
    with open(CONFIG_DIR / "weather.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def round_coord(v: float) -> float:
    return round(float(v), 2)


# ---------- Open-Meteo calls ----------

def geocode(place: str) -> dict | None:
    """Typed village / town -> {lat, lon, place} (best match), or None."""
    s = get_settings()
    place = place.strip()
    if not place or not s.weather_enabled:
        return None

    def call():
        r = httpx.get(s.geocode_url, params={"name": place, "count": 1, "format": "json"},
                      timeout=s.weather_timeout)
        r.raise_for_status()
        return (r.json().get("results") or [None])[0]

    try:
        hit = calllog.record("geocode", "open-meteo", "geocoding", {"place": place}, call,
                             lambda h: {"found": h is not None})
    except Exception:
        log.warning("geocoding failed", exc_info=True)
        return None
    if not hit:
        return None
    name = ", ".join(x for x in (hit.get("name"), hit.get("admin1"), hit.get("country")) if x)
    return {"lat": round_coord(hit["latitude"]), "lon": round_coord(hit["longitude"]), "place": name}


def fetch_daily(lat: float, lon: float, days: int) -> dict:
    """Daily weather for the last `days` full days (today excluded): {"time": [...], <var>: [...]}."""
    s = get_settings()
    key = (lat, lon, days, date.today())
    if key in _cache:
        return _cache[key]

    def call():
        r = httpx.get(s.weather_url, params={
            "latitude": lat, "longitude": lon, "past_days": days, "forecast_days": 1,
            "daily": ",".join(DAILY), "timezone": "auto"}, timeout=s.weather_timeout)
        r.raise_for_status()
        return r.json()["daily"]

    daily = calllog.record("weather", "open-meteo", "forecast+past_days", {"lat": lat, "lon": lon, "days": days},
                           call, lambda d: {"days": len(d.get("time", []))})
    # past days come first; drop today (forecast_days=1)
    daily = {k: v[:days] for k, v in daily.items() if isinstance(v, list)}
    _cache[key] = daily
    return daily


# ---------- features + rules ----------

def _longest(flags: list[bool]) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def features(daily: dict) -> dict[str, float]:
    """Summaries over the last 14/21/30/42/60 days (days with missing values are skipped)."""
    rows = list(zip(daily.get("precipitation_sum", []), daily.get("temperature_2m_max", []),
                    daily.get("temperature_2m_mean", []), daily.get("relative_humidity_2m_mean", [])))
    out: dict[str, float] = {}
    for w in WINDOWS:
        win = rows[-w:]
        rain = [r for r, *_ in win if r is not None]
        wet = [r >= RAIN_DAY_MM for r in rain]
        means = [t for _, _, t, _ in win if t is not None]
        out[f"rain_mm_{w}"] = round(sum(rain), 1)
        out[f"rain_days_{w}"] = sum(wet)
        out[f"dry_days_{w}"] = len(wet) - sum(wet)
        out[f"humid_days_{w}"] = sum(1 for *_, h in win if h is not None and h >= HUMID_RH)
        out[f"hot_days_{w}"] = sum(1 for _, mx, _, _ in win if mx is not None and mx >= HOT_MAX_C)
        out[f"warm_wet_days_{w}"] = sum(1 for r, _, t, _ in win
                                        if r is not None and t is not None and r >= RAIN_DAY_MM and 18 <= t <= 26)
        out[f"cool_wet_days_{w}"] = sum(1 for r, _, t, _ in win
                                        if r is not None and t is not None and r >= RAIN_DAY_MM and t <= 22)
        out[f"mean_temp_{w}"] = round(sum(means) / len(means), 1) if means else None
        out[f"longest_wet_spell_{w}"] = _longest(wet)
        out[f"longest_dry_spell_{w}"] = _longest([not x for x in wet])
    return out


def _met(rule: dict, feats: dict) -> bool:
    v = feats.get(rule["feature"])
    if v is None:
        return False
    return ("min" not in rule or v >= rule["min"]) and ("max" not in rule or v <= rule["max"])


def risks(feats: dict) -> dict[str, dict]:
    """{condition: {score -1..1, bonus, level, reasons_for, reasons_against}} for conditions with rules."""
    cfg = config()
    max_bonus = float(cfg.get("max_bonus", 0.1))
    out = {}
    for cond, rule in (cfg.get("rules") or {}).items():
        fav = [r for r in rule.get("favours") or [] if _met(r, feats)]
        ag = [r for r in rule.get("against") or [] if _met(r, feats)]
        n = max(len(rule.get("favours") or []), 1)
        score = max(-1.0, min(1.0, (len(fav) - len(ag)) / n))
        out[cond] = {
            "score": round(score, 2),
            "bonus": round(score * max_bonus, 3),
            "level": "high" if score >= 0.67 else "medium" if score > 0 else "low" if score < 0 else "neutral",
            "reasons_for": [r["reason"].format(v=feats[r["feature"]]) for r in fav],
            "reasons_against": [r["reason"].format(v=feats[r["feature"]]) for r in ag],
        }
    return out


def for_location(lat: float, lon: float) -> dict | None:
    """Fetch + reason. Returns the dict stored on the case (case.weather), or None if weather is unavailable."""
    s = get_settings()
    if not s.weather_enabled:
        return None
    lat, lon = round_coord(lat), round_coord(lon)
    days = int(config().get("lookback_days", 60))
    try:
        daily = fetch_daily(lat, lon, days)
    except Exception as e:
        log.warning("weather unavailable (%s)", type(e).__name__)
        return None
    if not daily.get("time"):
        return None
    feats = features(daily)
    return {
        "source": "open-meteo",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lat": lat, "lon": lon,
        "period": [daily["time"][0], daily["time"][-1]],
        "summary": {k: feats[k] for k in ("rain_mm_30", "rain_days_30", "humid_days_30", "mean_temp_30",
                                          "longest_wet_spell_30", "longest_dry_spell_60", "hot_days_60")},
        "features": feats,
        "risks": risks(feats),
        "daily": daily,
    }


def bonuses(weather: dict | None) -> dict[str, float]:
    return {c: r["bonus"] for c, r in ((weather or {}).get("risks") or {}).items() if r.get("bonus")}
