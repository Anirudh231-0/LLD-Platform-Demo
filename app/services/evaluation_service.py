"""
Orchestrates the Evaluation state machine:

    PENDING --(deterministic check passes)--> EVALUATING --> COMPLETED
       \\--(deterministic check fails)-------------------> FAILED
                                        \\--(AI call errors)--> FAILED

Kept separate from the Evaluator strategy (services/evaluator.py) on
purpose: this module owns *when* and *how state transitions happen*
and is persistence-aware; Evaluator only knows how to judge text and
has no idea a database exists. That separation is what lets us unit
test Evaluator with zero DB setup, and test the state machine with a
fake Evaluator (see tests/).
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.domain import Evaluation, EvaluationStatus, FeedbackItem, Submission
from app.services.evaluator import Evaluator, EvaluatorError, run_deterministic_checks


def create_pending_evaluation(db: Session, submission: Submission) -> Evaluation:
    """
    Called synchronously in the submit request so the learner immediately
    sees a status, per helping guide section 10 ("store the submission
    before evaluation starts so it is not lost on evaluator failure").
    """
    evaluation = Evaluation(submission_id=submission.id, status=EvaluationStatus.PENDING)
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)
    return evaluation


def run_evaluation(db: Session, evaluation_id: str, evaluator: Evaluator) -> None:
    """
    Runs the actual evaluation. Designed to be called from a FastAPI
    BackgroundTask so the submit request isn't blocked on a slow AI call.
    """
    evaluation = db.query(Evaluation).filter(Evaluation.id == evaluation_id).first()
    if evaluation is None:
        return  # nothing to do - shouldn't happen, but don't crash a background task

    submission = evaluation.submission
    problem = submission.attempt.problem

    deterministic = run_deterministic_checks(submission.content)
    if not deterministic.passed:
        evaluation.status = EvaluationStatus.FAILED
        evaluation.error_message = deterministic.reason
        evaluation.completed_at = datetime.utcnow()
        db.commit()
        return

    evaluation.status = EvaluationStatus.EVALUATING
    evaluation.evaluator_name = evaluator.name
    db.commit()

    try:
        result = evaluator.evaluate(
            problem_prompt=problem.prompt,
            requirements=problem.requirements,
            submission_content=submission.content,
        )
    except EvaluatorError as exc:
        evaluation.status = EvaluationStatus.FAILED
        evaluation.error_message = str(exc)
        evaluation.completed_at = datetime.utcnow()
        db.commit()
        return

    evaluation.overall_summary = result.overall_summary
    evaluation.status = EvaluationStatus.COMPLETED
    evaluation.completed_at = datetime.utcnow()
    for item in result.items:
        db.add(
            FeedbackItem(
                evaluation_id=evaluation.id,
                criterion=item.criterion,
                score=item.score,
                evidence=item.evidence,
                concern=item.concern,
                suggestion=item.suggestion,
            )
        )
    db.commit()
