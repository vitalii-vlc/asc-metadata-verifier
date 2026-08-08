"""Offline tests for the vision screenshot judge (Task 17).

Every model call is served by a `FunctionModel` (pydantic_ai.models.function):
a local function inspects the incoming prompt (text portion only -- the fake
model cannot see pixels) and returns a controlled `RubricVerdict` via the
agent's structured output tool. No network, no API key.

The offline seam: `judge_screenshots` includes the screenshot's filename in
the text part of the prompt, so a `FunctionModel` can key on "bad" vs "good"
in the filename to return a `fail` vs `pass` verdict. This exercises the
plumbing (screenshot -> verdict with correct locale/dimension/field) and the
skip path for unreadable/remote screenshots, which is what's verifiable
offline -- it does NOT prove real-model vision quality.
"""

import logging

import pytest
from pydantic_ai.messages import BinaryContent, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge.vision import (
    VISION_DIMENSIONS,
    build_vision_judge,
    judge_screenshots,
)
from asc_metadata_verifier.models import RubricVerdict, Screenshot

FIXTURE_DIR = "tests/fixtures/screenshots"

EXPECTED_VISION_IDS = [
    "placeholder_image",
    "other_platform_ui",
    "misleading_screenshot",
    "excessive_text",
]


def _user_text_and_images(messages) -> tuple[str, int]:
    """Concatenate text parts and count BinaryContent parts in user prompts."""
    text_chunks: list[str] = []
    image_count = 0
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if isinstance(part, UserPromptPart):
                content = part.content
                if isinstance(content, str):
                    text_chunks.append(content)
                else:
                    for item in content:
                        if isinstance(item, str):
                            text_chunks.append(item)
                        elif isinstance(item, BinaryContent):
                            image_count += 1
    return "\n".join(text_chunks), image_count


def _model(verdict_factory) -> FunctionModel:
    """Build a FunctionModel whose function returns `verdict_factory(text, n_images)`.

    Mirrors `tests/test_judge.py`'s `_model` helper (Task 9): reads the
    structured output tool name dynamically, never hardcoded.
    """

    def fn(messages, info: AgentInfo) -> ModelResponse:
        text, n_images = _user_text_and_images(messages)
        verdict = verdict_factory(text, n_images)
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name, verdict.model_dump())])

    return FunctionModel(fn)


def _bogus_verdict(verdict: str = "pass") -> RubricVerdict:
    return RubricVerdict(
        dimension="echoed-by-model",
        verdict=verdict,
        severity="low" if verdict == "pass" else "high",
        confidence=0.9,
        rationale="stub",
        locale="echoed-by-model",
        field="echoed-by-model",
    )


def _keyed_on_filename_factory(text: str, _n_images: int) -> RubricVerdict:
    # Match the literal "Screenshot filename: bad.png" line, not a bare "bad"
    # substring -- some dimension descriptions contain "bad" inside unrelated
    # words (e.g. "Play Store badge"), which would false-positive on a naive
    # substring check.
    if "Screenshot filename: bad.png" in text:
        return RubricVerdict(
            dimension="echoed-by-model",
            verdict="fail",
            severity="high",
            confidence=0.9,
            rationale="Looks like placeholder art.",
            locale="echoed-by-model",
            field="echoed-by-model",
        )
    return RubricVerdict(
        dimension="echoed-by-model",
        verdict="pass",
        severity="low",
        confidence=0.9,
        rationale="Looks like real app UI.",
        locale="echoed-by-model",
        field="echoed-by-model",
    )


def test_vision_dimensions_are_exactly_the_four_ids():
    assert [d.id for d in VISION_DIMENSIONS] == EXPECTED_VISION_IDS
    assert len(VISION_DIMENSIONS) == 4
    for d in VISION_DIMENSIONS:
        assert d.description.strip()


