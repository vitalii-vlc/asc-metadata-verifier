"""Opt-in LLM jury layer for the code analyzer.

Off by default; the static catalog stands alone. When enabled (`--jury` + a
judges config), it reuses the metadata jury's config + consensus `POLICIES` +
`JudgeVote`/`PanelVerdict` models, but with code-specific units and prompt --
the metadata `JudgePanel` is bound to `LocaleMetadata`/dimensions and cannot be
reused directly.

Two bounded modes:
  1. Adjudicate findings from rules marked `interpretive=True` (e.g.
     `boilerplate-usage-string`): a `pass`/dismiss consensus drops the static
     finding; a `fail`/`warn` keeps it with the `PanelVerdict` attached.
  2. Answer a FIXED set of interpretive questions over code regions whose
     trigger symbols appear (account-gating vs 5.1.1(v), IAP-bypass vs 3.1.1).

Every jury-produced item is a `CodeFinding` tagged `source="jury"` carrying the
full vote record -- LLM judgment is never presented as a deterministic fact.
Judge errors are isolated (any exception -> an `error` JudgeVote), and a
total judge failure yields the consensus policy's empty (pass) verdict, so a
broken jury never fabricates a finding."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Literal

from pydantic import BaseModel

from asc_metadata_verifier.code.parser import ASTIndex
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.code.rules import REGISTRY
from asc_metadata_verifier.judge.consensus import DEFAULT_POLICY, POLICIES
from asc_metadata_verifier.models import CodeFinding, JudgeVote, PanelVerdict, RubricVerdict

CODE_JURY_SYSTEM_PROMPT = (
    "You are an App Store review judge inspecting a SNIPPET of app source or a "
    "config value. Decide ONLY the specific question asked, grounded ONLY in the "
    "provided guideline text. If the snippet is insufficient to be sure, return "
    "verdict 'pass' with low confidence rather than guessing. Never invent a "
    "guideline_ref."
)

# A fixed, closed list -- NOT open-ended. Each question is asked only when its
# trigger symbols appear in the project's AST.
INTERPRETIVE_QUESTIONS: list[dict] = [
    {
        "id": "account-gating-5.1.1v",
        "guideline_ref": "5.1.1(v)",
        "triggers": {"loginViewController", "requireLogin", "AuthViewController", "signInRequired"},
        "question": "Does this code force account creation for features that don't need one "
                    "(5.1.1(v))?",
    },
    {
        "id": "iap-bypass-3.1.1",
        "guideline_ref": "3.1.1",
        "triggers": {"SKPayment", "StoreKit", "PurchaseManager", "checkoutURL"},
        "question": "Does this code sell digital goods/subscriptions outside In-App Purchase "
                    "(3.1.1)?",
    },
]

_INTERPRETIVE_RULE_IDS = frozenset(r.id for r in REGISTRY if getattr(r, "interpretive", False))


class InterpretiveUnit(BaseModel):
    id: str
    kind: Literal["adjudicate", "question"]
    question: str
    file: str
    line: int | None = None
    excerpt: str
    guideline_ref: str
    finding_ref: str | None = None
    finding: CodeFinding | None = None


def _build_code_prompt(unit: InterpretiveUnit, grounding: str) -> str:
    anchor = f"{unit.file}:{unit.line}" if unit.line is not None else unit.file
    parts = [
        f"Question: {unit.question}",
        f"Guideline: {unit.guideline_ref}",
        f"Location: {anchor}",
        "Code / config context:",
        unit.excerpt,
    ]
    if grounding:
        parts += ["Guideline text:", grounding]
    return "\n".join(parts)


class CodeJudge:
    """One configured model, judging code interpretive units. Never raises into
    the jury: any error becomes an `error` JudgeVote (mirrors JudgeClient)."""

    def __init__(self, name: str, agent):
        self.name = name
        self._agent = agent

    @classmethod
    def from_model(cls, name: str, model):
        from pydantic_ai import Agent

        return cls(name, Agent(model, output_type=RubricVerdict,
                               system_prompt=CODE_JURY_SYSTEM_PROMPT))

    @classmethod
    def from_spec(cls, spec):
        from pydantic_ai import Agent

        from asc_metadata_verifier.judge.client import _model_ref

        return cls(spec.name, Agent(_model_ref(spec), output_type=RubricVerdict,
                                    system_prompt=CODE_JURY_SYSTEM_PROMPT, defer_model_check=True))

    async def run(self, unit: InterpretiveUnit, grounding: str) -> JudgeVote:
        start = time.monotonic()
        try:
            result = await self._agent.run(_build_code_prompt(unit, grounding))
            update: dict[str, object] = {"locale": "code", "dimension": unit.id, "field": unit.file}
            if not grounding:
                update["guideline_ref"] = None
            verdict = result.output.model_copy(update=update)
        except Exception as exc:  # noqa: BLE001 - one judge's failure must not kill the jury
            return JudgeVote(judge=self.name, status="error", error=str(exc)[:300],
                             latency_ms=(time.monotonic() - start) * 1000)
        return JudgeVote(judge=self.name, status="voted", verdict=verdict,
                         latency_ms=(time.monotonic() - start) * 1000)

    def run_sync(self, unit: InterpretiveUnit, grounding: str) -> JudgeVote:
        return asyncio.run(self.run(unit, grounding))


class CodeJury:
    def __init__(self, judges: list[CodeJudge], policy_name: str, max_concurrency: int = 8):
        self.judges = list(judges)
        self.policy_name = policy_name if policy_name in POLICIES else DEFAULT_POLICY
        self.policy = POLICIES[self.policy_name]
        self.max_concurrency = max_concurrency

    @classmethod
    def build(cls, specs, policy_name: str, max_concurrency: int = 8) -> CodeJury | None:
        judges = [CodeJudge.from_spec(s) for s in specs if s.available]
        if not judges:
            return None
        return cls(judges, policy_name, max_concurrency)

    def judge_one(self, unit: InterpretiveUnit, grounding: str) -> PanelVerdict:
        async def _run() -> PanelVerdict:
            sem = asyncio.Semaphore(self.max_concurrency)

            async def bounded(judge: CodeJudge) -> JudgeVote:
                async with sem:
                    return await judge.run(unit, grounding)

            votes = list(await asyncio.gather(*[bounded(j) for j in self.judges]))
            cons, agr = self.policy(
                votes, locale="code", dimension=unit.id, default_field=unit.file)
            return PanelVerdict(locale="code", dimension=unit.id, field=unit.file, votes=votes,
                                consensus=cons, policy=self.policy_name, agreement=agr)

        return asyncio.run(_run())


def _project_symbols(asts: ASTIndex) -> set[str]:
    out: set[str] = set()
    for ast in asts.values():
        out |= ast.symbols()
    return out


def _first_symbol_site(triggers: set[str], asts: ASTIndex) -> tuple[str, int | None]:
    for path, ast in sorted(asts.items()):
        if triggers & ast.symbols():
            return path, 1
    return "<project>", None


def build_units(
    findings: list[CodeFinding], project: ProjectModel, asts: ASTIndex
) -> list[InterpretiveUnit]:
    units: list[InterpretiveUnit] = []
    for f in findings:
        if f.rule_id in _INTERPRETIVE_RULE_IDS:
            units.append(InterpretiveUnit(
                id=f.rule_id, kind="adjudicate",
                question=f"Is this a real {f.guideline_ref} problem, or acceptable? {f.detail}",
                file=f.file, line=f.line, excerpt=f.evidence, guideline_ref=f.guideline_ref,
                finding_ref=f.rule_id, finding=f))
    symbols = _project_symbols(asts)
    for q in INTERPRETIVE_QUESTIONS:
        hit = q["triggers"] & symbols
        if hit:
            file, line = _first_symbol_site(q["triggers"], asts)
            units.append(InterpretiveUnit(
                id=q["id"], kind="question", question=q["question"], file=file, line=line,
                excerpt=", ".join(sorted(hit)), guideline_ref=q["guideline_ref"]))
    return units


def _resolve_specs(judges):
    if not judges:
        return []
    from asc_metadata_verifier.judge.config import load_judges

    return load_judges(judges).specs


def _best_effort_grounding() -> str:
    try:
        from asc_metadata_verifier.guidelines.source import get_guidelines

        g = get_guidelines(uuid.uuid4().hex)
        return g.text if g.available else ""
    except Exception:  # noqa: BLE001 - grounding is optional; offline -> no grounding, never fatal
        return ""


def apply_jury(
    findings: list[CodeFinding],
    project: ProjectModel,
    asts: ASTIndex,
    *,
    judges=None,
    policy: str = DEFAULT_POLICY,
    jury: CodeJury | None = None,
    grounding: str | None = None,
) -> tuple[list[CodeFinding], bool]:
    """Adjudicate interpretive findings and answer triggered questions. Returns
    `(findings, used)`. With no judges available (offline / no keys), returns
    the input findings unchanged and `used=False`."""
    if jury is None:
        jury = CodeJury.build(_resolve_specs(judges), policy)
    if jury is None:
        return findings, False
    if grounding is None:
        grounding = _best_effort_grounding()

    out = [f for f in findings if f.rule_id not in _INTERPRETIVE_RULE_IDS]
    for unit in build_units(findings, project, asts):
        pv = jury.judge_one(unit, grounding)
        keep = pv.consensus.verdict in ("fail", "warn")
        if unit.kind == "adjudicate":
            if keep and unit.finding is not None:
                out.append(unit.finding.model_copy(
                    update={"source": "jury", "panel": pv, "confidence": pv.consensus.confidence}))
        elif keep:
            out.append(CodeFinding(
                rule_id=unit.id, category="interpretive", severity=pv.consensus.severity,
                guideline_ref=unit.guideline_ref, file=unit.file, line=unit.line,
                evidence=unit.excerpt[:120], detail=pv.consensus.rationale, source="jury",
                panel=pv, confidence=pv.consensus.confidence))
    out.sort(key=lambda f: (f.file, f.line or 0, f.rule_id))
    return out, True
