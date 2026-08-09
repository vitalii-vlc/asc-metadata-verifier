"""One configured model, wrapped as a judge that votes on text and (optionally)
vision units. Mirrors v1's honesty post-processing per call and never raises
into the panel: any error becomes an `error` JudgeVote."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pydantic_ai import Agent, BinaryContent

from asc_metadata_verifier.judge import prompts
from asc_metadata_verifier.models import JudgeVote, RubricVerdict

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from asc_metadata_verifier.judge.config import JudgeSpec
    from asc_metadata_verifier.judge.rubric import RubricDimension
    from asc_metadata_verifier.judge.vision import VisionDimension
    from asc_metadata_verifier.models import LocaleMetadata, Screenshot

_ERR_MAX = 300


class JudgeClient:
    def __init__(self, name, text_agent, vision_agent=None, supports_vision=False):
        self.name = name
        self._text_agent = text_agent
        self._vision_agent = vision_agent
        self.supports_vision = supports_vision

    @classmethod
    def from_model(cls, name: str, model: Model | str, *, supports_vision: bool = False):
        text = Agent(model, output_type=RubricVerdict, system_prompt=prompts.TEXT_SYSTEM_PROMPT)
        vision = (
            Agent(model, output_type=RubricVerdict, system_prompt=prompts.VISION_SYSTEM_PROMPT)
            if supports_vision else None
        )
        return cls(name, text, vision, supports_vision)

    @classmethod
    def from_spec(cls, spec: JudgeSpec):
        model_ref = _model_ref(spec)
        text = Agent(model_ref, output_type=RubricVerdict,
                     system_prompt=prompts.TEXT_SYSTEM_PROMPT, defer_model_check=True)
        vision = (
            Agent(model_ref, output_type=RubricVerdict,
                  system_prompt=prompts.VISION_SYSTEM_PROMPT, defer_model_check=True)
            if spec.vision else None
        )
        return cls(spec.name, text, vision, spec.vision)

    async def run_text(self, dimension: RubricDimension, locale_meta: LocaleMetadata,
                       grounding: str) -> JudgeVote:
        # text: field is model-reported (v1 behavior) -> stamp only locale+dimension.
        # Prompt building happens inside `_run`'s try so it can never raise into the caller.
        return await self._run(
            self._text_agent,
            lambda: [prompts.build_text_prompt(dimension, locale_meta, grounding)],
            locale_meta.locale, dimension.id, None, grounding,
        )

    async def run_vision(self, screenshot: Screenshot, image_bytes: bytes, media_type: str,
                         dimension: VisionDimension, grounding: str) -> JudgeVote:
        if not self.supports_vision or self._vision_agent is None:
            return JudgeVote(judge=self.name, status="not_applicable")

        def build_content():
            prompt = prompts.build_vision_prompt(dimension, screenshot, grounding)
            return [prompt, BinaryContent(data=image_bytes, media_type=media_type)]

        return await self._run(self._vision_agent, build_content,
                               screenshot.locale, dimension.id, "screenshot", grounding)

    async def _run(self, agent, build_content, locale, dimension, field, grounding) -> JudgeVote:
        """Run one agent call and stamp the verdict. Everything that can raise --
        prompt/content construction, the model call, and the post-run `model_copy`
        stamping -- lives inside this single `try` so `run_text`/`run_vision` truly
        never raise into the panel; any failure anywhere in that path becomes an
        `error` JudgeVote instead.
        """
        start = time.monotonic()
        try:
            content = build_content()
            result = await agent.run(content)
            update: dict[str, object] = {"locale": locale, "dimension": dimension}
            if field is not None:
                update["field"] = field
            if not grounding:
                update["guideline_ref"] = None
            verdict = result.output.model_copy(update=update)
        except Exception as exc:  # noqa: BLE001 - one judge's failure must not kill the panel
            return JudgeVote(judge=self.name, status="error", error=str(exc)[:_ERR_MAX],
                             latency_ms=(time.monotonic() - start) * 1000)
        return JudgeVote(judge=self.name, status="voted", verdict=verdict,
                         latency_ms=(time.monotonic() - start) * 1000)


def _model_ref(spec: JudgeSpec):
    """Resolve a JudgeSpec to a pydantic-ai model reference.

    anthropic -> "anthropic:<model>" (deferred by the Agent). openai (and any
    OpenAI-compatible base_url) -> an OpenAI model carrying base_url + key.

    Task 4 Step 0 verification: the installed pydantic-ai (2.27+) exposes
    `OpenAIChatModel` in `pydantic_ai.models.openai` (there is no
    `OpenAIModel` in this version) -- see BUILD_LOG.md for the exact
    `dir()` output recorded at implementation time.
    """
    if spec.provider == "anthropic":
        return f"anthropic:{spec.model}"
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    provider = OpenAIProvider(
        base_url=spec.base_url or "https://api.openai.com/v1",
        api_key=spec.api_key or "not-needed",   # local servers ignore it; client needs non-empty
    )
    return OpenAIChatModel(spec.model, provider=provider)
