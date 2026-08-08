"""pydantic-ai rejection-risk judge, grounded in the live App Store guidelines.

Builds ONE ``pydantic_ai.Agent`` whose structured output is a ``RubricVerdict``,
then runs it once per (locale, dimension). Two honesty layers keep the judge
from fabricating a guideline reference:

1. The system prompt instructs the model to cite ``guideline_ref`` ONLY from the
   grounding text it is given, and to return null when no grounding is present.
2. Defensive post-processing (``judge_field``) authoritatively stamps the
   verdict's ``locale`` and ``dimension`` from the inputs, and forces
   ``guideline_ref = None`` whenever the guidelines were unavailable -- so the
   honesty constraint holds regardless of what the model returned.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pydantic_ai import Agent

from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge.rubric import RubricDimension
from asc_metadata_verifier.models import AppMetadata, LocaleMetadata, RubricVerdict

if TYPE_CHECKING:
    from pydantic_ai.models import Model

# Default judge model; overridable via the ASC_JUDGE_MODEL env var. pydantic-ai
# addresses Anthropic models with an "anthropic:" prefix (see its known-model
# names, e.g. "anthropic:claude-sonnet-5").
DEFAULT_JUDGE_MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = (
    "You are an App Store metadata rejection-risk judge. Given a rubric "
    "dimension, a locale's metadata fields, and (optionally) grounding text "
    "from the current App Store Review Guidelines, return a structured "
    "verdict. Cite `guideline_ref` ONLY using the provided grounding text; if "
    "NO grounding text is provided, `guideline_ref` MUST be null. Never invent "
    "a guideline reference. Quote the offending span verbatim in "
    "`offending_quote`."
)

# The locale text fields shown to the judge, in a stable order.
_TEXT_FIELDS = (
    "app_name",
    "subtitle",
    "promotional_text",
    "keywords",
    "description",
    "whats_new",
)


def build_judge(model: Model | str | None = None) -> Agent[None, RubricVerdict]:
    """Construct the single rejection-risk judge agent.

    If ``model`` is None, resolve the Anthropic model from ``ASC_JUDGE_MODEL``
    (default ``claude-sonnet-5``) and build the ``anthropic:<name>`` reference.
    Model resolution is deferred (``defer_model_check=True``) so constructing
    the agent never requires an API key -- only an actual run does. If ``model``
    is provided (e.g. a ``TestModel``/``FunctionModel`` or a model string), it is
    used directly, which is how the offline test suite injects a fake model.
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


def _format_fields(locale_meta: LocaleMetadata) -> str:
    lines = []
    for name in _TEXT_FIELDS:
        value = getattr(locale_meta, name, None)
        lines.append(f"{name}: {value if value is not None else ''}")
    return "\n".join(lines)


def _grounding_for(guidelines: Guidelines, dimension: RubricDimension) -> str:
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


def _build_prompt(
    dimension: RubricDimension, locale_meta: LocaleMetadata, grounding: str
) -> str:
    parts = [
        f"Rubric dimension id: {dimension.id}",
        f"What this dimension flags: {dimension.description}",
        "",
        f"Locale: {locale_meta.locale}",
        "Metadata fields:",
        _format_fields(locale_meta),
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


def judge_field(
    meta: AppMetadata,
    guidelines: Guidelines,
    dimensions: list[RubricDimension],
    model: Model | str | None = None,
) -> list[RubricVerdict]:
    """Judge every (locale, dimension) pair and return the collected verdicts.

    One agent run per pair. After each run the verdict's ``locale`` and
    ``dimension`` are set authoritatively from the inputs (the model is not
    trusted to echo them), and ``guideline_ref`` is forced to None whenever the
    guidelines were unavailable.
    """
    agent = build_judge(model)
    verdicts: list[RubricVerdict] = []
    for locale_meta in meta.locales:
        for dimension in dimensions:
            grounding = _grounding_for(guidelines, dimension)
            prompt = _build_prompt(dimension, locale_meta, grounding)
            result = agent.run_sync(prompt)

            update: dict[str, object] = {
                "locale": locale_meta.locale,
                "dimension": dimension.id,
            }
            if not guidelines.available:
                update["guideline_ref"] = None
            verdicts.append(result.output.model_copy(update=update))
    return verdicts