def test_bad_screenshot_yields_fail_verdict_with_correct_locale():
    guidelines = Guidelines(available=False, text="", sections={}, source="offline")
    screenshots = [Screenshot(locale="en-US", path=f"{FIXTURE_DIR}/bad.png")]

    verdicts = judge_screenshots(
        screenshots, guidelines, model=_model(_keyed_on_filename_factory)
    )

    assert len(verdicts) == len(VISION_DIMENSIONS)
    for v in verdicts:
        assert v.verdict == "fail"
        assert v.locale == "en-US"
        assert v.dimension in EXPECTED_VISION_IDS
        assert v.field == "screenshot"


def test_good_screenshot_yields_pass_verdict():
    guidelines = Guidelines(available=False, text="", sections={}, source="offline")
    screenshots = [Screenshot(locale="en-US", path=f"{FIXTURE_DIR}/good.png")]

    verdicts = judge_screenshots(
        screenshots, guidelines, model=_model(_keyed_on_filename_factory)
    )

    assert len(verdicts) == len(VISION_DIMENSIONS)
    for v in verdicts:
        assert v.verdict == "pass"
        assert v.locale == "en-US"


def test_image_bytes_are_actually_sent_to_the_model():
    guidelines = Guidelines(available=False, text="", sections={}, source="offline")
    screenshots = [Screenshot(locale="en-US", path=f"{FIXTURE_DIR}/good.png")]
    seen_image_counts: list[int] = []

    def fn(messages, info: AgentInfo) -> ModelResponse:
        _text, n_images = _user_text_and_images(messages)
        seen_image_counts.append(n_images)
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name, _bogus_verdict().model_dump())])

    judge_screenshots(screenshots, guidelines, model=FunctionModel(fn))

    assert seen_image_counts == [1] * len(VISION_DIMENSIONS)


def test_missing_file_is_skipped_with_warning_and_run_continues(caplog):
    guidelines = Guidelines(available=False, text="", sections={}, source="offline")
    screenshots = [
        Screenshot(locale="en-US", path=f"{FIXTURE_DIR}/does_not_exist.png"),
        Screenshot(locale="en-US", path=f"{FIXTURE_DIR}/good.png"),
    ]

    with caplog.at_level(logging.WARNING):
        verdicts = judge_screenshots(
            screenshots, guidelines, model=_model(_keyed_on_filename_factory)
        )

    # only the readable screenshot produced verdicts
    assert len(verdicts) == len(VISION_DIMENSIONS)
    assert all(v.verdict == "pass" for v in verdicts)
    assert any("does_not_exist.png" in record.message for record in caplog.records)


def test_url_screenshot_is_skipped_with_warning_no_fetch():
    guidelines = Guidelines(available=False, text="", sections={}, source="offline")
    screenshots = [Screenshot(locale="en-US", path="http://example.com/shot.png")]

    def fn(_messages, _info: AgentInfo) -> ModelResponse:
        raise AssertionError("model must not be called for a URL screenshot")

    verdicts = judge_screenshots(screenshots, guidelines, model=FunctionModel(fn))

    assert verdicts == []


def test_unreadable_non_image_file_is_skipped(tmp_path, caplog):
    guidelines = Guidelines(available=False, text="", sections={}, source="offline")
    bogus = tmp_path / "not_an_image.png"
    bogus.write_bytes(b"this is definitely not a png")
    screenshots = [Screenshot(locale="en-US", path=str(bogus))]

    def fn(_messages, _info: AgentInfo) -> ModelResponse:
        raise AssertionError("model must not be called for an undecodable image")

    with caplog.at_level(logging.WARNING):
        verdicts = judge_screenshots(screenshots, guidelines, model=FunctionModel(fn))

    assert verdicts == []
    assert any("not_an_image.png" in record.message for record in caplog.records)


