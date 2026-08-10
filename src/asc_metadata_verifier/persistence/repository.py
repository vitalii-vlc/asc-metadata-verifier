from typing import Protocol

from asc_metadata_verifier.models import RubricVerdict
from asc_metadata_verifier.persistence.models import RunRecord, RunSummary


class Repository(Protocol):
    """Structured store for runs, the judge verdict cache, and guideline snapshots.

    Implementations are free to choose their storage backend; callers only rely
    on this interface. `put_cached_verdict` / `put_guideline_snapshot` are keyed
    by content hash, so writes must be idempotent (same key -> same value).
    """

    def save_run(self, record: RunRecord) -> None: ...

    def get_run(self, run_id: str) -> RunRecord | None: ...

    def list_runs(self, app_id: str | None = None, limit: int = 50) -> list[RunSummary]:
        """Newest first (by `created_at`), optionally filtered to one `app_id`."""
        ...

    def get_cached_verdict(self, key: str) -> RubricVerdict | None: ...

    def put_cached_verdict(self, key: str, verdict: RubricVerdict) -> None: ...

    def get_guideline_snapshot(self, hash: str) -> str | None: ...

    def put_guideline_snapshot(self, hash: str, text: str) -> None: ...


class RepositoryError(Exception):
    """Raised by any Repository implementation when the store cannot be read or
    written, rather than letting a raw backend traceback (e.g. sqlite3.Error)
    surface to the caller.
    """
