"""Tests for the offline project loader (v2 sub-project C, Task 2)."""

import plistlib
from pathlib import Path

from asc_metadata_verifier.code.project import load_project


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_discovers_sources_manifests_and_skips_pods(tmp_path: Path):
    _write(tmp_path / "App/View.swift", "import UIKit\n")
    _write(tmp_path / "App/Legacy.m", "#import <UIKit/UIKit.h>\n")
    _write(tmp_path / "Pods/Dep/Ignore.swift", "let ignored = 1\n")
    (tmp_path / "App/Info.plist").write_bytes(
        plistlib.dumps({"CFBundleName": "Demo", "ITSAppUsesNonExemptEncryption": False})
    )
    (tmp_path / "App/PrivacyInfo.xcprivacy").write_bytes(
        plistlib.dumps({"NSPrivacyAccessedAPITypes": []})
    )
    (tmp_path / "App/App.entitlements").write_bytes(
        plistlib.dumps({"aps-environment": "development"})
    )

    proj = load_project(tmp_path)
    langs = {s.language for s in proj.sources}
    paths = {Path(s.path).name for s in proj.sources}
    assert paths == {"View.swift", "Legacy.m"} and langs == {"swift", "objc"}
    assert len(proj.info_plists) == 1 and proj.info_plists[0].data["CFBundleName"] == "Demo"
    assert len(proj.privacy_manifests) == 1 and len(proj.entitlements) == 1


def test_malformed_plist_is_factual_not_fatal(tmp_path: Path):
    (tmp_path / "Info.plist").write_text("not a plist <<<")
    proj = load_project(tmp_path)
    assert proj.info_plists[0].data is None
    assert proj.info_plists[0].parse_error  # non-empty factual message
