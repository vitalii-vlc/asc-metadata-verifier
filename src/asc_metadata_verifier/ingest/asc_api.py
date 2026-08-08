"""Ingest adapter for the live App Store Connect API.

Authenticates with a JWT (ES256) built from an App Store Connect API key
(`.p8` file, key id, issuer id) per Apple's documented scheme, then fetches
app-info localizations, App Store version localizations, and screenshot
asset URLs -- mapping the JSON:API compound-document response shape into the
canonical `AppMetadata`/`LocaleMetadata`/`Screenshot` models.

Honesty note: this adapter is designed against Apple's *documented* App
Store Connect API structure and exercised in tests against mocked httpx
responses shaped like that documentation. It has not been validated against
the real App Store Connect API (no live credentials are available in this
environment) -- treat the response mapping as best-effort until run once
against a real account.

Known limitation (YAGNI, by design): if `appInfoLocalizations` or
`appStoreVersionLocalizations` for an app spans more than one page, only the
first page is fetched -- no paginator is built. Apps with a handful of
locales (the common case) fit in a single page.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from asc_metadata_verifier.ingest.base import IngestError
from asc_metadata_verifier.models import AppMetadata, LocaleMetadata, Screenshot

BASE_URL = "https://api.appstoreconnect.apple.com"
DEFAULT_TIMEOUT = 30.0

# ASC API tokens must expire in <= 20 minutes; stay comfortably under that.
_JWT_TTL_SECONDS = 19 * 60

# App-info localization attribute -> LocaleMetadata field.
_APP_INFO_FIELD_MAP = {
    "name": "app_name",
    "subtitle": "subtitle",
    "privacyPolicyUrl": "privacy_url",
}

# App Store version localization attribute -> LocaleMetadata field.
_VERSION_FIELD_MAP = {
    "description": "description",
    "keywords": "keywords",
    "promotionalText": "promotional_text",
    "whatsNew": "whats_new",
    "marketingUrl": "marketing_url",
    "supportUrl": "support_url",
}


class AscApiAdapter:
    """Ingest adapter that fetches metadata live from App Store Connect."""

    def __init__(
        self,
        app_id: str,
        key_id: str,
        issuer_id: str,
        key_path: str | Path,
        client: httpx.Client | None = None,
    ) -> None:
        self._app_id = app_id
        self._key_id = key_id
        self._issuer_id = issuer_id
        self._key_path = Path(key_path)
        self._client = client

    def load(self) -> AppMetadata:
        token = self._build_jwt()
        headers = {"Authorization": f"Bearer {token}"}

        owns_client = self._client is None
        client = self._client or httpx.Client(base_url=BASE_URL, timeout=DEFAULT_TIMEOUT)
        try:
            app_info_locs = self._fetch_app_info_localizations(client, headers)
            version_locs = self._fetch_version_localizations(client, headers)
            screenshots = self._fetch_screenshots(client, headers, version_locs)
        finally:
            if owns_client:
                client.close()

        locales = self._merge_locales(app_info_locs, version_locs)
        return AppMetadata(app_id=self._app_id, locales=locales, screenshots=screenshots)

    # -- JWT (ES256) ---------------------------------------------------

    def _build_jwt(self) -> str:
        private_key = self._load_private_key()
        now = int(time.time())
        payload = {
            "iss": self._issuer_id,
            "iat": now,
            "exp": now + _JWT_TTL_SECONDS,
            "aud": "appstoreconnect-v1",
        }
        header = {"alg": "ES256", "kid": self._key_id, "typ": "JWT"}
        try:
            return jwt.encode(payload, private_key, algorithm="ES256", headers=header)
        except Exception as exc:
            # Defensive: PyJWT/cryptography signing failures for a key that
            # loaded but is otherwise unusable. Never let a raw traceback
            # (or key material) surface -- the exception message from PyJWT
            # here does not include key bytes.
            raise IngestError(f"Could not sign App Store Connect API JWT: {exc}") from exc

    def _load_private_key(self) -> ec.EllipticCurvePrivateKey:
        try:
            key_bytes = self._key_path.read_bytes()
        except OSError as exc:
            raise IngestError(f"Could not load ASC API key at {self._key_path}: {exc}") from exc

        try:
            private_key = serialization.load_pem_private_key(key_bytes, password=None)
        except (ValueError, TypeError) as exc:
            raise IngestError(f"Could not load ASC API key at {self._key_path}: {exc}") from exc

        if not isinstance(private_key, ec.EllipticCurvePrivateKey):
            raise IngestError(
                f"Could not load ASC API key at {self._key_path}: expected an EC "
                "private key (App Store Connect API keys are ES256/P-256)"
            )

        return private_key

    # -- fetch + map -----------------------------------------------------

    def _fetch_app_info_localizations(
        self, client: httpx.Client, headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        app_infos = self._get(client, headers, f"/v1/apps/{self._app_id}/appInfos")
        app_info_data = app_infos.get("data") or []
        if not app_info_data:
            return []

        app_info_id = app_info_data[0]["id"]
        localizations = self._get(
            client, headers, f"/v1/appInfos/{app_info_id}/appInfoLocalizations"
        )
        return localizations.get("data") or []

    def _fetch_version_localizations(
        self, client: httpx.Client, headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        versions = self._get(client, headers, f"/v1/apps/{self._app_id}/appStoreVersions")
        version_data = versions.get("data") or []
        if not version_data:
            return []

        version_id = version_data[0]["id"]
        localizations = self._get(
            client,
            headers,
            f"/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations",
        )
        return localizations.get("data") or []

    def _fetch_screenshots(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        version_localizations: list[dict[str, Any]],
    ) -> list[Screenshot]:
        screenshots: list[Screenshot] = []
        for loc in version_localizations:
            locale = loc.get("attributes", {}).get("locale")
            loc_id = loc.get("id")
            if not locale or not loc_id:
                continue

            sets_response = self._get(
                client,
                headers,
                f"/v1/appStoreVersionLocalizations/{loc_id}/appScreenshotSets",
                params={"include": "appScreenshots"},
            )
            for item in sets_response.get("included") or []:
                if item.get("type") != "appScreenshots":
                    continue
                image_asset = item.get("attributes", {}).get("imageAsset") or {}
                url = image_asset.get("templateUrl")
                if url:
                    screenshots.append(Screenshot(locale=locale, path=url))

        return screenshots

    @staticmethod
    def _merge_locales(
        app_info_locs: list[dict[str, Any]],
        version_locs: list[dict[str, Any]],
    ) -> list[LocaleMetadata]:
        merged: dict[str, dict[str, str | None]] = {}

        for loc in app_info_locs:
            attrs = loc.get("attributes") or {}
            locale = attrs.get("locale")
            if not locale:
                continue
            entry = merged.setdefault(locale, {})
            for api_field, model_field in _APP_INFO_FIELD_MAP.items():
                entry[model_field] = attrs.get(api_field)

        for loc in version_locs:
            attrs = loc.get("attributes") or {}
            locale = attrs.get("locale")
            if not locale:
                continue
            entry = merged.setdefault(locale, {})
            for api_field, model_field in _VERSION_FIELD_MAP.items():
                entry[model_field] = attrs.get(api_field)

        return [LocaleMetadata(locale=locale, **fields) for locale, fields in merged.items()]

    def _get(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = client.get(path, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise IngestError(
                f"Network error contacting App Store Connect API at {path}: {exc}"
            ) from exc

        if response.status_code in (401, 403):
            raise IngestError(
                f"App Store Connect API authentication failed at {path} "
                f"(HTTP {response.status_code}). Check --asc-api-key-id, "
                "--asc-api-issuer-id, and --asc-api-key -- the key id/issuer id may "
                "be wrong, or the signed token may have expired."
            )

        if response.status_code >= 400:
            raise IngestError(
                f"App Store Connect API request to {path} failed: "
                f"HTTP {response.status_code} {response.text[:200]}"
            )

        return response.json()
