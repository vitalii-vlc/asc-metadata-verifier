"""Render a GateReport as a self-contained, offline, deterministic HTML report.

Pure string building (like report.py); no time/randomness (the caller passes
`generated_at`). Honesty: evidence-only (no fabricated before/after), prompts
from real fields, everything model-derived is html.escape'd, guideline_ref None
-> "n/a", jury panels show real votes. CSS/JS ported verbatim from the approved
template."""

from __future__ import annotations

from dataclasses import dataclass

from asc_metadata_verifier.gate import (
    _code_level,
    _finding_level,
    _page_level,
    _verdict_level,
)
from asc_metadata_verifier.models import GateReport, PanelVerdict

_SEV_LABEL = {"block": "Block", "warn": "Warn"}


@dataclass(frozen=True)
class _Row:
    subsystem: str
    level: str
    sev_label: str
    rule_label: str
    guideline_ref: str | None
    anchor: str
    source: str
    rationale: str
    evidence: str | None
    suggested_fix: str | None
    panel: PanelVerdict | None


def _rows_from_report(report: GateReport) -> list[_Row]:
    rows: list[_Row] = []
    if report.panels:
        for p in report.panels:
            v = p.consensus
            level = _verdict_level(v)
            if level == "none":
                continue
            rows.append(_Row("Metadata", level, _SEV_LABEL[level], v.dimension, v.guideline_ref,
                             f"{v.locale} · {v.field}", "jury", v.rationale,
                             v.offending_quote, v.suggested_fix, p))
    else:
        for v in report.verdicts:
            level = _verdict_level(v)
            if level == "none":
                continue
            rows.append(_Row("Metadata", level, _SEV_LABEL[level], v.dimension, v.guideline_ref,
                             f"{v.locale} · {v.field}", "static", v.rationale,
                             v.offending_quote, v.suggested_fix, None))
    for f in report.deterministic_findings:
        level = _finding_level(f)
        if level == "none":
            continue
        rows.append(_Row("Metadata", level, _SEV_LABEL[level], f.kind, None,
                         f"{f.locale} · {f.field}", "static", f.detail, None, None, None))
    for f in report.code_findings:
        level = _code_level(f)
        anchor = f"{f.file}:{f.line}" if f.line is not None else f.file
        rows.append(_Row("Code", level, _SEV_LABEL[level], f.rule_id, f.guideline_ref, anchor,
                         f.source, f.detail, f.evidence, f.suggested_fix, f.panel))
    for f in report.page_findings:
        level = _page_level(f)
        rows.append(_Row("Pages", level, _SEV_LABEL[level], f.rule_id, f.guideline_ref,
                         f"{f.page_type} · {f.url}", f.source, f.detail, f.evidence,
                         f.suggested_fix, f.panel))
    return rows
