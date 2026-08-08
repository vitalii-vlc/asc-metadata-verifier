"""Render a `GateReport` as markdown or JSON, and compute the CLI exit code.

Pure string building only -- no `rich`/console output here. That belongs to
the CLI (Task 12), which decides how to print/colorize what these functions
return.
"""

from collections import defaultdict

from asc_metadata_verifier.models import DeterministicFinding, GateReport, RubricVerdict

_NOT_AVAILABLE = "n/a"


def render_json(report: GateReport) -> str:
    """Serialize a GateReport to JSON (round-trips via `GateReport.model_validate_json`)."""
    return report.model_dump_json(indent=2)


def _verdict_section(verdict: RubricVerdict) -> list[str]:
    lines = [f"- **verdict:** {verdict.verdict} (severity: {verdict.severity})"]
    lines.append(f"  - **offending quote:** {verdict.offending_quote or _NOT_AVAILABLE}")
    lines.append(f"  - **guideline:** {verdict.guideline_ref or _NOT_AVAILABLE}")
    lines.append(f"  - **rationale:** {verdict.rationale}")
    lines.append(f"  - **suggested fix:** {verdict.suggested_fix or _NOT_AVAILABLE}")
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


def render_markdown(report: GateReport) -> str:
    """Render a GateReport as a human-readable markdown report.

    Sections, in order:
      1. Overall status heading, plus a note when guideline references were
         unavailable (offline mode).
      2. Rubric verdicts, grouped by locale x dimension; each non-pass
         verdict includes its offending quote, guideline reference (or
         "n/a"), rationale, and suggested fix.
      3. Deterministic findings (locale, field, kind, detail).
    """
    lines: list[str] = [f"# ASC Metadata Verifier Report: {report.status}", ""]
    if not report.guidelines_available:
        lines.append("_Note: guideline references unavailable (offline)._")
        lines.append("")

    lines.extend(_render_verdicts(report.verdicts))
    lines.extend(_render_findings(report.deterministic_findings))

    return "\n".join(lines).rstrip() + "\n"


def exit_code(report: GateReport) -> int:
    """Return the process exit code for a GateReport: 1 for BLOCK, 0 otherwise."""
    return 1 if report.status == "BLOCK" else 0
