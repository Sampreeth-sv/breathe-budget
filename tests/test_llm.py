import asyncio

import pytest

from app.config import Settings
from app.services.llm import MAX_SUMMARY_CHARS, Explainer, build_facts, clean_summary


def test_clean_summary_strips_markup_and_whitespace():
    text = "<b>Air</b> is   bad today.\n\n<script>alert(1)</script> Stay in and run a purifier."
    cleaned = clean_summary(text)
    assert "<" not in cleaned and ">" not in cleaned
    assert "  " not in cleaned and "\n" not in cleaned


@pytest.mark.parametrize("bad", [None, 42, [], "", "short", "   ", "<p></p>"])
def test_clean_summary_rejects_unusable(bad):
    assert clean_summary(bad) is None


def test_clean_summary_truncates():
    assert len(clean_summary("word " * 1000)) == MAX_SUMMARY_CHARS


def test_build_facts_contains_only_computed_values():
    actions = [
        {"title": f"A{i}", "exposure_reduction_pct": i, "cost_tier": "free", "detail": "secret"}
        for i in range(5)
    ]
    facts = build_facts("Delhi", 150.04, 200, "Unhealthy", "2 adult(s)", actions, 35.0)
    assert len(facts["top_actions"]) == 3
    assert "detail" not in facts["top_actions"][0]
    assert facts["pm25_ug_m3"] == 150.0


def test_explainer_disabled_without_key():
    explainer = Explainer(Settings(gemini_api_key=None))
    assert not explainer.enabled
    assert asyncio.run(explainer.summarise({})) is None


async def test_explainer_returns_none_on_timeout_or_error():
    explainer = Explainer(Settings(gemini_api_key=None, llm_timeout_s=0.05))
    explainer._client = object()  # pretend a client exists

    async def slow(_facts):
        await asyncio.sleep(1)

    explainer._call = slow  # type: ignore[method-assign]
    assert await explainer.summarise({}) is None

    async def boom(_facts):
        raise RuntimeError("quota")

    explainer._call = boom  # type: ignore[method-assign]
    assert await explainer.summarise({}) is None


class _FakeModels:
    def __init__(self, text=None, error=None):
        self._text, self._error, self.kwargs = text, error, None

    async def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if self._error:
            raise self._error

        class Response:
            text = self._text

        return Response()


def _explainer_with(models):
    explainer = Explainer(Settings(gemini_api_key=None))

    class Aio:
        pass

    class Client:
        aio = Aio()

    Client.aio.models = models
    explainer._client = Client()
    return explainer


async def test_call_sends_only_facts_and_parses_json():
    models = _FakeModels('{"summary": "Air is heavy today. Moving workouts indoors helps most. You can do this!"}')
    result = await _explainer_with(models).summarise({"pm25_ug_m3": 150})
    assert result.startswith("Air is heavy")
    assert models.kwargs["contents"] == '{"pm25_ug_m3": 150}'
    assert models.kwargs["config"].response_mime_type == "application/json"
    assert "never invent" in models.kwargs["config"].system_instruction.lower()


@pytest.mark.parametrize("text", ["not json", '["list"]', '{"other": 1}', "", None])
async def test_call_rejects_unusable_model_output(text):
    assert await _explainer_with(_FakeModels(text)).summarise({}) is None
