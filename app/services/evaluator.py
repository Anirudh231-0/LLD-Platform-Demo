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

SDK note (2026-09): this uses the current `google-genai` package
(`from google import genai`), NOT the legacy `google-generativeai`
package. The legacy package's support (including bug fixes) ended
2025-11-30 and it isn't declared in requirements.txt -- importing it
here would work only on a machine that happens to already have it
installed, and break with ModuleNotFoundError anywhere else.
"""

from __future__ import annotations

import json
import os
import re
import time
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
# Retry helper for transient rate-limit (429) errors
# ---------------------------------------------------------------------------

MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 2.0  # used when the API doesn't tell us how long to wait

# Matches Google's error payload, e.g. "retry_delay { seconds: 3 }"
_RETRY_DELAY_PATTERN = re.compile(r"retry_delay\s*\{\s*seconds:\s*(\d+)")
# Fallback: matches "Please retry in 3.30s" style messages
_RETRY_IN_PATTERN = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "quota" in text.lower()


def _suggested_retry_delay(exc: Exception, attempt: int) -> float:
    """Use the delay Google's error suggests, if present; otherwise back off."""
    text = str(exc)
    match = _RETRY_DELAY_PATTERN.search(text) or _RETRY_IN_PATTERN.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return DEFAULT_BACKOFF_SECONDS * (2 ** attempt)  # exponential fallback


def _call_with_retry(fn):
    """
    Runs fn() with retries on rate-limit errors only. Any other exception
    (auth failure, malformed request, etc.) is raised immediately -- retrying
    those would just waste time and hide the real problem.
    """
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised/wrapped below
            last_exc = exc
            if not _is_rate_limit_error(exc) or attempt == MAX_RETRIES - 1:
                raise
            time.sleep(_suggested_retry_delay(exc, attempt))
    raise last_exc


# ---------------------------------------------------------------------------
# AI rubric evaluator (Gemini)
# ---------------------------------------------------------------------------

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


class AIRubricEvaluator(Evaluator):
    """
    Uses the Gemini API (current google-genai SDK) with a fixed rubric and
    forced structured (JSON) output. Deliberately does NOT ask an
    open-ended "how good is this design?" question -- see helping guide
    section 7.
    """

    def __init__(self, model: str | None = None, client=None):
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self.name = f"ai-rubric-{self.model}"
        self._client = client  # injected in tests to avoid real API calls

    def _get_client(self):
        if self._client is not None:
            return self._client
        from google import genai  # local import so the module loads even without the package during tests

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("API key not found. Please set GEMINI_API_KEY in your .env")
        return genai.Client(api_key=api_key)

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
        client = self._get_client()
        prompt = self._build_prompt(problem_prompt, requirements, submission_content)

        def _do_call():
            return client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "max_output_tokens": 2000,
                },
            )

        try:
            response = _call_with_retry(_do_call)
            raw_text = response.text
        except Exception as exc:  # network/auth/rate-limit (after retries) etc.
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
