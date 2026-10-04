import logging
from datetime import date, timedelta

from sqlalchemy import select

from app.models import Case, KnowledgeProfile
from app.privacy import decrypt_phone, encrypt_phone, hash_phone

PHONE = "+254700000001"


def test_hash_is_stable_salted_and_not_plain():
    h = hash_phone(PHONE)
    assert h == hash_phone(PHONE) and len(h) == 64
    assert PHONE not in h and h != hash_phone("+254700000002")
    import hashlib

    assert h != hashlib.sha256(PHONE.encode()).hexdigest()  # salt applied


def test_encrypt_roundtrip():
    tok = encrypt_phone(PHONE)
    assert PHONE not in tok and decrypt_phone(tok) == PHONE
    assert encrypt_phone(PHONE) != tok  # Fernet is randomized


def test_cleanup_deletes_expired_cases_and_audio(db):
    from app.cases import create_case
    from app.storage import get_storage
    from scripts.cleanup import cleanup

    st = get_storage()
    st.save("old.ogg", b"x")
    st.save("leftover.ogg", b"x")
    st.save("keep.ogg", b"x")
    old = create_case(db, "voice", "sw", phone=PHONE, audio_consent="keep_for_training", audio_path="old.ogg")
    old.delete_after = date.today() - timedelta(days=1)
    db.add(KnowledgeProfile(condition="leaf_rust", vector={"orange_powder_under_leaf": 1}, source="verified_case",
                            case_id=old.id))
    left = create_case(db, "voice", "sw", audio_consent="answer_only", audio_path="leftover.ogg")
    keep = create_case(db, "voice", "sw", audio_consent="keep_for_training", audio_path="keep.ogg")
    db.commit()

    stats = cleanup(db)
    assert stats["cases_deleted"] == 1 and stats["audio_deleted"] == 2
    db.expire_all()
    assert db.get(Case, old.id) is None and not st.exists("old.ogg")
    assert db.get(Case, left.id).audio_path is None and not st.exists("leftover.ogg")
    assert db.get(Case, keep.id).audio_path == "keep.ogg" and st.exists("keep.ogg")
    kp = db.scalars(select(KnowledgeProfile).where(KnowledgeProfile.source == "verified_case")).one()
    assert kp.case_id is None  # anonymous vector kept, link removed


def test_delete_after_default(db):
    from app.cases import create_case

    c = create_case(db, "sms", "sw")
    assert c.delete_after >= date.today() + timedelta(days=364)


def test_no_phone_or_transcript_in_info_logs(client, monkeypatch, caplog):
    import json

    from app.languages import symptoms
    from app.pipeline import extract

    monkeypatch.setattr(extract, "_chat", lambda m, s, p=None: json.dumps({k: 0 for k in symptoms()}))
    secret_text = "SECRET-TRANSCRIPT-unga"
    with caplog.at_level(logging.INFO):
        client.post("/sms/incoming", data={"From": PHONE, "Body": secret_text})
    for rec in caplog.records:
        if rec.levelno >= logging.INFO:
            assert PHONE not in rec.getMessage() and secret_text not in rec.getMessage()
