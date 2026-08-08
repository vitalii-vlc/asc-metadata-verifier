from pathlib import Path

import pytest

from asc_metadata_verifier.ingest.base import IngestError
from asc_metadata_verifier.ingest.yaml_source import YamlAdapter

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "metadata.yaml"


def test_load_yields_both_locales_with_expected_fields():
    metadata = YamlAdapter(FIXTURE_PATH).load()

    locales_by_code = {locale.locale: locale for locale in metadata.locales}

    assert set(locales_by_code) == {"en-US", "de-DE"}

    en_us = locales_by_code["en-US"]
    assert en_us.app_name == "Sunrise Tasks"
    assert en_us.subtitle == "Plan your day with ease"
    assert en_us.description.startswith("Sunrise Tasks helps you plan")
    assert en_us.keywords == "tasks,todo,planner,productivity"
    assert en_us.promotional_text == "Now with dark mode!"
    assert en_us.whats_new == "Bug fixes and performance improvements."
    assert en_us.support_url == "https://example.com/support"
    assert en_us.marketing_url == "https://example.com"
    assert en_us.privacy_url == "https://example.com/privacy"

    de_de = locales_by_code["de-DE"]
    assert de_de.app_name == "Sonnenaufgang Aufgaben"
    assert de_de.description.startswith("Sonnenaufgang Aufgaben hilft dir")
    assert de_de.keywords == "aufgaben,todo,planer,produktivitaet"
    # Fields absent from the fixture for de-DE should be lenient None defaults.
    assert de_de.subtitle is None
    assert de_de.promotional_text is None


def test_load_populates_app_id_and_primary_locale():
    metadata = YamlAdapter(FIXTURE_PATH).load()

    assert metadata.app_id == "123456789"
    assert metadata.primary_locale == "en-US"


def test_load_populates_locale_tagged_screenshots():
    metadata = YamlAdapter(FIXTURE_PATH).load()

    assert len(metadata.screenshots) == 2
    for screenshot in metadata.screenshots:
        assert screenshot.locale == "en-US"

    paths = {screenshot.path for screenshot in metadata.screenshots}
    assert paths == {"screenshots/en-US/1.png", "screenshots/en-US/2.png"}


def test_load_with_no_screenshots_key_yields_empty_list(tmp_path):
    yaml_path = tmp_path / "no_screenshots.yaml"
    yaml_path.write_text(
        """
locales:
  en-US:
    app_name: "No Screens"
"""
    )

    metadata = YamlAdapter(yaml_path).load()

    assert metadata.screenshots == []


def test_unknown_locale_fields_are_ignored(tmp_path):
    yaml_path = tmp_path / "unknown_fields.yaml"
    yaml_path.write_text(
        """
locales:
  en-US:
    app_name: "Known Field App"
    some_unrecognized_field: "should be ignored"
"""
    )

    metadata = YamlAdapter(yaml_path).load()

    assert len(metadata.locales) == 1
    assert metadata.locales[0].app_name == "Known Field App"


def test_malformed_yaml_raises_actionable_ingest_error(tmp_path):
    yaml_path = tmp_path / "broken.yaml"
    yaml_path.write_text("locales: [unclosed")

    with pytest.raises(IngestError) as exc_info:
        YamlAdapter(yaml_path).load()

    message = str(exc_info.value)
    assert str(yaml_path) in message


def test_missing_locales_key_raises_ingest_error(tmp_path):
    yaml_path = tmp_path / "no_locales.yaml"
    yaml_path.write_text("app_id: '123'\n")

    with pytest.raises(IngestError) as exc_info:
        YamlAdapter(yaml_path).load()

    message = str(exc_info.value)
    assert str(yaml_path) in message
    assert "locales" in message.lower()


def test_empty_locales_raises_ingest_error(tmp_path):
    yaml_path = tmp_path / "empty_locales.yaml"
    yaml_path.write_text("locales: {}\n")

    with pytest.raises(IngestError):
        YamlAdapter(yaml_path).load()


def test_non_dict_top_level_raises_ingest_error(tmp_path):
    yaml_path = tmp_path / "list_top_level.yaml"
    yaml_path.write_text("- just\n- a\n- list\n")

    with pytest.raises(IngestError):
        YamlAdapter(yaml_path).load()


def test_missing_file_raises_actionable_ingest_error(tmp_path):
    missing_path = tmp_path / "does_not_exist.yaml"

    with pytest.raises(IngestError) as exc_info:
        YamlAdapter(missing_path).load()

    message = str(exc_info.value)
    assert str(missing_path) in message
