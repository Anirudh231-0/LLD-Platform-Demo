from app.models.domain import Attempt, EvaluationStatus, Problem, Submission
from app.services.evaluation_service import create_pending_evaluation, run_evaluation
from app.services.evaluator import EvaluationResult, EvaluatorError, FeedbackItemResult


class _FakeSuccessEvaluator:
    name = "fake-success"

    def evaluate(self, problem_prompt, requirements, submission_content):
        return EvaluationResult(
            overall_summary="Looks good.",
            items=[
                FeedbackItemResult(
                    criterion="class_responsibilities",
                    score=4,
                    evidence="uses a ParkingLot class",
                    concern=None,
                    suggestion=None,
                )
            ],
            evaluator_name=self.name,
        )


class _FakeErroringEvaluator:
    name = "fake-error"

    def evaluate(self, problem_prompt, requirements, submission_content):
        raise EvaluatorError("simulated AI failure")


def _make_submission(db_session, content="class ParkingLot: responsibility is to assign spots"):
    problem = Problem(
        title="Test Problem", prompt="p", requirements="r", constraints="c"
    )
    db_session.add(problem)
    db_session.commit()

    attempt = Attempt(problem_id=problem.id, learner_id="demo-learner")
    db_session.add(attempt)
    db_session.commit()

    submission = Submission(
        attempt_id=attempt.id, content=content, content_hash="hash1", version=1
    )
    db_session.add(submission)
    db_session.commit()
    db_session.refresh(submission)
    return submission


def test_pending_evaluation_created_on_submission(db_session):
    submission = _make_submission(db_session)
    evaluation = create_pending_evaluation(db_session, submission)
    assert evaluation.status == EvaluationStatus.PENDING


def test_successful_evaluation_reaches_completed(db_session):
    submission = _make_submission(db_session)
    evaluation = create_pending_evaluation(db_session, submission)

    run_evaluation(db_session, evaluation.id, _FakeSuccessEvaluator())

    db_session.refresh(evaluation)
    assert evaluation.status == EvaluationStatus.COMPLETED
    assert evaluation.overall_summary == "Looks good."
    assert len(evaluation.feedback_items) == 1
    assert evaluation.completed_at is not None


def test_ai_error_marks_evaluation_failed(db_session):
    submission = _make_submission(db_session)
    evaluation = create_pending_evaluation(db_session, submission)

    run_evaluation(db_session, evaluation.id, _FakeErroringEvaluator())

    db_session.refresh(evaluation)
    assert evaluation.status == EvaluationStatus.FAILED
    assert "simulated AI failure" in evaluation.error_message


def test_deterministic_failure_skips_ai_call_entirely(db_session):
    # Too short -> deterministic check fails -> AI evaluator should never run.
    submission = _make_submission(db_session, content="short")
    evaluation = create_pending_evaluation(db_session, submission)

    class _ShouldNotBeCalledEvaluator:
        name = "should-not-run"

        def evaluate(self, *args, **kwargs):
            raise AssertionError("AI evaluator should not be called when deterministic check fails")

    run_evaluation(db_session, evaluation.id, _ShouldNotBeCalledEvaluator())

    db_session.refresh(evaluation)
    assert evaluation.status == EvaluationStatus.FAILED
    assert "too short" in evaluation.error_message.lower()
