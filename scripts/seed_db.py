"""Load config/profiles.yaml into knowledge_profiles as source=seed (idempotent)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.languages import profiles  # noqa: E402
from app.models import KnowledgeProfile  # noqa: E402


def seed(session=None) -> int:
    init_db()
    own = session is None
    session = session or SessionLocal()
    try:
        session.execute(delete(KnowledgeProfile).where(KnowledgeProfile.source == "seed"))
        # verified cases for conditions that are no longer in the knowledge base can't be answered
        stale = session.execute(delete(KnowledgeProfile).where(
            KnowledgeProfile.condition.not_in(list(profiles())))).rowcount
        if stale:
            print(f"Removed {stale} verified case(s) for conditions no longer in profiles.yaml.")
        for condition, vector in profiles().items():
            session.add(KnowledgeProfile(condition=condition, vector=vector, source="seed"))
        session.commit()
        return len(session.scalars(select(KnowledgeProfile).where(KnowledgeProfile.source == "seed")).all())
    finally:
        if own:
            session.close()


if __name__ == "__main__":
    print(f"Seeded {seed()} profiles.")
