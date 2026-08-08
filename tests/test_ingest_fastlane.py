from pathlib import Path

import pytest

from asc_metadata_verifier.ingest.base import IngestError
from asc_metadata_verifier.ingest.fastlane import FastlaneAdapter

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "fastlane_clean"


def test_load_yields_both_locales_with_expected_fields():
    metadata = FastlaneAdapter(FIXTURE_ROOT).load()

    locales_by_code = {locale.locale: locale for locale in metadata.locales}

    assert set(locales_by_code) == {"en-US", "de-DE"}

    en_us = locales_by_code["en-US"]
    assert en_us.app_name == "Sunrise Tasks"
    assert en_us.description.startswith("Sunrise Tasks helps you plan")
    assert en_us.subtitle == "Plan your day with ease"
    assert en_us.keywords == "tasks,todo,planner,productivity"
    assert en_us.promotional_text == "Now with dark mode!"
    assert en_us.whats_new == "Bug fixes and performance improvements."
    assert en_us.support_url == "https://example.com/support"
    assert en_us.marketing_url == "https://example.com"
    assert en_us.privacy_url == "https://example.com/privacy"

    de_de = locales_by_code["de-DE"]
    assert de_de.app_name == "Sonnenaufgang Aufgaben"
    assert de_de.description.startswith("Sonnenaufgang Aufgaben hilft dir")


def test_load_populates_screenshots_for_correct_locale():
    metadata = FastlaneAdapter(FIXTURE_ROOT).load()

    assert len(metadata.screenshots) == 2
    for screenshot in metadata.screenshots:
        assert screenshot.locale == "en-US"

    paths = {Path(s.path).name for s in metadata.screenshots}
    assert paths == {"shot1.png", "shot2.png"}


def test_load_leaves_app_id_and_primary_locale_none():
    metadata = FastlaneAdapter(FIXTURE_ROOT).load()

    assert metadata.app_id is None
    assert metadata.primary_locale is None


def test_missing_metadata_dir_raises_actionable_ingest_error(tmp_path):
    empty_root = tmp_path / "no_metadata_here"
    empty_root.mkdir()

    with pytest.raises(IngestError) as exc_info:
        FastlaneAdapter(empty_root).load()

    message = str(exc_info.value)
    assert str(empty_root) in message
    assert "metadata" in message.lower()


def test_missing_deliver_root_raises_actionable_ingest_error(tmp_path):
    nonexistent_root = tmp_path / "does_not_exist"

    with pytest.raises(IngestError):
        FastlaneAdapter(nonexistent_root).load()


def test_metadata_dir_with_no_locale_subdirs_raises_ingest_error(tmp_path):
    root = tmp_path / "deliver_root"
    (root / "metadata").mkdir(parents=True)

    with pytest.raises(IngestError):
        FastlaneAdapter(root).load()
