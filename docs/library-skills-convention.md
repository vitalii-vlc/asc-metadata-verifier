# The `library-skills` bundling convention (derived from source)

Research for Task 1 of the `asc-metadata-verifier` project. Consumed by Task 14, which bundles a Claude
skill named `app-store-review-gate` inside this pip package.

`library-skills` is a real, actively-developed tool by Sebastián Ramírez (tiangolo):

- Repo: [`github.com/tiangolo/library-skills`](https://github.com/tiangolo/library-skills) (761 stars,
  MIT license, pushed 2026-08-07).
- PyPI: [`pypi.org/project/library-skills`](https://pypi.org/project/library-skills/) — latest `0.0.19`.
- Docs site: [`library-skills.io`](https://library-skills.io).

All findings below cite the exact source fetched. Research was pinned to commit
[`7b3f937`](https://github.com/tiangolo/library-skills/commit/7b3f93723025902618b1a44aa3faa736bab062a3)
(`main` as of this research) so line references stay stable even if the repo changes later.

**Status legend:** `CONFIRMED` = directly verified from a fetched source. `PARTIALLY CONFIRMED` = the
mechanism is confirmed but a specific detail needed for our use case is not documented and must be
verified empirically. `UNCONFIRMED` = no source found; do not assume, fall back to manual install.

---

## (a) Exact in-package path/folder where skill file(s) live — CONFIRMED

**Convention:** `<package-root>/.agents/skills/<skill-name>/SKILL.md`

Source: [`docs/create/index.md`](https://github.com/tiangolo/library-skills/blob/7b3f937/docs/create/index.md)
(verbatim):

> Libraries can define their own skills in a `.agents/skills/` directory inside of their own package.
>
> It is recommended to name them with a **prefix using their own name**, to avoid conflicts with other
> libraries.
>
> For example, FastAPI could name a skill `fastapi/SKILL.md`, or `fastapi-development/SKILL.md`:
>
> ```
> fastapi/.agents/skills/fastapi/SKILL.md
> ```
>
> By bundling it with the published package, it will be available for agents when installed.
>
> ## In Python
>
> For example, if the Python virtual environment being used is at `.venv`, the skill would end up
> located at:
>
> ```
> .venv/lib/python3.14/site-packages/fastapi/.agents/skills/fastapi/SKILL.md
> ```

This is corroborated independently by the actual discovery code, not just the doc prose:

- [`src/library_skills/scanner.py`](https://github.com/tiangolo/library-skills/blob/7b3f937/src/library_skills/scanner.py),
  `_is_skill_file_record()`: walks the installed wheel's `RECORD` file and matches any path whose parts
  contain `.agents` → `skills` → `<name>` → `SKILL.md`.
- The Node.js side of the same scanner globs `package_root.glob(".agents/skills/*/SKILL.md")` directly
  (same file).
- [`tests/test_scanner.py`](https://github.com/tiangolo/library-skills/blob/7b3f937/tests/test_scanner.py),
  helper `write_skill()`: constructs test fixtures at `root / ".agents" / "skills" / name / "SKILL.md"`,
  confirming this is the literal path the scanner looks for, not just documentation.

**Applied to this project:** the skill should live at
`src/asc_metadata_verifier/.agents/skills/app-store-review-gate/SKILL.md` (assuming a `src/` layout with
module `asc_metadata_verifier`), which after `pip`/`uv` install ends up at
`site-packages/asc_metadata_verifier/.agents/skills/app-store-review-gate/SKILL.md`.

Note: the doc's own naming recommendation is to prefix the skill name with the library's name (e.g.
`fastapi-development`) to avoid collisions across installed packages. Task 14's brief already fixes the
name as `app-store-review-gate`; that is a judgment call for whoever wrote the brief, not something this
research should override — flagging it here only so Task 14 can decide consciously.

---

## (b) `pyproject.toml` / build config that makes discovery work — PARTIALLY CONFIRMED

**What is CONFIRMED:** the discovery mechanism has no entry-point, plugin registration, or special
`[tool.*]` config at all. It is pure file-path convention, read off two things:

1. **Installed Python packages:** the scanner reads the wheel's `*.dist-info/RECORD` file (standard pip
   metadata, listing every file the wheel installed) and looks for any entry matching
   `.agents/skills/*/SKILL.md`. Source:
   [`scanner.py`](https://github.com/tiangolo/library-skills/blob/7b3f937/src/library_skills/scanner.py)
   `_scan_distribution_records()` / `_is_skill_file_record()`. There is also an editable-install fallback
   (`_scan_editable_direct_url()`) that reads `direct_url.json` and globs the source tree directly when a
   package was `pip install -e`'d.
2. **Installed Node packages:** globs `node_modules/<pkg>/.agents/skills/*/SKILL.md` directly (no
   manifest needed on the JS side).

I searched the entire `library-skills` repository (via `gh api search/code`) for `package-data`,
`package_data`, `MANIFEST`, and `hatch` — **zero hits**. `docs/create/index.md` (quoted above in full) is
the entirety of the "how do I bundle a skill" guidance the project ships, and it stops at "put the file
there, it'll be available when bundled" — it does **not** specify what build-backend config, if any, is
needed to make a build backend actually put a dot-prefixed directory into the wheel.

**What is UNCONFIRMED from `library-skills` source:** whether a producing library needs *any* extra
`pyproject.toml` wiring (e.g. `package-data`, `MANIFEST.in`, hatchling `force-include`) to get the
`.agents/` directory into the built wheel, because dot-prefixed paths are a common thing for build
backends to special-case.

I also checked whether any real library has actually adopted the convention yet, since the `library-skills`
README names FastAPI and Streamlit as examples:

- `gh api search/code` for `.agents/skills` scoped to `repo:tiangolo/fastapi` → **0 results**.
- `gh api repos/tiangolo/fastapi/contents/.agents` → **404 Not Found**.
- Checked `fastapi/typer` and `streamlit/streamlit` top-level contents → neither has an `.agents`
  directory.

**Conclusion: no reference implementation exists yet to check against.** The repo is very new (created
2026-04-26, most activity within the last day at time of writing) and the README's claim that FastAPI/
Streamlit "include their own AI skills embedded" is aspirational/forward-looking, not yet shipped as of
this research.

**Secondary evidence (not from `library-skills` itself — from `uv`'s own build-backend docs, cited
separately since `asc-metadata-verifier` is Python/`uv`-based and `library-skills` uses `uv_build` for
itself per its own
[`pyproject.toml`](https://github.com/tiangolo/library-skills/blob/7b3f937/pyproject.toml)):
[`docs.astral.sh/uv/concepts/build-backend/`](https://docs.astral.sh/uv/concepts/build-backend/) and the
[settings reference](https://docs.astral.sh/uv/reference/settings/#build-backend) state that `uv_build`'s
wheel contents default to "the module under `module-root`" (default `module-root = "src"`), and that
`default-excludes` (default `true`) only excludes `__pycache__`, `*.pyc`, and `*.pyo` — there is **no
documented default exclusion of dot-prefixed directories**. This suggests that *if* this project uses the
`uv_build` backend and places the skill under `src/asc_metadata_verifier/.agents/skills/...`, it would
likely be included with zero extra config. But this is my inference by combining two separate sources
(`library-skills`' file-convention + `uv`'s generic wheel-inclusion rule), **not** a claim either project
makes explicitly about the other, and it is untested against a real build.

**Action for Task 14 (do not skip):** after adding the skill files, actually build the wheel
(`uv build` or `python -m build --wheel`) and inspect it — `unzip -l dist/*.whl` or check
`*.dist-info/RECORD` inside — to confirm the `SKILL.md` path is really present before relying on it. If
the chosen build backend excludes it, the fix is backend-specific (e.g. `[tool.uv.build-backend] data =`,
`[tool.hatch.build.targets.wheel.force-include]`, or `MANIFEST.in` + `include_package_data` for
setuptools) and none of those exact configs are confirmed here — treat as `UNCONFIRMED`, verify by
inspecting the built artifact, not by assuming any one of them is right.

---

## (c) Exact `SKILL.md` frontmatter fields `library-skills` reads — CONFIRMED

**Fields: `name` and `description`. Nothing else.** This is read directly from the parser code, not
inferred:

[`scanner.py`](https://github.com/tiangolo/library-skills/blob/7b3f937/src/library_skills/scanner.py),
`_parse_skill_frontmatter()`:

```python
metadata: dict[str, str] = {}
for key in ("name", "description"):
    value = parsed.get(key)
    if isinstance(value, str):
        metadata[key] = value.strip()
```

Frontmatter must be YAML between `---` markers at the top of the file (`text.startswith("---")`, closing
`\n---`).

**Validation rules**, from `_validate_skill_metadata()` in the same file:

| Field | Rule |
|---|---|
| `name` | Required. Must match regex `^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$` (lowercase letters, digits, hyphens; 1–64 chars). Must **not** contain `--` (double hyphen). Must **exactly equal the parent directory name** — i.e. `.agents/skills/<X>/SKILL.md` frontmatter `name:` must literally be `X`. |
| `description` | Required. Max 1024 characters. |

Confirmed against `app-store-review-gate` (Task 14's skill name): it satisfies the regex (lowercase +
hyphens, no double-hyphen), so it is a valid `name` as long as the skill's directory is also literally
named `app-store-review-gate`.

Corroborating source: [`agentskills.io/home`](https://agentskills.io/home) (the open standard
`library-skills` explicitly says it follows — `docs/create/index.md`: *"Library Skills are the same
standard Agent Skills ... following the same format and conventions"*) states: *"This file includes
metadata (`name` and `description`, at minimum)."* — consistent with `library-skills` reading exactly
those two as the required minimum.

**Supplementary context (not read by `library-skills`, but relevant since the skill also needs to work
as an actual Claude Code skill once installed):** per
[`code.claude.com/docs/en/skills`](https://code.claude.com/docs/en/skills), the portable subset of
frontmatter fields that work across Claude Code, claude.ai skill uploads, and the Skills API is exactly
six: `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`. Everything else
(`disable-model-invocation`, `disallowed-tools`, `argument-hint`, `context`, `background`, `arguments`,
...) is a **Claude-Code-only extension** and is silently unused by `library-skills`' own scanner (it only
ever reads `name`/`description`, confirmed above) — so it's safe to add Claude-Code-specific fields to
`app-store-review-gate/SKILL.md` in Task 14 without breaking `library-skills` discovery, as long as `name`
and `description` are present and valid.

Personal-install path referenced in this project's `README.md` (`~/.claude/skills/app-store-review-gate/`)
is confirmed correct: `code.claude.com/docs/en/skills` table — *"Personal | `~/.claude/skills/<skill-name>/SKILL.md` | All your projects"*.

---

## (d) User install/discovery command — CONFIRMED

Primary command (from
[`README.md`](https://github.com/tiangolo/library-skills/blob/7b3f937/README.md) and
[`docs/use/index.md`](https://github.com/tiangolo/library-skills/blob/7b3f937/docs/use/index.md), and
independently confirmed live on the [PyPI project page](https://pypi.org/project/library-skills/)):

```bash
uvx library-skills          # Python — no separate install needed, uvx runs it in an ephemeral env
npx library-skills          # Node.js equivalent
```

Behavior (verbatim from `docs/use/index.md`): it checks declared dependencies in `pyproject.toml` /
`package.json`, scans the project's environment (`.venv` or `node_modules`), finds skills bundled by
*installed* packages, shows install/repair/remove status, and — on confirmation — creates a **relative
symlink** (or copies with `--copy` if symlinks aren't supported) from the target directory into the
package's `.agents/skills/<name>/` directory.

**Because Claude Code specifically does not read the generic `.agents/` directory**, the tool needs an
extra flag for Claude Code users — confirmed by `docs/use/index.md`, "Claude Code" section (verbatim):

> If you are using Claude Code, it doesn't support the `.agents` directory, only the `.claude` directory.
> When Library Skills asks for installation targets, select `.claude/skills`.
> For non-interactive installs, use `--claude` to install in `.claude/skills` too.
>
> ```bash
> uvx library-skills --claude
> ```

Other confirmed entry points (same source): `pip install library-skills && library-skills` (plain pip,
non-`uvx`), `bunx library-skills` (Bun). Non-interactive/CI flags: `--yes`/`-y` (skip prompts, reconcile
drift), `--check` (validate only, exit 1 on drift — usable as a pre-commit hook, an example is given in
the doc), `--all` (install every newly discovered skill), `-s/--skill NAME` (install one named skill).

This project's `README.md` already documents this correctly:

```bash
uv add asc-metadata-verifier
uvx library-skills          # discovers + installs the bundled `app-store-review-gate` skill
```

— matches the confirmed convention. For Claude Code users specifically, `uvx library-skills --claude`
(or interactively selecting `.claude/skills` when prompted) is the more precise command, since plain
`uvx library-skills` targets `.agents/skills` by default and Claude Code doesn't read that directory.

**Manual fallback (UNCONFIRMED convenience, but consistent with source):** if a user can't or won't run
`library-skills` (e.g. air-gapped, or `library-skills` itself is unavailable), the fallback is to
manually copy the **entire skill directory** — not just the file — into Claude Code's personal skills
folder:

```bash
cp -r site-packages/asc_metadata_verifier/.agents/skills/app-store-review-gate ~/.claude/skills/
```

Note: this project's own `README.md` currently says *"copy `app-store-review-gate/SKILL.md` into
`~/.claude/skills/app-store-review-gate/`"* (singular file). Per `installer.py`'s `install_skill()`
(`source = skill.skill_dir.resolve()`; `shutil.copytree(source, dest)`), `library-skills` itself always
installs the **whole skill directory**, not just `SKILL.md`. If Task 14's skill ends up bundling any
supporting files (scripts/references/assets, per the Agent Skills spec structure) alongside `SKILL.md`,
the manual fallback instructions should say "copy the whole directory," or those extra files will be
silently missing for anyone who follows the manual path literally. Flagging this as a small but real gap
between the existing README wording and the confirmed tool behavior — worth fixing when Task 14 lands the
actual file layout (whether the skill needs extra files or is `SKILL.md`-only won't be known until then).

---

## Sources fetched

| # | URL | What it confirmed |
|---|---|---|
| 1 | [`github.com/tiangolo/library-skills`](https://github.com/tiangolo/library-skills) | Repo is real, 761 stars, MIT, active; README summary of the tool. |
| 2 | [`repos/tiangolo/library-skills` GitHub API metadata](https://api.github.com/repos/tiangolo/library-skills) | Created 2026-04-26, `main` default branch, last pushed 2026-08-07. |
| 3 | [`.../git/trees/main?recursive=true`](https://api.github.com/repos/tiangolo/library-skills/git/trees/main?recursive=true) | Full repo file listing — located `src/library_skills/{scanner,installer,cli}.py`, `docs/create/index.md`, `docs/use/index.md`, `tests/test_scanner.py`. |
| 4 | [`pyproject.toml`](https://github.com/tiangolo/library-skills/blob/7b3f937/pyproject.toml) | Package metadata, author Sebastián Ramírez, `build-backend = "uv_build"`, no skill-related `[tool.*]` config present. |
| 5 | [`src/library_skills/scanner.py`](https://github.com/tiangolo/library-skills/blob/7b3f937/src/library_skills/scanner.py) | (a) exact discovery path pattern `.agents/skills/*/SKILL.md`; (b) discovery is pure RECORD/glob scanning, no entry points; (c) exact frontmatter fields read (`name`, `description`) and their validation rules. |
| 6 | [`src/library_skills/installer.py`](https://github.com/tiangolo/library-skills/blob/7b3f937/src/library_skills/installer.py) | Install mechanism is symlink (default) or `copytree` (`--copy`) of the **whole skill directory**; confirms `.claude/skills` and `.agents/skills` as the two install targets. |
| 7 | [`docs/create/index.md`](https://github.com/tiangolo/library-skills/blob/7b3f937/docs/create/index.md) | Primary source for (a) — the producer-side "how to bundle a skill" guide, verbatim path examples for Python and Node.js. |
| 8 | [`docs/use/index.md`](https://github.com/tiangolo/library-skills/blob/7b3f937/docs/use/index.md) | Primary source for (d) — full CLI behavior, `--claude` flag necessity, pre-commit hook example, JSON output flags. |
| 9 | [`docs/reference.md`](https://github.com/tiangolo/library-skills/blob/7b3f937/docs/reference.md) | Full CLI reference (`scan`, `list`, `install`, `remove` subcommands and flags) — cross-checked against `docs/use/index.md`. |
| 10 | [`README.md`](https://github.com/tiangolo/library-skills/blob/7b3f937/README.md) | Top-level install command (`uvx library-skills` / `npx library-skills`), symlink behavior, tip about Claude Code needing `.claude/skills`. |
| 11 | [`src/library_skills/tool_skill/SKILL.md`](https://github.com/tiangolo/library-skills/blob/7b3f937/src/library_skills/tool_skill/SKILL.md) | The tool's own bundled meta-skill — real example of a valid `SKILL.md` frontmatter (`name: library-skills`, `description: ...`). |
| 12 | [`tests/test_scanner.py`](https://github.com/tiangolo/library-skills/blob/7b3f937/tests/test_scanner.py) | Confirms via test fixtures that discovery literally expects `root/.agents/skills/<name>/SKILL.md`, not just as documented prose. |
| 13 | `gh api search/code` for `package-data`/`package_data`/`MANIFEST`/`hatch` scoped to `repo:tiangolo/library-skills` | Zero hits — confirms (b) has no documented build-backend wiring anywhere in the repo. |
| 14 | [`repos/tiangolo/fastapi/contents/.agents`](https://github.com/tiangolo/fastapi) (404), plus content listings of `fastapi/typer` and `streamlit/streamlit` | Confirms **no reference library has adopted the convention yet** — the README's FastAPI/Streamlit examples are aspirational, not a working reference implementation to check against. |
| 15 | [`docs.astral.sh/uv/concepts/build-backend/`](https://docs.astral.sh/uv/concepts/build-backend/) | `uv_build` default wheel-exclude list is only `__pycache__`, `*.pyc`, `*.pyo` — no documented dot-directory exclusion (secondary evidence for (b), from `uv`'s docs, not `library-skills`'). |
| 16 | [`docs.astral.sh/uv/reference/settings/#build-backend`](https://docs.astral.sh/uv/reference/settings/#build-backend) | Exact `[tool.uv.build-backend]` setting names/defaults (`module-root="src"`, `default-excludes=true`, `wheel-exclude=[]`, etc.), used to reason about (b). |
| 17 | [`pypi.org/project/library-skills/`](https://pypi.org/project/library-skills/) | Confirms real PyPI package by tiangolo, version `0.0.19`, `uvx library-skills` install line, independent of GitHub. |
| 18 | [`agentskills.io/home`](https://agentskills.io/home) | The open Agent Skills standard `library-skills` follows: skill = folder + `SKILL.md`, minimum metadata is `name` + `description` — corroborates (c). |
| 19 | [`code.claude.com/docs/en/skills`](https://code.claude.com/docs/en/skills) | Claude Code's own SKILL.md frontmatter reference — confirms the 6-field portable subset (`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`) vs. Claude-Code-only extensions; confirms `~/.claude/skills/<name>/SKILL.md` as the personal-install path used in this project's fallback instructions. |