def test_mixed_readable_and_unreadable_continues_past_bad_one():
    guidelines = Guidelines(available=False, text="", sections={}, source="offline")
    screenshots = [
        Screenshot(locale="en-US", path="http://example.com/shot.png"),
        Screenshot(locale="en-US", path=f"{FIXTURE_DIR}/good.png"),
        Screenshot(locale="fr-FR", path=f"{FIXTURE_DIR}/does_not_exist.png"),
        Screenshot(locale="de-DE", path=f"{FIXTURE_DIR}/bad.png"),
    ]

    verdicts = judge_screenshots(
        screenshots, guidelines, model=_model(_keyed_on_filename_factory)
    )

    # 2 readable screenshots x 4 dimensions
    assert len(verdicts) == 2 * len(VISION_DIMENSIONS)
    locales_seen = {v.locale for v in verdicts}
    assert locales_seen == {"en-US", "de-DE"}


def test_honesty_guideline_ref_forced_none_when_guidelines_unavailable():
    """Critical: same honesty enforcement as Task 9's text judge.

    Even when the model hands back a bogus, invented reference, an
    unavailable Guidelines object must produce verdicts with
    `guideline_ref is None`.
    """
    guidelines = Guidelines(available=False, text="", sections={}, source="offline")
    screenshots = [Screenshot(locale="en-US", path=f"{FIXTURE_DIR}/good.png")]

    def fn(_messages, info: AgentInfo) -> ModelResponse:
        verdict = RubricVerdict(
            dimension="bogus",
            verdict="warn",
            severity="medium",
            confidence=0.8,
            rationale="Model tried to cite a guideline it was not given.",
            guideline_ref="2.3.99",  # invented; must be scrubbed
            locale="bogus",
            field="bogus",
        )
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name, verdict.model_dump())])

    verdicts = judge_screenshots(screenshots, guidelines, model=FunctionModel(fn))

    assert len(verdicts) == len(VISION_DIMENSIONS)
    for v in verdicts:
        assert v.guideline_ref is None


def test_honesty_guideline_ref_forced_none_when_available_but_grounding_empty():
    guidelines = Guidelines(available=True, text="", sections={}, source="x")
    screenshots = [Screenshot(locale="en-US", path=f"{FIXTURE_DIR}/good.png")]

    def fn(_messages, info: AgentInfo) -> ModelResponse:
        verdict = RubricVerdict(
            dimension="bogus",
            verdict="warn",
            severity="medium",
            confidence=0.8,
            rationale="Model tried to cite a guideline it was not given.",
            guideline_ref="2.3.99",
            locale="bogus",
            field="bogus",
        )
        tool_name = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name, verdict.model_dump())])

    verdicts = judge_screenshots(screenshots, guidelines, model=FunctionModel(fn))

    for v in verdicts:
        assert v.guideline_ref is None


def test_empty_screenshot_list_yields_no_verdicts_and_no_model_call():
    guidelines = Guidelines(available=False, text="", sections={}, source="offline")

    def fn(_messages, _info: AgentInfo) -> ModelResponse:
        raise AssertionError("model must not be called with no screenshots")

    verdicts = judge_screenshots([], guidelines, model=FunctionModel(fn))

    assert verdicts == []


def test_build_vision_judge_accepts_a_model_instance():
    agent = build_vision_judge(model=_model(_keyed_on_filename_factory))
    assert agent is not None


def test_build_vision_judge_default_is_keyless_and_uses_default_model(monkeypatch):
    """HARD constraint: offline-safe by construction + default claude-sonnet-5."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ASC_JUDGE_MODEL", raising=False)

    agent = build_vision_judge()  # must not raise without a key

    assert "claude-sonnet-5" in str(agent.model)


def test_build_vision_judge_respects_asc_judge_model_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ASC_JUDGE_MODEL", "claude-opus-4-8")

    agent = build_vision_judge()  # must not raise without a key

    assert "claude-opus-4-8" in str(agent.model)


@pytest.mark.skipif(
    not __import__("os").environ.get("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY; skipped in offline runs",
)
def test_real_model_smoke():  # pragma: no cover - network-gated, skipped offline
    guidelines = Guidelines(available=False, text="", sections={}, source="offline")
    screenshots = [Screenshot(locale="en-US", path=f"{FIXTURE_DIR}/good.png")]
    verdicts = judge_screenshots(screenshots, guidelines)
    assert len(verdicts) == len(VISION_DIMENSIONS)
