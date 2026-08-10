from asc_metadata_verifier.models import GateReport, RubricVerdict
from asc_metadata_verifier.persistence.models import (
    FindingDelta,
    FindingStatus,
    RunDiff,
    RunRecord,
    RunSummary,
)


def _report():
    return GateReport(status="WARN", guidelines_available=True,
                      verdicts=[RubricVerdict(dimension="placeholder_text", verdict="warn",
                                              severity="medium", confidence=0.7, rationale="r",
                                              locale="en-US", field="description")])


def test_runrecord_roundtrips_and_embeds_report():
    r = RunRecord(run_id="ab12", created_at="2026-08-10T12:00:00Z", app_id="123",
                  version=None, primary_locale="en-US", source="fastlane",
                  config_fingerprint="cfp", gate_status="WARN", report=_report(),
                  guideline_snapshot_hash="deadbeef")
    again = RunRecord.model_validate_json(r.model_dump_json())
    assert again.report.status == "WARN" and again.version is None
    assert again.gate_status == "WARN"


def test_run_summary_fields():
    s = RunSummary(run_id="ab12", created_at="t", app_id="123", version=None,
                   gate_status="WARN", source="fastlane")
    assert s.run_id == "ab12"


def test_rundiff_holds_deltas():
    d = RunDiff(status_a="PASS", status_b="BLOCK",
                deltas=[FindingDelta(locale="en-US", dimension="placeholder_text",
                                     field="description", kind=None,
                                     status=FindingStatus.new, severity_a=None, severity_b="high")])
    assert d.status_a == "PASS" and d.deltas[0].status is FindingStatus.new
