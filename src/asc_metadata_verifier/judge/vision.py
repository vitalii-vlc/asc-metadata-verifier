"""pydantic-ai vision judge for App Store screenshots (Phase 2, Task 17).

Mirrors `judge/agent.py` (Task 9)'s patterns for a fourth artifact type --
screenshots instead of text fields:

- ONE ``pydantic_ai.Agent`` whose structured output is a ``RubricVerdict``,
  run once per (screenshot, vision dimension), with the image bytes attached
  as ``BinaryContent``.
- Same two honesty layers as the text judge: the system prompt instructs the
  model to cite ``guideline_ref`` ONLY from the grounding text it is given
  and to return null when none is present; defensive post-processing then
  authoritatively stamps ``locale``/``dimension``/``field`` from the inputs
  and forces ``guideline_ref = None`` whenever the grounding actually used
  for that call is empty.

Scope limit (deliberate, not an oversight): only LOCAL screenshot files are
judged. A ``Screenshot.path`` that is a remote URL (starts with ``http``) is
skipped with a warning -- fetching and judging remote screenshot URLs is a
documented Phase-2+ limitation, not implemented here. A path that is missing,
unreadable, or not a decodable image is skipped the same way. Skipping never
raises; the run continues with the remaining screenshots.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic_ai import Agent, BinaryContent

from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge import images, prompts
from asc_metadata_verifier.models import RubricVerdict, Screenshot

if TYPE_CHECKING:
    from pydantic_ai.models import Model

# Default judge model; overridable via the ASC_JUDGE_MODEL env var, same
# knob as the text judge (`judge/agent.py`) -- one env var controls both.
DEFAULT_JUDGE_MODEL = "claude-sonnet-5"

# Module alias kept so any external import of `SYSTEM_PROMPT` still resolves.
SYSTEM_PROMPT = prompts.VISION_SYSTEM_PROMPT


@dataclass(frozen=True)
class VisionDimension:
    """One rejection-risk dimension the vision judge evaluates a screenshot against."""

    id: str
    description: str


# EXACTLY these 4 ids, in this order.
VISION_DIMENSIONS: list[VisionDimension] = [
    VisionDimension(
        id="placeholder_image",
        description=(
            "The screenshot shows placeholder or mockup art -- 'image coming "
            "soon', a blank/gray box, lorem-ipsum-style filler graphics -- "
            "rather than the real app UI."
        ),
    ),
    VisionDimension(
        id="other_platform_ui",
        description=(
            "The screenshot shows Android or Google Play UI chrome (Android "
            "system bars, Material Design widgets, a Play Store badge) instead "
            "of iOS UI."
        ),
    ),
    VisionDimension(
        id="misleading_screenshot",
        description=(
            "The screenshot depicts features, content, or functionality that "
            "the app does not actually provide."
        ),
    ),
    VisionDimension(
        id="excessive_text",
        description=(
            "The screenshot is mostly marketing text/graphics rather than an "
            "actual view of the app's UI."
        ),
    ),
]


def build_vision_judge(model: Model | str | None = None) -> Agent[None, RubricVerdict]:
    """Construct the single vision judge agent.

    Same construction contract as `judge.agent.build_judge`: with no `model`,
    resolve the Anthropic model from `ASC_JUDGE_MODEL` (default
    `claude-sonnet-5`) and defer model resolution (`defer_model_check=True`)
    so constructing the agent never requires an API key -- only an actual run
    does. An injected `model` (e.g. `TestModel`/`FunctionModel`, or a model
    string) is used directly, which is how the offline test suite and any
    caller with a specific model preference inject it.
    """
    if model is None:
        model_name = os.environ.get("ASC_JUDGE_MODEL", DEFAULT_JUDGE_MODEL)
        return Agent(
            f"anthropic:{model_name}",
            output_type=RubricVerdict,
            system_prompt=prompts.VISION_SYSTEM_PROMPT,
            defer_model_check=True,
        )
    return Agent(model, output_type=RubricVerdict, system_prompt=prompts.VISION_SYSTEM_PROMPT)


def judge_screenshots(
    screenshots: list[Screenshot],
    guidelines: Guidelines,
    model: Model | str | None = None,
) -> list[RubricVerdict]:
    """Judge every readable screenshot against every vision dimension.

    For each `Screenshot`, local image bytes are read from `screenshot.path`.
    A screenshot whose path is a URL, or whose file is missing/unreadable/not
    a decodable image, is SKIPPED with a `logging.warning` -- it never raises
    and never halts the run; judging continues with the remaining
    screenshots.

    For each readable screenshot x each `VISION_DIMENSIONS` entry, the vision
    agent is run once with the dimension description, grounding text (when
    `guidelines.available`), and the image as `BinaryContent`.

    Honesty enforcement mirrors `judge.agent.judge_field`: after each run,
    `locale`, `dimension`, and `field` are stamped authoritatively from the
    inputs (the model is not trusted to echo them), and `guideline_ref` is
    forced to None whenever the grounding actually used for that call is
    empty/falsy.
    """
    agent = build_vision_judge(model)
    verdicts: list[RubricVerdict] = []

    for screenshot in screenshots:
        image = images.read_image(screenshot)
        if image is None:
            continue
        image_bytes, media_type = image

        for dimension in VISION_DIMENSIONS:
            grounding = prompts.grounding_for_vision(guidelines, dimension)
            prompt = prompts.build_vision_prompt(dimension, screenshot, grounding)
            result = agent.run_sync(
                [prompt, BinaryContent(data=image_bytes, media_type=media_type)]
            )

            update: dict[str, object] = {
                "locale": screenshot.locale,
                "dimension": dimension.id,
                "field": "screenshot",
            }
            if not grounding:
                update["guideline_ref"] = None
            verdicts.append(result.output.model_copy(update=update))

    return verdicts
