from asc_metadata_verifier.models import GateReport, RubricVerdict
from asc_metadata_verifier.persistence.models import RunRecord
from asc_metadata_verifier.persistence.sqlite_repo import SqliteRepository


def _rec(run_id, app_id="123", status="WARN", created="2026-08-10T00:00:00Z"):
    return RunRecord(run_id=run_id, created_at=created, app_id=app_id, version=None,
                     primary_locale="en-US", source="fastlane", config_fingerprint="cfp",
                     gate_status=status,
                     report=GateReport(status=status, guidelines_available=True))


def _repo(tmp_path):
    return SqliteRepository(tmp_path / "runs.db")


def test_save_get_roundtrip(tmp_path):
    repo = _repo(tmp_path)
    repo.save_run(_rec("aa"))
    got = repo.get_run("aa")
    assert got is not None and got.gate_status == "WARN" and got.report.status == "WARN"
    assert repo.get_run("missing") is None


def test_list_runs_newest_first_and_filtered(tmp_path):
    repo = _repo(tmp_path)
    repo.save_run(_rec("old", app_id="A", created="2026-08-01T00:00:00Z"))
    repo.save_run(_rec("new", app_id="A", created="2026-08-09T00:00:00Z"))
    repo.save_run(_rec("other", app_id="B", created="2026-08-10T00:00:00Z"))
    ids = [s.run_id for s in repo.list_runs(app_id="A")]
    assert ids == ["new", "old"]
    assert {s.run_id for s in repo.list_runs()} == {"old", "new", "other"}
    assert len(repo.list_runs(limit=1)) == 1


def test_verdict_cache_put_get(tmp_path):
    repo = _repo(tmp_path)
    v = RubricVerdict(dimension="placeholder_text", verdict="fail", severity="high",
                      confidence=0.9, rationale="r", locale="en-US", field="description")
    assert repo.get_cached_verdict("k") is None
    repo.put_cached_verdict("k", v)
    assert repo.get_cached_verdict("k").verdict == "fail"


def test_guideline_snapshot_dedup(tmp_path):
    repo = _repo(tmp_path)
    repo.put_guideline_snapshot("h1", "2.3 body")
    repo.put_guideline_snapshot("h1", "2.3 body")  # idempotent
    assert repo.get_guideline_snapshot("h1") == "2.3 body"
    assert repo.get_guideline_snapshot("nope") is None


def test_reopen_persists(tmp_path):
    _repo(tmp_path).save_run(_rec("aa"))
    assert SqliteRepository(tmp_path / "runs.db").get_run("aa") is not None
