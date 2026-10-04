import json

from sqlalchemy import select

from app.languages import symptoms
from app.models import Case, KnowledgeProfile
from app.pipeline import extract

AUTH = ("expert", "pw")


def set_llm(monkeypatch, **on):
    f = {k: 0 for k in symptoms()}
    f.update(on)
    monkeypatch.setattr(extract, "_chat", lambda m, s, p=None: json.dumps(f))


# ---------- M3 demo ----------

def test_demo_page(client):
    r = client.get("/demo")
    assert r.status_code == 200 and "MediaRecorder" in r.text


def test_demo_text_submit(client, monkeypatch):
    set_llm(monkeypatch, orange_powder_under_leaf=1, yellow_spots_on_leaf=1)
    r = client.post("/demo", data={"lang": "sw", "consent": "answer_only",
                                   "text": "Majani yana unga wa machungwa na madoa ya njano"})
    assert r.status_code == 200
    assert "leaf_rust" in r.text and "kutu ya majani" in r.text


def test_demo_model_switch_and_language(client, monkeypatch):
    used = []

    def chat(m, s, p=None):
        used.append(p)
        return json.dumps({k: 0 for k in symptoms()})

    monkeypatch.setattr(extract, "_chat", chat)
    r = client.post("/demo", data={"lang": "hi", "mode": "local", "text": "पत्तियों पर धब्बे"})
    assert used == ["ollama"]
    assert '<option value="hi" selected>' in r.text and '<option value="local" selected>' in r.text

    used.clear()
    r = client.post("/demo", data={"lang": "ar", "mode": "together", "text": "بقع على الأوراق"})
    assert used[0] == "together"
    assert '<option value="ar" selected>' in r.text


# ---------- M4 review + feedback loop ----------

def test_review_requires_auth(client):
    assert client.get("/review").status_code == 401
    assert client.get("/review", auth=("expert", "wrong")).status_code == 401


def test_feedback_loop(client, db, monkeypatch):
    # ambiguous input -> not sure -> review queue
    set_llm(monkeypatch, orange_powder_under_leaf=1, small_hole_in_berry=1)
    text = "Kuna unga wa machungwa kwenye majani na matundu madogo kwenye buni"
    client.post("/demo", data={"lang": "sw", "text": text})
    case = db.scalars(select(Case).where(Case.status == "in_review")).one()
    assert case.result == "not_sure"

    lst = client.get("/review", auth=AUTH)
    assert case.id in lst.text
    page = client.get(f"/review/{case.id}", auth=AUTH)
    assert page.status_code == 200 and "berry_borer" in page.text

    form = {"expert_label": "berry_borer", "reviewed_by": "Dr. Officer", "transcript_corrected": text}
    form.update({f"p_{k}": str(v) for k, v in case.parameters.items()})
    r = client.post(f"/review/{case.id}", data=form, auth=AUTH, follow_redirects=False)
    assert r.status_code == 303

    db.expire_all()
    labeled = db.get(Case, case.id)
    assert (labeled.status, labeled.expert_label, labeled.reviewed_by) == ("labeled", "berry_borer", "Dr. Officer")
    assert labeled.transcript_corrected is None  # unchanged transcript is not stored twice
    kp = db.scalars(select(KnowledgeProfile).where(KnowledgeProfile.source == "verified_case")).one()
    assert kp.condition == "berry_borer" and kp.case_id == case.id

    # same input now returns a sure answer
    r = client.post("/demo", data={"lang": "sw", "text": text})
    assert "berry_borer" in r.text and "toboa buni" in r.text


def test_unclear_label_does_not_learn(client, db, monkeypatch):
    set_llm(monkeypatch, orange_powder_under_leaf=1)
    client.post("/demo", data={"lang": "sw", "text": "unga"})
    case = db.scalars(select(Case)).one()
    client.post(f"/review/{case.id}", data={"expert_label": "unclear"}, auth=AUTH)
    assert db.scalars(select(KnowledgeProfile).where(KnowledgeProfile.source == "verified_case")).first() is None


def test_invalid_label_rejected(client, db, monkeypatch):
    set_llm(monkeypatch)
    client.post("/demo", data={"lang": "sw", "text": "x"})
    case = db.scalars(select(Case)).one()
    assert client.post(f"/review/{case.id}", data={"expert_label": "made_up"}, auth=AUTH).status_code == 400
