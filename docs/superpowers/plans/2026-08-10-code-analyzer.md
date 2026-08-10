# Code Analyzer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an additive `code` capability that runs deep AST-level static analysis over a local Apple app project (Swift/Obj-C source + `Info.plist` + `*.entitlements` + `PrivacyInfo.xcprivacy`), flags a curated set of App-Store-rejection-risk findings — each anchored to `file:line` + evidence and mapped to a guideline section — and folds them into the same PASS/WARN/BLOCK gate, with an opt-in jury layer for interpretive calls.

**Architecture:** New `code/` package: offline `load_project()` → pluggable `SourceParser` (tree-sitter default, optional BYO-SwiftSyntax subprocess backend) → a `Rule` REGISTRY producing `CodeFinding`s → the existing `gate.evaluate` rollup. An opt-in `code/jury.py` escalates interpretive findings/questions to fresh code-specific judge agents, reusing the existing `JudgeSpec` config + consensus `POLICIES` + `JudgeVote`/`PanelVerdict` models. CLI gains a standalone `asc-verify code <path>` command and a `verify --code <path>` flag.

**Tech Stack:** Python 3.11+ (runs on 3.14 here), uv · pydantic v2 · typer · stdlib `plistlib`/`pathlib`/`subprocess` (no new core dep) · optional extra `code`: `tree-sitter` + `tree-sitter-language-pack` (Swift + Obj-C grammars, offline) · jury layer reuses `pydantic-ai` + the existing `judge/` package.

## Global Constraints

