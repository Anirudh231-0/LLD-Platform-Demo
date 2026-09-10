"""
Core domain model for the LLD Practice Platform.

Design intent (see DESIGN_NOTE.md for full rationale):

    Problem   1 --- n   Attempt   1 --- n   Submission
                            |
                            1
                            |
                            n
                       Evaluation   1 --- n   FeedbackItem

- Problem: static practice content (seeded, not user-authored in MVP).
- Attempt: one learner's ongoing practice session against a Problem.
           A learner can retry -> multiple Submissions under one Attempt.
- Submission: one immutable snapshot of the learner's design text.
              Only the *latest* Submission on an Attempt is "active",
              but old ones are kept for history/audit.
- Evaluation: the judged result of ONE Submission. Owns a state machine
              (PENDING -> EVALUATING -> COMPLETED / FAILED) so the API
              can return quickly and evaluate asynchronously.
- FeedbackItem: one rubric criterion's verdict for an Evaluation
                (score, evidence, concern, suggestion).

Why Evaluation is separate from Submission (not just fields on it):
  it lets us plug in a different Evaluator (rule engine, human review)
  later without touching Submission at all -- see Evaluator interface
  in app/services/evaluator.py and "Change Test B" in DESIGN_NOTE.md.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    ForeignKey,
    Enum as SAEnum,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


class EvaluationStatus(str, enum.Enum):
    PENDING = "PENDING"
    EVALUATING = "EVALUATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Problem(Base):
    """A fixed LLD practice problem (e.g. 'Design a Parking Lot')."""

    __tablename__ = "problems"

    id = Column(String, primary_key=True, default=_uuid)
    title = Column(String, nullable=False)
    prompt = Column(Text, nullable=False)
    requirements = Column(Text, nullable=False)  # newline-separated, kept simple for MVP
    constraints = Column(Text, nullable=False)  # newline-separated
    created_at = Column(DateTime, default=datetime.utcnow)

    attempts = relationship("Attempt", back_populates="problem")


class Attempt(Base):
    """A learner's practice session on one Problem. Holds 1..n Submissions."""

    __tablename__ = "attempts"

    id = Column(String, primary_key=True, default=_uuid)
    problem_id = Column(String, ForeignKey("problems.id"), nullable=False)
    learner_id = Column(String, nullable=False, default="demo-learner")  # single demo user in MVP
    created_at = Column(DateTime, default=datetime.utcnow)

    problem = relationship("Problem", back_populates="attempts")
    submissions = relationship(
        "Submission", back_populates="attempt", order_by="Submission.created_at"
    )

    @property
    def latest_submission(self):
        return self.submissions[-1] if self.submissions else None


class Submission(Base):
    """
    One immutable snapshot of a learner's design text for an Attempt.
    Retrying = creating a new Submission on the same Attempt, not a new Attempt.
    """

    __tablename__ = "submissions"
    __table_args__ = (
        # Deterministic duplicate-submission guard (Design guide section 10):
        # the same exact content re-submitted on the same attempt is a no-op,
        # not a fresh evaluation.
        UniqueConstraint("attempt_id", "content_hash", name="uq_attempt_content_hash"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    attempt_id = Column(String, ForeignKey("attempts.id"), nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)  # 1st, 2nd, ... submission on this attempt
    created_at = Column(DateTime, default=datetime.utcnow)

    attempt = relationship("Attempt", back_populates="submissions")
    evaluation = relationship(
        "Evaluation", back_populates="submission", uselist=False
    )


class Evaluation(Base):
    """
    The judged result of one Submission. Explicit state machine so the
    API can return immediately after storing the submission and let
    evaluation happen in the background (Design guide section 10).
    """

    __tablename__ = "evaluations"

    id = Column(String, primary_key=True, default=_uuid)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=False, unique=True)
    status = Column(SAEnum(EvaluationStatus), nullable=False, default=EvaluationStatus.PENDING)
    evaluator_name = Column(String, nullable=False, default="ai-rubric-v1")  # which Evaluator impl ran
    overall_summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    submission = relationship("Submission", back_populates="evaluation")
    feedback_items = relationship(
        "FeedbackItem", back_populates="evaluation", cascade="all, delete-orphan"
    )


class FeedbackItem(Base):
    """One rubric criterion's verdict within an Evaluation."""

    __tablename__ = "feedback_items"

    id = Column(String, primary_key=True, default=_uuid)
    evaluation_id = Column(String, ForeignKey("evaluations.id"), nullable=False)
    criterion = Column(String, nullable=False)  # e.g. "Class Responsibilities"
    score = Column(Integer, nullable=False)  # 1-5 scale, see RUBRIC in services/rubric.py
    evidence = Column(Text, nullable=False)  # quote/reference from the submission
    concern = Column(Text, nullable=True)
    suggestion = Column(Text, nullable=True)

    evaluation = relationship("Evaluation", back_populates="feedback_items")
