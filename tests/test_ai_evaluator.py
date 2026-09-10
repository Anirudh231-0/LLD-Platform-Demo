import json

import pytest

from app.services.evaluator import AIRubricEvaluator, EvaluatorError
from app.services.rubric import criteria_keys


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, response_text):
        self._response_text = response_text

    def create(self, **kwargs):
        return _FakeResponse(self._response_text)


class _FakeClient:
    def __init__(self, response_text):
        self.messages = _FakeMessages(response_text)


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
