"""Retention job (run daily, e.g. cron / Task Scheduler):
- delete cases (and their audio) where delete_after < today
- safety net: delete audio of answer_only cases that still has a file
- delete model call logs (data/logs/model_calls-*.jsonl) older than RETENTION_DAYS
Verified knowledge rows keep their anonymous symptom vector but lose the link to the deleted case.
"""
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Case, KnowledgeProfile  # noqa: E402
from app.pipeline import calllog  # noqa: E402
from app.storage import get_storage  # noqa: E402

log = logging.getLogger("cleanup")


def cleanup(session=None, today: date | None = None) -> dict:
    today = today or date.today()
    own = session is None
    session = session or SessionLocal()
    storage = get_storage()
    stats = {"cases_deleted": 0, "audio_deleted": 0}
    try:
        expired = session.scalars(select(Case).where(Case.delete_after < today)).all()
        ids = [c.id for c in expired]
        for c in expired:
            if c.audio_path:
                storage.delete(c.audio_path)
                stats["audio_deleted"] += 1
            session.delete(c)
        if ids:
            session.execute(update(KnowledgeProfile).where(KnowledgeProfile.case_id.in_(ids)).values(case_id=None))
        stats["cases_deleted"] = len(ids)

        leftovers = session.scalars(
            select(Case).where(Case.audio_consent == "answer_only", Case.audio_path.is_not(None))).all()
        for c in leftovers:
            storage.delete(c.audio_path)
            c.audio_path = None
            stats["audio_deleted"] += 1
        session.commit()
        stats["model_logs_deleted"] = calllog.cleanup(get_settings().retention_days, today)
        return stats
    finally:
        if own:
            session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print(cleanup())
