"""Gate aggregation: classify verdicts/findings and decide PASS/WARN/BLOCK.

Two kinds of input feed the gate:
  - `RubricVerdict`s from the LLM judge (Task 9).
  - `DeterministicFinding`s from the LLM-free checks (Task 5).

Each item is classified into an outcome level ("block", "warn", or "none"),
then the overall `GateReport.status` is rolled up from those levels per the
`fail_on` threshold. See the per-function docstrings for the exact rules.
"""

from typing import Literal

from asc_metadata_verifier.models import (
    CodeFinding,
    DeterministicFinding,
    GateReport,
    PanelVerdict,
    RubricVerdict,
)

Level = Literal["block", "warn", "none"]

# Deterministic findings are objective vs. heuristic:
#   - over_limit / missing_required are guaranteed App Store rejections ->
#     BLOCK-worthy, same tier as a high-severity judge fail.
#   - placeholder / malformed_url are heuristic signals -> WARN-worthy.
# This mapping is deliberately a small, visible/revisable dict rather than
# inline conditionals, since the plan did not pin it explicitly.
_DETERMINISTIC_LEVEL: dict[str, Level] = {
    "over_limit": "block",
    "missing_required": "block",
    "placeholder": "warn",
    "malformed_url": "warn",
}


def _verdict_level(verdict: RubricVerdict) -> Level:
    """Classify a single RubricVerdict into a block/warn/none outcome level.

    - fail + high severity -> block (a hard rejection signal).
    - fail + low/medium severity, or any warn -> warn (a soft signal).
    - pass -> none.
    """
    if verdict.verdict == "fail":
        return "block" if verdict.severity == "high" else "warn"
    if verdict.verdict == "warn":
        return "warn"
    return "none"


def _finding_level(finding: DeterministicFinding) -> Level:
    """Classify a single DeterministicFinding via the `_DETERMINISTIC_LEVEL` map."""
    return _DETERMINISTIC_LEVEL.get(finding.kind, "none")


def _code_level(finding: CodeFinding) -> Level:
    """high -> block (near-certain rejection); medium/low -> warn. Mirrors
    `_verdict_level`: only high severity blocks by default. A CodeFinding's
    severity is always low/medium/high, so this never returns "none"."""
    return "block" if finding.severity == "high" else "warn"


def evaluate(
    verdicts: list[RubricVerdict],
    deterministic_findings: list[DeterministicFinding],
    fail_on: Literal["fail", "warn"] = "fail",
    guidelines_available: bool = True,
    panels: list[PanelVerdict] | None = None,
    code_findings: list[CodeFinding] | None = None,
) -> GateReport:
    """Aggregate verdicts + deterministic findings into a single GateReport.

    Every item is classified into a level (see `_verdict_level` /
    `_finding_level`), then the overall status is decided by `fail_on`:

    - `fail_on="fail"` (default): status is "BLOCK" if any item is
      block-worthy; else "WARN" if any item is warn-worthy; else "PASS".
      Only high-severity fails (and over_limit/missing_required findings)
      block by default -- a medium/low-severity fail is WARN, not BLOCK.
    - `fail_on="warn"` (lowered threshold): status is "BLOCK" if any item is
      block-worthy OR warn-worthy; else "PASS".
    """
    code_findings = code_findings or []
    levels: list[Level] = [_verdict_level(v) for v in verdicts]
    levels.extend(_finding_level(f) for f in deterministic_findings)
    levels.extend(_code_level(f) for f in code_findings)

    has_block = "block" in levels
    has_warn = "warn" in levels

    status: Literal["PASS", "WARN", "BLOCK"]
    if fail_on == "warn":
        status = "BLOCK" if (has_block or has_warn) else "PASS"
    else:
        status = "BLOCK" if has_block else ("WARN" if has_warn else "PASS")

    return GateReport(
        status=status,
        verdicts=verdicts,
        deterministic_findings=deterministic_findings,
        guidelines_available=guidelines_available,
        panels=panels or [],
        code_findings=code_findings,
    )
