import json
from datetime import date, timedelta

import httpx

from app.languages import languages, symptoms
from app.models import Case
from app.pipeline import extract, weather
from app.pipeline.match import match

AUTH = ("expert", "pw")


def daily(days=60, rain=0.0, tmax=28.0, tmean=22.0, rh=70.0):
    """Open-Meteo-shaped daily block: `days` past days + today."""
    start = date.today() - timedelta(days=days)
    n = days + 1
    return {"time": [(start + timedelta(days=i)).isoformat() for i in range(n)],
            "precipitation_sum": [rain] * n, "temperature_2m_max": [tmax] * n,
            "temperature_2m_mean": [tmean] * n, "relative_humidity_2m_mean": [rh] * n}


def fake_get(weather_daily, geo=None, seen=None):
    def get(url, params=None, timeout=None):
        if seen is not None:
            seen.append((url, params))
        req = httpx.Request("GET", url)
        if "geocoding" in url:
            return httpx.Response(200, json={"results": [geo]} if geo else {}, request=req)
        return httpx.Response(200, json={"daily": weather_daily}, request=req)
    return get


def set_llm(monkeypatch, **on):
    f = {k: 0 for k in symptoms()}
    f.update(on)
    monkeypatch.setattr(extract, "_chat", lambda m, s, p=None: json.dumps(f))


def lang():
    return next(iter(languages()))


# ---------- features and rules ----------

def test_features_drop_today_and_count():
    d = daily(rain=5.0, tmean=22.0, rh=90.0)
    d = {k: v[:60] for k, v in d.items()}  # what fetch_daily keeps
    f = weather.features(d)
    assert f["rain_days_30"] == 30 and f["rain_mm_30"] == 150.0
    assert f["humid_days_21"] == 21 and f["warm_wet_days_42"] == 42
    assert f["longest_wet_spell_30"] == 30 and f["longest_dry_spell_60"] == 0


def test_wet_weather_favours_rust_and_berry_disease_not_scale():
    f = weather.features({k: v[:60] for k, v in daily(rain=5.0, tmean=21.0, rh=90.0).items()})
    r = weather.risks(f)
    assert r["leaf_rust"]["level"] == "high" and r["leaf_rust"]["bonus"] > 0
    assert r["coffee_berry_disease"]["level"] == "high"
    assert r["green_scale"]["bonus"] < 0 and r["green_scale"]["reasons_against"]
    assert "coffee_wilt_disease" not in r  # no weather rule -> no effect


def test_dry_hot_weather_favours_green_scale():
    f = weather.features({k: v[:60] for k, v in daily(rain=0.0, tmax=32.0, tmean=25.0, rh=50.0).items()})
    r = weather.risks(f)
    assert r["green_scale"]["level"] == "high"
    assert r["leaf_rust"]["bonus"] < 0


# ---------- matcher: weather breaks ties, never answers alone ----------

PROFILES = [("cercospora", {"brown_spot_grey_center": 1, "leaves_yellowing": 1, "leaves_falling": 1}),
            ("green_scale", {"black_sooty_mold": 1, "leaves_yellowing": 1, "leaves_falling": 1})]


def test_weather_breaks_a_tie():
    params = {"leaves_yellowing": 1, "leaves_falling": 1}  # 1.0 vs 1.0
    assert match(params, PROFILES).not_sure_reason == "too_close"
    m = match(params, PROFILES, {"cercospora": 0.1, "green_scale": -0.1})
    assert m.result == "cercospora"


def test_weather_cannot_rescue_a_weak_match():
    params = {"brown_spot_grey_center": 1, "black_sooty_mold": 1}  # 0.5 vs 0.5
    m = match(params, PROFILES, {"cercospora": 0.1, "green_scale": -0.1})
    assert m.result == "not_sure" and m.not_sure_reason == "weak_match"


# ---------- demo end to end ----------

def test_demo_with_gps_stores_weather(client, db, monkeypatch):
    seen = []
    monkeypatch.setattr(weather.httpx, "get", fake_get(daily(rain=5.0, tmean=21.0, rh=90.0), seen=seen))
    weather._cache.clear()
    set_llm(monkeypatch, orange_powder_under_leaf=1, yellow_spots_on_leaf=1)
    r = client.post("/demo", data={"lang": lang(), "text": "x", "lat": "-3.3712", "lon": "36.6831"})
    assert r.status_code == 200 and "Weather at the farm" in r.text and "leaf_rust" in r.text

    case = db.query(Case).order_by(Case.created_at.desc()).first()
    assert (case.lat, case.lon) == (-3.37, 36.68)  # rounded to ~1 km
    assert seen[0][1]["latitude"] == -3.37 and seen[0][1]["past_days"] == 60
    assert case.weather["risks"]["leaf_rust"]["level"] == "high"
    assert len(case.weather["daily"]["time"]) == 60
    assert client.get(f"/review/{case.id}", auth=AUTH).text.count("Weather at the farm") == 1


def test_demo_geocodes_typed_place(client, db, monkeypatch):
    geo = {"name": "Moshi", "admin1": "Kilimanjaro", "country": "Tanzania", "latitude": -3.3349, "longitude": 37.3404}
    monkeypatch.setattr(weather.httpx, "get", fake_get(daily(), geo=geo))
    weather._cache.clear()
    set_llm(monkeypatch, orange_powder_under_leaf=1, yellow_spots_on_leaf=1)
    client.post("/demo", data={"lang": lang(), "text": "x", "place": "Moshi"})
    case = db.query(Case).order_by(Case.created_at.desc()).first()
    assert case.place == "Moshi, Kilimanjaro, Tanzania" and (case.lat, case.lon) == (-3.33, 37.34)
    assert case.weather is not None


def test_weather_failure_still_answers(client, db, monkeypatch):
    def down(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(weather.httpx, "get", down)
    weather._cache.clear()
    set_llm(monkeypatch, orange_powder_under_leaf=1, yellow_spots_on_leaf=1)
    r = client.post("/demo", data={"lang": lang(), "text": "x", "lat": "-3.37", "lon": "36.68"})
    case = db.query(Case).order_by(Case.created_at.desc()).first()
    assert r.status_code == 200 and case.weather is None and case.result == "leaf_rust"
    assert "Weather not available" in r.text
