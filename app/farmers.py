"""Farmer registry helpers shared by the registration API and the voice line."""
import re

from sqlalchemy import delete, select

from app.config import get_settings
from app.languages import default_language, languages
from app.models import Case, Farmer
from app.privacy import hash_phone

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str) -> str:
    """Typed number -> E.164, the format Twilio sends as `From`. Raises ValueError if it can't be one."""
    p = re.sub(r"[\s\-()]", "", raw or "")
    if p.startswith("00"):
        p = "+" + p[2:]
    if not p.startswith("+"):  # national number: add the default country code
        p = get_settings().default_country_code + p.lstrip("0")
    if not _E164.match(p):
        raise ValueError("not a phone number")
    return p


def farmer_language() -> str:
    lang = get_settings().farmer_language
    return lang if lang in languages() else default_language()


def find_farmer(session, phone: str | None) -> Farmer | None:
    if not phone:
        return None
    return session.scalar(select(Farmer).where(Farmer.phone_hash == hash_phone(phone)))


def delete_caller_data(session, phone_hash: str) -> None:
    """Delete-my-data: every case of this number and its registry entry."""
    session.execute(delete(Case).where(Case.phone_hash == phone_hash))
    session.execute(delete(Farmer).where(Farmer.phone_hash == phone_hash))
    session.commit()
