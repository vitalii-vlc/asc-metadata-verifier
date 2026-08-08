from pathlib import Path

from asc_metadata_verifier.ingest.base import IngestError
from asc_metadata_verifier.models import AppMetadata, LocaleMetadata, Screenshot

# fastlane deliver text file name -> LocaleMetadata field name
_FIELD_FILES = {
    "name.txt": "app_name",
    "subtitle.txt": "subtitle",
    "description.txt": "description",
    "keywords.txt": "keywords",
    "promotional_text.txt": "promotional_text",
    "release_notes.txt": "whats_new",
    "support_url.txt": "support_url",
    "marketing_url.txt": "marketing_url",
    "privacy_url.txt": "privacy_url",
}


class FastlaneAdapter:
    """Ingest adapter for a fastlane `deliver` root directory.

    `path` is the deliver root — the directory that *contains* `metadata/`
    and `screenshots/` (not `metadata/` itself).
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> AppMetadata:
        metadata_dir = self._path / "metadata"
        locale_dirs = self._locale_dirs(metadata_dir)

        metadata = AppMetadata()
        for locale_dir in locale_dirs:
            metadata.locales.append(self._load_locale(locale_dir))
            metadata.screenshots.extend(self._load_screenshots(locale_dir.name))

        return metadata

    def _locale_dirs(self, metadata_dir: Path) -> list[Path]:
        if not metadata_dir.is_dir():
            raise IngestError(
                f"No fastlane metadata found at {metadata_dir} — "
                "expected per-locale subdirectories"
            )

        locale_dirs = sorted(p for p in metadata_dir.iterdir() if p.is_dir())
        if not locale_dirs:
            raise IngestError(
                f"No fastlane metadata found at {metadata_dir} — "
                "expected per-locale subdirectories"
            )

        return locale_dirs

    def _load_locale(self, locale_dir: Path) -> LocaleMetadata:
        fields: dict[str, str | None] = {}
        for filename, field_name in _FIELD_FILES.items():
            fields[field_name] = self._read_field_file(locale_dir / filename)

        return LocaleMetadata(locale=locale_dir.name, **fields)

    @staticmethod
    def _read_field_file(file_path: Path) -> str | None:
        if not file_path.is_file():
            return None

        value = file_path.read_text(encoding="utf-8").strip()
        return value or None

    def _load_screenshots(self, locale: str) -> list[Screenshot]:
        screenshots_dir = self._path / "screenshots" / locale
        if not screenshots_dir.is_dir():
            return []

        return [
            Screenshot(locale=locale, path=str(p))
            for p in sorted(screenshots_dir.iterdir())
            if p.is_file()
        ]
