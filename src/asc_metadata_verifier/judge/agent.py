"""pydantic-ai rejection-risk judge, grounded in the live App Store guidelines.

Builds ONE ``pydantic_ai.Agent`` whose structured output is a ``RubricVerdict``,
then runs it once per (locale, dimension). Two honesty layers keep the judge
from fabricating a guideline reference:

1. The system prompt instructs the model to cite ``guideline_ref`` ONLY from the
   grounding text it is given, and to return null when no grounding is present.
2. Defensive post-processing (``judge_field``) authoritatively stamps the
   verdict's ``locale`` and ``dimension`` from the inputs, and forces
   ``guideline_ref = None`` whenever the grounding text actually used for
   that call is empty -- which covers both ``guidelines.available is False``
   and the available-but-empty case -- so the honesty constraint holds
   regardless of what the model returned.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pydantic_ai import Agent

from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge import prompts
from asc_metadata_verifier.judge.rubric import RubricDimension
from asc_metadata_verifier.models import AppMetadata, RubricVerdict

if TYPE_CHECKING:
    from pydantic_ai.models import Model

# Default judge model; overridable via the ASC_JUDGE_MODEL env var. pydantic-ai
# addresses Anthropic models with an "anthropic:" prefix (see its known-model
# names, e.g. "anthropic:claude-sonnet-5").
DEFAULT_JUDGE_MODEL = "claude-sonnet-5"

# Module alias kept so any external import of `SYSTEM_PROMPT` still resolves.
SYSTEM_PROMPT = prompts.TEXT_SYSTEM_PROMPT


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
            system_prompt=prompts.TEXT_SYSTEM_PROMPT,
            defer_model_check=True,
        )
    return Agent(model, output_type=RubricVerdict, system_prompt=prompts.TEXT_SYSTEM_PROMPT)


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
    grounding text actually used for that call is empty/falsy (which covers both
    ``guidelines.available is False`` and available-but-empty guidelines).
    """
    agent = build_judge(model)
    verdicts: list[RubricVerdict] = []
    for locale_meta in meta.locales:
        for dimension in dimensions:
            grounding = prompts.grounding_for_text(guidelines, dimension)
            prompt = prompts.build_text_prompt(dimension, locale_meta, grounding)
            result = agent.run_sync(prompt)

            update: dict[str, object] = {
                "locale": locale_meta.locale,
                "dimension": dimension.id,
            }
            # Force-None keys on the grounding ACTUALLY USED for this call, not
            # merely on `guidelines.available`: `grounding_for_text` can return ""
            # even when available is True (empty text + sections), and in that
            # case the prompt already told the model to return null -- so layer 2
            # must agree with layer 1 and scrub any ref regardless.
            if not grounding:
                update["guideline_ref"] = None
            verdicts.append(result.output.model_copy(update=update))
    return verdicts
