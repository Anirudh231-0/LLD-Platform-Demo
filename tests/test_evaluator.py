import json

import pytest

from app.services.evaluator import (
    AIRubricEvaluator,
    EvaluatorError,
    _call_with_retry,
    _is_rate_limit_error,
    _suggested_retry_delay,
)
from app.services.rubric import criteria_keys


# ---------------------------------------------------------------------------
# Fake client matching the google-genai SDK shape:
#   client.models.generate_content(model=..., contents=..., config=...) -> obj with .text
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, response_text, fail_times=0, failure_text="429 quota exceeded"):
        self._response_text = response_text
        self._fail_times = fail_times
        self._failure_text = failure_text
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise RuntimeError(self._failure_text)
        return _FakeResponse(self._response_text)


class _FakeClient:
    def __init__(self, response_text, fail_times=0, failure_text="429 quota exceeded"):
        self.models = _FakeModels(response_text, fail_times=fail_times, failure_text=failure_text)


def _valid_ai_json():
    items = [
        {
            "criterion": key,
            "score": 4,
            "evidence": f"the submission mentions relevant structure for {key}",
            "concern": None,
            "suggestion": "Consider an interface here.",
        }
        for key in criteria_keys()
    ]
    return json.dumps({"overall_summary": "Solid first pass.", "items": items})


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def test_parses_valid_json_response():
    client = _FakeClient(_valid_ai_json())
    evaluator = AIRubricEvaluator(client=client)

    result = evaluator.evaluate("prompt", "reqs", "class ParkingLot: ...")

    assert result.overall_summary == "Solid first pass."
    assert len(result.items) == len(criteria_keys())
    assert all(1 <= item.score <= 5 for item in result.items)


def test_strips_markdown_fences():
    fenced = "```json\n" + _valid_ai_json() + "\n```"
    client = _FakeClient(fenced)
    evaluator = AIRubricEvaluator(client=client)

    result = evaluator.evaluate("prompt", "reqs", "class ParkingLot: ...")
    assert len(result.items) == len(criteria_keys())


def test_ignores_hallucinated_criteria():
    data = json.loads(_valid_ai_json())
    data["items"].append({"criterion": "made_up_criterion", "score": 5, "evidence": "n/a"})
    client = _FakeClient(json.dumps(data))
    evaluator = AIRubricEvaluator(client=client)

    result = evaluator.evaluate("prompt", "reqs", "content")
    assert all(item.criterion in criteria_keys() for item in result.items)


def test_clamps_out_of_range_scores():
    data = json.loads(_valid_ai_json())
    data["items"][0]["score"] = 99
    client = _FakeClient(json.dumps(data))
    evaluator = AIRubricEvaluator(client=client)

    result = evaluator.evaluate("prompt", "reqs", "content")
    assert all(1 <= item.score <= 5 for item in result.items)


def test_raises_on_invalid_json():
    client = _FakeClient("not json at all")
    evaluator = AIRubricEvaluator(client=client)

    with pytest.raises(EvaluatorError):
        evaluator.evaluate("prompt", "reqs", "content")


def test_raises_on_empty_items():
    client = _FakeClient(json.dumps({"overall_summary": "x", "items": []}))
    evaluator = AIRubricEvaluator(client=client)

    with pytest.raises(EvaluatorError):
        evaluator.evaluate("prompt", "reqs", "content")


def test_evaluator_name_reflects_configured_model():
    evaluator = AIRubricEvaluator(model="gemini-3.5-flash-lite", client=_FakeClient(_valid_ai_json()))
    assert evaluator.name == "ai-rubric-gemini-3.5-flash-lite"


# ---------------------------------------------------------------------------
# Retry-on-429 behavior (see the real error this was written against:
# "429 ... quota_metric ... retry_delay { seconds: 3 }")
# ---------------------------------------------------------------------------

REAL_RATE_LIMIT_ERROR_TEXT = (
    "429 You exceeded your current quota, please check your plan and billing "
    "details. quota_metric: \"generativelanguage.googleapis.com/generate_content_free_tier_requests\" "
    "retry_delay { seconds: 3 }"
)


def test_recovers_from_transient_rate_limit(monkeypatch):
    # Fails twice with a 429-shaped error, succeeds on the 3rd attempt.
    client = _FakeClient(_valid_ai_json(), fail_times=2, failure_text=REAL_RATE_LIMIT_ERROR_TEXT)
    evaluator = AIRubricEvaluator(client=client)

    monkeypatch.setattr("app.services.evaluator.time.sleep", lambda s: None)  # don't actually wait in tests

    result = evaluator.evaluate("prompt", "reqs", "content")

    assert result.overall_summary == "Solid first pass."
    assert client.models.calls == 3


def test_gives_up_after_max_retries(monkeypatch):
    client = _FakeClient(_valid_ai_json(), fail_times=99, failure_text=REAL_RATE_LIMIT_ERROR_TEXT)
    evaluator = AIRubricEvaluator(client=client)

    monkeypatch.setattr("app.services.evaluator.time.sleep", lambda s: None)

    with pytest.raises(EvaluatorError):
        evaluator.evaluate("prompt", "reqs", "content")


def test_does_not_retry_non_rate_limit_errors():
    client = _FakeClient(_valid_ai_json(), fail_times=99, failure_text="invalid API key")
    evaluator = AIRubricEvaluator(client=client)

    with pytest.raises(EvaluatorError):
        evaluator.evaluate("prompt", "reqs", "content")

    assert client.models.calls == 1  # no retries wasted on a non-transient error


def test_is_rate_limit_error_detects_429_and_quota_text():
    assert _is_rate_limit_error(RuntimeError(REAL_RATE_LIMIT_ERROR_TEXT)) is True
    assert _is_rate_limit_error(RuntimeError("RESOURCE_EXHAUSTED")) is True
    assert _is_rate_limit_error(ValueError("invalid api key")) is False


def test_suggested_retry_delay_reads_googles_retry_delay_field():
    delay = _suggested_retry_delay(RuntimeError(REAL_RATE_LIMIT_ERROR_TEXT), attempt=0)
    assert delay == 3.0


def test_suggested_retry_delay_falls_back_to_backoff_when_unparseable():
    delay = _suggested_retry_delay(RuntimeError("429 rate limited, no delay given"), attempt=1)
    assert delay > 0  # exponential fallback, exact value not load-bearing


def test_call_with_retry_stops_immediately_on_non_rate_limit_error():
    calls = {"n": 0}

    def always_fails():
        calls["n"] += 1
        raise ValueError("boom")

    with pytest.raises(ValueError):
        _call_with_retry(always_fails)

    assert calls["n"] == 1
