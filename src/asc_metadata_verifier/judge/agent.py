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
from typing import TYPE_CHECKING, Protocol

from pydantic_ai import Agent

from asc_metadata_verifier.guidelines.source import Guidelines
from asc_metadata_verifier.judge import prompts
from asc_metadata_verifier.judge.rubric import RubricDimension
from asc_metadata_verifier.models import AppMetadata, RubricVerdict
from asc_metadata_verifier.persistence.cache import verdict_cache_key

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    class _VerdictCacheLike(Protocol):
        """Duck-typed cache seam: anything with `.get`/`.put` for RubricVerdict."""

        def get(self, key: str) -> RubricVerdict | None: ...

        def put(self, key: str, verdict: RubricVerdict) -> None: ...

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
    cache: _VerdictCacheLike | None = None,
) -> list[RubricVerdict]:
    """Judge every (locale, dimension) pair and return the collected verdicts.

    One agent run per pair. After each run the verdict's ``locale`` and
    ``dimension`` are set authoritatively from the inputs (the model is not
    trusted to echo them), and ``guideline_ref`` is forced to None whenever the
    grounding text actually used for that call is empty/falsy (which covers both
    ``guidelines.available is False`` and available-but-empty guidelines).

    ``cache`` is an OPTIONAL, duck-typed seam (anything with ``.get``/``.put``,
    e.g. ``persistence.cache.VerdictCache``). When ``None`` (the default), the
    agent runs exactly as before -- no cache lookups, no behavior change. When
    provided, each (locale, dimension) prompt is hashed (together with the
    resolved model name) into a cache key: a hit reuses the cached verdict
    (still defensively re-stamped with the authoritative locale/dimension, and
    with no model call), a miss runs the agent as usual and stores the result.
    """
    agent = build_judge(model)
    model_name = str(agent.model) if cache is not None else None
    verdicts: list[RubricVerdict] = []
    for locale_meta in meta.locales:
        for dimension in dimensions:
            grounding = prompts.grounding_for_text(guidelines, dimension)
            prompt = prompts.build_text_prompt(dimension, locale_meta, grounding)

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

            if cache is not None:
                key = verdict_cache_key(prompt, model_name)
                cached = cache.get(key)
                if cached is not None:
                    verdicts.append(cached.model_copy(update=update))
                    continue
                result = agent.run_sync(prompt)
                verdict = result.output.model_copy(update=update)
                cache.put(key, verdict)
                verdicts.append(verdict)
                continue

            result = agent.run_sync(prompt)
            verdicts.append(result.output.model_copy(update=update))
    return verdicts
