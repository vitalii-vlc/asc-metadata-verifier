"""Persistence record models. `created_at` is always PASSED IN (never generated
here) so the store stays deterministically testable."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from asc_metadata_verifier.models import GateReport


class RunRecord(BaseModel):
    run_id: str
    created_at: str  # ISO-8601, supplied by the caller
    app_id: str | None = None
    version: str | None = None  # not in AppMetadata today; future ASC-API populates it
    primary_locale: str | None = None
    source: str
    config_fingerprint: str
    gate_status: str
    report: GateReport
    guideline_snapshot_hash: str | None = None


class RunSummary(BaseModel):
    run_id: str
    created_at: str
    app_id: str | None = None
    version: str | None = None
    gate_status: str
    source: str


class FindingStatus(StrEnum):
    new = "new"
    resolved = "resolved"
    persisting = "persisting"
    severity_changed = "severity_changed"


class FindingDelta(BaseModel):
    locale: str
    dimension: str | None = None  # rubric verdicts
    field: str
    kind: str | None = None        # deterministic findings
    status: FindingStatus
    severity_a: str | None = None
    severity_b: str | None = None


class RunDiff(BaseModel):
    status_a: str
    status_b: str
    deltas: list[FindingDelta] = Field(default_factory=list)
