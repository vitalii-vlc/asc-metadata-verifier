"""Render a `GateReport` as markdown or JSON, and compute the CLI exit code.

Pure string building only -- no `rich`/console output here. That belongs to
the CLI (Task 12), which decides how to print/colorize what these functions
return.
"""

from collections import Counter, defaultdict

from asc_metadata_verifier.models import (
    CodeFinding,
    CodeReport,
    DeterministicFinding,
    GateReport,
    PanelVerdict,
    RubricVerdict,
)

_NOT_AVAILABLE = "n/a"


def render_json(report: GateReport) -> str:
    """Serialize a GateReport to JSON (round-trips via `GateReport.model_validate_json`)."""
    return report.model_dump_json(indent=2)


def _or_not_available(value: str | None) -> str:
    return _NOT_AVAILABLE if value is None else value


def _verdict_section(verdict: RubricVerdict) -> list[str]:
    lines = [
        f"- **field:** {verdict.field} — **verdict:** {verdict.verdict} "
        f"(severity: {verdict.severity})"
    ]
    lines.append(f"  - **offending quote:** {_or_not_available(verdict.offending_quote)}")
    lines.append(f"  - **guideline:** {_or_not_available(verdict.guideline_ref)}")
    lines.append(f"  - **rationale:** {verdict.rationale}")
    lines.append(f"  - **suggested fix:** {_or_not_available(verdict.suggested_fix)}")
    return lines


def _render_verdicts(verdicts: list[RubricVerdict]) -> list[str]:
    if not verdicts:
        return ["## Rubric verdicts", "", "No rubric verdicts.", ""]

    grouped: dict[tuple[str, str], list[RubricVerdict]] = defaultdict(list)
    for verdict in verdicts:
        grouped[(verdict.locale, verdict.dimension)].append(verdict)

    lines = ["## Rubric verdicts", ""]
    for locale, dimension in sorted(grouped):
        lines.append(f"### {locale} / {dimension}")
        lines.append("")
        for verdict in grouped[(locale, dimension)]:
            if verdict.verdict == "pass":
                lines.append(f"- **verdict:** pass (severity: {verdict.severity})")
                continue
            lines.extend(_verdict_section(verdict))
        lines.append("")
    return lines


def compute_degradation(panels: list[PanelVerdict]) -> tuple[int, int]:
    """Count signs of a degraded jury run across `panels`.

    Returns `(error_votes, empty_tally_units)`:
      - `error_votes`: total judge votes with `status == "error"` across all
        panels (a runtime failure -- revoked key, bad model id, network --
        as opposed to `abstained`/`not_applicable`, which are expected).
      - `empty_tally_units`: panels (locale x dimension units) where NOT ONE
        vote has `status == "voted"` -- every judge failed/abstained for
        that unit, so the consensus policy fell back to its empty-tally
        `pass` (see `judge.consensus._empty`) and the unit silently
        defaulted to pass rather than reflecting a real judgment.

    Both are 0 for a healthy run, so callers gate a warning on
    `error_votes or empty_tally_units`. Shared by `render_markdown` (inline
    note) and the CLI (`verify`'s stderr warning) so both surfaces agree on
    what counts as "degraded".
    """
    error_votes = sum(1 for p in panels for v in p.votes if v.status == "error")
    empty_tally_units = sum(1 for p in panels if not any(v.status == "voted" for v in p.votes))
    return error_votes, empty_tally_units


def _degradation_note(panels: list[PanelVerdict]) -> str | None:
    """The markdown degraded-jury note, or None when the run is healthy.

    Only mentions the parts that are non-zero, so e.g. an empty-tally unit
    caused purely by abstains (0 errors) doesn't claim a false "N judge
    call(s) failed".
    """
    error_votes, empty_tally_units = compute_degradation(panels)
    if not error_votes and not empty_tally_units:
        return None

    parts = []
    if error_votes:
        parts.append(f"{error_votes} judge call(s) failed")
    if empty_tally_units:
        parts.append(
            f"{empty_tally_units} unit(s) received no successful vote — "
            "those units defaulted to pass"
        )
    return f"_Note: {' and '.join(parts)}. See --format json for per-judge errors._"


