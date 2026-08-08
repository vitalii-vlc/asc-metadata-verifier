"""Tests for the App Store Connect API ingestion adapter (Task 16, Phase 2).

Two hard constraints drive these tests:

- NEVER read a real `.p8` key: each test generates a throwaway EC P-256
  private key with `cryptography`, serializes it to PEM/PKCS8, and writes it
  to `tmp_path`. The JWT signing is genuinely exercised against that key.
- NEVER hit the network: `httpx.MockTransport` intercepts every outbound
  request and returns canned JSON shaped like the documented App Store
  Connect API (JSON:API `data`/`included` compound documents).
"""

from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from typer.testing import CliRunner

from asc_metadata_verifier import cli
from asc_metadata_verifier.ingest.asc_api import AscApiAdapter
from asc_metadata_verifier.ingest.base import IngestError
from asc_metadata_verifier.models import AppMetadata, LocaleMetadata

APP_ID = "1234567890"
KEY_ID = "ABCD1234EF"
ISSUER_ID = "11111111-2222-3333-4444-555555555555"

runner = CliRunner()


def _write_test_key(tmp_path) -> str:
    """Generate a throwaway EC P-256 key and write it to tmp_path as a .p8 file."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path = tmp_path / "AuthKey_TEST.p8"
    key_path.write_bytes(pem)
    return str(key_path)


def _app_infos_response() -> dict:
    return {"data": [{"type": "appInfos", "id": "info-1", "attributes": {}}]}


def _app_info_localizations_response() -> dict:
    return {
        "data": [
            {
                "type": "appInfoLocalizations",
                "id": "info-loc-en",
                "attributes": {
                    "locale": "en-US",
                    "name": "Widgetify",
                    "subtitle": "Widgets, simplified",
                    "privacyPolicyUrl": "https://example.com/privacy/en",
                },
            },
            {
                "type": "appInfoLocalizations",
                "id": "info-loc-es",
                "attributes": {
                    "locale": "es-ES",
                    "name": "Widgetify ES",
                    "subtitle": "Widgets, simplificado",
                    "privacyPolicyUrl": "https://example.com/privacy/es",
                },
            },
        ]
    }


def _app_store_versions_response() -> dict:
    return {"data": [{"type": "appStoreVersions", "id": "version-1", "attributes": {}}]}


def _app_store_version_localizations_response() -> dict:
    return {
        "data": [
            {
                "type": "appStoreVersionLocalizations",
                "id": "ver-loc-en",
                "attributes": {
                    "locale": "en-US",
                    "description": "The best widget app.",
                    "keywords": "widgets,tools",
                    "promotionalText": "Now with more widgets!",
                    "whatsNew": "Bug fixes.",
                    "marketingUrl": "https://example.com/en",
                    "supportUrl": "https://example.com/support/en",
                },
            },
            {
                "type": "appStoreVersionLocalizations",
                "id": "ver-loc-es",
                "attributes": {
                    "locale": "es-ES",
                    "description": "La mejor app de widgets.",
                    "keywords": "widgets,herramientas",
                    "promotionalText": "Ahora con mas widgets!",
                    "whatsNew": "Correcciones de errores.",
                    "marketingUrl": "https://example.com/es",
                    "supportUrl": "https://example.com/support/es",
                },
            },
        ]
    }


def _screenshot_sets_response(locale: str) -> dict:
    return {
        "data": [{"type": "appScreenshotSets", "id": f"set-{locale}", "attributes": {}}],
        "included": [
            {
                "type": "appScreenshots",
                "id": f"shot-{locale}-1",
                "attributes": {
                    "imageAsset": {
                        "templateUrl": f"https://example.com/shots/{locale}/1_{{w}}x{{h}}.png",
                        "width": 1284,
                        "height": 2778,
                    }
                },
            }
        ],
    }


def _make_handler(captured_requests: list):
    """Build a MockTransport handler routing on request path; records each request."""

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        path = request.url.path

        if path == f"/v1/apps/{APP_ID}/appInfos":
            return httpx.Response(200, json=_app_infos_response())
        if path == "/v1/appInfos/info-1/appInfoLocalizations":
            return httpx.Response(200, json=_app_info_localizations_response())
        if path == f"/v1/apps/{APP_ID}/appStoreVersions":
            return httpx.Response(200, json=_app_store_versions_response())
        if path == "/v1/appStoreVersions/version-1/appStoreVersionLocalizations":
            return httpx.Response(200, json=_app_store_version_localizations_response())
        if path == "/v1/appStoreVersionLocalizations/ver-loc-en/appScreenshotSets":
            return httpx.Response(200, json=_screenshot_sets_response("en-US"))
        if path == "/v1/appStoreVersionLocalizations/ver-loc-es/appScreenshotSets":
            return httpx.Response(200, json=_screenshot_sets_response("es-ES"))

        return httpx.Response(404, json={"errors": [{"title": "not found in test fixture"}]})

    return handler


def _client_with_handler(handler) -> httpx.Client:
    return httpx.Client(
        base_url="https://api.appstoreconnect.apple.com",
        transport=httpx.MockTransport(handler),
    )


class TestLoadMapsAscApiJsonToAppMetadata:
    def test_maps_two_locales_with_localizations_and_screenshots(self, tmp_path):
        key_path = _write_test_key(tmp_path)
        captured: list[httpx.Request] = []
        client = _client_with_handler(_make_handler(captured))

        adapter = AscApiAdapter(
            app_id=APP_ID,
            key_id=KEY_ID,
            issuer_id=ISSUER_ID,
            key_path=key_path,
            client=client,
        )

        metadata = adapter.load()

        assert isinstance(metadata, AppMetadata)
        by_locale = {loc.locale: loc for loc in metadata.locales}
        assert set(by_locale) == {"en-US", "es-ES"}

        en = by_locale["en-US"]
        assert en.app_name == "Widgetify"
        assert en.subtitle == "Widgets, simplified"
        assert en.privacy_url == "https://example.com/privacy/en"
        assert en.description == "The best widget app."
        assert en.keywords == "widgets,tools"
        assert en.promotional_text == "Now with more widgets!"
        assert en.whats_new == "Bug fixes."
        assert en.marketing_url == "https://example.com/en"
        assert en.support_url == "https://example.com/support/en"

        es = by_locale["es-ES"]
        assert es.app_name == "Widgetify ES"
        assert es.description == "La mejor app de widgets."

        screenshot_locales = {s.locale for s in metadata.screenshots}
        assert screenshot_locales == {"en-US", "es-ES"}
        en_shot = next(s for s in metadata.screenshots if s.locale == "en-US")
        assert en_shot.path == "https://example.com/shots/en-US/1_{w}x{h}.png"

    def test_outbound_requests_carry_bearer_authorization_header(self, tmp_path):
        key_path = _write_test_key(tmp_path)
        captured: list[httpx.Request] = []
        client = _client_with_handler(_make_handler(captured))

        adapter = AscApiAdapter(
            app_id=APP_ID, key_id=KEY_ID, issuer_id=ISSUER_ID, key_path=key_path, client=client
        )
        adapter.load()

        assert captured, "expected at least one outbound request"
        for request in captured:
            auth = request.headers.get("authorization", "")
            assert auth.startswith("Bearer "), f"missing/invalid auth header: {auth!r}"
            token = auth.removeprefix("Bearer ")
            header = jwt.get_unverified_header(token)
            assert header["alg"] == "ES256"
            assert header["kid"] == KEY_ID
            payload = jwt.decode(token, options={"verify_signature": False})
            assert payload["iss"] == ISSUER_ID
            assert payload["aud"] == "appstoreconnect-v1"
            assert payload["exp"] - payload["iat"] <= 20 * 60


class TestKeyErrors:
    def test_malformed_key_raises_ingest_error(self, tmp_path):
        key_path = tmp_path / "AuthKey_BAD.p8"
        key_path.write_bytes(b"this is not a valid EC private key")

        adapter = AscApiAdapter(
            app_id=APP_ID,
            key_id=KEY_ID,
            issuer_id=ISSUER_ID,
            key_path=str(key_path),
            client=_client_with_handler(_make_handler([])),
        )

        with pytest.raises(IngestError, match=str(key_path)):
            adapter.load()

    def test_missing_key_file_raises_ingest_error(self, tmp_path):
        missing_path = tmp_path / "does_not_exist.p8"

        adapter = AscApiAdapter(
            app_id=APP_ID,
            key_id=KEY_ID,
            issuer_id=ISSUER_ID,
            key_path=str(missing_path),
            client=_client_with_handler(_make_handler([])),
        )

        with pytest.raises(IngestError):
            adapter.load()


class TestHttpErrors:
    def test_401_response_raises_ingest_error_mentioning_auth(self, tmp_path):
        key_path = _write_test_key(tmp_path)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"errors": [{"title": "Unauthenticated"}]})

        client = _client_with_handler(handler)
        adapter = AscApiAdapter(
            app_id=APP_ID, key_id=KEY_ID, issuer_id=ISSUER_ID, key_path=key_path, client=client
        )

        with pytest.raises(IngestError, match=r"(?i)auth"):
            adapter.load()

    def test_network_error_raises_ingest_error(self, tmp_path):
        key_path = _write_test_key(tmp_path)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client = _client_with_handler(handler)
        adapter = AscApiAdapter(
            app_id=APP_ID, key_id=KEY_ID, issuer_id=ISSUER_ID, key_path=key_path, client=client
        )

        with pytest.raises(IngestError):
            adapter.load()


class TestCliAscApiWiring:
    """CLI wiring for the deferred --asc-api-* flags (fulfills the Task 12 deferral)."""

    def _canned_metadata(self) -> AppMetadata:
        return AppMetadata(
            app_id=APP_ID,
            locales=[
                LocaleMetadata(
                    locale="en-US",
                    app_name="Widgetify",
                    description="Great.",
                    keywords="widgets,tools",
                )
            ],
            screenshots=[],
        )

    def test_all_four_asc_flags_select_asc_api_adapter_and_exit_zero(self, monkeypatch):
        captured_kwargs = {}

        class FakeAdapter:
            def __init__(self, **kwargs):
                captured_kwargs.update(kwargs)

            def load(_self):
                return self._canned_metadata()

        monkeypatch.setattr(cli, "AscApiAdapter", FakeAdapter)

        result = runner.invoke(
            cli.app,
            [
                "--asc-api-app-id",
                APP_ID,
                "--asc-api-key-id",
                KEY_ID,
                "--asc-api-issuer-id",
                ISSUER_ID,
                "--asc-api-key",
                "/tmp/does-not-matter.p8",
                "--dry-run",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "PASS" in result.output or "WARN" in result.output
        assert captured_kwargs.get("app_id") == APP_ID
        assert captured_kwargs.get("key_id") == KEY_ID
        assert captured_kwargs.get("issuer_id") == ISSUER_ID
        assert captured_kwargs.get("key_path") == Path("/tmp/does-not-matter.p8")

    def test_partial_asc_flags_is_a_clear_error(self):
        result = runner.invoke(
            cli.app,
            [
                "--asc-api-app-id",
                APP_ID,
                "--asc-api-key-id",
                KEY_ID,
                "--dry-run",
            ],
        )

        assert result.exit_code != 0
        assert "Traceback" not in result.output
        assert result.output.strip() != ""
