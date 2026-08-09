"""Shared prompt-building helpers for the text and vision judges.

Extracted verbatim from `judge/agent.py` (text) and `judge/vision.py` (vision)
so a future `JudgeClient` can build the same system prompts, grounding text,
and user prompts without depending on either judge module directly. Pure
move -- no behavior change.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge.rubric import RubricDimension
from asc_metadata_verifier.models import LocaleMetadata, Screenshot

if TYPE_CHECKING:
    from asc_metadata_verifier.judge.vision import VisionDimension

TEXT_SYSTEM_PROMPT = (
    "You are an App Store metadata rejection-risk judge. Given a rubric "
    "dimension, a locale's metadata fields, and (optionally) grounding text "
    "from the current App Store Review Guidelines, return a structured "
    "verdict. Cite `guideline_ref` ONLY using the provided grounding text; if "
    "NO grounding text is provided, `guideline_ref` MUST be null. Never invent "
    "a guideline reference. Quote the offending span verbatim in "
    "`offending_quote`."
)

VISION_SYSTEM_PROMPT = (
    "You are an App Store screenshot rejection-risk judge. Given a vision "
    "rubric dimension, a screenshot image, and (optionally) grounding text "
    "from the current App Store Review Guidelines, return a structured "
    "verdict. Cite `guideline_ref` ONLY using the provided grounding text; if "
    "NO grounding text is provided, `guideline_ref` MUST be null. Never invent "
    "a guideline reference. `offending_quote` has no text span to quote for an "
    "image -- leave it null or use it for a short textual description of what "
    "you observed."
)

# The locale text fields shown to the judge, in a stable order.
TEXT_FIELDS = (
    "app_name",
    "subtitle",
    "promotional_text",
    "keywords",
    "description",
    "whats_new",
)


def format_fields(locale_meta: LocaleMetadata) -> str:
    lines = []
    for name in TEXT_FIELDS:
        value = getattr(locale_meta, name, None)
        lines.append(f"{name}: {value if value is not None else ''}")
    return "\n".join(lines)


def grounding_for_text(guidelines: Guidelines, dimension: RubricDimension) -> str:
    """Resolve grounding text for a dimension, or '' when none is available.

    Never fabricates: returns '' unless the guidelines were actually fetched.
    """
    if not guidelines.available:
        return ""
    return (
        guidelines.sections.get(dimension.guideline_hint)
        or guidelines.sections.get("2.3")
        or guidelines.text
    )


def build_text_prompt(
    dimension: RubricDimension, locale_meta: LocaleMetadata, grounding: str
) -> str:
    parts = [
        f"Rubric dimension id: {dimension.id}",
        f"What this dimension flags: {dimension.description}",
        "",
        f"Locale: {locale_meta.locale}",
        "Metadata fields:",
        format_fields(locale_meta),
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


def grounding_for_vision(guidelines: Guidelines, dimension: VisionDimension) -> str:
    """Resolve grounding text for a dimension, or '' when none is available.

    Never fabricates: returns '' unless the guidelines were actually fetched.
    Screenshots don't map to one specific guideline section the way text
    rubric dimensions do (via `guideline_hint`), so this falls back to the
    general accurate-metadata section (2.3) or the raw guidelines text.

    Documented simplification: `dimension` is accepted for signature symmetry
    with `grounding_for_text`, but is currently unused -- ALL 4
    `VISION_DIMENSIONS` share this same grounding text (there is no
    per-dimension `guideline_hint` for vision, unlike `RubricDimension` in
    `judge.rubric`).
    """
    if not guidelines.available:
        return ""
    return guidelines.sections.get("2.3") or guidelines.text


def build_vision_prompt(dimension: VisionDimension, screenshot: Screenshot, grounding: str) -> str:
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
