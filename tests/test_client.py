import asyncio

from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge import prompts
from asc_metadata_verifier.judge.client import JudgeClient
from asc_metadata_verifier.judge.rubric import DIMENSIONS
from asc_metadata_verifier.judge.vision import VISION_DIMENSIONS
from asc_metadata_verifier.models import LocaleMetadata, RubricVerdict, Screenshot


def _user_text(messages):
    out = []
    for m in messages:
        for p in getattr(m, "parts", []):
            if isinstance(p, UserPromptPart) and isinstance(p.content, str):
                out.append(p.content)
    return "\n".join(out)


def _model(factory):
    def fn(messages, info: AgentInfo) -> ModelResponse:
        v = factory(_user_text(messages))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, v.model_dump())])
    return FunctionModel(fn)


def _rv(**kw):
    base = dict(dimension="echo", verdict="fail", severity="high", confidence=0.9,
               rationale="r", offending_quote="Android", guideline_ref="2.3.99",
               locale="echo", field="description")
    base.update(kw)
    return RubricVerdict(**base)


def test_run_text_votes_and_stamps_authoritatively():
    client = JudgeClient.from_model("c", _model(lambda t: _rv()), supports_vision=False)
    lm = LocaleMetadata(locale="en-US", description="Also on Android")
    _g = Guidelines(available=True, text="2.3.10 body", sections={"2.3.10": "body"}, source="t")
    grounding = "2.3.10 body"
    vote = asyncio.run(client.run_text(DIMENSIONS[1], lm, grounding))
    assert vote.status == "voted"
    assert vote.verdict.locale == "en-US"                 # authoritative
    assert vote.verdict.dimension == "other_platform_mentions"
    assert vote.verdict.guideline_ref == "2.3.99"         # grounding present -> not scrubbed
    assert vote.verdict.field == "description"            # text: model-reported, not stamped


def test_run_text_scrubs_guideline_ref_when_no_grounding():
    client = JudgeClient.from_model("c", _model(lambda t: _rv()))
    lm = LocaleMetadata(locale="en-US", description="x")
    vote = asyncio.run(client.run_text(DIMENSIONS[0], lm, ""))   # empty grounding
    assert vote.verdict.guideline_ref is None


def test_run_text_error_becomes_error_vote_not_raise():
    def boom(_t):
        raise RuntimeError("kaboom")
    client = JudgeClient.from_model("c", _model(boom))
    lm = LocaleMetadata(locale="en-US", description="x")
    vote = asyncio.run(client.run_text(DIMENSIONS[0], lm, "g"))
    assert vote.status == "error" and "kaboom" in vote.error and vote.verdict is None


def test_run_text_prompt_build_error_becomes_error_vote_not_raise(monkeypatch):
    def boom(*_a, **_kw):
        raise RuntimeError("prompt boom")

    monkeypatch.setattr(prompts, "build_text_prompt", boom)
    client = JudgeClient.from_model("c", _model(lambda t: _rv()))
    lm = LocaleMetadata(locale="en-US", description="x")
    vote = asyncio.run(client.run_text(DIMENSIONS[0], lm, "g"))
    assert vote.status == "error"
    assert "prompt boom" in vote.error
    assert vote.verdict is None


def test_non_vision_client_run_vision_is_not_applicable_without_a_call():
    called = {"n": 0}
    def fn(_t):
        called["n"] += 1
        return _rv()
    client = JudgeClient.from_model("c", _model(fn), supports_vision=False)
    s = Screenshot(locale="en-US", path="x.png")
    vote = asyncio.run(
        client.run_vision(s, b"\x89PNG\r\n\x1a\n", "image/png", VISION_DIMENSIONS[0], "g")
    )
    assert vote.status == "not_applicable" and called["n"] == 0


def test_vision_client_stamps_field_screenshot():
    client = JudgeClient.from_model("c", _model(lambda t: _rv(field="wrong")), supports_vision=True)
    s = Screenshot(locale="de-DE", path="x.png")
    vote = asyncio.run(
        client.run_vision(s, b"\x89PNG\r\n\x1a\n", "image/png", VISION_DIMENSIONS[0], "")
    )
    assert vote.status == "voted"
    assert vote.verdict.field == "screenshot" and vote.verdict.locale == "de-DE"
    assert vote.verdict.guideline_ref is None            # empty grounding scrubbed


def test_from_model_default_is_keyless():
    JudgeClient.from_model("c", _model(lambda t: _rv()), supports_vision=True)  # must not raise
