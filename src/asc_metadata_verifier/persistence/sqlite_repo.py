"""SQLite-backed `Repository`: runs, the judge verdict cache, and guideline
snapshots.

Uses stdlib `sqlite3` only -- no ORM, no new dependency. One connection is
opened per `SqliteRepository` instance and reused for its lifetime; WAL mode
is enabled so concurrent readers don't block a writer. Tables are created
(idempotently) on first open, and every `sqlite3.Error` is wrapped in
`RepositoryError` so callers never see a raw sqlite traceback.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from asc_metadata_verifier.models import GateReport, RubricVerdict
from asc_metadata_verifier.persistence.models import RunRecord, RunSummary
from asc_metadata_verifier.persistence.repository import RepositoryError

_SCHEMA_VERSION = 1

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    app_id TEXT,
    version TEXT,
    primary_locale TEXT,
    source TEXT,
    config_fingerprint TEXT,
    gate_status TEXT,
    guideline_snapshot_hash TEXT,
    report_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verdict_cache (
    key TEXT PRIMARY KEY,
    verdict_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guideline_snapshots (
    hash TEXT PRIMARY KEY,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""


class SqliteRepository:
    """`Repository` implementation backed by a single SQLite file."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_CREATE_TABLES_SQL)
            self._migrate()
            self._conn.commit()
        except sqlite3.Error as exc:
            raise RepositoryError(f"failed to open repository at {self._db_path}: {exc}") from exc

    def _migrate(self) -> None:
        """Bring an existing DB up to `_SCHEMA_VERSION`. No-op at v1 (the only
        version that exists so far) -- this is the seam future schema bumps
        (ALTER TABLE, backfills, ...) hook into, keyed off the stored version.
        """
        row = self._conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,)
            )

    def save_run(self, record: RunRecord) -> None:
        try:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO runs
                    (run_id, created_at, app_id, version, primary_locale, source,
                     config_fingerprint, gate_status, guideline_snapshot_hash, report_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id,
                    record.created_at,
                    record.app_id,
                    record.version,
                    record.primary_locale,
                    record.source,
                    record.config_fingerprint,
                    record.gate_status,
                    record.guideline_snapshot_hash,
                    record.report.model_dump_json(),
                ),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise RepositoryError(f"failed to save run {record.run_id}: {exc}") from exc

    def get_run(self, run_id: str) -> RunRecord | None:
        try:
            row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        except sqlite3.Error as exc:
            raise RepositoryError(f"failed to get run {run_id}: {exc}") from exc
        return None if row is None else self._row_to_run_record(row)

    def list_runs(self, app_id: str | None = None, limit: int = 50) -> list[RunSummary]:
        summary_cols = "run_id, created_at, app_id, version, gate_status, source"
        try:
            if app_id is None:
                rows = self._conn.execute(
                    f"SELECT {summary_cols} FROM runs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    f"SELECT {summary_cols} FROM runs WHERE app_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (app_id, limit),
                ).fetchall()
        except sqlite3.Error as exc:
            raise RepositoryError(f"failed to list runs: {exc}") from exc
        return [
            RunSummary(
                run_id=row["run_id"],
                created_at=row["created_at"],
                app_id=row["app_id"],
                version=row["version"],
                gate_status=row["gate_status"],
                source=row["source"],
            )
            for row in rows
        ]

    def get_cached_verdict(self, key: str) -> RubricVerdict | None:
        try:
            row = self._conn.execute(
                "SELECT verdict_json FROM verdict_cache WHERE key = ?", (key,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise RepositoryError(f"failed to get cached verdict {key}: {exc}") from exc
        return None if row is None else RubricVerdict.model_validate_json(row["verdict_json"])

    def put_cached_verdict(self, key: str, verdict: RubricVerdict) -> None:
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO verdict_cache (key, verdict_json) VALUES (?, ?)",
                (key, verdict.model_dump_json()),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise RepositoryError(f"failed to put cached verdict {key}: {exc}") from exc

    def get_guideline_snapshot(self, hash: str) -> str | None:
        try:
            row = self._conn.execute(
                "SELECT text FROM guideline_snapshots WHERE hash = ?", (hash,)
            ).fetchone()
        except sqlite3.Error as exc:
            raise RepositoryError(f"failed to get guideline snapshot {hash}: {exc}") from exc
        return None if row is None else row["text"]

    def put_guideline_snapshot(self, hash: str, text: str) -> None:
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO guideline_snapshots (hash, text) VALUES (?, ?)",
                (hash, text),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise RepositoryError(f"failed to put guideline snapshot {hash}: {exc}") from exc

    def _row_to_run_record(self, row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            created_at=row["created_at"],
            app_id=row["app_id"],
            version=row["version"],
            primary_locale=row["primary_locale"],
            source=row["source"],
            config_fingerprint=row["config_fingerprint"],
            gate_status=row["gate_status"],
            report=GateReport.model_validate_json(row["report_json"]),
            guideline_snapshot_hash=row["guideline_snapshot_hash"],
        )
