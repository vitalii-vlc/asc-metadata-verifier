"""Concurrent panel of judges. Gathers each client's vote per unit under a
shared semaphore, then applies the consensus policy. Vision reads each image
once and dispatches the bytes to every client (non-vision clients return
not_applicable). Sync `run_panel` wraps the async work for the CLI (called
outside any running loop)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from asc_metadata_verifier.judge import images, prompts
from asc_metadata_verifier.judge.client import JudgeClient
from asc_metadata_verifier.models import PanelVerdict

if TYPE_CHECKING:
    from asc_metadata_verifier.judge.config import JudgeSpec


class JudgePanel:
    def __init__(self, clients, policy, policy_name, max_concurrency=8):
        self.clients = list(clients)
        self.policy = policy
        self.policy_name = policy_name
        self.max_concurrency = max_concurrency
        self._sem: asyncio.Semaphore | None = None

    async def _bounded(self, coro):
        async with self._sem:
            return await coro

    async def judge_text(self, meta, guidelines, dimensions) -> list[PanelVerdict]:
        # Built fresh on every top-level call rather than once in `__init__`:
        # `asyncio.Semaphore` binds to whichever loop first `await`s it, and
        # `run_panel` opens a new loop per call via `asyncio.run`. A
        # semaphore built once in `__init__` would raise `RuntimeError:
        # bound to a different event loop` the first time a SECOND
        # `run_panel()` call on this same instance actually contends on it.
        # Safe to assign here with no race: this line runs to completion
        # before any `await`, so no other task can interleave and see a
        # half-built semaphore. Still a single semaphore shared by every
        # unit x judge call within this one call, i.e. concurrency
        # semantics are unchanged.
        self._sem = asyncio.Semaphore(self.max_concurrency)
        units = [(lm, d) for lm in meta.locales for d in dimensions]

        async def one(lm, d):
            grounding = prompts.grounding_for_text(guidelines, d)
            votes = list(await asyncio.gather(
                *[self._bounded(c.run_text(d, lm, grounding)) for c in self.clients]
            ))
            cons, agr = self.policy(votes, locale=lm.locale, dimension=d.id,
                                    default_field="description")
            return PanelVerdict(locale=lm.locale, dimension=d.id, field=cons.field,
                                votes=votes, consensus=cons, policy=self.policy_name, agreement=agr)

        return list(await asyncio.gather(*[one(lm, d) for lm, d in units]))

    async def judge_vision(self, screenshots, guidelines, dimensions) -> list[PanelVerdict]:
        if not any(c.supports_vision for c in self.clients):
            return []
        # Fresh semaphore for this entrypoint too -- see `judge_text` above.
        # `run_panel` awaits `judge_text` to completion before calling this,
        # so the two never contend on the semaphore concurrently; each still
        # bounds its own unit x judge calls to `max_concurrency` in flight.
        self._sem = asyncio.Semaphore(self.max_concurrency)
        prepared = []
        for s in screenshots:
            img = images.read_image(s)
            if img is not None:
                prepared.append((s, img))
        units = [(s, img, d) for (s, img) in prepared for d in dimensions]

        async def one(s, img, d):
            image_bytes, media_type = img
            grounding = prompts.grounding_for_vision(guidelines, d)
            votes = list(await asyncio.gather(
                *[self._bounded(c.run_vision(s, image_bytes, media_type, d, grounding))
                  for c in self.clients]
            ))
            cons, agr = self.policy(votes, locale=s.locale, dimension=d.id,
                                    default_field="screenshot")
            return PanelVerdict(locale=s.locale, dimension=d.id, field="screenshot",
                                votes=votes, consensus=cons, policy=self.policy_name, agreement=agr)

        return list(await asyncio.gather(*[one(s, img, d) for (s, img, d) in units]))

    def run_panel(self, meta, guidelines, text_dimensions, *, screenshots=None,
                  vision_dimensions=None, no_vision=False) -> list[PanelVerdict]:
        async def _all():
            text = await self.judge_text(meta, guidelines, text_dimensions)
            vision: list[PanelVerdict] = []
            if not no_vision and screenshots and vision_dimensions:
                vision = await self.judge_vision(screenshots, guidelines, vision_dimensions)
            return text + vision

        return asyncio.run(_all())


def build_panel(specs: list[JudgeSpec], policy_name: str, max_concurrency: int = 8):
    from asc_metadata_verifier.judge.consensus import POLICIES

    clients = [JudgeClient.from_spec(s) for s in specs if s.available]
    if not clients:
        return None
    return JudgePanel(clients, POLICIES[policy_name], policy_name, max_concurrency)
