"""
Evaluation strategy layer.

Design rationale (see DESIGN_NOTE.md "Change Test B"):
  Evaluation is behind an `Evaluator` interface. The practice/submission
  flow (routers/attempts.py) only depends on this interface, never on
  a concrete AI implementation. Adding a RuleBasedEvaluator or
  HumanReviewEvaluator later means writing a new class here and
  changing a config value -- not touching the submission flow.

Two layers of checking, per the helping guide (section 6):
  1. `run_deterministic_checks` - fast, free, rule-based. Runs BEFORE
     the AI call. If a submission fails these, we skip the (slow,
     costly) AI call entirely and fail fast with a clear reason.
  2. `AIRubricEvaluator` - judgment-heavy criteria that benefit from
     an LLM (responsibilities, coupling, extensibility, etc.), scored
     against the fixed rubric in services/rubric.py with required
     structured output (criterion -> score -> evidence -> concern ->
     suggestion), never an unconstrained "rate this design" prompt.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.services.rubric import RUBRIC_CRITERIA, SCORE_MIN, SCORE_MAX, criteria_keys


# ---------------------------------------------------------------------------
# Deterministic checks (no AI, no network, instant)
# ---------------------------------------------------------------------------

@dataclass
class DeterministicCheckResult:
    passed: bool
    reason: str | None = None


MIN_SUBMISSION_LENGTH = 40  # characters - just enough to reject empty/lazy submissions


def run_deterministic_checks(content: str) -> DeterministicCheckResult:
    """Cheap structural checks that don't need an LLM call."""
    stripped = content.strip()

    if len(stripped) < MIN_SUBMISSION_LENGTH:
        return DeterministicCheckResult(
            passed=False,
            reason=f"Submission is too short to evaluate (minimum {MIN_SUBMISSION_LENGTH} characters).",
        )

    # A text LLD design should at least gesture at some class/entity structure.
    # This is a weak heuristic on purpose -- it exists to catch "empty effort"
    # submissions, not to judge quality (that's the AI's job).
    structure_hints = ["class", "object", "responsibilit", "interface", "->", ":"]
    if not any(hint in stripped.lower() for hint in structure_hints):
        return DeterministicCheckResult(
            passed=False,
            reason=(
                "Submission doesn't appear to describe any classes, objects, or "
                "responsibilities. Include your class/entity breakdown."
            ),
        )

    return DeterministicCheckResult(passed=True)


# ---------------------------------------------------------------------------
# Evaluator interface
# ---------------------------------------------------------------------------

@dataclass
class FeedbackItemResult:
    criterion: str
    score: int
    evidence: str
    concern: str | None
    suggestion: str | None


@dataclass
class EvaluationResult:
    overall_summary: str
    items: list[FeedbackItemResult]
    evaluator_name: str


class Evaluator(ABC):
    """
    Strategy interface for judging a submission. Any evaluator
    (AI, rule-based, human-review-backed) implements this same shape,
    so the calling code (routers/services/evaluation_service.py)
    never needs to know which one is behind it.
    """

    name: str

    @abstractmethod
    def evaluate(self, problem_prompt: str, requirements: str, submission_content: str) -> EvaluationResult:
        ...


class EvaluatorError(Exception):
    """Raised when an evaluator fails to produce a usable result."""


# ---------------------------------------------------------------------------
# AI rubric evaluator (Claude)
# ---------------------------------------------------------------------------

class AIRubricEvaluator(Evaluator):
    """
    Uses the Gemini API with a fixed rubric and forced structured
    (JSON) output. 
    """

    name = "ai-rubric-gemini-3.5-flash-lite"

    def __init__(self, model: str = "gemini-3.5-flash-lite", client=None):
        self.model = model
        self._client = client  

    def _get_client(self):
        if self._client is not None:
            return self._client
        import google.generativeai as genai
        api_key = os.environ.get("GEMINI_API_KEY") 
        if not api_key:
            raise ValueError("API key not found. Please set GEMINI_API_KEY in your .env")

        genai.configure(api_key = api_key)
        return genai 

        

    def _build_prompt(self, problem_prompt: str, requirements: str, submission_content: str) -> str:
        criteria_desc = "\n".join(
            f"- {c['key']}: {c['label']} -- {c['description']}" for c in RUBRIC_CRITERIA
        )
        return f"""You are evaluating a learner's Low-Level Design (LLD) solution against a fixed rubric.

PROBLEM PROMPT:
{problem_prompt}

REQUIREMENTS:
{requirements}

LEARNER'S SUBMISSION:
{submission_content}

Evaluate the submission against EXACTLY these rubric criteria, no others:
{criteria_desc}

For each criterion, score {SCORE_MIN}-{SCORE_MAX} (1=poor, 5=excellent).
"evidence" must reference something specific and concrete from the learner's submission
(quote or closely paraphrase a part of it) -- never a generic statement.
"concern" and "suggestion" may be null if there is nothing meaningful to add for that criterion.

Respond with ONLY valid JSON, no markdown fences, no preamble, in exactly this shape:
{{
  "overall_summary": "2-3 sentence summary of the design's main strengths and weaknesses",
  "items": [
    {{
      "criterion": "<one of: {', '.join(criteria_keys())}>",
      "score": <int {SCORE_MIN}-{SCORE_MAX}>,
      "evidence": "<specific reference to the submission>",
      "concern": "<specific concern or null>",
      "suggestion": "<specific actionable suggestion or null>"
    }}
  ]
}}

Include exactly one item per criterion listed above."""

    def evaluate(self, problem_prompt: str, requirements: str, submission_content: str) -> EvaluationResult:
        genai = self._get_client()
        prompt = self._build_prompt(problem_prompt, requirements, submission_content)

        try:
            model = genai.GenerativeModel(self.model)
            response = model.generate_content(
                prompt,
                generation_config = genai.GenerationConfig(
                    response_mime_type = "application/json",
                    max_output_tokens = 2000
                )
            )
            raw_text = response.text
        except Exception as exc:  # network/auth/rate-limit errors etc.
            raise EvaluatorError(f"AI evaluator request failed: {exc}") from exc

        return self._parse_response(raw_text)

    def _parse_response(self, raw_text: str) -> EvaluationResult:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.split("\n", 1)[-1] if cleaned.lower().startswith("json") else cleaned

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise EvaluatorError(f"AI evaluator returned non-JSON output: {exc}") from exc

        valid_keys = set(criteria_keys())
        items = []
        for raw_item in data.get("items", []):
            criterion = raw_item.get("criterion")
            if criterion not in valid_keys:
                continue  # ignore hallucinated criteria rather than failing the whole evaluation
            score = int(raw_item.get("score", 0))
            score = max(SCORE_MIN, min(SCORE_MAX, score))  # clamp defensively
            items.append(
                FeedbackItemResult(
                    criterion=criterion,
                    score=score,
                    evidence=raw_item.get("evidence") or "",
                    concern=raw_item.get("concern"),
                    suggestion=raw_item.get("suggestion"),
                )
            )

        if not items:
            raise EvaluatorError("AI evaluator returned no valid rubric items.")

        return EvaluationResult(
            overall_summary=data.get("overall_summary", ""),
            items=items,
            evaluator_name=self.name,
        )


# ---------------------------------------------------------------------------
# Factory - swap evaluator implementation via config, not code changes
# ---------------------------------------------------------------------------

def get_default_evaluator() -> Evaluator:
    return AIRubricEvaluator()
