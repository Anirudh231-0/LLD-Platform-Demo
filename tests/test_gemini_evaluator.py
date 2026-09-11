import json

import pytest

from app.services.evaluator import GeminiRubricEvaluator, EvaluatorError
from app.services.rubric import criteria_keys


class _FakeGeminiResponse:
    def __init__(self, text):
        self.text = text


class _FakeGeminiModels:
    def __init__(self, response_text):
        self._response_text = response_text

    def generate_content(self, **kwargs):
        return _FakeGeminiResponse(self._response_text)


class _FakeGeminiClient:
    def __init__(self, response_text):
        self.models = _FakeGeminiModels(response_text)


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


def test_parses_valid_gemini_response():
    client = _FakeGeminiClient(_valid_ai_json())
    evaluator = GeminiRubricEvaluator(client=client)

    result = evaluator.evaluate("prompt", "reqs", "class ParkingLot: ...")

    assert result.overall_summary == "Solid first pass."
    assert result.evaluator_name == "ai-rubric-gemini-v1"
    assert len(result.items) == len(criteria_keys())
    assert all(1 <= item.score <= 5 for item in result.items)


def test_gemini_raises_on_invalid_json():
    client = _FakeGeminiClient("not json at all")
    evaluator = GeminiRubricEvaluator(client=client)

    with pytest.raises(EvaluatorError):
        evaluator.evaluate("prompt", "reqs", "content")


def test_gemini_and_claude_use_the_same_rubric_prompt_and_parser():
    """
    Both evaluators share build_rubric_prompt/parse_rubric_json, so given
    identical model output they must produce identical evaluation results
    -- swapping providers changes only how the API is called, never what
    is measured. See DESIGN_NOTE.md "Change Test B".
    """
    from app.services.evaluator import AIRubricEvaluator

    class _FakeClaudeBlock:
        type = "text"

        def __init__(self, text):
            self.text = text

    class _FakeClaudeResponse:
        def __init__(self, text):
            self.content = [_FakeClaudeBlock(text)]

    class _FakeClaudeMessages:
        def __init__(self, text):
            self._text = text

        def create(self, **kwargs):
            return _FakeClaudeResponse(self._text)

    class _FakeClaudeClient:
        def __init__(self, text):
            self.messages = _FakeClaudeMessages(text)

    text = _valid_ai_json()
    gemini_result = GeminiRubricEvaluator(client=_FakeGeminiClient(text)).evaluate("p", "r", "s")
    claude_result = AIRubricEvaluator(client=_FakeClaudeClient(text)).evaluate("p", "r", "s")

    assert gemini_result.overall_summary == claude_result.overall_summary
    assert [(i.criterion, i.score) for i in gemini_result.items] == [
        (i.criterion, i.score) for i in claude_result.items
    ]
