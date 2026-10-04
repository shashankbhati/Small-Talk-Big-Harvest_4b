import json

from sqlalchemy import select

from app.languages import symptoms
from app.models import Case
from app.pipeline import extract

PHONE = "+254700000001"


def set_llm(monkeypatch, **on):
    f = {k: 0 for k in symptoms()}
    f.update(on)
    monkeypatch.setattr(extract, "_chat", lambda m, s, p=None: json.dumps(f))


# ---------- M5 voice ----------

def test_voice_flow(client, db, monkeypatch, tmp_path):
    from app.routes import voice

    r = client.post("/voice/incoming", data={"From": PHONE, "CallSid": "CA1"})
    assert r.status_code == 200 and "<Gather" in r.text
    case = db.scalars(select(Case)).one()
    assert case.phone_hash and case.phone_encrypted and PHONE not in case.phone_encrypted

    from app.languages import languages

    lang, cfg = next(iter(languages().items()))
    r = client.post(f"/voice/language?case_id={case.id}", data={"Digits": cfg["ivr_key"]})
    assert "<Record" in r.text and "/voice/consent" not in r.text  # no consent question: straight to recording
    db.expire_all()
    case = db.get(Case, case.id)
    assert (case.language, case.audio_consent) == (lang, "answer_only")

    # pretend the background job finished
    seen = {}
    monkeypatch.setattr(voice, "process_recording", lambda cid, url, sid: seen.update(cid=cid, url=url, sid=sid))
    r = client.post(f"/voice/recorded?case_id={case.id}",
                    data={"RecordingUrl": "https://api.twilio.com/rec/RE1", "RecordingSid": "RE1"})
    assert "/voice/result" in r.text and seen["sid"] == "RE1"

    r = client.post(f"/voice/result?case_id={case.id}&try=1")
    assert "<Pause" in r.text and "try=2" in r.text  # still processing

    case.status, case.result = "answered", "leaf_rust"
    db.commit()
    r = client.post(f"/voice/result?case_id={case.id}&try=2")
    assert "<Hangup" in r.text
    assert f"/{lang}/leaf_rust.mp3" in r.text or "<Say" in r.text  # answer in the chosen language


def test_voice_invalid_digit_repeats_then_defaults(client, db):
    client.post("/voice/incoming", data={"From": PHONE})
    case = db.scalars(select(Case)).one()
    r = client.post(f"/voice/language?case_id={case.id}&attempt=0", data={"Digits": "7"})
    assert "attempt=1" in r.text
    r = client.post(f"/voice/language?case_id={case.id}&attempt=1", data={"Digits": "7"})
    assert "<Record" in r.text
    db.expire_all()
    from app.languages import default_language

    assert db.get(Case, case.id).language == default_language()


def test_voice_timeout_goes_to_review(client, db):
    client.post("/voice/incoming", data={"From": PHONE})
    case = db.scalars(select(Case)).one()
    from app.config import get_settings

    r = client.post(f"/voice/result?case_id={case.id}&try={get_settings().voice_max_tries}")
    assert "<Hangup" in r.text
    db.expire_all()
    c = db.get(Case, case.id)
    assert (c.status, c.result) == ("in_review", "not_sure")


def test_voice_no_consent_digit_defaults_to_answer_only(client, db):
    client.post("/voice/incoming", data={"From": PHONE})
    case = db.scalars(select(Case)).one()
    client.post(f"/voice/consent?case_id={case.id}", data={})
    db.expire_all()
    assert db.get(Case, case.id).audio_consent == "answer_only"


def test_voice_delete_my_data(client, db):
    client.post("/voice/incoming", data={"From": PHONE})
    client.post("/voice/incoming", data={"From": PHONE})
    case = db.scalars(select(Case)).first()
    client.post(f"/voice/language?case_id={case.id}", data={"Digits": "9"})
    db.expire_all()
    assert db.scalars(select(Case)).all() == []


def test_signature_validation(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "twilio_validate", True)
    monkeypatch.setattr(get_settings(), "twilio_auth_token", "secret")
    assert client.post("/voice/incoming", data={"From": PHONE}).status_code == 403

    from twilio.request_validator import RequestValidator

    params = {"From": PHONE}
    url = "http://testserver/voice/incoming"
    sig = RequestValidator("secret").compute_signature(url, params)
    r = client.post("/voice/incoming", data=params, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200


# ---------- M6 SMS ----------

def test_sms_language_detection():
    from app.routes.sms import detect_language

    assert detect_language("AR أوراق") == ("ar", "أوراق")
    assert detect_language("hi: पत्तियाँ")[0] == "hi"
    assert detect_language("أوراق البن عليها مسحوق برتقالي")[0] == "ar"
    assert detect_language("पत्तियों पर नारंगी पाउडर")[0] == "hi"
    assert detect_language("majani yana unga")[0] == "sw"
    assert detect_language("SWAHILI is not a prefix")[0] == "sw"


def test_sms_arabic_reply(client, monkeypatch):
    set_llm(monkeypatch, orange_powder_under_leaf=1, yellow_spots_on_leaf=1)
    body = "أوراق البن عليها مسحوق برتقالي تحت الورقة وبقع صفراء"
    r = client.post("/sms/incoming", data={"From": PHONE, "Body": body})
    assert "<Message>" in r.text and "صدأ أوراق البن" in r.text
    assert "رقمك محمي" in r.text  # privacy line on first contact
    r = client.post("/sms/incoming", data={"From": PHONE, "Body": body})
    assert "رقمك محمي" not in r.text
