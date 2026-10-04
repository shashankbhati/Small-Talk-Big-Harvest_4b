from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.farmers import normalize_phone
from app.models import Case, Farmer
from app.privacy import hash_phone

PHONE = "+919876543210"
BODY = {"phone": "9876543210", "lat": 12.41987, "lon": 75.73912, "place": "", "crops": ["coffee", "maize"],
        "area_acres": 2.5, "consent": True}


def register(client, **over) -> str:
    r = client.post("/api/farmers", json={**BODY, **over})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def call(client, db, phone=PHONE) -> Case:
    client.post("/voice/incoming", data={"From": phone})
    db.expire_all()
    return db.scalars(select(Case).order_by(Case.created_at.desc())).first()


# ---------- phone numbers ----------

@pytest.mark.parametrize("raw,expected", [
    ("9876543210", "+919876543210"),       # national number -> default country code
    ("09876543210", "+919876543210"),
    ("+49 151 2345-6789", "+4915123456789"),
    ("004915123456789", "+4915123456789"),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "+12", "+0123456789", "98765x3210"])
def test_normalize_phone_rejects(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


# ---------- registration ----------

def test_register_stores_hashes_and_rounded_location(client, db):
    token = register(client)
    f = db.scalars(select(Farmer)).one()
    assert f.phone_hash == hash_phone(PHONE)  # matches Twilio's E.164 `From`
    assert f.token_hash != token and len(f.token_hash) == 64
    assert (f.lat, f.lon) == (12.42, 75.74)  # ~1 km
    assert (f.crops, f.area_acres, f.language) == (["coffee", "maize"], 2.5, "hi")


def test_register_needs_consent_and_a_valid_phone(client, db):
    assert client.post("/api/farmers", json={**BODY, "consent": False}).status_code == 400
    assert client.post("/api/farmers", json={**BODY, "phone": "12345x7"}).status_code == 422
    assert client.post("/api/farmers", json={**BODY, "area_acres": 0}).status_code == 422
    assert client.post("/api/farmers", json={**BODY, "lat": 123}).status_code == 422
    assert db.scalars(select(Farmer)).all() == []


def test_register_geocodes_a_typed_village(client, db, monkeypatch):
    from app.pipeline import weather

    monkeypatch.setattr(weather, "geocode", lambda place: {"lat": 12.42, "lon": 75.74, "place": "Madikeri, India"})
    register(client, lat=None, lon=None, place="Madikeri")
    f = db.scalars(select(Farmer)).one()
    assert (f.lat, f.lon, f.place) == (12.42, 75.74, "Madikeri, India")

    monkeypatch.setattr(weather, "geocode", lambda place: None)  # weather service down: keep the name
    register(client, lat=None, lon=None, place="Nowhere")
    db.expire_all()
    f = db.scalars(select(Farmer)).one()
    assert (f.lat, f.lon, f.place) == (None, None, "Nowhere")


def test_update_details(client, db):
    token = register(client)
    r = client.put("/api/farmers/me", json={**BODY, "crops": ["beans"], "area_acres": 4}, headers=auth(token))
    assert r.status_code == 200
    f = db.scalars(select(Farmer)).one()
    assert (f.crops, f.area_acres) == (["beans"], 4)


def test_api_needs_a_valid_token(client):
    assert client.get("/api/farmers/me/cases").status_code == 401
    assert client.get("/api/farmers/me/cases", headers=auth("wrong")).status_code == 401
    assert client.put("/api/farmers/me", json=BODY, headers=auth("wrong")).status_code == 401
    assert client.delete("/api/farmers/me", headers=auth("wrong")).status_code == 401


# ---------- the call finds the farm ----------

def test_registered_caller_skips_language_menu_and_gets_location(client, db):
    register(client)
    r = client.post("/voice/incoming", data={"From": PHONE})
    assert "/voice/consent" in r.text and "/voice/language" not in r.text
    case = db.scalars(select(Case)).one()
    assert (case.language, case.lat, case.lon) == ("hi", 12.42, 75.74)


def test_unregistered_caller_gets_language_menu(client, db):
    r = client.post("/voice/incoming", data={"From": "+254700000001"})
    assert "/voice/language" in r.text
    assert db.scalars(select(Case)).one().lat is None


# ---------- answers in the app ----------

def test_cases_show_the_same_fixed_answer_as_the_call(client, db):
    from app.languages import answers

    token = register(client)
    assert client.get("/api/farmers/me/cases", headers=auth(token)).json() == []

    case = call(client, db)
    assert client.get("/api/farmers/me/cases", headers=auth(token)).json() == []  # still processing

    case.status, case.result = "answered", "leaf_rust"
    case.weather = {"summary": {"rain_mm_30": 120.5, "rain_days_30": 14, "mean_temp_30": 22.1}}
    db.commit()
    (c,) = client.get("/api/farmers/me/cases", headers=auth(token)).json()
    text = answers("hi")["leaf_rust"]["text"]
    assert c["status"] == "answered" and c["advice_text"] == text
    assert text.startswith(c["result_title"]) and len(c["result_title"]) < len(text)
    assert "120.5" in c["weather_summary"] and c["created_at"].endswith("Z")


def test_unsure_case_is_in_review_until_an_expert_labels_it(client, db):
    from app.languages import answers

    token = register(client)
    case = call(client, db)
    case.status, case.result = "in_review", "not_sure"
    db.commit()
    (c,) = client.get("/api/farmers/me/cases", headers=auth(token)).json()
    assert c["status"] == "in_review" and c["advice_text"] == answers("hi")["not_sure"]["text"]
    assert c["weather_summary"] is None

    case.status, case.expert_label = "labeled", "berry_borer"
    db.commit()
    (c,) = client.get("/api/farmers/me/cases", headers=auth(token)).json()
    assert c["status"] == "answered" and c["advice_text"] == answers("hi")["berry_borer"]["text"]

    case.expert_label = "unclear"
    db.commit()
    (c,) = client.get("/api/farmers/me/cases", headers=auth(token)).json()
    assert c["status"] == "in_review"


def test_cases_of_other_numbers_are_not_shown(client, db):
    token = register(client)
    other = call(client, db, phone="+919000000001")
    other.status, other.result = "answered", "leaf_rust"
    db.commit()
    assert client.get("/api/farmers/me/cases", headers=auth(token)).json() == []


def test_registering_a_number_again_hides_earlier_cases(client, db):
    old = register(client)
    case = call(client, db)
    case.status, case.result = "answered", "leaf_rust"
    db.commit()
    assert len(client.get("/api/farmers/me/cases", headers=auth(old)).json()) == 1

    new = register(client)  # no SMS code check: a new registration must not reveal the old history
    assert client.get("/api/farmers/me/cases", headers=auth(old)).status_code == 401
    assert client.get("/api/farmers/me/cases", headers=auth(new)).json() == []
    assert len(db.scalars(select(Farmer)).all()) == 1


# ---------- delete my data ----------

def test_delete_from_the_app(client, db):
    token = register(client)
    call(client, db)
    assert client.delete("/api/farmers/me", headers=auth(token)).status_code == 204
    db.expire_all()
    assert db.scalars(select(Farmer)).all() == [] and db.scalars(select(Case)).all() == []
    assert client.get("/api/farmers/me/cases", headers=auth(token)).status_code == 401


def test_key_9_on_the_call_deletes_the_registration_too(client, db):
    register(client)
    case = call(client, db)
    r = client.post(f"/voice/consent?case_id={case.id}", data={"Digits": "9"})
    assert "<Hangup" in r.text
    db.expire_all()
    assert db.scalars(select(Farmer)).all() == [] and db.scalars(select(Case)).all() == []


def test_cleanup_deletes_expired_registrations(client, db):
    from scripts.cleanup import cleanup

    register(client)
    register(client, phone="9000000001")
    f = db.scalars(select(Farmer).where(Farmer.phone_hash == hash_phone(PHONE))).one()
    f.delete_after = date.today() - timedelta(days=1)
    db.commit()
    assert cleanup(db)["farmers_deleted"] == 1
    assert len(db.scalars(select(Farmer)).all()) == 1


# ---------- browser access ----------

def test_cors_preflight_allows_the_app(client):
    r = client.options("/api/farmers/me/cases", headers={
        "Origin": "https://app.example", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization,ngrok-skip-browser-warning"})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "*"
