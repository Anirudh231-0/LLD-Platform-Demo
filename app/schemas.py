from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProblemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    prompt: str
    requirements: str
    constraints: str


class AttemptCreate(BaseModel):
    problem_id: str


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    problem_id: str
    created_at: datetime


class SubmissionCreate(BaseModel):
    content: str


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    attempt_id: str
    version: int
    content: str
    created_at: datetime


class FeedbackItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    criterion: str
    score: int
    evidence: str
    concern: str | None
    suggestion: str | None


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    submission_id: str
    status: str
    evaluator_name: str
    overall_summary: str | None
    error_message: str | None
    feedback_items: list[FeedbackItemOut] = []


class AttemptHistoryOut(BaseModel):
    """One row in the learner's attempt history list."""

    attempt_id: str
    problem_id: str
    problem_title: str
    created_at: datetime
    latest_submission: SubmissionOut | None
    latest_evaluation: EvaluationOut | None
