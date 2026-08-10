from asc_metadata_verifier.models import DeterministicFinding, GateReport, RubricVerdict
from asc_metadata_verifier.persistence.diff import diff_runs, render_diff_markdown
from asc_metadata_verifier.persistence.models import FindingStatus, RunRecord


def _v(dim, verdict, sev, field="description", locale="en-US"):
    return RubricVerdict(dimension=dim, verdict=verdict, severity=sev, confidence=0.9,
                         rationale="r", locale=locale, field=field)


def _rec(run_id, status, verdicts=(), findings=()):
    return RunRecord(run_id=run_id, created_at="t", source="fastlane", config_fingerprint="c",
                     gate_status=status,
                     report=GateReport(status=status, guidelines_available=True,
                                       verdicts=list(verdicts),
                                       deterministic_findings=list(findings)))


def test_new_resolved_persisting_severity_changed():
    a = _rec("a", "WARN", verdicts=[_v("placeholder_text", "warn", "medium"),
                                    _v("misleading_claims", "fail", "high")])
    b = _rec("b", "BLOCK", verdicts=[_v("placeholder_text", "warn", "high"),   # severity changed
                                     _v("other_platform_mentions", "fail", "high")])  # new
    d = diff_runs(a, b)
    by = {(x.dimension, x.status) for x in d.deltas}
    assert ("other_platform_mentions", FindingStatus.new) in by
    assert ("misleading_claims", FindingStatus.resolved) in by
    assert ("placeholder_text", FindingStatus.severity_changed) in by
    assert d.status_a == "WARN" and d.status_b == "BLOCK"


def test_pass_verdicts_are_not_findings():
    a = _rec("a", "PASS", verdicts=[_v("placeholder_text", "pass", "low")])
    b = _rec("b", "PASS", verdicts=[_v("placeholder_text", "pass", "low")])
    assert diff_runs(a, b).deltas == []


def test_deterministic_findings_diffed_by_kind():
    fa = DeterministicFinding(locale="en-US", field="app_name", kind="over_limit", detail="d")
    d = diff_runs(_rec("a", "BLOCK", findings=[fa]), _rec("b", "PASS"))
    assert d.deltas[0].status is FindingStatus.resolved and d.deltas[0].kind == "over_limit"


def test_markdown_renders_sections():
    a = _rec("a", "PASS")
    b = _rec("b", "BLOCK", verdicts=[_v("placeholder_text", "fail", "high")])
    md = render_diff_markdown(diff_runs(a, b))
    assert "PASS" in md and "BLOCK" in md and "placeholder_text" in md
