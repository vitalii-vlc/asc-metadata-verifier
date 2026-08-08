from unittest.mock import Mock

import httpx
import pytest

from asc_metadata_verifier.guidelines import source
from asc_metadata_verifier.guidelines.source import get_guidelines

FIXTURE_HTML = """
<html>
<body>
<h2>2.1 App Completeness</h2>
<p>Your app should be fully functional at the time of submission.</p>
<h2>2.3 Accurate Metadata</h2>
<p>Your app's metadata, including its name, description, screenshots, and
keywords, should accurately reflect the app's core functionality &amp;
features. Don't include hidden, dormant, or undocumented features.</p>
<h2>2.3.1 Inaccurate Screenshots</h2>
<p>Screenshots should reflect the app in use.</p>
<h2>3.1 In-App Purchase</h2>
<p>Some unrelated section about payments.</p>
</body>
</html>
"""


def _mock_client(status_code: int = 200, text: str = FIXTURE_HTML) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.text = text
    response.raise_for_status = Mock()
    client = Mock()
    client.get = Mock(return_value=response)
    return client


class TestFetchAndCache:
    def test_fetch_success_extracts_sections_and_writes_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "CACHE_DIR", tmp_path / "asc_cache")
        client = _mock_client()

        result = get_guidelines("sess1", client=client)

        assert result.available is True
        assert "2.3" in result.sections
        assert "Accurate Metadata" in result.sections["2.3"]
        assert result.text  # full stripped text populated
        assert result.source == source.GUIDELINES_URL
        cache_file = (tmp_path / "asc_cache") / "sess1.guidelines.json"
        assert cache_file.exists()

    def test_second_call_same_session_serves_from_cache_no_refetch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "CACHE_DIR", tmp_path / "asc_cache")
        client = _mock_client()

        first = get_guidelines("sess1", client=client)
        second = get_guidelines("sess1", client=client)

        assert client.get.call_count == 1
        assert second.available is True
        assert second.source == "cache"
        assert second.sections == first.sections
        assert second.text == first.text

    def test_different_session_ids_each_trigger_their_own_fetch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "CACHE_DIR", tmp_path / "asc_cache")
        client = _mock_client()

        get_guidelines("sess1", client=client)
        get_guidelines("sess2", client=client)

        assert client.get.call_count == 2


class TestFetchFailure:
    def test_client_raises_connect_error_returns_unavailable_not_raise(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "CACHE_DIR", tmp_path / "asc_cache")
        client = Mock()
        client.get = Mock(side_effect=httpx.ConnectError("connection refused"))

        result = get_guidelines("sess2", client=client)

        assert result.available is False
        assert result.text == ""
        assert result.sections == {}
        assert result.source == source.GUIDELINES_URL

    def test_non_200_status_raises_via_raise_for_status_returns_unavailable(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(source, "CACHE_DIR", tmp_path / "asc_cache")
        response = Mock()
        response.status_code = 500
        response.text = ""
        response.raise_for_status = Mock(
            side_effect=httpx.HTTPStatusError(
                "server error", request=Mock(), response=Mock(status_code=500)
            )
        )
        client = Mock()
        client.get = Mock(return_value=response)

        result = get_guidelines("sess-fail-status", client=client)

        assert result.available is False
        assert result.text == ""
        assert result.sections == {}

    def test_fetch_failure_does_not_write_cache_file(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "asc_cache"
        monkeypatch.setattr(source, "CACHE_DIR", cache_dir)
        client = Mock()
        client.get = Mock(side_effect=httpx.ConnectError("connection refused"))

        get_guidelines("sess-fail", client=client)

        cache_file = cache_dir / "sess-fail.guidelines.json"
        assert not cache_file.exists()


class TestOverridePath:
    def test_override_path_reads_local_file_bypasses_network(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "CACHE_DIR", tmp_path / "asc_cache")
        override_file = tmp_path / "offline_guidelines.html"
        override_file.write_text(FIXTURE_HTML)
        client = _mock_client()

        result = get_guidelines("sess3", override_path=override_file, client=client)

        assert result.available is True
        assert result.source == str(override_file)
        assert "2.3" in result.sections
        client.get.assert_not_called()

    def test_override_path_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(source, "CACHE_DIR", tmp_path / "asc_cache")
        missing = tmp_path / "does_not_exist.html"

        with pytest.raises((FileNotFoundError, ValueError)):
            get_guidelines("sess4", override_path=missing)

    def test_override_path_does_not_write_session_cache(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "asc_cache"
        monkeypatch.setattr(source, "CACHE_DIR", cache_dir)
        override_file = tmp_path / "offline_guidelines.html"
        override_file.write_text(FIXTURE_HTML)

        get_guidelines("sess5", override_path=override_file)

        cache_file = cache_dir / "sess5.guidelines.json"
        assert not cache_file.exists()


class TestDefaultClient:
    def test_no_client_and_no_cache_creates_default_client(self, tmp_path, monkeypatch):
        # No client injected and no cache present -> module must construct a
        # default httpx.Client itself. We don't want a real network call in
        # tests, so we monkeypatch httpx.Client to a stub that mimics failure
        # (ConnectError) and assert the honesty-bar contract still holds.
        monkeypatch.setattr(source, "CACHE_DIR", tmp_path / "asc_cache")

        class _StubClient:
            def __init__(self, *args, **kwargs):
                pass

            def get(self, url):
                raise httpx.ConnectError("no network in tests")

            def close(self):
                pass

        monkeypatch.setattr(httpx, "Client", _StubClient)

        result = get_guidelines("sess-default-client")

        assert result.available is False
