"""Tests for Task 14: bundling the `app-store-review-gate` Claude skill.

Two things must be true for the `library-skills` convention (see
`docs/library-skills-convention.md`) to actually work for this package:

1. The skill directory must physically end up inside the built **wheel** at
   `asc_metadata_verifier/.agents/skills/app-store-review-gate/SKILL.md` --
   `library-skills` discovers skills by scanning the installed wheel's
   `RECORD` for that exact path pattern (source-derived, not documented
   prose). This is the empirical check the convention doc says is
   UNCONFIRMED until a real build is inspected, so this test builds the
   wheel for real (via `uv build --wheel`) and inspects it with `zipfile`
   rather than trusting that files under `src/` "should" end up there.
2. The committed `SKILL.md`'s frontmatter must satisfy the exact two fields
   `library-skills`' parser reads (`name`, `description`) and their
   validation rules (name == parent directory name, name regex, no `--`,
   description <= 1024 chars).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "app-store-review-gate"
_SKILL_REL_PARTS = ("asc_metadata_verifier", ".agents", "skills", SKILL_NAME, "SKILL.md")
SKILL_MD_PATH = REPO_ROOT / "src" / Path(*_SKILL_REL_PARTS)
WHEEL_RECORD_PATH = "/".join(_SKILL_REL_PARTS)

# Same regex `library-skills`' `_validate_skill_metadata()` enforces for `name`.
_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Parse the YAML frontmatter block from a SKILL.md's contents.

    Mirrors what `library-skills`' `_parse_skill_frontmatter()` does: the
    file must start with `---`, and frontmatter is everything up to the next
    `\n---` line.
    """
    assert text.startswith("---"), "SKILL.md must start with a `---` frontmatter marker"
    _, _, rest = text.partition("---")
    frontmatter_raw, marker, _ = rest.partition("\n---")
    assert marker, "SKILL.md frontmatter must be closed with a `---` line"
    parsed = yaml.safe_load(frontmatter_raw)
    assert isinstance(parsed, dict), "SKILL.md frontmatter must parse to a YAML mapping"
    return parsed


@pytest.fixture(scope="module")
def built_wheel_path(tmp_path_factory) -> Path:
    """Build the real wheel with `uv build --wheel` and return its path.

    Runs a real subprocess build (not a mock) because the whole point of
    this task is to empirically prove the dot-prefixed `.agents/` directory
    survives into the wheel -- the convention doc explicitly flags this as
    UNCONFIRMED and something that must be checked against a real build, not
    assumed.
    """
    uv_bin = shutil.which("uv")
    assert uv_bin, "the `uv` binary must be on PATH to build the wheel for this test"

    out_dir = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [uv_bin, "build", "--wheel", "--out-dir", str(out_dir)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(out_dir.glob("*.whl"))
    assert wheels, f"uv build --wheel produced no .whl file in {out_dir}"
    return wheels[0]


class TestWheelIncludesSkill:
    def test_skill_md_present_at_expected_record_path(self, built_wheel_path):
        with zipfile.ZipFile(built_wheel_path) as wheel:
            names = wheel.namelist()

        assert WHEEL_RECORD_PATH in names, (
            f"{WHEEL_RECORD_PATH!r} not found in built wheel {built_wheel_path.name}; "
            f"wheel contents: {sorted(names)}"
        )

    def test_skill_md_content_matches_source_file(self, built_wheel_path):
        with zipfile.ZipFile(built_wheel_path) as wheel:
            packaged = wheel.read(WHEEL_RECORD_PATH).decode("utf-8")

        assert packaged == SKILL_MD_PATH.read_text(encoding="utf-8")


class TestSkillFrontmatter:
    def test_skill_md_exists(self):
        assert SKILL_MD_PATH.is_file(), f"expected SKILL.md at {SKILL_MD_PATH}"

    def test_name_equals_parent_directory_name(self):
        frontmatter = _parse_frontmatter(SKILL_MD_PATH.read_text(encoding="utf-8"))
        assert frontmatter.get("name") == SKILL_NAME == SKILL_MD_PATH.parent.name

    def test_name_matches_required_regex_and_has_no_double_hyphen(self):
        frontmatter = _parse_frontmatter(SKILL_MD_PATH.read_text(encoding="utf-8"))
        name = frontmatter["name"]
        assert _NAME_RE.match(name), f"name {name!r} fails library-skills' name regex"
        assert "--" not in name

    def test_description_present_and_within_length_limit(self):
        frontmatter = _parse_frontmatter(SKILL_MD_PATH.read_text(encoding="utf-8"))
        description = frontmatter.get("description")
        assert isinstance(description, str) and description.strip()
        assert len(description) <= 1024
