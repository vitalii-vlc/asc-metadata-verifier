import pytest

from asc_metadata_verifier.persistence.config import resolve_repository
from asc_metadata_verifier.persistence.repository import RepositoryError
from asc_metadata_verifier.persistence.sqlite_repo import SqliteRepository


def test_none_disables_persistence():
    assert resolve_repository(None) is None
    assert resolve_repository("") is None


def test_sqlite_url_and_bare_path(tmp_path):
    r1 = resolve_repository(f"sqlite:///{tmp_path/'a.db'}")
    r2 = resolve_repository(str(tmp_path / "b.db"))
    assert isinstance(r1, SqliteRepository) and isinstance(r2, SqliteRepository)


def test_unknown_scheme_raises_without_leaking_credentials():
    with pytest.raises(RepositoryError) as ei:
        resolve_repository("postgres://user:secretpw@host/db")
    assert "secretpw" not in str(ei.value)
