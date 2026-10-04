from app.models import Case
from app.privacy import encrypt_phone, hash_phone


def create_case(session, channel: str, language: str, *, phone: str | None = None,
                transcript: str | None = None, audio_consent: str = "n/a",
                audio_path: str | None = None, status: str = "processing",
                lat: float | None = None, lon: float | None = None, place: str | None = None) -> Case:
    case = Case(
        channel=channel,
        language=language,
        phone_hash=hash_phone(phone) if phone else None,
        phone_encrypted=encrypt_phone(phone) if phone else None,
        transcript=transcript,
        audio_consent=audio_consent,
        audio_path=audio_path,
        status=status,
        lat=lat,
        lon=lon,
        place=place,
    )
    session.add(case)
    session.commit()
    return case
