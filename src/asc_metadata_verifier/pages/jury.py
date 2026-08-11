"""Opt-in page jury. Off by default; reuses A's config + consensus + models with
page-specific units. Grounded ONLY in the fetched page text. Error-isolated; a
total judge failure yields the empty (pass) consensus, never a fabricated finding.
Direct analogue of code/jury.py."""

from __future__ import annotations

import asyncio
import time

from pydantic import BaseModel

from asc_metadata_verifier.judge.consensus import DEFAULT_POLICY, POLICIES
from asc_metadata_verifier.models import JudgeVote, PageFinding, PanelVerdict, RubricVerdict
from asc_metadata_verifier.pages.fetch import FetchedPage
from asc_metadata_verifier.pages.profile import DataCollectionProfile

PAGE_JURY_SYSTEM_PROMPT = (
    "You are an App Store review judge inspecting the TEXT of one of the app's web "
    "pages (privacy policy, support, or marketing). Decide ONLY the specific question "
    "asked, grounded ONLY in the provided page text. If the text is insufficient to be "
    "sure, return verdict 'pass' with low confidence rather than guessing. Never invent "
    "a guideline_ref."
)


class PageUnit(BaseModel):
    id: str
    page_type: str
    url: str
    question: str
    guideline_ref: str
    text: str
    category: str | None = None


def _build_prompt(unit: PageUnit, grounding: str) -> str:
    parts = [f"Question: {unit.question}", f"Guideline: {unit.guideline_ref}",
             f"Page ({unit.page_type}): {unit.url}", "Page text:", unit.text[:6000]]
    if grounding:
        parts += ["Guideline text:", grounding]
    return "\n".join(parts)


class PageJudge:
    def __init__(self, name: str, agent):
        self.name = name
        self._agent = agent

    @classmethod
    def from_model(cls, name: str, model):
        from pydantic_ai import Agent

        return cls(name, Agent(model, output_type=RubricVerdict,
                               system_prompt=PAGE_JURY_SYSTEM_PROMPT))

    @classmethod
    def from_spec(cls, spec):
        from pydantic_ai import Agent

        from asc_metadata_verifier.judge.client import _model_ref

        return cls(spec.name, Agent(_model_ref(spec), output_type=RubricVerdict,
                                    system_prompt=PAGE_JURY_SYSTEM_PROMPT, defer_model_check=True))

    async def run(self, unit: PageUnit, grounding: str) -> JudgeVote:
        start = time.monotonic()
        try:
            result = await self._agent.run(_build_prompt(unit, grounding))
            update: dict[str, object] = {
                "locale": "page", "dimension": unit.id, "field": unit.page_type}
            if not grounding:
                update["guideline_ref"] = None
            verdict = result.output.model_copy(update=update)
        except Exception as exc:  # noqa: BLE001 - one judge's failure must not kill the jury
            return JudgeVote(judge=self.name, status="error", error=str(exc)[:300],
                             latency_ms=(time.monotonic() - start) * 1000)
        return JudgeVote(judge=self.name, status="voted", verdict=verdict,
                         latency_ms=(time.monotonic() - start) * 1000)

    def run_sync(self, unit: PageUnit, grounding: str) -> JudgeVote:
        return asyncio.run(self.run(unit, grounding))


class PageJury:
    def __init__(self, judges: list[PageJudge], policy_name: str, max_concurrency: int = 8):
        self.judges = list(judges)
        self.policy_name = policy_name if policy_name in POLICIES else DEFAULT_POLICY
        self.policy = POLICIES[self.policy_name]
        self.max_concurrency = max_concurrency

    @classmethod
    def build(cls, specs, policy_name: str, max_concurrency: int = 8) -> PageJury | None:
        judges = [PageJudge.from_spec(s) for s in specs if s.available]
        return cls(judges, policy_name, max_concurrency) if judges else None

    def judge_one(self, unit: PageUnit, grounding: str) -> PanelVerdict:
        async def _run() -> PanelVerdict:
            sem = asyncio.Semaphore(self.max_concurrency)

            async def bounded(judge: PageJudge) -> JudgeVote:
                async with sem:
                    return await judge.run(unit, grounding)

            votes = list(await asyncio.gather(*[bounded(j) for j in self.judges]))
            cons, agr = self.policy(votes, locale="page", dimension=unit.id,
                                    default_field=unit.page_type)
            return PanelVerdict(locale="page", dimension=unit.id, field=unit.page_type, votes=votes,
                                consensus=cons, policy=self.policy_name, agreement=agr)

        return asyncio.run(_run())


def _finding(unit: PageUnit, pv: PanelVerdict, severity: str, category: str,
             evidence: str) -> PageFinding:
    return PageFinding(page_type=unit.page_type, url=unit.url, rule_id=unit.id, category=category,
                       severity=severity, guideline_ref=unit.guideline_ref, evidence=evidence,
                       detail=pv.consensus.rationale, source="jury", panel=pv,
                       confidence=pv.consensus.confidence)


def apply_page_jury(pages_by_type: dict[str, FetchedPage], profile: DataCollectionProfile, *,
                    jury: PageJury, grounding: str = "") -> list[PageFinding]:
    out: list[PageFinding] = []
    priv = pages_by_type.get("privacy")
    if priv and priv.ok and priv.text:
        u = PageUnit(id="privacy-policy-inadequate", page_type="privacy", url=priv.url,
                     question="Is this a genuine, adequate privacy policy (states what data is "
                     "collected, how it is used, and a contact)?", guideline_ref="5.1.1",
                     text=priv.text)
        pv = jury.judge_one(u, grounding)
        if pv.consensus.verdict in ("fail", "warn"):
            out.append(_finding(u, pv, "high", "privacy", priv.text[:120]))
        for cat in profile.categories:
            u = PageUnit(id="privacy-code-mismatch", page_type="privacy", url=priv.url,
                         question=f"The app's code accesses {cat}. Does this privacy policy "
                         f"disclose collecting or using {cat}?", guideline_ref="5.1.1",
                         text=priv.text, category=cat)
            pv = jury.judge_one(u, grounding)
            if pv.consensus.verdict in ("fail", "warn"):
                out.append(_finding(u, pv, "high", cat, f"code accesses {cat}; policy silent"))
    supp = pages_by_type.get("support")
    if supp and supp.ok and supp.text:
        u = PageUnit(id="support-inadequate", page_type="support", url=supp.url,
                     question="Does this support page offer a real way to get help or contact a "
                     "human (email, form, or clear instructions)?", guideline_ref="5.1.1",
                     text=supp.text)
        pv = jury.judge_one(u, grounding)
        if pv.consensus.verdict in ("fail", "warn"):
            out.append(_finding(u, pv, "medium", "support", supp.text[:120]))
    mkt = pages_by_type.get("marketing")
    if mkt and mkt.ok and mkt.text:
        u = PageUnit(id="marketing-overclaim", page_type="marketing", url=mkt.url,
                     question="Does this marketing copy overclaim, mention other platforms "
                     "(Android/Google Play), or mislead about the app?", guideline_ref="2.3.1",
                     text=mkt.text)
        pv = jury.judge_one(u, grounding)
        if pv.consensus.verdict in ("fail", "warn"):
            out.append(_finding(u, pv, "medium", "marketing", mkt.text[:120]))
    return out
