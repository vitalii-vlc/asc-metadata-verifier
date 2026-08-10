"""Cross-run diff: compare two `RunRecord`s' findings.

A "present finding" is either:
  - a `RubricVerdict` with `verdict in {"warn", "fail"}` (a "pass" verdict is
    not a finding), keyed `(locale, dimension, field)`, carrying `severity`; or
  - a `DeterministicFinding`, always present, keyed `(locale, field, kind)`,
    with no severity (`dimension=None` on the resulting `FindingDelta`).

The two key spaces never collide (they're tagged with a `"rubric"`/`"det"`
discriminator internally), so a rubric finding and a deterministic finding
with coincidentally matching locale/field never merge into one delta.

For the union of keys across both runs, each key becomes one `FindingDelta`:
  - `new`: present in b, not a.
  - `resolved`: present in a, not b.
  - `severity_changed`: present in both, rubric severities differ (only
    possible for rubric findings -- deterministic findings have no severity,
    so they are never `severity_changed`).
  - `persisting`: present in both, otherwise (same rubric severity, or any
    deterministic finding present in both).

Pure, offline, deterministic: no timestamps, no I/O, no randomness. `deltas`
are sorted by a stable key so re-running the same diff always yields the same
list order.
"""

from __future__ import annotations

from asc_metadata_verifier.models import DeterministicFinding, GateReport, RubricVerdict
from asc_metadata_verifier.persistence.models import FindingDelta, FindingStatus, RunDiff, RunRecord

# Internal-only key shape (never persisted): a 4-tuple tagged "rubric" or
# "det" as its first element, which keeps the two key spaces disjoint even
# when locale/field happen to coincide -- ("rubric", locale, dimension, field)
# vs. ("det", locale, field, kind).
_FindingKey = tuple[str, str, str, str]


def _present_findings(report: GateReport) -> dict[_FindingKey, str | None]:
    """Map each present finding's key to its severity (`None` for deterministic
    findings, which have no severity concept)."""
    findings: dict[_FindingKey, str | None] = {}
    verdict: RubricVerdict
    for verdict in report.verdicts:
        if verdict.verdict in ("warn", "fail"):
            key = ("rubric", verdict.locale, verdict.dimension, verdict.field)
            findings[key] = verdict.severity
    finding: DeterministicFinding
    for finding in report.deterministic_findings:
        findings[("det", finding.locale, finding.field, finding.kind)] = None
    return findings


def _delta_sort_key(delta: FindingDelta) -> tuple[str, str, str, str, str]:
    return (delta.locale, delta.field, delta.dimension or "", delta.kind or "", delta.status)


def diff_runs(a: RunRecord, b: RunRecord) -> RunDiff:
    """Diff two runs' findings. Pure function of `a.report`/`b.report` (plus
    `a.gate_status`/`b.gate_status`) -- see the module docstring for semantics."""
    findings_a = _present_findings(a.report)
    findings_b = _present_findings(b.report)

    deltas: list[FindingDelta] = []
    for key in set(findings_a) | set(findings_b):
        source = key[0]
        in_a = key in findings_a
        in_b = key in findings_b
        severity_a = findings_a.get(key)
        severity_b = findings_b.get(key)

        if in_b and not in_a:
            status = FindingStatus.new
        elif in_a and not in_b:
            status = FindingStatus.resolved
        elif source == "rubric" and severity_a != severity_b:
            status = FindingStatus.severity_changed
        else:
            status = FindingStatus.persisting

        if source == "rubric":
            _, locale, dimension, field = key
            kind = None
        else:
            _, locale, field, kind = key
            dimension = None

        deltas.append(
            FindingDelta(
                locale=locale,
                dimension=dimension,
                field=field,
                kind=kind,
                status=status,
                severity_a=severity_a,
                severity_b=severity_b,
            )
        )

    deltas.sort(key=_delta_sort_key)
    return RunDiff(status_a=a.gate_status, status_b=b.gate_status, deltas=deltas)


def _delta_label(delta: FindingDelta) -> str:
    if delta.dimension is not None:
        return f"{delta.locale} / {delta.dimension} / {delta.field}"
    return f"{delta.locale} / {delta.field} ({delta.kind})"


def _delta_line(delta: FindingDelta) -> str:
    label = _delta_label(delta)
    if delta.status == FindingStatus.severity_changed:
        return f"{label}: {delta.severity_a} -> {delta.severity_b}"
    severity = delta.severity_a if delta.status == FindingStatus.resolved else delta.severity_b
    if delta.status == FindingStatus.persisting:
        severity = delta.severity_a or delta.severity_b
    return f"{label}: severity {severity}" if severity is not None else label


_SECTIONS = (
    (FindingStatus.new, "New"),
    (FindingStatus.resolved, "Resolved"),
    (FindingStatus.persisting, "Persisting"),
    (FindingStatus.severity_changed, "Severity changed"),
)


def render_diff_markdown(diff: RunDiff) -> str:
    """Render a `RunDiff` as human-readable markdown, grouped into New /
    Resolved / Persisting / Severity changed sections (in that order)."""
    lines: list[str] = [f"# Run diff: {diff.status_a} -> {diff.status_b}", ""]

    for status, title in _SECTIONS:
        matches = [d for d in diff.deltas if d.status == status]
        lines.append(f"## {title} ({len(matches)})")
        lines.append("")
        if not matches:
            lines.append(f"No {title.lower()} findings.")
            lines.append("")
            continue
        for delta in matches:
            lines.append(f"- {_delta_line(delta)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_diff_json(diff: RunDiff) -> str:
    """Serialize a `RunDiff` to JSON (round-trips via `RunDiff.model_validate_json`)."""
    return diff.model_dump_json(indent=2)
