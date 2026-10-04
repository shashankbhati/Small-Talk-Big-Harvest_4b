"""Registration app API: register a farm once, then read the answers given on later calls.

The app keeps a bearer token; the server stores only its hash. There is no SMS code check in this
prototype, so registering a number again issues a new token and hides cases from before that moment.
"""
import hashlib
import re
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select

from app.db import SessionLocal
from app.farmers import delete_caller_data, farmer_language, normalize_phone
from app.languages import conditions
from app.models import Case, Farmer, _delete_after, _now
from app.pipeline import weather
from app.pipeline.answer import render_answer
from app.pipeline.match import NOT_SURE
from app.privacy import hash_phone

router = APIRouter(prefix="/api/farmers")
_bearer = HTTPBearer(auto_error=False)

SHOWN = ("answered", "in_review", "labeled", "error")
_SENTENCE_END = re.compile(r"(?<=[।.!?؟])\s+")
_WEATHER_LINE = {
    "hi": "पिछले 30 दिन: {rain} मिमी बारिश, {days} दिन बारिश, औसत तापमान {temp}°C",
    "en": "Last 30 days: {rain} mm rain, {days} rainy days, average temperature {temp}°C",
}

Crop = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class Registration(BaseModel):
    phone: str = Field(min_length=7, max_length=20)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    place: str = Field("", max_length=160)
    crops: list[Crop] = Field(default_factory=list, max_length=8)
    area_acres: float = Field(gt=0, le=1000)
    consent: bool


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _location(body: Registration) -> dict:
    """App GPS wins, else geocode the typed village; rounded to ~1 km."""
    place = body.place.strip() or None
    if body.lat is not None and body.lon is not None:
        return {"lat": weather.round_coord(body.lat), "lon": weather.round_coord(body.lon), "place": place}
    if place:
        return weather.geocode(place) or {"lat": None, "lon": None, "place": place}
    return {"lat": None, "lon": None, "place": None}


def _apply(farmer: Farmer, body: Registration) -> None:
    loc = _location(body)
    farmer.lat, farmer.lon, farmer.place = loc["lat"], loc["lon"], loc["place"]
    farmer.crops = list(body.crops)
    farmer.area_acres = body.area_acres


def current_farmer_id(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"})
    with SessionLocal() as session:
        fid = session.scalar(select(Farmer.id).where(Farmer.token_hash == _token_hash(creds.credentials)))
    if fid is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Bearer"})
    return fid


@router.post("", status_code=status.HTTP_201_CREATED)
def register(body: Registration) -> dict:
    if not body.consent:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "consent is required")
    try:
        phone_hash = hash_phone(normalize_phone(body.phone))
    except ValueError:
        raise HTTPException(422, "invalid phone number")
    token = secrets.token_urlsafe(32)
    with SessionLocal() as session:
        farmer = session.scalar(select(Farmer).where(Farmer.phone_hash == phone_hash))
        if farmer is None:
            farmer = Farmer(phone_hash=phone_hash, language=farmer_language())
            session.add(farmer)
        farmer.token_hash = _token_hash(token)
        farmer.registered_at = _now()
        farmer.delete_after = _delete_after()
        _apply(farmer, body)
        session.commit()
    return {"token": token}


@router.put("/me")
def update(body: Registration, farmer_id: str = Depends(current_farmer_id)) -> dict:
    """Change the farm details. The phone number can't be changed here: register the new number instead."""
    with SessionLocal() as session:
        _apply(session.get(Farmer, farmer_id), body)
        session.commit()
    return {"ok": True}


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(farmer_id: str = Depends(current_farmer_id)) -> Response:
    with SessionLocal() as session:
        delete_caller_data(session, session.get(Farmer, farmer_id).phone_hash)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _answer_key(case: Case) -> str:
    """An expert's label replaces the system's guess once the case is reviewed."""
    if case.status == "labeled" and case.expert_label in conditions():
        return case.expert_label
    if case.status == "answered" and case.result:
        return case.result
    return NOT_SURE


def _weather_line(case: Case) -> str | None:
    s = (case.weather or {}).get("summary")
    if not s:
        return None
    line = _WEATHER_LINE.get(case.language, _WEATHER_LINE["en"])
    return line.format(rain=s.get("rain_mm_30"), days=s.get("rain_days_30"), temp=s.get("mean_temp_30"))


@router.get("/me/cases")
def my_cases(farmer_id: str = Depends(current_farmer_id)) -> list[dict]:
    with SessionLocal() as session:
        farmer = session.get(Farmer, farmer_id)
        cases = session.scalars(
            select(Case).where(Case.phone_hash == farmer.phone_hash, Case.created_at >= farmer.registered_at,
                               Case.status.in_(SHOWN)).order_by(Case.created_at.desc()).limit(50)).all()
    out = []
    for c in cases:
        key = _answer_key(c)
        text = render_answer(key, c.language).text  # human-written text only, same as the call
        out.append({
            "id": c.id,
            "created_at": c.created_at.isoformat(timespec="seconds") + "Z",
            "status": "in_review" if key == NOT_SURE else "answered",
            "result_title": _SENTENCE_END.split(text, maxsplit=1)[0],
            "advice_text": text,
            "weather_summary": _weather_line(c),
        })
    return out
