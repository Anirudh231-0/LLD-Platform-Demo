from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.domain import Attempt
from app.routers.attempts import DEMO_LEARNER_ID
from app.schemas import AttemptHistoryOut

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("", response_model=list[AttemptHistoryOut])
def get_history(db: Session = Depends(get_db)):
    attempts = (
        db.query(Attempt)
        .options(joinedload(Attempt.submissions))
        .filter(Attempt.learner_id == DEMO_LEARNER_ID)
        .order_by(Attempt.created_at.desc())
        .all()
    )

    rows = []
    for attempt in attempts:
        latest = attempt.latest_submission
        rows.append(
            AttemptHistoryOut(
                attempt_id=attempt.id,
                problem_id=attempt.problem_id,
                problem_title=attempt.problem.title,
                created_at=attempt.created_at,
                latest_submission=latest,
                latest_evaluation=latest.evaluation if latest else None,
            )
        )
    return rows
