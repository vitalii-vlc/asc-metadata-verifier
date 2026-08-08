from pathlib import Path
from typing import Any

import yaml

from asc_metadata_verifier.ingest.base import IngestError
from asc_metadata_verifier.models import AppMetadata, LocaleMetadata, Screenshot

# Known LocaleMetadata field names (besides `locale` itself) — unknown keys
# under a locale entry are ignored rather than passed through.
_LOCALE_FIELDS = {
    "app_name",
    "subtitle",
    "promotional_text",
    "keywords",
    "description",
    "whats_new",
    "support_url",
    "marketing_url",
    "privacy_url",
}


class YamlAdapter:
    """Ingest adapter for a single YAML metadata file.

    Expected shape:

        app_id: "123456789"          # optional
        primary_locale: en-US        # optional
        locales:
          en-US:
            app_name: "My App"
            ...
        screenshots:                 # optional
          en-US:
            - screenshots/en-US/1.png
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> AppMetadata:
        raw = self._read_yaml()

        if not isinstance(raw, dict) or not raw.get("locales"):
            raise IngestError(f"No 'locales' found in {self._path}")

        locales = [
            self._load_locale(locale_code, fields)
            for locale_code, fields in raw["locales"].items()
        ]
        screenshots = self._load_screenshots(raw.get("screenshots") or {})

        return AppMetadata(
            app_id=raw.get("app_id"),
            primary_locale=raw.get("primary_locale"),
            locales=locales,
            screenshots=screenshots,
        )

    def _read_yaml(self) -> Any:
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise IngestError(f"Could not read YAML at {self._path}: {exc}") from exc

        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise IngestError(f"Failed to parse YAML at {self._path}: {exc}") from exc

    @staticmethod
    def _load_locale(locale_code: str, fields: Any) -> LocaleMetadata:
        known_fields = fields if isinstance(fields, dict) else {}
        filtered = {k: v for k, v in known_fields.items() if k in _LOCALE_FIELDS}
        return LocaleMetadata(locale=locale_code, **filtered)

    @staticmethod
    def _load_screenshots(screenshots_by_locale: Any) -> list[Screenshot]:
        if not isinstance(screenshots_by_locale, dict):
            return []

        screenshots: list[Screenshot] = []
        for locale_code, paths in screenshots_by_locale.items():
            for path in paths or []:
                screenshots.append(Screenshot(locale=locale_code, path=str(path)))

        return screenshots