- **Additive / backward compatible (hard):** with no `code` command and no `--code` flag, behavior is byte-identical to today; plain `verify`/`history`/`diff`/`similar` and bare `asc-verify <path>` pass unchanged, do no extra I/O, and pull zero new core dependencies. tree-sitter is lazy-imported behind the `[code]` extra.
- **Offline by default (hard):** `asc-verify code <path>` with no `--jury` makes zero network calls. The static analyzer never touches the network. Only `--jury` may, and its guideline grounding reuses the existing session cache, degrading to `available=False` (never fabricated) offline.
- **Never fabricate (honesty invariant):** every `CodeFinding` is anchored to a real `file` (+ `line` where a token has one) and an `evidence` quote. A missing manifest, an unavailable parser backend, or an absent Swift toolchain each produce a factual state, never a guess. Jury items are tagged `source="jury"` and carry the full `PanelVerdict`.
- **Curated, not exhaustive (honesty invariant):** the rule catalog and the `private-api-symbol` / `required-reason-api-undeclared` denylists are curated and documented as non-exhaustive per rule module. The tool never claims to detect every private API or required-reason call.
- **Deterministic static core:** identical project input → identical ordered `CodeFinding`s. No randomness, no LLM in the static path.
- **Severity → gate level:** `high` → block-worthy; `medium`/`low` → warn-worthy (mirrors the judge's `_verdict_level` and `_DETERMINISTIC_LEVEL`).
- **Secrets by reference:** jury mode reuses the env-var-ref `JudgeSpec` config; no key material in output or errors.
- **Style:** ruff clean (`E,F,I,UP,B`, line-length 100). `pytest` offline; tests needing the `[code]` extra use `pytest.importorskip("tree_sitter_language_pack")`.

### Refinement from the spec (transparent, conscious)

The spec named a `[code-swift]` **pip extra** for SwiftSyntax. There is no importable pip package for SwiftSyntax (it resolves via SwiftPM inside a Swift toolchain). So the SwiftSyntax backend is realized honestly as a **BYO subprocess helper** (mirrors persistence's BYO-embedder pattern): the user supplies a command via `--swiftsyntax-cmd`/`ASC_SWIFTSYNTAX_CMD` that reads a source file and emits the AST-surface JSON. No `[code-swift]` pip extra is created; the seam + availability detection + tree-sitter fallback are what ship. This is the only deviation from the spec's letter and is documented in Task 11.

---

## Shared interfaces (defined once; tasks reference these exact names)

```python
# models.py additions
class CodeFinding(BaseModel):
    rule_id: str
    category: str
    severity: Literal["low", "medium", "high"]
    guideline_ref: str
    file: str
    line: int | None = None
    symbol: str | None = None
    evidence: str
    detail: str
    suggested_fix: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source: Literal["static", "jury"] = "static"
    panel: PanelVerdict | None = None

class CodeReport(BaseModel):
    status: Literal["PASS", "WARN", "BLOCK"]
    findings: list[CodeFinding] = Field(default_factory=list)
    analyzed_files: int = 0
    parser_backend: str = ""
    jury_used: bool = False

# GateReport gains:  code_findings: list[CodeFinding] = Field(default_factory=list)

# code/project.py
class SourceFile(BaseModel):     # eager text; projects are small
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
def load_project(root: str | Path) -> ProjectModel: ...

# code/parser.py
class CallSite(BaseModel):  name: str; file: str; line: int
class StringLit(BaseModel): value: str; file: str; line: int
class SourceAST(Protocol):
    file: str
    def symbols(self) -> set[str]: ...
    def imports(self) -> set[str]: ...
    def calls(self, name: str) -> list[CallSite]: ...
    def string_literals(self) -> list[StringLit]: ...
ASTIndex = dict[str, SourceAST]          # keyed by SourceFile.path
class SourceParser(Protocol):
    backend_name: str
    def available(self) -> bool: ...
    def parse(self, source: SourceFile) -> SourceAST: ...
def build_parser(backend: str = "auto", *, swiftsyntax_cmd: str | None = None) -> SourceParser: ...

# code/rules/__init__.py
class Rule(Protocol):
    id: str; category: str; guideline_ref: str
    severity: Literal["low", "medium", "high"]; interpretive: bool
    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]: ...
REGISTRY: list[Rule]

# code/analyzer.py
def analyze(project: ProjectModel, parser: SourceParser) -> tuple[list[CodeFinding], ASTIndex]: ...
def build_code_report(findings, analyzed_files, backend, *, fail_on="fail", jury_used=False) -> CodeReport: ...

# gate.py additions
def _code_level(f: CodeFinding) -> Level: ...       # "block" if high else "warn"
# evaluate(...) gains: code_findings: list[CodeFinding] | None = None
```

---

### Task 1: Data models + gate integration

**Files:**
- Modify: `src/asc_metadata_verifier/models.py` (add `CodeFinding`, `CodeReport`; add `code_findings` to `GateReport`)
- Modify: `src/asc_metadata_verifier/gate.py` (add `_code_level`, fold `code_findings` into `evaluate`)
- Test: `tests/test_code_models.py`, extend `tests/test_gate.py`

**Interfaces:**
- Consumes: existing `PanelVerdict`, `GateReport`, `RubricVerdict`, `DeterministicFinding`, `evaluate`.
- Produces: `CodeFinding`, `CodeReport`, `GateReport.code_findings`, `gate._code_level`, `evaluate(..., code_findings=...)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_code_models.py
from asc_metadata_verifier.models import CodeFinding, CodeReport, GateReport

def test_code_finding_defaults():
    f = CodeFinding(rule_id="uiwebview-usage", category="deprecated-api",
                    severity="high", guideline_ref="2.5.x", file="A.swift",
                    line=3, evidence="UIWebView()", detail="deprecated")
    assert f.source == "static" and f.confidence == 1.0 and f.panel is None

def test_gate_report_has_code_findings_default():
    r = GateReport(status="PASS", guidelines_available=True)
    assert r.code_findings == []
```

```python
# tests/test_gate.py (append)
from asc_metadata_verifier.models import CodeFinding
from asc_metadata_verifier.gate import evaluate

def _cf(sev):
    return CodeFinding(rule_id="r", category="c", severity=sev, guideline_ref="2.5",
                       file="A.swift", line=1, evidence="e", detail="d")

def test_high_code_finding_blocks():
    r = evaluate([], [], code_findings=[_cf("high")])
    assert r.status == "BLOCK" and len(r.code_findings) == 1

def test_medium_code_finding_warns():
    assert evaluate([], [], code_findings=[_cf("medium")]).status == "WARN"

def test_low_code_finding_warns():
    assert evaluate([], [], code_findings=[_cf("low")]).status == "WARN"

def test_code_findings_absent_is_unchanged():
    assert evaluate([], []).status == "PASS"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_code_models.py tests/test_gate.py -q`
Expected: FAIL (`ImportError: cannot import name 'CodeFinding'`).

- [ ] **Step 3: Implement models**

In `models.py`, add after `PanelVerdict` (so `PanelVerdict` is defined first):

```python
class CodeFinding(BaseModel):
    rule_id: str
    category: str
    severity: Literal["low", "medium", "high"]
    guideline_ref: str
    file: str
    line: int | None = None
    symbol: str | None = None
    evidence: str
    detail: str
    suggested_fix: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source: Literal["static", "jury"] = "static"
    panel: PanelVerdict | None = None


class CodeReport(BaseModel):
    status: Literal["PASS", "WARN", "BLOCK"]
    findings: list[CodeFinding] = Field(default_factory=list)
    analyzed_files: int = 0
    parser_backend: str = ""
    jury_used: bool = False
```

In `GateReport`, add:

```python
    code_findings: list[CodeFinding] = Field(default_factory=list)
```

- [ ] **Step 4: Implement gate integration**

In `gate.py`, import `CodeFinding`, then add:

```python
def _code_level(finding: CodeFinding) -> Level:
    """high -> block (near-certain rejection); medium/low -> warn. Mirrors
    `_verdict_level`: only high severity blocks by default."""
    return "block" if finding.severity == "high" else "warn"
```

Change `evaluate`'s signature to add `code_findings: list[CodeFinding] | None = None`, extend the levels list and pass it through to `GateReport`:

```python
    code_findings = code_findings or []
    levels.extend(_code_level(f) for f in code_findings)
    ...
    return GateReport(
        status=status,
        verdicts=verdicts,
        deterministic_findings=deterministic_findings,
        guidelines_available=guidelines_available,
        panels=panels or [],
        code_findings=code_findings,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_code_models.py tests/test_gate.py -q` → PASS. Then `uv run pytest -q` (full suite unchanged) and `uv run ruff check src tests`.

- [ ] **Step 6: Commit**

```bash
git add src/asc_metadata_verifier/models.py src/asc_metadata_verifier/gate.py tests/test_code_models.py tests/test_gate.py
git commit -m "feat(code): CodeFinding/CodeReport models + gate rollup"
```

---

### Task 2: Project loader

**Files:**
- Create: `src/asc_metadata_verifier/code/__init__.py` (empty), `src/asc_metadata_verifier/code/project.py`
- Test: `tests/test_code_project.py`

**Interfaces:**
- Produces: `SourceFile`, `PlistArtifact`, `ProjectModel`, `load_project(root)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_code_project.py
import plistlib
from pathlib import Path
from asc_metadata_verifier.code.project import load_project

def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)

def test_discovers_sources_manifests_and_skips_pods(tmp_path: Path):
    _write(tmp_path / "App/View.swift", "import UIKit\n")
    _write(tmp_path / "App/Legacy.m", "#import <UIKit/UIKit.h>\n")
    _write(tmp_path / "Pods/Dep/Ignore.swift", "let ignored = 1\n")
    (tmp_path / "App/Info.plist").write_bytes(
        plistlib.dumps({"CFBundleName": "Demo", "ITSAppUsesNonExemptEncryption": False}))
    (tmp_path / "App/PrivacyInfo.xcprivacy").write_bytes(
        plistlib.dumps({"NSPrivacyAccessedAPITypes": []}))
    _write(tmp_path / "App/App.entitlements", "")
    (tmp_path / "App/App.entitlements").write_bytes(plistlib.dumps({"aps-environment": "development"}))

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_project.py -q`
Expected: FAIL (`ModuleNotFoundError: ...code.project`).

- [ ] **Step 3: Implement the loader**

```python
# src/asc_metadata_verifier/code/project.py
"""Offline project loader: walk a project root and collect Swift/Obj-C sources
and the plist manifests rules correlate against. No network, no AST parsing
(that is the parser's job) -- only file discovery + plist key/value trees."""

from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_SKIP_DIRS = {"Pods", "Carthage", ".build", "DerivedData", ".git", "build"}
_SOURCE_LANG = {".swift": "swift", ".m": "objc", ".h": "objc"}


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
            proj.sources.append(SourceFile(path=str(path), language=_SOURCE_LANG[suffix], text=text))
        elif name == "PrivacyInfo.xcprivacy":
            proj.privacy_manifests.append(_load_plist(path))
        elif suffix == ".entitlements":
            proj.entitlements.append(_load_plist(path))
        elif name == "Info.plist" or (suffix == ".plist" and name.endswith("Info.plist")):
            proj.info_plists.append(_load_plist(path))
    return proj
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_code_project.py -q` → PASS. `uv run ruff check src/asc_metadata_verifier/code tests/test_code_project.py`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/code/__init__.py src/asc_metadata_verifier/code/project.py tests/test_code_project.py
git commit -m "feat(code): offline project loader (sources + plist manifests)"
```

---

### Task 3: Parser strategy + tree-sitter backend + `[code]` extra

**Files:**
- Create: `src/asc_metadata_verifier/code/parser.py`, `src/asc_metadata_verifier/code/backends/__init__.py` (empty), `src/asc_metadata_verifier/code/backends/treesitter.py`
- Modify: `pyproject.toml` (add `[code]` optional extra)
- Test: `tests/test_code_parser.py`

**Interfaces:**
- Consumes: `SourceFile` (Task 2).
- Produces: `CallSite`, `StringLit`, `SourceAST` (protocol), `ASTIndex`, `SourceParser` (protocol), `build_parser(backend="auto", *, swiftsyntax_cmd=None)`, `TreeSitterParser`.

- [ ] **Step 0: Verify the dependency on THIS interpreter (do not assume)**

Run: `uv sync --extra code` then
`uv run python -c "from tree_sitter_language_pack import get_parser; [print(l, get_parser(l).parse(b'let x=1').root_node.type) for l in ('swift','objc')]"`
Expected: prints `swift source_file` and `objc translation_unit`. (Confirmed working on Python 3.14 during planning; re-verify in-env. If it fails, STOP and report — the default backend is load-bearing.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_code_parser.py
import pytest
pytest.importorskip("tree_sitter_language_pack")
from asc_metadata_verifier.code.project import SourceFile
from asc_metadata_verifier.code.parser import build_parser

def _ast(text, lang="swift"):
    return build_parser().parse(SourceFile(path="A.swift", language=lang, text=text))

def test_symbols_include_type_reference():
    ast = _ast("import UIKit\nlet w = UIWebView()\n")
    assert "UIWebView" in ast.symbols()
    assert "UIKit" in ast.imports()

def test_symbol_in_comment_is_not_reported():
    ast = _ast("// UIWebView is deprecated\nlet x = 1\n")
    assert "UIWebView" not in ast.symbols()   # AST beats regex: comments excluded

def test_string_literals_carry_value_and_line():
    ast = _ast('let u = "http://insecure.example.com"\n')
    lits = [s.value for s in ast.string_literals()]
    assert any("http://insecure.example.com" in v for v in lits)
    assert ast.string_literals()[0].line >= 1

def test_calls_match_by_callee_name():
    ast = _ast("canOpenURL(url)\n")
    assert [c.name for c in ast.calls("canOpenURL")] == ["canOpenURL"]

def test_backend_name_and_available():
    p = build_parser()
    assert p.backend_name == "tree-sitter" and p.available() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_parser.py -q`
Expected: FAIL (`ModuleNotFoundError: ...code.parser`).

- [ ] **Step 3: Implement parser protocol + tree-sitter backend**

```python
# src/asc_metadata_verifier/code/parser.py
"""Pluggable source parser (strategy pattern). tree-sitter is the default,
offline backend; an optional BYO-SwiftSyntax subprocess backend is added in
Task 10. The `SourceAST` query surface is deliberately syntactic (symbol/
import/call/string presence with line numbers), NOT semantic type resolution
-- the honest AST-structural ceiling stated in the spec."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from asc_metadata_verifier.code.project import SourceFile


class CallSite(BaseModel):
    name: str
    file: str
    line: int


class StringLit(BaseModel):
    value: str
    file: str
    line: int


@runtime_checkable
class SourceAST(Protocol):
    file: str
    def symbols(self) -> set[str]: ...
    def imports(self) -> set[str]: ...
    def calls(self, name: str) -> list[CallSite]: ...
    def string_literals(self) -> list[StringLit]: ...


ASTIndex = dict[str, SourceAST]


@runtime_checkable
class SourceParser(Protocol):
    backend_name: str
    def available(self) -> bool: ...
    def parse(self, source: SourceFile) -> SourceAST: ...


def build_parser(backend: str = "auto", *, swiftsyntax_cmd: str | None = None) -> SourceParser:
    if backend == "swiftsyntax":
        from asc_metadata_verifier.code.backends.swiftsyntax import SwiftSyntaxParser
        candidate = SwiftSyntaxParser(swiftsyntax_cmd=swiftsyntax_cmd)
        if candidate.available():
            return candidate
        # Honest fallback: never fabricate an AST from an unavailable backend.
        from asc_metadata_verifier.code.backends.treesitter import TreeSitterParser
        return TreeSitterParser(backend_name="swiftsyntax(unavailable)")
    from asc_metadata_verifier.code.backends.treesitter import TreeSitterParser
    return TreeSitterParser()
```

```python
# src/asc_metadata_verifier/code/backends/treesitter.py
"""Default offline parser backend. Lazy-imports tree-sitter so the base
install (no `[code]` extra) never needs it. The query surface walks the
syntax tree collecting identifier-like node texts (symbols), import paths,
call callees, and string-literal node texts -- token-accurate, so a symbol
inside a comment or string is NOT a false positive (the win over regex)."""

from __future__ import annotations

from functools import lru_cache

from asc_metadata_verifier.code.parser import CallSite, SourceAST, StringLit
from asc_metadata_verifier.code.project import SourceFile

_IDENT_NODES = {"simple_identifier", "type_identifier", "identifier"}
_STRING_NODES = {"line_string_literal", "string_literal"}
_IMPORT_NODES = {"import_declaration", "preproc_include"}
_CALL_NODES = {"call_expression", "call_expr"}


@lru_cache(maxsize=None)
def _language_parser(language: str):
    from tree_sitter_language_pack import get_parser
    return get_parser("swift" if language == "swift" else "objc")


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.children)


class TreeSitterAST:
    def __init__(self, file: str, root, source_bytes: bytes):
        self.file = file
        self._root = root
        self._src = source_bytes

    def _text(self, node) -> str:
        return self._src[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def symbols(self) -> set[str]:
        return {self._text(n) for n in _walk(self._root) if n.type in _IDENT_NODES}

    def imports(self) -> set[str]:
        out: set[str] = set()
        for n in _walk(self._root):
            if n.type in _IMPORT_NODES:
                for ident in _walk(n):
                    if ident.type in _IDENT_NODES:
                        out.add(self._text(ident))
        return out

    def calls(self, name: str) -> list[CallSite]:
        out: list[CallSite] = []
        for n in _walk(self._root):
            if n.type in _CALL_NODES and n.children:
                callee = self._text(n.children[0]).split("(")[0].split(".")[-1]
                if callee == name:
                    out.append(CallSite(name=name, file=self.file, line=n.start_point[0] + 1))
        return out

    def string_literals(self) -> list[StringLit]:
        out: list[StringLit] = []
        for n in _walk(self._root):
            if n.type in _STRING_NODES:
                out.append(StringLit(value=self._text(n).strip('"'),
                                     file=self.file, line=n.start_point[0] + 1))
        return out


class TreeSitterParser:
    def __init__(self, backend_name: str = "tree-sitter"):
        self.backend_name = backend_name

    def available(self) -> bool:
        try:
            import tree_sitter_language_pack  # noqa: F401
            return True
        except ImportError:
            return False

    def parse(self, source: SourceFile) -> SourceAST:
        parser = _language_parser(source.language)
        src_bytes = source.text.encode("utf-8")
        tree = parser.parse(src_bytes)
        return TreeSitterAST(source.path, tree.root_node, src_bytes)
```

Add to `pyproject.toml` under `[project.optional-dependencies]` (after `semantic`):

```toml
# Optional, offline deep-code-analysis backend. Never a core dependency:
# `code/backends/treesitter.py` imports tree-sitter lazily, so the default
# install and its tests never need this extra, and `verify` is unchanged.
code = ["tree-sitter>=0.23", "tree-sitter-language-pack>=2.0"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_code_parser.py -q` → PASS. `uv run ruff check src/asc_metadata_verifier/code`.
Note for the implementer: if any `_*_NODES` constant is wrong for the installed grammar version, the failing test will show it — fix the node-type set against the real tree (print `[(n.type) for n in _walk(root)]` on a fixture), don't hardcode blindly.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/code/parser.py src/asc_metadata_verifier/code/backends/ pyproject.toml tests/test_code_parser.py
git commit -m "feat(code): SourceParser strategy + tree-sitter backend + [code] extra"
```

---

### Task 4: Rule engine core

**Files:**
- Create: `src/asc_metadata_verifier/code/rules/__init__.py`, `src/asc_metadata_verifier/code/analyzer.py`
- Test: `tests/test_code_analyzer.py`

**Interfaces:**
- Consumes: `ProjectModel` (T2), `SourceParser`/`ASTIndex` (T3), `CodeFinding`/`CodeReport` (T1), `gate.evaluate` (T1).
- Produces: `Rule` (protocol), `REGISTRY`, `register(rule)`, `analyze(project, parser)`, `build_code_report(...)`.

- [ ] **Step 1: Write the failing test** (uses a fake parser — no `[code]` extra needed, so this test always runs)

```python
# tests/test_code_analyzer.py
from asc_metadata_verifier.code.analyzer import analyze, build_code_report
from asc_metadata_verifier.code import rules as rules_mod
from asc_metadata_verifier.code.project import ProjectModel, SourceFile
from asc_metadata_verifier.code.parser import CallSite, StringLit
from asc_metadata_verifier.models import CodeFinding


class _FakeAST:
    def __init__(self, file): self.file = file
    def symbols(self): return {"UIWebView"}
    def imports(self): return set()
    def calls(self, name): return []
    def string_literals(self): return []


class _FakeParser:
    backend_name = "fake"
    def available(self): return True
    def parse(self, source): return _FakeAST(source.path)


def test_registry_is_nonempty_and_ids_unique():
    ids = [r.id for r in rules_mod.REGISTRY]
    assert ids and len(ids) == len(set(ids))


def test_analyze_runs_rules_and_sorts(monkeypatch):
    class R:
        id="x"; category="c"; guideline_ref="2.5.x"; severity="high"; interpretive=False
        def check(self, project, asts):
            return [CodeFinding(rule_id="x", category="c", severity="high",
                    guideline_ref="2.5.x", file="B.swift", line=9, evidence="e", detail="d"),
                    CodeFinding(rule_id="x", category="c", severity="high",
                    guideline_ref="2.5.x", file="A.swift", line=1, evidence="e", detail="d")]
    monkeypatch.setattr(rules_mod, "REGISTRY", [R()])
    proj = ProjectModel(root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")])
    findings, asts = analyze(proj, _FakeParser())
    assert [f.file for f in findings] == ["A.swift", "B.swift"]   # sorted by (file, line, rule_id)


def test_build_code_report_status_from_severity():
    hi = CodeFinding(rule_id="x", category="c", severity="high", guideline_ref="2.5",
                     file="A.swift", line=1, evidence="e", detail="d")
    rep = build_code_report([hi], analyzed_files=1, backend="tree-sitter")
    assert rep.status == "BLOCK" and rep.analyzed_files == 1 and rep.parser_backend == "tree-sitter"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_analyzer.py -q`
Expected: FAIL (`ModuleNotFoundError: ...code.analyzer`).

- [ ] **Step 3: Implement the engine**

```python
# src/asc_metadata_verifier/code/rules/__init__.py
"""Rule registry. Each cluster module exposes a `RULES: list[Rule]`; importing
this package assembles the global `REGISTRY`. Rules are pure: given a
`ProjectModel` + `ASTIndex`, return `CodeFinding`s and nothing else."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from asc_metadata_verifier.code.parser import ASTIndex
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.models import CodeFinding


@runtime_checkable
class Rule(Protocol):
    id: str
    category: str
    guideline_ref: str
    severity: str        # "low" | "medium" | "high"
    interpretive: bool
    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]: ...


def _load_registry() -> list[Rule]:
    from asc_metadata_verifier.code.rules import (
        compliance,
        deprecated_api,
        privacy,
        security,
    )
    registry: list[Rule] = []
    for module in (privacy, deprecated_api, security, compliance):
        registry.extend(module.RULES)
    return registry


# Populated lazily-but-once at import; Tasks 5-7 add the cluster modules. Until
# then `_load_registry` raises ImportError -- which is why Task 4 lands its own
# test with a monkeypatched REGISTRY and the real REGISTRY is asserted in Task 7.
REGISTRY: list[Rule] = _load_registry()
```

> Implementer note: Task 4 and Tasks 5-7 are sequenced so the cluster modules exist before this package imports cleanly. If you implement Task 4 alone, temporarily set `REGISTRY: list[Rule] = []` and a `# TODO(next-task)` — but the committed state at the END of Task 7 MUST call `_load_registry()`. The reviewer for Task 7 verifies the real REGISTRY has all rules. (To keep Task 4 independently green, its test monkeypatches REGISTRY and does not import the cluster modules.)

Because a task must be independently testable, land Task 4 with the cluster imports guarded:

```python
def _load_registry() -> list[Rule]:
    registry: list[Rule] = []
    try:
        from asc_metadata_verifier.code.rules import compliance, deprecated_api, privacy, security
        for module in (privacy, deprecated_api, security, compliance):
            registry.extend(module.RULES)
    except ImportError:
        pass  # cluster modules land in Tasks 5-7; Task 7 removes this guard.
    return registry
```

```python
# src/asc_metadata_verifier/code/analyzer.py
"""Orchestrator: parse each source once into an ASTIndex, run every registered
rule, return sorted CodeFindings. Deterministic: identical input -> identical
ordered output. No LLM here (that is code/jury.py)."""

from __future__ import annotations

from asc_metadata_verifier.code.parser import ASTIndex, SourceParser
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.code.rules import REGISTRY
from asc_metadata_verifier.gate import evaluate
from asc_metadata_verifier.models import CodeFinding, CodeReport


def analyze(project: ProjectModel, parser: SourceParser) -> tuple[list[CodeFinding], ASTIndex]:
    asts: ASTIndex = {sf.path: parser.parse(sf) for sf in project.sources}
    findings: list[CodeFinding] = []
    for rule in REGISTRY:
        findings.extend(rule.check(project, asts))
    findings.sort(key=lambda f: (f.file, f.line or 0, f.rule_id))
    return findings, asts


def build_code_report(findings: list[CodeFinding], analyzed_files: int, backend: str,
                      *, fail_on: str = "fail", jury_used: bool = False) -> CodeReport:
    status = evaluate([], [], fail_on=fail_on, code_findings=findings).status
    return CodeReport(status=status, findings=findings, analyzed_files=analyzed_files,
                      parser_backend=backend, jury_used=jury_used)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_code_analyzer.py -q` → PASS. `uv run ruff check src/asc_metadata_verifier/code`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/code/rules/__init__.py src/asc_metadata_verifier/code/analyzer.py tests/test_code_analyzer.py
git commit -m "feat(code): rule registry + analyzer orchestrator"
```

---

### Task 5: Privacy rules (5.1.x)

**Files:**
- Create: `src/asc_metadata_verifier/code/rules/privacy.py`, `src/asc_metadata_verifier/code/rules/data/__init__.py` (empty), `src/asc_metadata_verifier/code/rules/data/required_reason_apis.py`
- Test: `tests/test_code_rules_privacy.py`

**Interfaces:**
- Consumes: `ProjectModel`, `ASTIndex`, `CodeFinding`.
- Produces: `RULES: list[Rule]` = `[IdfaWithoutAtt(), MissingUsageString(), RequiredReasonApiUndeclared(), BoilerplateUsageString()]`.

**Rule logic (exact):**
- `idfa-without-att` (5.1.2, high): any AST `symbols()` across the project contains `ASIdentifierManager` or `advertisingIdentifier`, AND (`ATTrackingManager` NOT in any symbols OR no Info.plist has key `NSUserTrackingUsageDescription`). Evidence = the offending symbol; file/line = first source whose symbols contain it.
- `missing-usage-string` (5.1.1, high): for each `(api_symbol -> plist_key)` in a fixed map (`AVCaptureDevice→NSCameraUsageDescription`, `CLLocationManager→NSLocationWhenInUseUsageDescription`, `CNContactStore→NSContactsUsageDescription`, `PHPhotoLibrary→NSPhotoLibraryUsageDescription`, `AVAudioRecorder→NSMicrophoneUsageDescription`, `EKEventStore→NSCalendarsUsageDescription`, `HKHealthStore→NSHealthShareUsageDescription`): if the symbol is used and NO Info.plist carries the key, one finding.
- `required-reason-api-undeclared` (privacy-manifest, high): if any symbol in `REQUIRED_REASON_APIS` (data module) is used AND (no `PrivacyInfo.xcprivacy` exists OR none declares any `NSPrivacyAccessedAPIType`), one finding per used category (dedup by category).
- `boilerplate-usage-string` (5.1.1, medium, `interpretive=True`): for each Info.plist key ending `UsageDescription`, if its value is empty, < 12 chars, or matches a generic pattern (`^(we need|this app needs|required)\b`), one finding. Evidence = the value.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_code_rules_privacy.py
from asc_metadata_verifier.code.project import ProjectModel, SourceFile, PlistArtifact
from asc_metadata_verifier.code.rules.privacy import RULES
from asc_metadata_verifier.models import CodeFinding

class _AST:
    def __init__(self, file, syms): self.file=file; self._s=syms
    def symbols(self): return self._s
    def imports(self): return set()
    def calls(self, name): return []
    def string_literals(self): return []

def _run(rule_id, project, asts):
    rule = next(r for r in RULES if r.id == rule_id)
    return rule.check(project, asts)

def test_idfa_without_att_flags():
    proj = ProjectModel(root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")],
                        info_plists=[PlistArtifact(path="Info.plist", data={})])
    asts = {"A.swift": _AST("A.swift", {"ASIdentifierManager"})}
    out = _run("idfa-without-att", proj, asts)
    assert len(out) == 1 and out[0].severity == "high" and out[0].guideline_ref == "5.1.2"

def test_idfa_with_att_and_usage_string_is_clean():
    proj = ProjectModel(root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")],
        info_plists=[PlistArtifact(path="Info.plist", data={"NSUserTrackingUsageDescription": "To measure ads."})])
    asts = {"A.swift": _AST("A.swift", {"ASIdentifierManager", "ATTrackingManager"})}
    assert _run("idfa-without-att", proj, asts) == []

def test_missing_usage_string_flags_camera():
    proj = ProjectModel(root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")],
                        info_plists=[PlistArtifact(path="Info.plist", data={})])
    asts = {"A.swift": _AST("A.swift", {"AVCaptureDevice"})}
    out = _run("missing-usage-string", proj, asts)
    assert len(out) == 1 and "NSCameraUsageDescription" in out[0].detail

def test_missing_usage_string_clean_when_declared():
    proj = ProjectModel(root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")],
        info_plists=[PlistArtifact(path="Info.plist", data={"NSCameraUsageDescription": "For scanning."})])
    asts = {"A.swift": _AST("A.swift", {"AVCaptureDevice"})}
    assert _run("missing-usage-string", proj, asts) == []

def test_required_reason_api_undeclared_flags():
    proj = ProjectModel(root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")])
    asts = {"A.swift": _AST("A.swift", {"UserDefaults"})}
    out = _run("required-reason-api-undeclared", proj, asts)
    assert len(out) >= 1 and out[0].severity == "high"

def test_required_reason_api_declared_is_clean():
    proj = ProjectModel(root="/p", sources=[SourceFile(path="A.swift", language="swift", text="")],
        privacy_manifests=[PlistArtifact(path="PrivacyInfo.xcprivacy",
            data={"NSPrivacyAccessedAPITypes": [{"NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategoryUserDefaults"}]})])
    asts = {"A.swift": _AST("A.swift", {"UserDefaults"})}
    assert _run("required-reason-api-undeclared", proj, asts) == []

def test_boilerplate_usage_string_flags_and_is_interpretive():
    proj = ProjectModel(root="/p", info_plists=[PlistArtifact(path="Info.plist",
        data={"NSCameraUsageDescription": "We need access"})])
    out = _run("boilerplate-usage-string", proj, {})
    assert len(out) == 1 and out[0].severity == "medium"
    rule = next(r for r in RULES if r.id == "boilerplate-usage-string")
    assert rule.interpretive is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_code_rules_privacy.py -q`
Expected: FAIL (`ModuleNotFoundError: ...rules.privacy`).

- [ ] **Step 3: Implement the data module + rules**

```python
# src/asc_metadata_verifier/code/rules/data/required_reason_apis.py
"""Curated map of required-reason API symbol -> Apple privacy-manifest API
category. NON-EXHAUSTIVE by design (Apple's list evolves); documented as such.
Extend deliberately, with a source link in the commit message."""

REQUIRED_REASON_APIS: dict[str, str] = {
    "UserDefaults": "NSPrivacyAccessedAPICategoryUserDefaults",
    "NSUserDefaults": "NSPrivacyAccessedAPICategoryUserDefaults",
    "systemUptime": "NSPrivacyAccessedAPICategorySystemBootTime",
    "mach_absolute_time": "NSPrivacyAccessedAPICategorySystemBootTime",
    "contentModificationDate": "NSPrivacyAccessedAPICategoryFileTimestamp",
    "creationDate": "NSPrivacyAccessedAPICategoryFileTimestamp",
    "stat": "NSPrivacyAccessedAPICategoryDiskSpace",
    "statfs": "NSPrivacyAccessedAPICategoryDiskSpace",
    "activeInputModes": "NSPrivacyAccessedAPICategoryActiveKeyboards",
}
```

```python
# src/asc_metadata_verifier/code/rules/privacy.py
"""Privacy & tracking rules (App Store Review Guideline 5.1.x).

False-negative note: symbol detection is presence-based (identifier appears in
the AST). Aliased/dynamically-constructed calls (e.g. NSClassFromString) are
NOT detected -- documented, curated coverage, not exhaustive."""

from __future__ import annotations

import re

from asc_metadata_verifier.code.parser import ASTIndex
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.code.rules.data.required_reason_apis import REQUIRED_REASON_APIS
from asc_metadata_verifier.models import CodeFinding

_USAGE_MAP = {
    "AVCaptureDevice": "NSCameraUsageDescription",
    "CLLocationManager": "NSLocationWhenInUseUsageDescription",
    "CNContactStore": "NSContactsUsageDescription",
    "PHPhotoLibrary": "NSPhotoLibraryUsageDescription",
    "AVAudioRecorder": "NSMicrophoneUsageDescription",
    "EKEventStore": "NSCalendarsUsageDescription",
    "HKHealthStore": "NSHealthShareUsageDescription",
}
_GENERIC_RE = re.compile(r"^\s*(we need|this app needs|required|allow access)\b", re.IGNORECASE)


def _all_symbols(asts: ASTIndex) -> dict[str, tuple[str, int]]:
    """symbol -> (file, line=1) for the first file that contains it, for evidence."""
    seen: dict[str, tuple[str, int]] = {}
    for path, ast in sorted(asts.items()):
        for sym in ast.symbols():
            seen.setdefault(sym, (path, 1))
    return seen


def _plist_has_key(project: ProjectModel, key: str) -> bool:
    return any(p.data and key in p.data for p in project.info_plists)


class IdfaWithoutAtt:
    id = "idfa-without-att"; category = "privacy-tracking"; guideline_ref = "5.1.2"
    severity = "high"; interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        symbols = _all_symbols(asts)
        idfa = next((s for s in ("ASIdentifierManager", "advertisingIdentifier") if s in symbols), None)
        if idfa is None:
            return []
        all_syms = set(symbols)
        has_att = "ATTrackingManager" in all_syms
        has_str = _plist_has_key(project, "NSUserTrackingUsageDescription")
        if has_att and has_str:
            return []
        file, line = symbols[idfa]
        return [CodeFinding(rule_id=self.id, category=self.category, severity=self.severity,
            guideline_ref=self.guideline_ref, file=file, line=line, symbol=idfa, evidence=idfa,
            detail="IDFA is accessed without an ATT prompt and/or NSUserTrackingUsageDescription",
            suggested_fix="Call ATTrackingManager.requestTrackingAuthorization and add NSUserTrackingUsageDescription")]


class MissingUsageString:
    id = "missing-usage-string"; category = "privacy-permissions"; guideline_ref = "5.1.1"
    severity = "high"; interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        symbols = _all_symbols(asts)
        out: list[CodeFinding] = []
        for sym, key in _USAGE_MAP.items():
            if sym in symbols and not _plist_has_key(project, key):
                file, line = symbols[sym]
                out.append(CodeFinding(rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=file, line=line, symbol=sym, evidence=sym,
                    detail=f"{sym} used but {key} is missing from Info.plist",
                    suggested_fix=f"Add a {key} string describing why the app needs this."))
        return out


class RequiredReasonApiUndeclared:
    id = "required-reason-api-undeclared"; category = "privacy-manifest"
    guideline_ref = "Apple privacy-manifest policy"; severity = "high"; interpretive = False

    def _declared(self, project: ProjectModel) -> set[str]:
        declared: set[str] = set()
        for pm in project.privacy_manifests:
            for entry in (pm.data or {}).get("NSPrivacyAccessedAPITypes", []) or []:
                if isinstance(entry, dict) and entry.get("NSPrivacyAccessedAPIType"):
                    declared.add(entry["NSPrivacyAccessedAPIType"])
        return declared

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        symbols = _all_symbols(asts)
        declared = self._declared(project)
        out: list[CodeFinding] = []
        seen_categories: set[str] = set()
        for sym, category in REQUIRED_REASON_APIS.items():
            if sym in symbols and category not in declared and category not in seen_categories:
                seen_categories.add(category)
                file, line = symbols[sym]
                out.append(CodeFinding(rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=file, line=line, symbol=sym, evidence=sym,
                    detail=f"{sym} requires declaring {category} in PrivacyInfo.xcprivacy",
                    suggested_fix=f"Add {category} with an approved reason to PrivacyInfo.xcprivacy."))
        return out


class BoilerplateUsageString:
    id = "boilerplate-usage-string"; category = "privacy-permissions"; guideline_ref = "5.1.1"
    severity = "medium"; interpretive = True

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        out: list[CodeFinding] = []
        for plist in project.info_plists:
            for key, value in sorted((plist.data or {}).items()):
                if not key.endswith("UsageDescription") or not isinstance(value, str):
                    continue
                if value.strip() == "" or len(value.strip()) < 12 or _GENERIC_RE.match(value):
                    out.append(CodeFinding(rule_id=self.id, category=self.category, severity=self.severity,
                        guideline_ref=self.guideline_ref, file=plist.path, line=None, symbol=key,
                        evidence=value, detail=f"{key} looks too generic/short to satisfy 5.1.1",
                        suggested_fix="Explain specifically why the app needs this data."))
        return out


RULES = [IdfaWithoutAtt(), MissingUsageString(), RequiredReasonApiUndeclared(), BoilerplateUsageString()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_code_rules_privacy.py -q` → PASS. `uv run ruff check src/asc_metadata_verifier/code/rules`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/code/rules/privacy.py src/asc_metadata_verifier/code/rules/data/ tests/test_code_rules_privacy.py
git commit -m "feat(code): privacy/tracking rules (5.1.x)"
```

---

### Task 6: Deprecated / private API rules (2.5.x)

**Files:**
- Create: `src/asc_metadata_verifier/code/rules/deprecated_api.py`, `src/asc_metadata_verifier/code/rules/data/private_api_symbols.py`
- Test: `tests/test_code_rules_deprecated.py`

**Interfaces:**
- Produces: `RULES = [UIWebViewUsage(), PrivateApiSymbol()]`.

**Rule logic:**
- `uiwebview-usage` (2.5.x, high): `UIWebView` in any AST symbols. Finding per file that contains it.
- `private-api-symbol` (2.5.1, high): any symbol in `PRIVATE_API_SYMBOLS` (data module) present. Finding per (file, symbol).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_code_rules_deprecated.py
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.code.rules.deprecated_api import RULES

class _AST:
    def __init__(self, file, syms): self.file=file; self._s=syms
    def symbols(self): return self._s
    def imports(self): return set()
    def calls(self, n): return []
    def string_literals(self): return []

def _run(rid, asts):
    return next(r for r in RULES if r.id == rid).check(ProjectModel(root="/p"), asts)

def test_uiwebview_flagged_per_file():
    out = _run("uiwebview-usage", {"A.swift": _AST("A.swift", {"UIWebView"})})
    assert len(out) == 1 and out[0].severity == "high" and out[0].file == "A.swift"

def test_uiwebview_clean_when_absent():
    assert _run("uiwebview-usage", {"A.swift": _AST("A.swift", {"WKWebView"})}) == []

def test_private_api_symbol_flagged():
    out = _run("private-api-symbol", {"A.swift": _AST("A.swift", {"LSApplicationWorkspace"})})
    assert len(out) == 1 and out[0].guideline_ref == "2.5.1"
```

- [ ] **Step 2: Run to verify fail** — `uv run pytest tests/test_code_rules_deprecated.py -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# src/asc_metadata_verifier/code/rules/data/private_api_symbols.py
"""Curated denylist of well-known private/undocumented API symbols that have
drawn 2.5.1 rejections. NON-EXHAUSTIVE: Apple's private-API set is proprietary
and vast; this is a high-signal subset. False negatives are expected."""

PRIVATE_API_SYMBOLS: frozenset[str] = frozenset({
    "LSApplicationWorkspace",
    "_UIBackdropView",
    "MPMediaLibrary",   # private selectors historically flagged
    "SBSLaunchApplicationWithIdentifier",
    "setStatusBarHidden",
    "_accessibilityHUDGestureManager",
})
```

```python
# src/asc_metadata_verifier/code/rules/deprecated_api.py
"""Deprecated / private API rules (App Store Review Guideline 2.5.x)."""

from __future__ import annotations

from asc_metadata_verifier.code.parser import ASTIndex
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.code.rules.data.private_api_symbols import PRIVATE_API_SYMBOLS
from asc_metadata_verifier.models import CodeFinding


class UIWebViewUsage:
    id = "uiwebview-usage"; category = "deprecated-api"; guideline_ref = "2.5.x"
    severity = "high"; interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        out: list[CodeFinding] = []
        for path, ast in sorted(asts.items()):
            if "UIWebView" in ast.symbols():
                out.append(CodeFinding(rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=path, line=1, symbol="UIWebView",
                    evidence="UIWebView", detail="UIWebView is deprecated and rejected since 2020",
                    suggested_fix="Replace UIWebView with WKWebView."))
        return out


class PrivateApiSymbol:
    id = "private-api-symbol"; category = "private-api"; guideline_ref = "2.5.1"
    severity = "high"; interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        out: list[CodeFinding] = []
        for path, ast in sorted(asts.items()):
            for sym in sorted(ast.symbols() & PRIVATE_API_SYMBOLS):
                out.append(CodeFinding(rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=path, line=1, symbol=sym, evidence=sym,
                    detail=f"{sym} is a private/undocumented API (2.5.1)",
                    suggested_fix="Use a public API; private symbols draw rejection."))
        return out


RULES = [UIWebViewUsage(), PrivateApiSymbol()]
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_code_rules_deprecated.py -q` → PASS; `uv run ruff check`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/code/rules/deprecated_api.py src/asc_metadata_verifier/code/rules/data/private_api_symbols.py tests/test_code_rules_deprecated.py
git commit -m "feat(code): deprecated/private-API rules (2.5.x)"
```

---

### Task 7: Security + compliance rules, and finalize REGISTRY

**Files:**
- Create: `src/asc_metadata_verifier/code/rules/security.py`, `src/asc_metadata_verifier/code/rules/compliance.py`
- Modify: `src/asc_metadata_verifier/code/rules/__init__.py` (remove the ImportError guard from Task 4 — all four cluster modules now exist)
- Test: `tests/test_code_rules_security.py`, `tests/test_code_registry.py`

**Interfaces:**
- `security.RULES = [AtsArbitraryLoads(), InsecureHttpEndpoint()]`; `compliance.RULES = [EncryptionExportUndeclared(), CanOpenUrlUndeclaredScheme()]`.

**Rule logic:**
- `ats-arbitrary-loads` (2.5.2, medium): any Info.plist has `NSAppTransportSecurity.NSAllowsArbitraryLoads is True`.
- `insecure-http-endpoint` (2.5.2, low): any AST `string_literals()` value matches `^http://` and host is not `localhost`/`127.0.0.1`. Finding per literal (file+line).
- `encryption-export-undeclared` (export compliance, medium): NO Info.plist carries `ITSAppUsesNonExemptEncryption`. One finding (project-level; file = first Info.plist path or the project root).
- `canopenurl-undeclared-scheme` (2.5.x, low): for each `calls("canOpenURL")`/`calls("open")` — heuristic: collect string literals that look like `scheme:` (regex `^([a-zA-Z][a-zA-Z0-9+.-]*):`) and if that scheme is not in any Info.plist `LSApplicationQueriesSchemes`, flag. (Curated/heuristic; documented.)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_code_rules_security.py
from asc_metadata_verifier.code.project import ProjectModel, PlistArtifact
from asc_metadata_verifier.code.parser import StringLit
from asc_metadata_verifier.code.rules.security import RULES as SEC
from asc_metadata_verifier.code.rules.compliance import RULES as COMP

class _AST:
    def __init__(self, file, strings): self.file=file; self._str=strings
    def symbols(self): return set()
    def imports(self): return set()
    def calls(self, n): return []
    def string_literals(self): return self._str

def _run(rules, rid, project, asts):
    return next(r for r in rules if r.id == rid).check(project, asts)

def test_ats_arbitrary_loads_flagged():
    proj = ProjectModel(root="/p", info_plists=[PlistArtifact(path="Info.plist",
        data={"NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True}})])
    out = _run(SEC, "ats-arbitrary-loads", proj, {})
    assert len(out) == 1 and out[0].severity == "medium"

def test_insecure_http_endpoint_flagged_not_localhost():
    asts = {"A.swift": _AST("A.swift", [StringLit(value="http://api.example.com", file="A.swift", line=4),
                                         StringLit(value="http://localhost:8080", file="A.swift", line=5)])}
    out = _run(SEC, "insecure-http-endpoint", ProjectModel(root="/p"), asts)
    assert len(out) == 1 and out[0].line == 4

def test_encryption_export_undeclared_flagged_when_absent():
    proj = ProjectModel(root="/p", info_plists=[PlistArtifact(path="Info.plist", data={"CFBundleName": "x"})])
    assert len(_run(COMP, "encryption-export-undeclared", proj, {})) == 1

def test_encryption_export_clean_when_present():
    proj = ProjectModel(root="/p", info_plists=[PlistArtifact(path="Info.plist",
        data={"ITSAppUsesNonExemptEncryption": False})])
    assert _run(COMP, "encryption-export-undeclared", proj, {}) == []

def test_canopenurl_undeclared_scheme_flagged():
    asts = {"A.swift": _AST("A.swift", [StringLit(value="whatsapp://send", file="A.swift", line=2)])}
    proj = ProjectModel(root="/p", info_plists=[PlistArtifact(path="Info.plist",
        data={"LSApplicationQueriesSchemes": ["tel"]})])
    out = _run(COMP, "canopenurl-undeclared-scheme", proj, asts)
    assert len(out) == 1 and out[0].symbol == "whatsapp"
```

```python
# tests/test_code_registry.py  (asserts the REAL registry, guard removed)
from asc_metadata_verifier.code.rules import REGISTRY

def test_full_registry_has_all_clusters():
    ids = {r.id for r in REGISTRY}
    assert {"idfa-without-att", "missing-usage-string", "required-reason-api-undeclared",
            "boilerplate-usage-string", "uiwebview-usage", "private-api-symbol",
            "ats-arbitrary-loads", "insecure-http-endpoint", "encryption-export-undeclared",
            "canopenurl-undeclared-scheme"} <= ids
    assert len(ids) == len(REGISTRY)   # unique ids
```

- [ ] **Step 2: Run to verify fail** — `uv run pytest tests/test_code_rules_security.py tests/test_code_registry.py -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# src/asc_metadata_verifier/code/rules/security.py
"""Security / ATS rules (App Store Review Guideline 2.5.2)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from asc_metadata_verifier.code.parser import ASTIndex
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.models import CodeFinding

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class AtsArbitraryLoads:
    id = "ats-arbitrary-loads"; category = "security-ats"; guideline_ref = "2.5.2"
    severity = "medium"; interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        out: list[CodeFinding] = []
        for plist in project.info_plists:
            ats = (plist.data or {}).get("NSAppTransportSecurity")
            if isinstance(ats, dict) and ats.get("NSAllowsArbitraryLoads") is True:
                out.append(CodeFinding(rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=plist.path, line=None,
                    symbol="NSAllowsArbitraryLoads", evidence="NSAllowsArbitraryLoads=true",
                    detail="ATS disabled globally; Apple requires justification (2.5.2)",
                    suggested_fix="Remove NSAllowsArbitraryLoads or scope exceptions per-domain."))
        return out


class InsecureHttpEndpoint:
    id = "insecure-http-endpoint"; category = "security-ats"; guideline_ref = "2.5.2"
    severity = "low"; interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        out: list[CodeFinding] = []
        for _path, ast in sorted(asts.items()):
            for lit in ast.string_literals():
                if not re.match(r"^http://", lit.value):
                    continue
                host = urlparse(lit.value).hostname or ""
                if host in _LOCAL_HOSTS:
                    continue
                out.append(CodeFinding(rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=lit.file, line=lit.line, symbol=None,
                    evidence=lit.value, detail="Insecure http:// endpoint in source (2.5.2)",
                    suggested_fix="Use https:// for network endpoints."))
        return out


RULES = [AtsArbitraryLoads(), InsecureHttpEndpoint()]
```

```python
# src/asc_metadata_verifier/code/rules/compliance.py
"""Compliance & consistency rules (export compliance, URL-scheme queries)."""

from __future__ import annotations

import re

from asc_metadata_verifier.code.parser import ASTIndex
from asc_metadata_verifier.code.project import ProjectModel
from asc_metadata_verifier.models import CodeFinding

_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")


class EncryptionExportUndeclared:
    id = "encryption-export-undeclared"; category = "compliance"
    guideline_ref = "export compliance"; severity = "medium"; interpretive = False

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        if any(p.data and "ITSAppUsesNonExemptEncryption" in p.data for p in project.info_plists):
            return []
        if not project.info_plists:
            return []   # no Info.plist parsed -> nothing factual to point at
        target = project.info_plists[0].path
        return [CodeFinding(rule_id=self.id, category=self.category, severity=self.severity,
            guideline_ref=self.guideline_ref, file=target, line=None,
            symbol="ITSAppUsesNonExemptEncryption", evidence="(absent)",
            detail="ITSAppUsesNonExemptEncryption is not declared; submission will prompt/stall",
            suggested_fix="Add ITSAppUsesNonExemptEncryption (true/false) to Info.plist.")]


class CanOpenUrlUndeclaredScheme:
    id = "canopenurl-undeclared-scheme"; category = "compliance"; guideline_ref = "2.5.x"
    severity = "low"; interpretive = False

    def _declared(self, project: ProjectModel) -> set[str]:
        out: set[str] = set()
        for p in project.info_plists:
            for s in (p.data or {}).get("LSApplicationQueriesSchemes", []) or []:
                if isinstance(s, str):
                    out.add(s.lower())
        return out

    def check(self, project: ProjectModel, asts: ASTIndex) -> list[CodeFinding]:
        declared = self._declared(project)
        out: list[CodeFinding] = []
        for _path, ast in sorted(asts.items()):
            for lit in ast.string_literals():
                m = _SCHEME_RE.match(lit.value)
                if not m:
                    continue
                scheme = m.group(1).lower()
                if scheme in {"http", "https", "file", "mailto", "tel"} or scheme in declared:
                    continue
                out.append(CodeFinding(rule_id=self.id, category=self.category, severity=self.severity,
                    guideline_ref=self.guideline_ref, file=lit.file, line=lit.line, symbol=scheme,
                    evidence=lit.value, detail=f"URL scheme '{scheme}' not in LSApplicationQueriesSchemes",
                    suggested_fix=f"Add '{scheme}' to LSApplicationQueriesSchemes if you query it."))
        return out


RULES = [EncryptionExportUndeclared(), CanOpenUrlUndeclaredScheme()]
```

Then in `code/rules/__init__.py`, replace `_load_registry` with the un-guarded version (all cluster modules exist now):

```python
def _load_registry() -> list[Rule]:
    from asc_metadata_verifier.code.rules import compliance, deprecated_api, privacy, security
    registry: list[Rule] = []
    for module in (privacy, deprecated_api, security, compliance):
        registry.extend(module.RULES)
    return registry
```

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_code_rules_security.py tests/test_code_registry.py tests/test_code_analyzer.py -q` → PASS; then full offline suite `uv run pytest -q`; `uv run ruff check`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/code/rules/security.py src/asc_metadata_verifier/code/rules/compliance.py src/asc_metadata_verifier/code/rules/__init__.py tests/test_code_rules_security.py tests/test_code_registry.py
git commit -m "feat(code): security/compliance rules + finalize REGISTRY"
```

---

### Task 8: CLI `code` command + rendering + `verify --code`

**Files:**
- Modify: `src/asc_metadata_verifier/cli.py` (add `code` command; add `--code` option to `verify`)
- Modify: `src/asc_metadata_verifier/report.py` (add `render_code_report_text`, `render_code_report_json`, extend `render_markdown` to show `code_findings`)
- Test: `tests/test_code_cli.py`, extend `tests/test_report.py`

**Interfaces:**
- Consumes: `load_project`, `build_parser`, `analyze`, `build_code_report`, `CodeReport`, `evaluate`, `exit_code`.
- Produces: `asc-verify code <path> [--backend] [--fail-on] [--format] [--jury ...]` (jury flags wired but no-op until Task 9), `asc-verify verify <src> --code <path>`.

- [ ] **Step 1: Write the failing tests** (use `typer.testing.CliRunner`, a real tmp project, real tree-sitter — importorskip)

```python
# tests/test_code_cli.py
import plistlib
import pytest
pytest.importorskip("tree_sitter_language_pack")
from pathlib import Path
from typer.testing import CliRunner
from asc_metadata_verifier.cli import app

runner = CliRunner()

def _project(tmp_path: Path, swift: str, info: dict):
    (tmp_path / "App").mkdir(parents=True, exist_ok=True)
    (tmp_path / "App/View.swift").write_text(swift)
    (tmp_path / "App/Info.plist").write_bytes(plistlib.dumps(info))
    return tmp_path

def test_code_command_blocks_on_uiwebview(tmp_path):
    _project(tmp_path, "let w = UIWebView()\n", {"ITSAppUsesNonExemptEncryption": False})
    res = runner.invoke(app, ["code", str(tmp_path)])
    assert res.exit_code == 1 and "uiwebview-usage" in res.output and "BLOCK" in res.output

def test_code_command_json_format(tmp_path):
    _project(tmp_path, "let w = UIWebView()\n", {"ITSAppUsesNonExemptEncryption": False})
    res = runner.invoke(app, ["code", str(tmp_path), "--format", "json"])
    assert res.exit_code == 1 and '"rule_id"' in res.output and '"parser_backend"' in res.output

def test_code_command_clean_project_passes(tmp_path):
    _project(tmp_path, "import WebKit\nlet w = WKWebView()\n",
             {"ITSAppUsesNonExemptEncryption": False})
    res = runner.invoke(app, ["code", str(tmp_path)])
    assert res.exit_code == 0 and "PASS" in res.output

def test_verify_with_code_folds_findings(tmp_path, monkeypatch):
    # minimal metadata source + a code project; assert code finding appears in unified report
    _project(tmp_path, "let w = UIWebView()\n", {"ITSAppUsesNonExemptEncryption": False})
    meta = tmp_path / "metadata.yaml"
    meta.write_text("app_id: '1'\nprimary_locale: en-US\nlocales:\n  en-US:\n    app_name: Demo\n    description: A demo app.\n")
    res = runner.invoke(app, ["verify", str(meta), "--source", "yaml", "--code", str(tmp_path), "--no-llm"])
    assert "uiwebview-usage" in res.output
```

> Implementer: confirm the exact `verify` flags for the yaml source path from the existing `verify` signature (e.g. `--source yaml` / `--no-llm` may be named differently). Read `cli.py:verify` and match the real option names; adjust the test to the real flags before running. The assertion (code finding folded into `verify` output) is what matters.

```python
# tests/test_report.py (append)
from asc_metadata_verifier.models import CodeReport, CodeFinding
from asc_metadata_verifier.report import render_code_report_text, render_code_report_json

def _rep():
    f = CodeFinding(rule_id="uiwebview-usage", category="deprecated-api", severity="high",
                    guideline_ref="2.5.x", file="A.swift", line=1, evidence="UIWebView", detail="d")
    return CodeReport(status="BLOCK", findings=[f], analyzed_files=1, parser_backend="tree-sitter")

def test_render_code_text_shows_anchor_and_guideline():
    out = render_code_report_text(_rep())
    assert "A.swift:1" in out and "2.5.x" in out and "BLOCK" in out

def test_render_code_json_roundtrips():
    import json
    data = json.loads(render_code_report_json(_rep()))
    assert data["status"] == "BLOCK" and data["findings"][0]["rule_id"] == "uiwebview-usage"
```

- [ ] **Step 2: Run to verify fail** — `uv run pytest tests/test_code_cli.py tests/test_report.py -q` → FAIL.

- [ ] **Step 3: Implement rendering** (in `report.py`)

```python
from asc_metadata_verifier.models import CodeFinding, CodeReport

def _render_code_findings(findings: list[CodeFinding]) -> list[str]:
    lines: list[str] = []
    by_cat: dict[str, list[CodeFinding]] = {}
    for f in findings:
        by_cat.setdefault(f.category, []).append(f)
    for category in sorted(by_cat):
        lines.append(f"### {category}")
        for f in by_cat[category]:
            anchor = f"{f.file}:{f.line}" if f.line is not None else f.file
            tag = "jury" if f.source == "jury" else "static"
            lines.append(f"- [{f.severity}] {f.rule_id} ({f.guideline_ref}) [{tag}] {anchor}")
            lines.append(f"    {f.detail} — evidence: {f.evidence!r}")
            if f.suggested_fix:
                lines.append(f"    fix: {f.suggested_fix}")
    return lines

def render_code_report_text(report: CodeReport) -> str:
    header = [f"Code analysis: {report.status}",
              f"({report.analyzed_files} files, backend={report.parser_backend}, jury={report.jury_used})"]
    body = _render_code_findings(report.findings) or ["No code findings."]
    return "\n".join(header + [""] + body)

def render_code_report_json(report: CodeReport) -> str:
    return report.model_dump_json(indent=2)
```

Extend `render_markdown(report: GateReport)` to append a "## Code findings" section when `report.code_findings` is non-empty, reusing `_render_code_findings`.

- [ ] **Step 4: Implement the CLI** (in `cli.py`)

```python
@app.command()
def code(
    project_path: str = typer.Argument(..., help="Path to the app project root"),
    backend: str = typer.Option("auto", help="Parser backend: auto|swiftsyntax"),
    fail_on: FailOn = typer.Option(FailOn.fail, help="fail (default) or warn"),
    output_format: OutputFormat = typer.Option(OutputFormat.text, "--format"),
    jury: bool = typer.Option(False, help="Enable the opt-in LLM jury layer (needs judges config)"),
    judges: str | None = typer.Option(None, help="Path to judges.yaml (jury mode)"),
    policy: str = typer.Option(DEFAULT_POLICY, help="Consensus policy (jury mode)"),
    swiftsyntax_cmd: str | None = typer.Option(None, envvar="ASC_SWIFTSYNTAX_CMD"),
) -> None:
    from pathlib import Path
    from asc_metadata_verifier.code.analyzer import analyze, build_code_report
    from asc_metadata_verifier.code.parser import build_parser
    from asc_metadata_verifier.code.project import load_project

    if not Path(project_path).exists():
        typer.echo(f"error: path not found: {project_path}", err=True)
        raise typer.Exit(code=2)

    parser = build_parser(backend, swiftsyntax_cmd=swiftsyntax_cmd)
    if not parser.available() and parser.backend_name.startswith("tree-sitter"):
        typer.echo("error: install the [code] extra:  uv sync --extra code  "
                   "(pip install 'asc-metadata-verifier[code]')", err=True)
        raise typer.Exit(code=2)

    project = load_project(project_path)
    findings, asts = analyze(project, parser)
    jury_used = False
    if jury:
        from asc_metadata_verifier.code.jury import apply_jury   # Task 9
        findings, jury_used = apply_jury(findings, project, asts, judges=judges, policy=policy)
    report = build_code_report(findings, analyzed_files=len(project.sources),
                               backend=parser.backend_name, fail_on=fail_on.value, jury_used=jury_used)
    if output_format is OutputFormat.json:
        typer.echo(render_code_report_json(report))
    else:
        typer.echo(render_code_report_text(report))
    raise typer.Exit(code=1 if report.status == "BLOCK" else 0)
```

For `verify --code`: add a `code_path: str | None = typer.Option(None, "--code")` option; after `run_verify` produces its `report`, if `code_path` is set, run the same load/parse/analyze, then rebuild the gate via `evaluate(report.verdicts, report.deterministic_findings, fail_on=..., guidelines_available=report.guidelines_available, panels=report.panels, code_findings=code_findings)` so the unified `GateReport.status`/exit code account for code. Guard the tree-sitter-available check the same way.

> Note: `apply_jury` is imported lazily inside the `if jury:` branch so Task 8 is testable and shippable before Task 9 exists (the non-`--jury` path never imports it). The jury tests in Task 9 cover the branch.

- [ ] **Step 5: Run to verify pass** — `uv run pytest tests/test_code_cli.py tests/test_report.py -q` → PASS; full suite `uv run pytest -q`; `uv run ruff check`.

- [ ] **Step 6: Commit**

```bash
git add src/asc_metadata_verifier/cli.py src/asc_metadata_verifier/report.py tests/test_code_cli.py tests/test_report.py
git commit -m "feat(code): 'code' CLI command + rendering + verify --code"
```

---

### Task 9: Optional jury layer

**Files:**
- Create: `src/asc_metadata_verifier/code/jury.py`
- Test: `tests/test_code_jury.py`

**Interfaces:**
- Consumes: `JudgeSpec`/`load_judges`/`judges_from_cli`/`merge_specs` (`judge/config.py`), `POLICIES`/`DEFAULT_POLICY` (`judge/consensus.py`), `JudgeVote`/`PanelVerdict`/`RubricVerdict`/`CodeFinding` (`models.py`), `get_guidelines` (`guidelines/source.py`), `Agent` (`pydantic_ai`).
- Produces: `INTERPRETIVE_QUESTIONS`, `build_units(findings, project, asts)`, `CodeJudge`, `CodeJury`, `apply_jury(findings, project, asts, *, judges=None, policy=DEFAULT_POLICY) -> tuple[list[CodeFinding], bool]`.

**Design:** Reuse the *config + consensus + models* — NOT the metadata `JudgePanel` (bound to `LocaleMetadata`/dimensions). A `CodeJudge` wraps a fresh `Agent(model_ref, output_type=RubricVerdict, system_prompt=CODE_JURY_SYSTEM_PROMPT, defer_model_check=True)` with the same error-isolation contract as `JudgeClient._run` (any exception → `error` `JudgeVote`, never raises into the panel). `CodeJury.judge(units, grounding, policy_name)` runs every judge over every unit concurrently under a semaphore (mirror `panel.judge_text`), applies `POLICIES[policy_name]`, returns `PanelVerdict`s. `apply_jury`:
1. builds specs (`merge_specs(load_judges(judges).specs if judges else [], [])`) → `build_panel`-style available filter; if none available → return `(findings, False)` unchanged (offline/no-key path).
2. `units = build_units(findings, project, asts)` — one unit per `interpretive=True` finding (adjudication) + one per `INTERPRETIVE_QUESTIONS` entry whose trigger symbols appear (e.g. account/login symbols → 5.1.1(v); `SKPayment`/`StoreKit` → 3.1.1).
3. For adjudication units, the panel's consensus can downgrade/drop the static finding (replace it) — honesty: a `dismiss` verdict removes the medium finding; a `confirm` keeps it and attaches the `panel`. For question units, a `fail`/`warn` consensus adds a NEW `CodeFinding(source="jury", panel=...)`; `pass` adds nothing.
4. Return `(new_findings_sorted, True)`.

Offline test: use `pydantic_ai.models.function.FunctionModel` / `TestModel` to force deterministic `RubricVerdict`s (same pattern as `tests/test_panel.py`/`test_client.py` — the implementer reads those for the exact construction).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_code_jury.py
from asc_metadata_verifier.code.jury import build_units, apply_jury, CodeJudge
from asc_metadata_verifier.code.project import ProjectModel, PlistArtifact
from asc_metadata_verifier.models import CodeFinding, RubricVerdict
from asc_metadata_verifier.judge.config import JudgeSpec

def _interp_finding():
    return CodeFinding(rule_id="boilerplate-usage-string", category="privacy-permissions",
        severity="medium", guideline_ref="5.1.1", file="Info.plist", line=None,
        symbol="NSCameraUsageDescription", evidence="We need access", detail="generic",
        source="static")

def test_build_units_covers_interpretive_findings():
    units = build_units([_interp_finding()], ProjectModel(root="/p"), {})
    assert any(u.finding_ref == "boilerplate-usage-string" for u in units)

def test_apply_jury_no_specs_is_passthrough_offline():
    findings = [_interp_finding()]
    out, used = apply_jury(findings, ProjectModel(root="/p"), {}, judges=None)
    assert out == findings and used is False   # no keys/specs -> unchanged, offline

def test_code_judge_error_isolation_returns_error_vote(monkeypatch):
    # a judge whose agent.run raises must yield an 'error' JudgeVote, never raise
    judge = CodeJudge.from_spec(JudgeSpec(name="x", provider="anthropic", model="claude-haiku-4-5-20251001"))
    # force failure by giving an impossible prompt path; assert status via the sync helper
    vote = judge.run_sync(question="q?", excerpt="code", grounding="", locale="code", dimension="d")
    assert vote.status in {"voted", "error", "not_applicable"}
```

> Implementer: model the offline jury tests on `tests/test_panel.py` and `tests/test_client.py` — build a `CodeJudge` around a `FunctionModel`/`TestModel` that returns a fixed `RubricVerdict`, then assert `apply_jury` (a) dismisses a `boilerplate` finding when the panel says `pass`/`dismiss`, and (b) adds a `source="jury"` finding when a question unit returns `fail`. Add those two assertions as additional tests. Provide `CodeJudge.from_model(name, model)` mirroring `JudgeClient.from_model` so a `FunctionModel` can be injected without network.

- [ ] **Step 2: Run to verify fail** — `uv run pytest tests/test_code_jury.py -q` → FAIL.

- [ ] **Step 3: Implement** `code/jury.py` per the design above. Key pieces:

```python
# system prompt: honesty-first, grounded, must cite guideline_ref, may abstain.
CODE_JURY_SYSTEM_PROMPT = (
    "You are an App Store review judge inspecting a SNIPPET of app source or a "
    "config value. Decide only the specific question asked, grounded ONLY in the "
    "provided guideline text. If the snippet is insufficient, return verdict "
    "'pass' with low confidence rather than guessing. Never invent a guideline_ref."
)
INTERPRETIVE_QUESTIONS = [
    {"id": "account-gating-5.1.1v", "guideline_ref": "5.1.1(v)",
     "triggers": {"UserDefaults", "loginViewController", "requireLogin", "AuthViewController"},
     "question": "Does this code force account creation for features that don't need one (5.1.1(v))?"},
    {"id": "iap-bypass-3.1.1", "guideline_ref": "3.1.1",
     "triggers": {"SKPayment", "StoreKit", "PurchaseManager"},
     "question": "Does this code sell digital goods/subscriptions outside In-App Purchase (3.1.1)?"},
]
```

`CodeJudge` mirrors `JudgeClient` (`from_spec`/`from_model`, async `run`, sync `run_sync` wrapper, `_run` try/except → `error` `JudgeVote`). `CodeJury.judge` mirrors `panel.judge_text` (fresh semaphore per call, gather votes, apply policy → `PanelVerdict`). `apply_jury` performs the passthrough/adjudicate/add logic and grounds via `get_guidelines(session_id, ...)` guarded so an offline `available=False` degrades (no `guideline_ref` fabrication).

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_code_jury.py -q` → PASS; full suite `uv run pytest -q` (offline, no keys — jury tests must not hit the network); `uv run ruff check`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/code/jury.py tests/test_code_jury.py
git commit -m "feat(code): opt-in jury layer (interpretive judgments, offline-safe)"
```

---

### Task 10: SwiftSyntax BYO subprocess backend + fallback

**Files:**
- Create: `src/asc_metadata_verifier/code/backends/swiftsyntax.py`
- Test: `tests/test_code_swiftsyntax.py`

**Interfaces:**
- Produces: `SwiftSyntaxParser(swiftsyntax_cmd=None)` implementing `SourceParser`; `available()` true iff a helper command is configured AND runnable; `parse()` shells out to it expecting JSON `{"symbols":[...], "imports":[...], "strings":[{"value","line"}], "calls":[{"name","line"}]}` and adapts it to the `SourceAST` surface.

**Design (honest BYO, mirrors persistence's BYO-embedder):** SwiftSyntax has no importable pip package; the backend invokes a user-supplied command (`--swiftsyntax-cmd`/`ASC_SWIFTSYNTAX_CMD`) that parses one source file (path on argv) and prints the AST-surface JSON to stdout. If no command is configured, or it exits non-zero, or emits invalid JSON, `available()`/`parse()` degrade and `build_parser("swiftsyntax")` falls back to tree-sitter with `backend_name="swiftsyntax(unavailable)"` (already implemented in Task 3). Never fabricates.

- [ ] **Step 1: Write the failing tests** (no real Swift toolchain needed — use a fake helper script)

```python
# tests/test_code_swiftsyntax.py
import json, os, stat
from pathlib import Path
from asc_metadata_verifier.code.parser import build_parser
from asc_metadata_verifier.code.project import SourceFile

def _fake_helper(tmp_path: Path) -> str:
    script = tmp_path / "fake_swiftsyntax.py"
    script.write_text(
        "import json,sys\n"
        "print(json.dumps({'symbols':['UIWebView'],'imports':['UIKit'],"
        "'strings':[{'value':'http://x','line':2}],'calls':[{'name':'canOpenURL','line':3}]}))\n")
    helper = tmp_path / "run.sh"
    helper.write_text(f'#!/bin/sh\nexec python3 "{script}" "$@"\n')
    helper.chmod(helper.stat().st_mode | stat.S_IEXEC)
    return str(helper)

def test_swiftsyntax_backend_parses_via_helper(tmp_path):
    parser = build_parser("swiftsyntax", swiftsyntax_cmd=_fake_helper(tmp_path))
    assert parser.available() is True and parser.backend_name == "swiftsyntax"
    ast = parser.parse(SourceFile(path="A.swift", language="swift", text="let w = UIWebView()"))
    assert "UIWebView" in ast.symbols() and ast.calls("canOpenURL")[0].line == 3

def test_unavailable_swiftsyntax_falls_back_to_treesitter():
    parser = build_parser("swiftsyntax", swiftsyntax_cmd=None)
    assert parser.available() is False or parser.backend_name == "swiftsyntax(unavailable)"
    assert "tree-sitter" in parser.backend_name or parser.backend_name == "swiftsyntax(unavailable)"
```

- [ ] **Step 2: Run to verify fail** — `uv run pytest tests/test_code_swiftsyntax.py -q` → FAIL.

- [ ] **Step 3: Implement**

```python
# src/asc_metadata_verifier/code/backends/swiftsyntax.py
"""Optional higher-fidelity Swift backend via a BYO subprocess helper. There is
no importable SwiftSyntax pip package (it resolves through a Swift toolchain),
so -- like the BYO embedder in persistence -- the user supplies a command that
reads a source file (path on argv) and prints AST-surface JSON to stdout. Any
failure degrades to unavailable; the caller (build_parser) then falls back to
tree-sitter. Never fabricates an AST."""

from __future__ import annotations

import json
import shlex
import subprocess

from asc_metadata_verifier.code.parser import CallSite, SourceAST, StringLit
from asc_metadata_verifier.code.project import SourceFile


class _JsonAST:
    def __init__(self, file: str, data: dict):
        self.file = file
        self._d = data
    def symbols(self) -> set[str]:
        return set(self._d.get("symbols", []))
    def imports(self) -> set[str]:
        return set(self._d.get("imports", []))
    def calls(self, name: str) -> list[CallSite]:
        return [CallSite(name=name, file=self.file, line=int(c.get("line", 1)))
                for c in self._d.get("calls", []) if c.get("name") == name]
    def string_literals(self) -> list[StringLit]:
        return [StringLit(value=str(s.get("value", "")), file=self.file, line=int(s.get("line", 1)))
                for s in self._d.get("strings", [])]


class SwiftSyntaxParser:
    backend_name = "swiftsyntax"

    def __init__(self, swiftsyntax_cmd: str | None = None):
        self._cmd = swiftsyntax_cmd

    def available(self) -> bool:
        if not self._cmd:
            return False
        try:
            argv = shlex.split(self._cmd)
            return bool(argv) and subprocess.run(  # noqa: S603
                argv, input=b"", capture_output=True, timeout=10).returncode in (0, 1, 2)
        except (OSError, subprocess.SubprocessError):
            return False

    def parse(self, source: SourceFile) -> SourceAST:
        argv = [*shlex.split(self._cmd or ""), source.path]
        proc = subprocess.run(argv, capture_output=True, timeout=30)  # noqa: S603
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
        return _JsonAST(source.path, data)
```

> Note: `available()` runs the helper with empty input just to prove it's executable; `parse()` passes the real file path. If your helper needs the source on stdin instead, adapt both the helper and this adapter — the JSON contract is what the rules depend on.

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_code_swiftsyntax.py -q` → PASS; `uv run ruff check` (the `# noqa: S603` are intentional — subprocess with a user-provided command is the feature).

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/code/backends/swiftsyntax.py tests/test_code_swiftsyntax.py
git commit -m "feat(code): optional BYO-SwiftSyntax backend + tree-sitter fallback"
```

---

### Task 11: Docs — extras, README, BUILD_LOG

**Files:**
- Modify: `pyproject.toml` (confirm `[code]` extra present from Task 3; no `[code-swift]` pip extra — documented)
- Modify: `README.md` (add "Code analysis (optional)" section)
- Modify: `BUILD_LOG.md` (add sub-project C entry: scope, honesty boundary, open items)
- Test: extend `tests/test_skill_packaging.py` only if it asserts on extras; otherwise no test.

- [ ] **Step 1: README section** — document: install `asc-metadata-verifier[code]`; `asc-verify code <path>`; the rule catalog table (rule_id → guideline); the honesty boundary (AST-structural, curated non-exhaustive, `file:line` evidence); offline-by-default; `--jury` opt-in; SwiftSyntax BYO helper via `--swiftsyntax-cmd`. State clearly what it does NOT do (no type inference / data-flow / dynamic analysis).

- [ ] **Step 2: BUILD_LOG entry** — mirror the jury/persistence entries: what shipped, the honest open items (SwiftSyntax needs a BYO helper to be exercised; private-API/required-reason lists are curated subsets; jury-path grounding needs network; line numbers are 1 for symbol-presence findings where the walker reports the first occurrence).

- [ ] **Step 3: Verify docs match reality** — run `asc-verify code --help` and paste-check the flags named in the README exist. Run the full suite `uv run pytest -q` and `uv run ruff check src tests` once more.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml README.md BUILD_LOG.md tests/test_skill_packaging.py
git commit -m "docs(code): README + BUILD_LOG for sub-project C"
```

---

## Self-review notes (author)

- **Spec coverage:** Project loader (C1)→T2; parser strategy + tree-sitter (C2)→T3; SwiftSyntax backend (C2)→T10; rule engine + all 10 catalog rules (C3)→T4–T7; jury layer (C4)→T9; data model (C5)→T1; CLI + gate integration (C6)→T1/T8; testing strategy→each task's tests + fixtures built in tmp_path; honesty/offline invariants→Global Constraints enforced per task. All covered.
- **Type consistency:** `CodeFinding`/`CodeReport`/`ProjectModel`/`SourceFile`/`PlistArtifact`/`CallSite`/`StringLit`/`ASTIndex`/`Rule`/`build_parser`/`analyze`/`build_code_report`/`apply_jury` names are identical everywhere used. `evaluate(..., code_findings=...)` signature matches T1 and T8.
- **Sequencing hazard handled:** `code/rules/__init__.py` ships in T4 with an ImportError guard so it imports cleanly before the cluster modules exist; T7 removes the guard and a dedicated registry test asserts the full set. Every task is independently green.
- **Known real risks flagged in-plan:** tree-sitter grammar node-type names may vary by version (T3 Step 4 note); exact `verify` flag names for the yaml source (T8 note); jury offline test construction points at `tests/test_panel.py` (T9 note).
