"""Orchestrates STT -> extract -> match -> answer and writes the case."""
import logging
import time

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Case, KnowledgeProfile
from app.pipeline import calllog
from app.pipeline.extract import ExtractionError, extract_parameters
from app.pipeline.match import NOT_SURE, MatchResult, match

log = logging.getLogger(__name__)


def knowledge(session) -> list[tuple[str, dict]]:
    return [(r.condition, r.vector) for r in session.scalars(select(KnowledgeProfile)).all()]


def _apply(case: Case, m: MatchResult) -> None:
    case.result = m.result
    case.score = m.score
    case.top2 = m.top2
    case.not_sure_reason = m.not_sure_reason
    case.status = "answered" if m.sure else "in_review"


def _delete_audio_if_answer_only(case: Case) -> None:
    if case.audio_consent == "answer_only" and case.audio_path:
        from app.storage import get_storage

        try:
            get_storage().delete(case.audio_path)
        finally:
            case.audio_path = None


def _process(case: Case, session) -> None:
    if case.audio_path and not case.transcript:
        from app.pipeline.stt import transcribe
        from app.storage import get_storage

        with get_storage().local_path(case.audio_path) as path:
            res = transcribe(path, case.language)
        text, detected, conf = res
        case.transcript, case.detected_language, case.asr_confidence = text, detected, conf
        case.stt_provider = getattr(res, "provider", None)
        if detected and detected != case.language:
            log.info("case %s: language mismatch (chosen=%s detected=%s)", case.id, case.language, detected)
        if conf is not None and conf < get_settings().asr_min_conf:
            _apply(case, MatchResult(NOT_SURE, None, [], "low_asr_confidence"))
            return

    try:
        flags = extract_parameters(case.transcript or "", case.language)
        case.parameters = dict(flags)
        case.llm_provider = getattr(flags, "provider", None)
    except ExtractionError as e:
        log.warning("case %s: extraction failed (%s)", case.id, e)
        _apply(case, MatchResult(NOT_SURE, None, [], "extraction_failed"))
        return

    if case.lat is not None and case.lon is not None and case.weather is None:
        from app.pipeline import weather

        case.weather = weather.for_location(case.lat, case.lon)
    from app.pipeline.weather import bonuses

    _apply(case, match(case.parameters, knowledge(session), bonuses(case.weather)))


def run_case(case_id: str, session=None) -> Case:
    own = session is None
    session = session or SessionLocal()
    case = session.get(Case, case_id)
    token = calllog.current_case.set(case_id)
    t0 = time.perf_counter()
    source = "audio" if case.audio_path and not case.transcript else "text"
    try:
        _process(case, session)
    except Exception:
        log.exception("case %s failed", case_id)
        case.status = "error"
        case.result = NOT_SURE
    finally:
        try:
            _delete_audio_if_answer_only(case)
        except Exception:
            log.exception("case %s: audio deletion failed", case_id)
        session.commit()
        calllog.write(
            "case", latency_ms=round((time.perf_counter() - t0) * 1000), channel=case.channel,
            language=case.language, input=source, transcript=case.transcript,
            detected_language=case.detected_language, asr_confidence=case.asr_confidence,
            stt_provider=case.stt_provider, llm_provider=case.llm_provider,
            symptoms={k: v for k, v in (case.parameters or {}).items() if v},
            result=case.result, score=case.score, top2=case.top2, not_sure_reason=case.not_sure_reason,
            status=case.status, place=case.place, lat=case.lat, lon=case.lon,
            weather_summary=(case.weather or {}).get("summary"),
            weather_bonus={c: r["bonus"] for c, r in ((case.weather or {}).get("risks") or {}).items() if r["bonus"]})
        calllog.current_case.reset(token)
        if own:
            session.close()
    return case
