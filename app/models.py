import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import get_settings
from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _delete_after() -> date:
    return (_now() + timedelta(days=get_settings().retention_days)).date()


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    channel: Mapped[str] = mapped_column(String(10))
    phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    phone_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(8))
    detected_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    audio_consent: Mapped[str] = mapped_column(String(20), default="n/a")
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_corrected: Mapped[str | None] = mapped_column(Text, nullable=True)
    asr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    stt_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)  # which STT answered
    llm_provider: Mapped[str | None] = mapped_column(String(20), nullable=True)  # which LLM answered
    parameters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[str | None] = mapped_column(String(40), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    top2: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # farm location (rounded to ~1 km) and the weather used for this case (features, risks, daily data)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    place: Mapped[str | None] = mapped_column(String(160), nullable=True)
    weather: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    not_sure_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="processing", index=True)
    expert_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delete_after: Mapped[date] = mapped_column(Date, default=_delete_after)


class KnowledgeProfile(Base):
    __tablename__ = "knowledge_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    condition: Mapped[str] = mapped_column(String(40), index=True)
    vector: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(20))  # seed | verified_case
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
