"""Offline project loader: walk a project root and collect Swift/Obj-C sources
and the plist manifests rules correlate against. No network, no AST parsing
(that is the parser's job) -- only file discovery + plist key/value trees."""

from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_SKIP_DIRS = {"Pods", "Carthage", ".build", "DerivedData", ".git", "build"}
_SOURCE_LANG: dict[str, Literal["swift", "objc"]] = {
    ".swift": "swift",
    ".m": "objc",
    ".h": "objc",
}


class SourceFile(BaseModel):
    path: str
    language: Literal["swift", "objc"]
    text: str


class PlistArtifact(BaseModel):
    path: str
    data: dict | None = None
    parse_error: str | None = None


class ProjectModel(BaseModel):
    root: str
    sources: list[SourceFile] = Field(default_factory=list)
    info_plists: list[PlistArtifact] = Field(default_factory=list)
    entitlements: list[PlistArtifact] = Field(default_factory=list)
    privacy_manifests: list[PlistArtifact] = Field(default_factory=list)


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS or part.endswith(".xcassets") for part in path.parts):
            continue
        yield path


def _load_plist(path: Path) -> PlistArtifact:
    try:
        data = plistlib.loads(path.read_bytes())
        return PlistArtifact(path=str(path), data=dict(data) if isinstance(data, dict) else {})
    except Exception as exc:  # noqa: BLE001 - a bad plist is a factual state, not fatal
        return PlistArtifact(path=str(path), data=None, parse_error=str(exc)[:200])


def load_project(root: str | Path) -> ProjectModel:
    root_path = Path(root)
    proj = ProjectModel(root=str(root_path))
    for path in _iter_files(root_path):
        name, suffix = path.name, path.suffix
        if suffix in _SOURCE_LANG:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            proj.sources.append(
                SourceFile(path=str(path), language=_SOURCE_LANG[suffix], text=text)
            )
        elif name == "PrivacyInfo.xcprivacy":
            proj.privacy_manifests.append(_load_plist(path))
        elif suffix == ".entitlements":
            proj.entitlements.append(_load_plist(path))
        elif name == "Info.plist" or (suffix == ".plist" and name.endswith("Info.plist")):
            proj.info_plists.append(_load_plist(path))
    return proj
