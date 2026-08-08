"""Offline tests for the pydantic-ai rejection-risk judge (Task 9).

Every model call is served by a `FunctionModel` (pydantic_ai.models.function):
a local function inspects the incoming prompt and returns a controlled
`RubricVerdict` via the agent's structured output tool. No network, no API key.
"""

import os

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge.agent import build_judge, judge_field
from asc_metadata_verifier.judge.rubric import DIMENSIONS, RubricDimension
from asc_metadata_verifier.models import AppMetadata, LocaleMetadata, RubricVerdict

EXPECTED_IDS = [
    "placeholder_text",
    "other_platform_mentions",
    "misleading_claims",
    "price_terms_in_description",
    "keyword_stuffing",
    "beta_demo_mentions",
    "unauthorized_contact_links",
    "third_party_trademark",
]


def _user_text(messages) -> str:
    """Concatenate the text of every user prompt part in the message history."""
    chunks: list[str] = []
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                chunks.append(part.content)
    return "\n".join(chunks)


def _model(verdict_factory) -> FunctionModel:
    """Build a FunctionModel whose function returns `verdict_factory(prompt_text)`.

    The verdict is delivered through the agent's structured output tool, whose
    name we read dynamically from `agent_info.output_tools[0].name` (never
    hardcoded), exactly as pydantic-ai's own TestModel does.
    """

    def fn(messages, info: AgentInfo) -> ModelResponse:
        verdict = verdict_factory(_user_text(messages))
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name, verdict.model_dump())])

    return FunctionModel(fn)


def _dim(dim_id: str) -> RubricDimension:
    return next(d for d in DIMENSIONS if d.id == dim_id)


def test_dimensions_are_exactly_the_eight_ids():
    assert [d.id for d in DIMENSIONS] == EXPECTED_IDS
    assert len(DIMENSIONS) == 8
    for d in DIMENSIONS:
        assert d.description.strip()
        assert d.guideline_hint.strip()


def test_other_platform_mention_detected():
    meta = AppMetadata(
        locales=[
            LocaleMetadata(
                locale="en-US",
                description="A great productivity app. Also available on Android.",
            )
        ]
    )
    guidelines = Guidelines(
        available=True,
        text="2.3.10 Do not reference other mobile platforms in your metadata.",
        sections={"2.3.10": "Do not reference other mobile platforms in your metadata."},
        source="test",
    )

    def factory(text: str) -> RubricVerdict:
        if "Android" in text:
            return RubricVerdict(
                dimension="echoed-by-model",
                verdict="fail",
                severity="high",
                confidence=0.95,
                rationale="References the Android platform.",
                offending_quote="Also available on Android",
                guideline_ref="2.3.10",
                locale="echoed-by-model",
                field="description",
            )
        return RubricVerdict(
            dimension="echoed-by-model",
            verdict="pass",
            severity="low",
            confidence=0.9,
            rationale="No other-platform references.",
            locale="echoed-by-model",
            field="description",
        )

    dims = [_dim("other_platform_mentions")]
    verdicts = judge_field(meta, guidelines, dims, model=_model(factory))

    assert len(verdicts) == 1
    v = verdicts[0]
    assert v.dimension == "other_platform_mentions"  # authoritative, not the echoed value
    assert v.verdict in {"fail", "warn"}
    assert v.offending_quote is not None
    assert v.locale == "en-US"  # authoritative, not the echoed value


def test_clean_text_yields_pass():
    meta = AppMetadata(
        locales=[LocaleMetadata(locale="en-US", description="A calm meditation timer.")]
    )
    guidelines = Guidelines(
        available=True,
        text="2.3 Accurate Metadata.",
        sections={"2.3": "Accurate Metadata."},
        source="test",
    )

    def factory(_text: str) -> RubricVerdict:
        return RubricVerdict(
            dimension="echoed-by-model",
            verdict="pass",
            severity="low",
            confidence=0.9,
            rationale="Nothing concerning.",
            locale="echoed-by-model",
            field="description",
        )

    dims = [_dim("other_platform_mentions")]
    verdicts = judge_field(meta, guidelines, dims, model=_model(factory))

    assert len(verdicts) == 1
    assert verdicts[0].verdict == "pass"
    assert verdicts[0].offending_quote is None


