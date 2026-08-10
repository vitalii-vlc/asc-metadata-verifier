"""Resolve a `--db` URL/path into a `Repository`, plus the backend registry.

`resolve_repository` is the single entry point the CLI calls to turn a
`--db` flag value into a `Repository` (or `None` to disable persistence).
Three input shapes are accepted:

- `None` / `""` -> persistence disabled, returns `None`.
- `<scheme>://...` (e.g. `sqlite:///abs/path`, `sqlite://relative`) -> dispatched
  to `BACKENDS[<scheme>]`.
- anything else (no `scheme://` prefix) -> treated as a bare filesystem path
  and handed straight to the `sqlite` backend, so `--db ./runs.db` works
  without a URL scheme.

`BACKENDS` is a `dict[str, Callable[[str], Repository]]` keyed by URL scheme,
so a future backend (e.g. postgres) registers a factory here without
touching the CLI or this dispatch logic.

Backend URLs may embed credentials (`postgres://user:pw@host/db`), so any
error raised here must never echo the raw URL or its netloc -- only the
scheme is reported.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlsplit

from asc_metadata_verifier.persistence.repository import Repository, RepositoryError
from asc_metadata_verifier.persistence.sqlite_repo import SqliteRepository


def _sqlite_factory(db_url: str) -> Repository:
    """Build a `SqliteRepository` from a `sqlite://` URL or a bare path.

    `urlsplit` puts everything between the leading `//` and the next `/`
    into `netloc`, and the rest into `path`; reassembling them as
    `netloc + path` recovers the original filesystem path for every shape
    this factory is called with:

    - `sqlite:///abs/path` -> netloc='',         path='/abs/path' -> '/abs/path'
    - `sqlite://relative`  -> netloc='relative',  path=''          -> 'relative'
    - bare path `b.db`     -> netloc='',          path='b.db'      -> 'b.db'
    """
    parsed = urlsplit(db_url)
    path = parsed.netloc + parsed.path
    return SqliteRepository(path)


BACKENDS: dict[str, Callable[[str], Repository]] = {
    "sqlite": _sqlite_factory,
}


def resolve_repository(db_url: str | None) -> Repository | None:
    """Resolve a `--db` value into a `Repository`, or `None` to disable persistence.

    A bare filesystem path (no `scheme://` prefix) is treated as a sqlite
    path directly. An unrecognized scheme raises `RepositoryError` naming
    only the scheme -- never the raw URL -- since backend URLs may embed
    credentials.
    """
    if not db_url:
        return None

    scheme = urlsplit(db_url).scheme
    if not scheme:
        return BACKENDS["sqlite"](db_url)

    factory = BACKENDS.get(scheme)
    if factory is None:
        available = ", ".join(sorted(BACKENDS)) or "none"
        raise RepositoryError(
            f"unsupported --db backend scheme {scheme!r}; available backends: {available}"
        )
    return factory(db_url)
