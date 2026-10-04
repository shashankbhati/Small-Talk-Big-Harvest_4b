from sqlalchemy import select

from app.languages import conditions, languages, symptoms
from app.models import KnowledgeProfile


def test_config_loads():
    assert set(languages()) == {"sw", "ar", "hi"}
    assert len(symptoms()) == 24
    assert len(conditions()) == 9


def test_profiles_use_known_symptoms():
    from app.languages import profiles

    keys = set(symptoms())
    for cond, vec in profiles().items():
        assert set(vec) <= keys, cond
        assert all(v in (-1, 0, 1) for v in vec.values())


def test_seed(db):
    rows = db.scalars(select(KnowledgeProfile)).all()
    assert len(rows) == 9
    assert all(r.source == "seed" for r in rows)


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["voice_webhook"].endswith("/voice/incoming")
