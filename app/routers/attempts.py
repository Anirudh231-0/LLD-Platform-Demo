import hashlib

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.domain import Attempt, Problem, Submission
from app.schemas import AttemptCreate, AttemptOut, SubmissionCreate, SubmissionOut, EvaluationOut
from app.services.evaluation_service import create_pending_evaluation, run_evaluation
from app.services.evaluator import get_default_evaluator

router = APIRouter(prefix="/api/attempts", tags=["attempts"])

DEMO_LEARNER_ID = "demo-learner"  # single fixed user for MVP, see DESIGN_NOTE.md scope


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()


@router.post("", response_model=AttemptOut)
def start_attempt(payload: AttemptCreate, db: Session = Depends(get_db)):
    problem = db.query(Problem).filter(Problem.id == payload.problem_id).first()
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")

    attempt = Attempt(problem_id=problem.id, learner_id=DEMO_LEARNER_ID)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


@router.get("/{attempt_id}", response_model=AttemptOut)
def get_attempt(attempt_id: str, db: Session = Depends(get_db)):
    attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    return attempt


@router.get("/{attempt_id}/submissions", response_model=list[SubmissionOut])
def list_submissions(attempt_id: str, db: Session = Depends(get_db)):
    attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")
    return attempt.submissions


@router.post("/{attempt_id}/submissions", response_model=SubmissionOut)
def submit_solution(
    attempt_id: str,
    payload: SubmissionCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found")

    content_hash = _content_hash(payload.content)

    # Idempotency / duplicate-submission guard (helping guide section 10):
    # resubmitting identical content on the same attempt returns the
    # existing submission instead of creating a duplicate evaluation.
    existing = (
        db.query(Submission)
        .filter(Submission.attempt_id == attempt_id, Submission.content_hash == content_hash)
        .first()
    )
    if existing is not None:
        return existing

    next_version = len(attempt.submissions) + 1
    submission = Submission(
        attempt_id=attempt_id,
        content=payload.content,
        content_hash=content_hash,
        version=next_version,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    # Store first, evaluate after (guide section 10) - the submission
    # is safely persisted even if the evaluator call below fails.
    evaluation = create_pending_evaluation(db, submission)
    background_tasks.add_task(
        run_evaluation, db=db, evaluation_id=evaluation.id, evaluator=get_default_evaluator()
    )

    return submission


@router.get("/{attempt_id}/submissions/{submission_id}/evaluation", response_model=EvaluationOut)
def get_evaluation_for_submission(attempt_id: str, submission_id: str, db: Session = Depends(get_db)):
    submission = (
        db.query(Submission)
        .options(joinedload(Submission.evaluation))
        .filter(Submission.id == submission_id, Submission.attempt_id == attempt_id)
        .first()
    )
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    if submission.evaluation is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return submission.evaluation