def _render_panels(panels: list[PanelVerdict]) -> list[str]:
    multi = [p for p in panels if sum(1 for v in p.votes if v.status == "voted") >= 2]
    if not multi:
        return []
    lines = ["## Panel deliberation", ""]
    for p in multi:
        voters = [v for v in p.votes if v.status == "voted"]
        tally = Counter(v.verdict.verdict for v in voters)
        breakdown = " / ".join(f"{n} {vd}" for vd, n in tally.most_common())
        agr = "n/a" if p.agreement is None else f"{p.agreement:.2f}"
        lines.append(
            f"- **{p.locale} / {p.dimension}**: {len(voters)} judges → {breakdown} "
            f"({p.policy} ⇒ {p.consensus.verdict}; agreement {agr})"
        )
    lines.append("")
    return lines


def _render_findings(findings: list[DeterministicFinding]) -> list[str]:
    lines = ["## Deterministic findings", ""]
    if not findings:
        lines.append("No deterministic findings.")
        lines.append("")
        return lines

    for finding in findings:
        lines.append(f"- **{finding.locale} / {finding.field}** ({finding.kind}): {finding.detail}")
    lines.append("")
    return lines


def _render_code_findings(findings: list[CodeFinding]) -> list[str]:
    """Render code findings grouped by category. Empty list -> no lines."""
    if not findings:
        return []
    lines: list[str] = ["## Code findings", ""]
    by_cat: dict[str, list[CodeFinding]] = defaultdict(list)
    for f in findings:
        by_cat[f.category].append(f)
    for category in sorted(by_cat):
        lines.append(f"### {category}")
        for f in by_cat[category]:
            anchor = f"{f.file}:{f.line}" if f.line is not None else f.file
            tag = "jury" if f.source == "jury" else "static"
            lines.append(f"- [{f.severity}] {f.rule_id} ({f.guideline_ref}) [{tag}] {anchor}")
            lines.append(f"    {f.detail} — evidence: {f.evidence!r}")
            if f.suggested_fix:
                lines.append(f"    fix: {f.suggested_fix}")
        lines.append("")
    return lines


def render_code_report_text(report: CodeReport) -> str:
    """Render a standalone CodeReport as human-readable text."""
    header = [
        f"Code analysis: {report.status}",
        f"({report.analyzed_files} files, backend={report.parser_backend}, "
        f"jury={report.jury_used})",
        "",
    ]
    body = _render_code_findings(report.findings) or ["No code findings."]
    return "\n".join(header + body).rstrip() + "\n"


def render_code_report_json(report: CodeReport) -> str:
    """Serialize a CodeReport to JSON (round-trips via `CodeReport.model_validate_json`)."""
    return report.model_dump_json(indent=2)


def render_markdown(report: GateReport) -> str:
    """Render a GateReport as a human-readable markdown report.

    Sections, in order:
      1. Overall status heading, plus a note when guideline references were
         unavailable (offline mode), plus a note when the jury panel is
         degraded (>=1 error vote and/or >=1 empty-tally unit -- see
         `compute_degradation`). Gate semantics are unchanged by this note:
         a degraded run still conservatively PASSes those units; the note
         only makes that fact visible instead of silent. Neither note
         appears for a healthy run.
      2. Rubric verdicts, grouped by locale x dimension; each non-pass
         verdict includes its field, offending quote, guideline reference
         (or "n/a"), rationale, and suggested fix.
      3. Panel deliberation: one line per panel with >=2 voted judges,
         showing the vote breakdown, policy, consensus, and agreement.
         Omitted entirely when no panel has >=2 voted votes.
      4. Deterministic findings (locale, field, kind, detail).
    """
    lines: list[str] = [f"# ASC Metadata Verifier Report: {report.status}", ""]
    if not report.guidelines_available:
        lines.append("_Note: guideline references unavailable (offline)._")
        lines.append("")

    degradation_note = _degradation_note(report.panels)
    if degradation_note is not None:
        lines.append(degradation_note)
        lines.append("")

    lines.extend(_render_verdicts(report.verdicts))
    lines.extend(_render_panels(report.panels))
    lines.extend(_render_findings(report.deterministic_findings))
    lines.extend(_render_code_findings(report.code_findings))

    return "\n".join(lines).rstrip() + "\n"


def exit_code(report: GateReport) -> int:
    """Return the process exit code for a GateReport: 1 for BLOCK, 0 otherwise."""
    return 1 if report.status == "BLOCK" else 0