def test_honesty_guideline_ref_forced_none_when_guidelines_unavailable():
    """Critical: defensive layer must null out guideline_ref when no grounding.

    Even when the model hands back a bogus, invented reference, an unavailable
    Guidelines object must produce verdicts with `guideline_ref is None`.
    """
    guidelines = Guidelines(available=False, text="", sections={}, source="offline")
    meta = AppMetadata(
        locales=[
            LocaleMetadata(locale="en-US", description="Beta build. Also available on Android.")
        ]
    )

    def factory(_text: str) -> RubricVerdict:
        return RubricVerdict(
            dimension="bogus-dimension",
            verdict="warn",
            severity="medium",
            confidence=0.8,
            rationale="Model tried to cite a guideline it was not given.",
            offending_quote="Beta build",
            guideline_ref="2.3.99",  # invented; must be scrubbed
            locale="bogus-locale",
            field="description",
        )

    verdicts = judge_field(meta, guidelines, DIMENSIONS, model=_model(factory))

    assert len(verdicts) == len(DIMENSIONS)
    for v in verdicts:
        assert v.guideline_ref is None  # honesty enforcement
        assert v.locale == "en-US"  # authoritative
    # dimensions echoed authoritatively, one per rubric dimension, in order
    assert [v.dimension for v in verdicts] == [d.id for d in DIMENSIONS]


def test_honesty_guideline_ref_forced_none_when_available_but_grounding_empty():
    """available is True but text+sections are empty -> grounding used is "".

    Layer 2 must agree with layer 1: an empty grounding string forces
    guideline_ref to None even though `guidelines.available` is True.
    """
    guidelines = Guidelines(available=True, text="", sections={}, source="x")
    meta = AppMetadata(
        locales=[LocaleMetadata(locale="en-US", description="Also available on Android.")]
    )

    def factory(_text: str) -> RubricVerdict:
        return RubricVerdict(
            dimension="bogus-dimension",
            verdict="warn",
            severity="medium",
            confidence=0.8,
            rationale="Model tried to cite a guideline it was not given.",
            offending_quote="Android",
            guideline_ref="2.3.99",  # invented; must be scrubbed
            locale="bogus-locale",
            field="description",
        )

    verdicts = judge_field(meta, guidelines, DIMENSIONS, model=_model(factory))

    assert len(verdicts) == len(DIMENSIONS)
    for v in verdicts:
        assert v.guideline_ref is None


def test_locale_and_dimension_are_authoritative_across_cross_product():
    meta = AppMetadata(
        locales=[
            LocaleMetadata(locale="en-US", description="Clean copy."),
            LocaleMetadata(locale="de-DE", description="Sauberer Text."),
        ]
    )
    guidelines = Guidelines(
        available=True,
        text="2.3 Accurate Metadata.",
        sections={"2.3": "Accurate Metadata."},
        source="test",
    )
    dims = [_dim("placeholder_text"), _dim("misleading_claims")]

    def factory(_text: str) -> RubricVerdict:
        return RubricVerdict(
            dimension="wrong",
            verdict="pass",
            severity="low",
            confidence=0.7,
            rationale="ok",
            locale="wrong",
            field="description",
        )

    verdicts = judge_field(meta, guidelines, dims, model=_model(factory))

    assert len(verdicts) == 4  # 2 locales x 2 dimensions
    seen = {(v.locale, v.dimension) for v in verdicts}
    assert seen == {
        ("en-US", "placeholder_text"),
        ("en-US", "misleading_claims"),
        ("de-DE", "placeholder_text"),
        ("de-DE", "misleading_claims"),
    }


def test_build_judge_accepts_a_model_instance():
    def factory(_text: str) -> RubricVerdict:
        return RubricVerdict(
            dimension="x",
            verdict="pass",
            severity="low",
            confidence=0.5,
            rationale="ok",
            locale="x",
            field="description",
        )

    agent = build_judge(model=_model(factory))
    assert agent is not None


def test_build_judge_default_is_keyless_and_uses_default_model(monkeypatch):
    """HARD constraint: offline-safe by construction + default claude-sonnet-5.

    No ANTHROPIC_API_KEY and no ASC_JUDGE_MODEL: constructing the default judge
    must NOT raise (keyless construction via defer_model_check=True), and its
    configured model reference must reflect the `claude-sonnet-5` default.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ASC_JUDGE_MODEL", raising=False)

    agent = build_judge()  # must not raise without a key

    assert "claude-sonnet-5" in str(agent.model)


def test_build_judge_respects_asc_judge_model_env(monkeypatch):
    """HARD constraint: ASC_JUDGE_MODEL overrides the default, still keyless."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ASC_JUDGE_MODEL", "claude-opus-4-8")

    agent = build_judge()  # must not raise without a key

    assert "claude-opus-4-8" in str(agent.model)


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY; skipped in offline runs",
)
def test_real_model_smoke():  # pragma: no cover - network-gated, skipped offline
    meta = AppMetadata(
        locales=[
            LocaleMetadata(
                locale="en-US",
                description="A todo app. Also available on Android and Google Play.",
            )
        ]
    )
    guidelines = Guidelines(
        available=True,
        text="2.3.10 Do not reference other mobile platforms.",
        sections={"2.3.10": "Do not reference other mobile platforms."},
        source="test",
    )
    verdicts = judge_field(meta, guidelines, [_dim("other_platform_mentions")])
    assert len(verdicts) == 1
    assert verdicts[0].dimension == "other_platform_mentions"
    assert verdicts[0].locale == "en-US"
