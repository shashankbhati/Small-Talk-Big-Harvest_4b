"""Expert review queue. Only human-verified labels enter the knowledge base."""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.languages import conditions, symptoms
from app.models import Case, KnowledgeProfile
from app.templating import templates

router = APIRouter(prefix="/review")
_basic = HTTPBasic()

UNCLEAR = "unclear"


def require_expert(creds: HTTPBasicCredentials = Depends(_basic)) -> str:
    s = get_settings()
    ok_user = secrets.compare_digest(creds.username.encode(), s.review_user.encode())
    ok_pw = secrets.compare_digest(creds.password.encode(), s.review_password.encode())
    if not (ok_user and ok_pw):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})
    return creds.username


def _get(session, case_id: str) -> Case:
    case = session.get(Case, case_id)
    if not case:
        raise HTTPException(404)
    return case


@router.get("")
def review_list(request: Request, show: str = "in_review", _u: str = Depends(require_expert)):
    with SessionLocal() as session:
        q = select(Case).order_by(Case.created_at.desc())
        if show != "all":
            q = q.where(Case.status == show)
        cases = session.scalars(q.limit(200)).all()
    return templates.TemplateResponse(request, "review_list.html", {"cases": cases, "show": show})


@router.get("/{case_id}")
def review_case(request: Request, case_id: str, _u: str = Depends(require_expert)):
    with SessionLocal() as session:
        case = _get(session, case_id)
    return templates.TemplateResponse(request, "review_case.html", {
        "c": case, "conditions": conditions() + [UNCLEAR], "symptoms": symptoms(),
    })


@router.get("/{case_id}/audio")
def review_audio(case_id: str, _u: str = Depends(require_expert)):
    from app.storage import get_storage

    with SessionLocal() as session:
        case = _get(session, case_id)
    if not case.audio_path:
        raise HTTPException(404)
    return Response(get_storage().read(case.audio_path), media_type="audio/ogg",
                    headers={"Cache-Control": "no-store"})


@router.post("/{case_id}")
async def review_submit(request: Request, case_id: str, user: str = Depends(require_expert)):
    form = await request.form()
    label = str(form.get("expert_label", ""))
    if label not in conditions() + [UNCLEAR]:
        raise HTTPException(400, "invalid label")
    with SessionLocal() as session:
        case = _get(session, case_id)
        params = dict(case.parameters or {k: 0 for k in symptoms()})
        for k in symptoms():  # expert may correct the extracted symptom flags
            v = form.get(f"p_{k}")
            if v in ("-1", "0", "1"):
                params[k] = int(v)
        corrected = str(form.get("transcript_corrected", "")).strip()
        case.transcript_corrected = corrected if corrected and corrected != (case.transcript or "") else None
        case.parameters = params
        case.expert_label = label
        case.reviewed_by = str(form.get("reviewed_by", "")).strip() or user
        case.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        case.status = "labeled"
        if label != UNCLEAR and any(v != 0 for v in params.values()):
            session.add(KnowledgeProfile(condition=label, vector=params, source="verified_case", case_id=case.id))
        session.commit()
    return RedirectResponse("/review", status_code=303)
