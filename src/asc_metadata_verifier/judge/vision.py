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

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_ai import Agent, BinaryContent

from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.models import RubricVerdict, Screenshot

if TYPE_CHECKING:
    from pydantic_ai.models import Model

logger = logging.getLogger(__name__)

# Default judge model; overridable via the ASC_JUDGE_MODEL env var, same
# knob as the text judge (`judge/agent.py`) -- one env var controls both.
DEFAULT_JUDGE_MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = (
    "You are an App Store screenshot rejection-risk judge. Given a vision "
    "rubric dimension, a screenshot image, and (optionally) grounding text "
    "from the current App Store Review Guidelines, return a structured "
    "verdict. Cite `guideline_ref` ONLY using the provided grounding text; if "
    "NO grounding text is provided, `guideline_ref` MUST be null. Never invent "
    "a guideline reference. `offending_quote` has no text span to quote for an "
    "image -- leave it null or use it for a short textual description of what "
    "you observed."
)

# Recognized image signatures, and the media type each one identifies.
# Deliberately minimal (no OCR, no image preprocessing, no third-party image
# library) -- just enough to avoid handing a non-image file to the vision
# model. This is the SINGLE SOURCE OF TRUTH for `BinaryContent.media_type`:
# it is derived from the matched signature (the actual bytes), never from the
# file's extension, which can lie (a `.jpg`-named file containing PNG bytes,
# or vice versa) -- `BinaryContent.media_type` is sent to the model verbatim
# and is not re-sniffed downstream, so an extension-derived type can silently
# mislabel the image.
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


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
            system_prompt=SYSTEM_PROMPT,
            defer_model_check=True,
        )
    return Agent(model, output_type=RubricVerdict, system_prompt=SYSTEM_PROMPT)


def _read_image(screenshot: Screenshot) -> tuple[bytes, str] | None:
    """Read and sanity-check local image bytes, or return None to skip.

    Returns `(data, media_type)`, where `media_type` is derived from the
    matched entry in `_IMAGE_SIGNATURES` (the actual bytes), NOT the file's
    extension -- see the module-level comment on `_IMAGE_SIGNATURES`. Returns
    None (logging a warning) when the path is a remote URL, the file is
    missing/unreadable, or the bytes don't match a recognized image
    signature. Never raises.
    """
    if screenshot.path.startswith("http://") or screenshot.path.startswith("https://"):
        logger.warning(
            "vision judge: skipping remote screenshot URL (Phase 2+ limitation, "
            "not fetched): %s",
            screenshot.path,
        )
        return None

    path = Path(screenshot.path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.warning("vision judge: skipping unreadable screenshot %s: %s", path, exc)
        return None

    for signature, media_type in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return data, media_type

    logger.warning(
        "vision judge: skipping %s -- not a decodable image (unrecognized signature)",
        path,
    )
    return None


def _grounding_for(guidelines: Guidelines, dimension: VisionDimension) -> str:
    """Resolve grounding text for a dimension, or '' when none is available.

    Never fabricates: returns '' unless the guidelines were actually fetched.
    Screenshots don't map to one specific guideline section the way text
    rubric dimensions do (via `guideline_hint`), so this falls back to the
    general accurate-metadata section (2.3) or the raw guidelines text.

    Documented simplification: `dimension` is accepted for signature symmetry
    with the text judge's `judge.agent._grounding_for`, but is currently
    unused -- ALL 4 `VISION_DIMENSIONS` share this same grounding text (there
    is no per-dimension `guideline_hint` for vision, unlike `RubricDimension`
    in `judge.rubric`).
    """
    if not guidelines.available:
        return ""
    return guidelines.sections.get("2.3") or guidelines.text


def _build_prompt(dimension: VisionDimension, screenshot: Screenshot, grounding: str) -> str:
    filename = Path(screenshot.path).name
    parts = [
        f"Vision rubric dimension id: {dimension.id}",
        f"What this dimension flags: {dimension.description}",
        "",
        f"Locale: {screenshot.locale}",
        f"Screenshot filename: {filename}",
        f"Screenshot display type: {screenshot.display_type or 'unspecified'}",
        "The screenshot image is attached below.",
    ]
    if grounding:
        parts += [
            "",
            "Grounding text from the CURRENT App Store Review Guidelines:",
            grounding,
            "",
            "Cite `guideline_ref` only using the grounding text above.",
        ]
    else:
        parts += [
            "",
            "No grounding text is available. `guideline_ref` MUST be null.",
        ]
    return "\n".join(parts)


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
        image = _read_image(screenshot)
        if image is None:
            continue
        image_bytes, media_type = image

        for dimension in VISION_DIMENSIONS:
            grounding = _grounding_for(guidelines, dimension)
            prompt = _build_prompt(dimension, screenshot, grounding)
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
