from typing import Protocol

from asc_metadata_verifier.models import AppMetadata


class IngestAdapter(Protocol):
    """Common interface for all metadata ingestion adapters (fastlane, YAML, ASC API)."""

    def load(self) -> AppMetadata: ...


class IngestError(Exception):
    """Raised by any ingest adapter when source metadata cannot be read.

    Carries an actionable message (what was missing/malformed and where) rather
    than letting a raw filesystem or parsing traceback surface to the caller.
    """
