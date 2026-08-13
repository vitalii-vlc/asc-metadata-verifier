# HTML Report Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an additive `--format html` output that renders a `GateReport` (and, via the same renderer, `CodeReport`/`PagesReport`) as a self-contained, offline, deterministic HTML report matching the approved template — with per-subsystem and master copy-ready fix prompts.

**Architecture:** A new pure string-building module `html_report.py` exposes `render_html(GateReport, …) -> str`. A `_Row` dataclass normalizes the four finding types into one shape grouped by Metadata/Code/Pages (reusing the gate's existing level classifiers). The CLI adds `html` to `OutputFormat`; `code`/`pages --format html` wrap their findings into a `GateReport` via `evaluate(...)` so one renderer serves all three commands. CSS/JS are ported verbatim from the approved template.

**Tech Stack:** Python 3.11+ (uv) · stdlib `html.escape` · pydantic v2 (existing models) · typer. **No new dependencies.**

## Global Constraints

- **Additive / backward compatible (hard):** `--format md` (default) and `--format json` are byte-unchanged; the full existing suite passes.
- **Self-contained & offline (hard):** rendered HTML inlines all CSS/JS, uses system-font stacks only (no external fonts/CDN/network), embeds no remote assets; opens from `file://`.
- **Deterministic (hard):** `render_html` does no time/randomness (timestamp passed by the caller); identical `GateReport` + context → byte-identical HTML.
- **Never fabricate (honesty):** no invented before/after diffs — evidence-only (a red line of the actual offending text) + the finding's own prose fix; a green "+" line only when a finding carries a concrete replacement (none do — dormant seam). Fix prompts built only from real fields. `guideline_ref == None` → `n/a`. Jury panels show real votes.
- **Escape everything model-derived** via `html.escape`.
- **Zero new core deps.**

### Canonical CSS/JS source

`_CSS` and `_JS` are ported **verbatim** from the approved template at
`/private/tmp/claude-501/-Users-vitalii-Projects-ObsidianVaults-VitaliiDevelopment/435598dd-3022-4202-b93d-c8290c809a50/scratchpad/asc-report-template.html`
— `_CSS` = the exact contents between `<style>` and `</style>`; `_JS` = the exact
contents between `<script>` and `</script>`. The static sample markup in that file
is the reference for every helper's output structure; the helpers below emit the
same markup with model data substituted (and escaped).

### Resolved facts

- A jury run populates **both** `report.panels` and `report.verdicts`
  (`verdicts = [p.consensus for p in panels]`), so metadata rows come from
  `panels` when non-empty, else `verdicts` — never both (avoids double-listing).
- `cli.py` already imports `from datetime import UTC, datetime`; the timestamp is
  stamped there, not in the renderer.
- `gate.py` exposes `_verdict_level`, `_finding_level`, `_DETERMINISTIC_LEVEL`,
  `_code_level`, `_page_level` (all return `"block"|"warn"|"none"`; code/page never
  `"none"`). `OutputFormat` in `cli.py` currently has `md` and `json`.

---

## Shared interfaces (defined once)

```python
# html_report.py
@dataclass(frozen=True)
class _Row:
    subsystem: str          # "Metadata" | "Code" | "Pages"
    level: str              # "block" | "warn"
    sev_label: str          # "Block" | "Warn"
    rule_label: str
    guideline_ref: str | None
    anchor: str
    source: str             # "static" | "jury"
    rationale: str
    evidence: str | None
    suggested_fix: str | None
    panel: PanelVerdict | None

def _rows_from_report(report: GateReport) -> list[_Row]: ...
def render_html(report: GateReport, *, app_id: str = "—", locale: str = "—",
                generated_at: str = "—", fail_on: str = "fail") -> str: ...

# cli.py: OutputFormat gains  html = "html"
```

---

### Task 1: The `_Row` normalizer

**Files:**
- Create: `src/asc_metadata_verifier/html_report.py`
- Test: `tests/test_html_report_rows.py`

**Interfaces:**
- Consumes: `GateReport`, `PanelVerdict`, `RubricVerdict`, `DeterministicFinding`, `CodeFinding`, `PageFinding`; `gate._verdict_level`/`_finding_level`/`_code_level`/`_page_level`.
- Produces: `_Row`, `_rows_from_report(report)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_html_report_rows.py
from asc_metadata_verifier.html_report import _rows_from_report
from asc_metadata_verifier.models import (
    AppMetadata, CodeFinding, DeterministicFinding, GateReport, JudgeVote,
    PageFinding, PanelVerdict, RubricVerdict,
)

def _rv(dimension="other_platform_mentions", verdict="fail", severity="high",
        guideline_ref="2.3.1", field="promotional_text", locale="en-US"):
    return RubricVerdict(dimension=dimension, verdict=verdict, severity=severity,
        confidence=0.9, rationale="mentions Android", offending_quote="Also on Android",
        guideline_ref=guideline_ref, suggested_fix="Remove it", locale=locale, field=field)

def test_metadata_prefers_panels_over_verdicts_no_double_count():
    v = _rv()
    panel = PanelVerdict(locale="en-US", dimension="other_platform_mentions",
        field="promotional_text", votes=[JudgeVote(judge="j", status="voted", verdict=v)],
        consensus=v, policy="majority_severe", agreement=1.0)
    # jury run: BOTH populated, verdicts == [consensus]
    report = GateReport(status="BLOCK", verdicts=[v], panels=[panel], guidelines_available=True)
    meta_rows = [r for r in _rows_from_report(report) if r.subsystem == "Metadata"]
    assert len(meta_rows) == 1 and meta_rows[0].source == "jury" and meta_rows[0].panel is panel

def test_single_judge_uses_verdicts():
    report = GateReport(status="BLOCK", verdicts=[_rv()], guidelines_available=True)
    rows = _rows_from_report(report)
    assert len(rows) == 1 and rows[0].source == "static" and rows[0].level == "block"

def test_pass_verdicts_excluded():
    report = GateReport(status="PASS", verdicts=[_rv(verdict="pass", severity="low")],
                        guidelines_available=True)
    assert _rows_from_report(report) == []

def test_deterministic_and_code_and_pages_rows():
    report = GateReport(status="BLOCK", guidelines_available=True,
        deterministic_findings=[DeterministicFinding(locale="en-US", field="app_name",
            kind="over_limit", detail="too long")],
        code_findings=[CodeFinding(rule_id="uiwebview-usage", category="deprecated-api",
            severity="high", guideline_ref="2.5.x", file="A.swift", line=42,
            evidence="UIWebView", detail="deprecated")],
        page_findings=[PageFinding(page_type="support", url="https://x/s",
            rule_id="page-unreachable", category="support", severity="high",
            guideline_ref="5.1.1", evidence="HTTP 404", detail="did not load")])
    rows = {r.subsystem: r for r in _rows_from_report(report)}
    assert rows["Metadata"].rule_label == "over_limit" and rows["Metadata"].level == "block"
    assert rows["Code"].anchor == "A.swift:42" and rows["Code"].evidence == "UIWebView"
    assert rows["Pages"].anchor == "support · https://x/s" and rows["Pages"].level == "block"
```

- [ ] **Step 2: Run tests to verify they fail** — `uv run pytest tests/test_html_report_rows.py -q` → FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement**

```python
# src/asc_metadata_verifier/html_report.py
"""Render a GateReport as a self-contained, offline, deterministic HTML report.

Pure string building (like report.py); no time/randomness (the caller passes
`generated_at`). Honesty: evidence-only (no fabricated before/after), prompts
from real fields, everything model-derived is html.escape'd, guideline_ref None
-> "n/a", jury panels show real votes. CSS/JS ported verbatim from the approved
template."""

from __future__ import annotations

from dataclasses import dataclass

from asc_metadata_verifier.gate import (
    _code_level,
    _finding_level,
    _page_level,
    _verdict_level,
)
from asc_metadata_verifier.models import GateReport, PanelVerdict

_SEV_LABEL = {"block": "Block", "warn": "Warn"}


@dataclass(frozen=True)
class _Row:
    subsystem: str
    level: str
    sev_label: str
    rule_label: str
    guideline_ref: str | None
    anchor: str
    source: str
    rationale: str
    evidence: str | None
    suggested_fix: str | None
    panel: PanelVerdict | None


def _rows_from_report(report: GateReport) -> list[_Row]:
    rows: list[_Row] = []
    if report.panels:
        for p in report.panels:
            v = p.consensus
            level = _verdict_level(v)
            if level == "none":
                continue
            rows.append(_Row("Metadata", level, _SEV_LABEL[level], v.dimension, v.guideline_ref,
                             f"{v.locale} · {v.field}", "jury", v.rationale,
                             v.offending_quote, v.suggested_fix, p))
    else:
        for v in report.verdicts:
            level = _verdict_level(v)
            if level == "none":
                continue
            rows.append(_Row("Metadata", level, _SEV_LABEL[level], v.dimension, v.guideline_ref,
                             f"{v.locale} · {v.field}", "static", v.rationale,
                             v.offending_quote, v.suggested_fix, None))
    for f in report.deterministic_findings:
        level = _finding_level(f)
        if level == "none":
            continue
        rows.append(_Row("Metadata", level, _SEV_LABEL[level], f.kind, None,
                         f"{f.locale} · {f.field}", "static", f.detail, None, None, None))
    for f in report.code_findings:
        level = _code_level(f)
        anchor = f"{f.file}:{f.line}" if f.line is not None else f.file
        rows.append(_Row("Code", level, _SEV_LABEL[level], f.rule_id, f.guideline_ref, anchor,
                         f.source, f.detail, f.evidence, f.suggested_fix, f.panel))
    for f in report.page_findings:
        level = _page_level(f)
        rows.append(_Row("Pages", level, _SEV_LABEL[level], f.rule_id, f.guideline_ref,
                         f"{f.page_type} · {f.url}", f.source, f.detail, f.evidence,
                         f.suggested_fix, f.panel))
    return rows
```

- [ ] **Step 4: Run tests to verify they pass** — `uv run pytest tests/test_html_report_rows.py -q` → PASS; `uv run ruff check src/asc_metadata_verifier/html_report.py tests/test_html_report_rows.py`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/html_report.py tests/test_html_report_rows.py
git commit -m "feat(html): _Row normalizer for the HTML report"
```

---

### Task 2: Page scaffold — CSS/JS + stamp, summary, controls, footer

**Files:**
- Modify: `src/asc_metadata_verifier/html_report.py` (add `_esc`, `_CSS`, `_JS`, `_verdict_stamp`, `_summary`, `_controls`, `_footer`, `render_html` with empty groups)
- Test: `tests/test_html_report_page.py`

**Interfaces:**
- Produces: `render_html(report, *, app_id, locale, generated_at, fail_on)`, `_esc`.
- `_group` is added in Task 3; until then `render_html` inserts no group markup (or `""`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_html_report_page.py
import re
from asc_metadata_verifier.html_report import render_html
from asc_metadata_verifier.models import CodeFinding, GateReport

def _report():
    return GateReport(status="BLOCK", guidelines_available=True,
        code_findings=[CodeFinding(rule_id="uiwebview-usage", category="deprecated-api",
            severity="high", guideline_ref="2.5.x", file="A.swift", line=42,
            evidence="UIWebView", detail="deprecated")])

def test_page_is_self_contained_and_has_stamp():
    html = render_html(_report(), app_id="123", locale="en-US", generated_at="2026-08-12 09:00 UTC")
    assert "<style>" in html and "<script>" in html
    assert "BLOCK" in html
    # no external assets: no CDN/font/remote links
    assert "fonts.googleapis" not in html and "cdn" not in html.lower()
    assert not re.search(r'(href|src)\s*=\s*["\']https?://', html)

def test_summary_counts_and_context():
    html = render_html(_report(), app_id="123", locale="en-US", generated_at="2026-08-12 09:00 UTC")
    assert "123" in html and "en-US" in html and "2026-08-12 09:00 UTC" in html

def test_render_is_deterministic():
    a = render_html(_report(), generated_at="t")
    b = render_html(_report(), generated_at="t")
    assert a == b
```

- [ ] **Step 2: Run to verify fail** — `uv run pytest tests/test_html_report_page.py -q` → FAIL (`ImportError: render_html`).

- [ ] **Step 3: Implement** — add to `html_report.py`:

```python
from html import escape as _escape


def _esc(text) -> str:
    return _escape(str(text), quote=True)
```

Then define `_CSS = """…"""` and `_JS = """…"""` by copying the exact text between
`<style>`/`</style>` and `<script>`/`</script>` from the canonical template file
(see Global Constraints → Canonical CSS/JS source). Then the shell helpers, whose
markup mirrors the template's masthead/summary/controls/footer:

```python
_STAMP_EXIT = {"PASS": "safe to submit · exit 0", "WARN": "review before submit · exit 0",
               "BLOCK": "do not submit · exit 1"}
_STAMP_CLASS = {"PASS": "sev-pass", "WARN": "sev-warn", "BLOCK": ""}  # card default is block-colored

def _counts(rows):
    blocking = sum(1 for r in rows if r.level == "block")
    warnings = sum(1 for r in rows if r.level == "warn")
    subsystems = len({r.subsystem for r in rows})
    return blocking, warnings, subsystems

def _passed(report):
    if report.panels:
        return sum(1 for p in report.panels if p.consensus.verdict == "pass")
    return sum(1 for v in report.verdicts if v.verdict == "pass")

def _verdict_stamp(status): ...      # returns the .stamp block, severity class by status
def _summary(rows, passed): ...      # stat cards (Blocking/Warnings/Passed/Subsystems) + .sevbar
def _controls(blocking, warnings, total): ...  # filter chips + skip-to-fix + theme toggle
def _footer(report, app_id, locale, generated_at): ...  # honest caveats + generated-by line

def render_html(report, *, app_id="—", locale="—", generated_at="—", fail_on="fail"):
    rows = _rows_from_report(report)
    blocking, warnings, subsystems = _counts(rows)
    passed = _passed(report)
    total = blocking + warnings
    groups_html = _render_groups(rows)   # Task 3; until then define _render_groups -> ""
    parts = [
        "<style>", _CSS, "</style>",
        '<div class="wrap">',
        _masthead(report, app_id, locale, generated_at, fail_on),
        _summary(rows, passed),
        _controls(blocking, warnings, total),
        groups_html,
        _footer(report, app_id, locale, generated_at),
        "</div>",
        "<script>", _JS, "</script>",
    ]
    return "\n".join(parts)
```

Implement `_masthead` (eyebrow + subject block with escaped `app_id`/`locale`/
`generated_at`/`fail_on` + `_verdict_stamp(report.status)`), and a temporary
`def _render_groups(rows): return ""` (Task 3 replaces it). The stat card for
"Passed" shows the count and, when `passed == 0`, add the note text
`no LLM verdicts` beside it. Use `_esc(...)` on every interpolated model/context value.

> Implementer: transcribe `_CSS`/`_JS` exactly; verify the page renders by
> eyeballing `render_html(_report())` once. The `re.search` test guards against
> any external `http(s)://` href/src slipping in — the sample URLs in findings are
> plain text inside `_esc`, not attributes, so they don't match.

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_html_report_page.py -q` → PASS; `uv run ruff check`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/html_report.py tests/test_html_report_page.py
git commit -m "feat(html): page scaffold — CSS/JS + stamp/summary/controls/footer"
```

---

### Task 3: Finding cards — evidence, fix line, jury panel, groups

**Files:**
- Modify: `src/asc_metadata_verifier/html_report.py` (add `_finding_card`, `_evidence_block`, `_jury_panel`, `_group`; replace `_render_groups`)
- Test: `tests/test_html_report_findings.py`

**Interfaces:**
- Consumes: `_Row`, `_esc`.
- Produces: `_render_groups(rows)` emitting one `<section>` per non-empty subsystem in order Metadata → Code → Pages.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_html_report_findings.py
from asc_metadata_verifier.html_report import render_html
from asc_metadata_verifier.models import (
    CodeFinding, GateReport, JudgeVote, PageFinding, PanelVerdict, RubricVerdict,
)

def _code(**kw):
    base = dict(rule_id="uiwebview-usage", category="deprecated-api", severity="high",
                guideline_ref="2.5.x", file="A.swift", line=42, evidence="UIWebView",
                detail="deprecated since 2020", suggested_fix="Use WKWebView")
    base.update(kw)
    return CodeFinding(**base)

def test_finding_renders_rule_guideline_anchor():
    html = render_html(GateReport(status="BLOCK", guidelines_available=True, code_findings=[_code()]))
    assert "uiwebview-usage" in html and "2.5.x" in html and "A.swift:42" in html and "WKWebView" in html

def test_evidence_is_escaped():
    html = render_html(GateReport(status="BLOCK", guidelines_available=True,
        code_findings=[_code(evidence="<script>alert(1)</script>")]))
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>alert(1)" not in html

def test_evidence_only_no_fabricated_addition_line():
    # a prose-only fix must not produce a green "+"/.add diff line
    html = render_html(GateReport(status="BLOCK", guidelines_available=True, code_findings=[_code()]))
    assert 'class="row add"' not in html

def test_none_guideline_renders_na():
    html = render_html(GateReport(status="BLOCK", guidelines_available=True,
        code_findings=[_code(guideline_ref=None)]))  # note: real code rules always set it; None exercises the path
    assert "n/a" in html

def test_jury_panel_shows_votes():
    v = RubricVerdict(dimension="other_platform_mentions", verdict="fail", severity="high",
        confidence=0.9, rationale="r", guideline_ref="2.3.1", locale="en-US", field="promotional_text")
    panel = PanelVerdict(locale="en-US", dimension="other_platform_mentions", field="promotional_text",
        votes=[JudgeVote(judge="claude-haiku", status="voted", verdict=v)],
        consensus=v, policy="majority_severe", agreement=1.0)
    html = render_html(GateReport(status="BLOCK", verdicts=[v], panels=[panel], guidelines_available=True))
    assert "claude-haiku" in html and "majority_severe" in html and "consensus" in html
```

- [ ] **Step 2: Run to verify fail** — `uv run pytest tests/test_html_report_findings.py -q` → FAIL (`guideline_ref=None` path / `add` assertion / jury markup absent because groups are empty).

- [ ] **Step 3: Implement** — replace the temporary `_render_groups` and add helpers. Markup mirrors the template's `.card` / `.diff` / `details.jury` (severity class `sev-warn`/`sev-pass` by level; `.card` default is block-colored):

```python
_SEV_ICON = {  # inline SVG per level, copied from the template's chips
    "block": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4">'
             '<polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/></svg>',
    "warn": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 '
            '1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/></svg>',
}
_GROUP_META = [
    ("Metadata", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                 'stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" '
                 'height="16" rx="2"/><path d="M7 8h10M7 12h6M7 16h8"/></svg>',
                 "App Store Connect text — judged against the live Review Guidelines."),
    ("Code", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="m16 18 4-4-4-4M8 6l-4 4 4 4M14 4l-4 16"/></svg>',
             "Deep AST analysis of the app project — symbols correlated against Info.plist & PrivacyInfo.xcprivacy."),
    ("Pages", '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
              'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/>'
              '<path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/></svg>',
              "Privacy / support / marketing URLs — reachability + privacy-policy↔code cross-reference."),
]

def _evidence_block(row):
    if not row.evidence:
        return ""
    return ('<div class="diff" aria-label="Offending value">'
            f'<div class="row del"><span class="g">-</span><span class="l">{_esc(row.evidence)}</span></div>'
            '</div>')

def _jury_panel(panel):
    if panel is None:
        return ""
    rows = []
    for vote in panel.votes:
        if vote.status == "voted" and vote.verdict is not None:
            vcls = vote.verdict.verdict  # pass|warn|fail
            detail = f"{_esc(vote.verdict.severity)} · conf {vote.verdict.confidence:.2f}"
            rows.append(f'<div class="vote"><span class="j">{_esc(vote.judge)}</span>'
                        f'<span class="v {vcls}">{_esc(vote.verdict.verdict)}</span>'
                        f'<span class="c">{detail}</span></div>')
        else:
            rows.append(f'<div class="vote"><span class="j">{_esc(vote.judge)}</span>'
                        f'<span class="v">{_esc(vote.status)}</span>'
                        f'<span class="c">{_esc(vote.error or "")}</span></div>')
    agr = "—" if panel.agreement is None else f"{panel.agreement:.2f}"
    cons = f'<div class="consensus"><span><b>consensus</b> {_esc(panel.consensus.verdict)} / ' \
           f'{_esc(panel.consensus.severity)}</span><span><b>agreement</b> {agr}</span>' \
           f'<span><b>policy</b> {_esc(panel.policy)}</span></div>'
    return ('<details class="jury"><summary><svg class="chev" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="m9 18 6-6-6-6"/></svg>Jury deliberation — consensus <b>'
            f'{_esc(panel.consensus.verdict)}</b> (policy: {_esc(panel.policy)})</summary>'
            f'<div class="votes">{"".join(rows)}{cons}</div></details>')

def _finding_card(row):
    card_cls = "card" if row.level == "block" else "card sev-warn"
    guideline = _esc(row.guideline_ref) if row.guideline_ref else "n/a"
    src = 'src jury' if row.source == "jury" else 'src'
    src_label = "jury" if row.source == "jury" else "static"
    fix = ""
    if row.suggested_fix:
        fix = ('<div class="fix"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
               'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/>'
               f'</svg><div><span class="k">Fix</span><br>{_esc(row.suggested_fix)}</div></div>')
    return (f'<article class="{card_cls}" data-sev="{row.level}">'
            f'<div class="fhead"><span class="sev">{_SEV_ICON[row.level]}{row.sev_label}</span>'
            f'<span class="rule">{_esc(row.rule_label)}</span>'
            f'<span class="pill">{guideline}</span>'
            f'<span class="anchor">{_esc(row.anchor)}</span>'
            f'<span class="spacer"></span><span class="{src}">{src_label}</span></div>'
            f'<p class="rationale">{_esc(row.rationale)}</p>'
            f'{_evidence_block(row)}{fix}{_jury_panel(row.panel)}</article>')

def _render_groups(rows):
    out = []
    for name, icon, sub in _GROUP_META:
        group_rows = [r for r in rows if r.subsystem == name]
        if not group_rows:
            continue
        cards = "".join(_finding_card(r) for r in group_rows)
        out.append(f'<section class="group" data-group><h2>{icon} {name} '
                   f'<span class="count">{len(group_rows)}</span></h2>'
                   f'<p class="gsub">{sub}</p><div class="cards">{cards}</div>'
                   f'{_fix_prompt(name, group_rows)}</section>')
    return "\n".join(out)
```

> Note: `_fix_prompt` is added in Task 4. To keep Task 3 independently green,
> define a temporary `def _fix_prompt(name, rows): return ""` now; Task 4 replaces it.
> The `pill` guideline pill has no `href` (it is not a link in the generator —
> avoids the external-link test and dead anchors); the template's `<a class="pill">`
> becomes `<span class="pill">`.

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_html_report_findings.py -q` → PASS; `uv run ruff check`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/html_report.py tests/test_html_report_findings.py
git commit -m "feat(html): finding cards + evidence + jury panels"
```

---

### Task 4: Fix prompts — per-section + master + skip-to-fix

**Files:**
- Modify: `src/asc_metadata_verifier/html_report.py` (replace `_fix_prompt`; add `_master_prompt`; wire master into `render_html` before the footer; ensure controls include skip-to-fix and master has `id="fix-all"`)
- Test: `tests/test_html_report_prompts.py`

**Interfaces:**
- Produces: `_fix_prompt(subsystem, rows)`, `_master_prompt(rows)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_html_report_prompts.py
from asc_metadata_verifier.html_report import render_html
from asc_metadata_verifier.models import CodeFinding, GateReport, PageFinding

def _report():
    return GateReport(status="BLOCK", guidelines_available=True,
        code_findings=[CodeFinding(rule_id="uiwebview-usage", category="deprecated-api",
            severity="high", guideline_ref="2.5.x", file="A.swift", line=42, evidence="UIWebView",
            detail="deprecated", suggested_fix="Replace UIWebView with WKWebView")],
        page_findings=[PageFinding(page_type="support", url="https://x/s", rule_id="page-unreachable",
            category="support", severity="high", guideline_ref="5.1.1", evidence="HTTP 404",
            detail="did not load", suggested_fix="Publish a live support page")])

def test_section_prompt_has_real_fields():
    html = render_html(_report())
    assert "[BLOCK] uiwebview-usage" in html and "2.5.x" in html and "A.swift:42" in html
    assert "Replace UIWebView with WKWebView" in html

def test_master_prompt_aggregates_and_anchors():
    html = render_html(_report())
    assert 'id="fix-all"' in html and 'href="#fix-all"' in html
    # master mentions both subsystems' rules
    assert html.count("uiwebview-usage") >= 2 and "page-unreachable" in html

def test_prompt_uses_detail_when_no_suggested_fix():
    r = GateReport(status="WARN", guidelines_available=True,
        code_findings=[CodeFinding(rule_id="insecure-http-endpoint", category="security-ats",
            severity="low", guideline_ref="2.5.2", file="B.swift", line=3, evidence="http://x",
            detail="insecure http endpoint", suggested_fix=None)])
    html = render_html(r)
    assert "insecure http endpoint" in html  # falls back to detail
```

- [ ] **Step 2: Run to verify fail** — `uv run pytest tests/test_html_report_prompts.py -q` → FAIL (no `id="fix-all"`, empty prompts).

- [ ] **Step 3: Implement**

```python
def _prompt_line(row):
    loc = f" — {row.anchor}" if row.anchor else ""
    gl = f" ({row.guideline_ref})" if row.guideline_ref else ""
    fix = row.suggested_fix or row.rationale
    return f"[{row.level.upper()}] {row.rule_label}{gl}{loc}\n   {fix}"

def _fix_prompt(subsystem, rows):
    body = "\n\n".join(_prompt_line(r) for r in rows)
    intro = (f"Fix these App Store rejection risks in the {subsystem.lower()} layer. "
             "Make the minimal change for each, preserve behavior, and show a diff.")
    text = _esc(f"{intro}\n\n{body}")
    wand = ('<svg class="wand" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M15 4V2M15 16v-2M8 9h2M20 9h2'
            'M17.8 11.8 19 13M15 9h0M17.8 6.2 19 5M3 21l9-9M12.2 6.2 11 5"/></svg>')
    copy = ('<button class="copy-prompt"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" '
            'height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
            '<span class="lbl">Copy prompt</span></button>')
    return (f'<div class="promptbox"><div class="phead">{wand}<b>Fix prompt</b> · {subsystem}'
            f'<span class="spacer"></span>{copy}</div><pre class="ptext">{text}</pre></div>')

def _master_prompt(rows):
    if not rows:
        return ""
    total = len(rows)
    blocking = sum(1 for r in rows if r.level == "block")
    warnings = total - blocking
    sections = []
    for name in ("Metadata", "Code", "Pages"):
        group = [r for r in rows if r.subsystem == name]
        if group:
            sections.append(name.upper() + "\n" + "\n\n".join(_prompt_line(r) for r in group))
    body = "\n\n".join(sections)
    intro = (f"You are helping ship an iOS app past App Store review. asc-verify returned a gate with "
             f"{blocking} blocking and {warnings} warning issue(s) across metadata, app code, and web "
             "pages. Fix ALL of them so a re-run returns no BLOCK. For each I give the rule, the App "
             "Store guideline, and the exact location. Make minimal changes, preserve behavior, and show "
             "a diff for every change. When finished, summarize what changed per file.")
    text = _esc(f"{intro}\n\n{body}")
    wand = ('<svg class="wand" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M15 4V2M15 16v-2M8 9h2M20 9h2'
            'M17.8 11.8 19 13M15 9h0M17.8 6.2 19 5M3 21l9-9M12.2 6.2 11 5"/></svg>')
    copy = ('<button class="copy-prompt"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" '
            'height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
            '<span class="lbl">Copy prompt</span></button>')
    return (f'<div class="promptbox master" id="fix-all"><div class="phead">{wand}'
            f'<b>Fix everything</b> · one prompt for all {total} issue(s)<span class="spacer"></span>'
            f'{copy}</div><p class="master-lead">Paste this into your coding agent to remediate the whole '
            f'report in one pass.</p><pre class="ptext">{text}</pre></div>')
```

Then in `render_html`, insert `_master_prompt(rows)` between `groups_html` and the
footer. Confirm `_controls` already renders the skip-to-fix anchor
(`<a class="skip" href="#fix-all">…</a>`) — it is part of the controls markup
ported from the template in Task 2; if Task 2 omitted it, add it here.

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_html_report_prompts.py -q` → PASS; full module suite `uv run pytest tests/test_html_report_*.py -q`; `uv run ruff check`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/html_report.py tests/test_html_report_prompts.py
git commit -m "feat(html): per-section + master fix prompts + skip-to-fix"
```

---

### Task 5: CLI `--format html`

**Files:**
- Modify: `src/asc_metadata_verifier/cli.py` (`OutputFormat.html`; `verify`/`code`/`pages` html branches)
- Test: `tests/test_html_report_cli.py`

**Interfaces:**
- Consumes: `render_html`, `evaluate`, `datetime`/`UTC` (already imported in cli.py).
- Produces: `--format html` on `verify`, `code`, `pages`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_html_report_cli.py
from typer.testing import CliRunner
from asc_metadata_verifier.cli import app

runner = CliRunner()

def test_verify_format_html_emits_report():
    res = runner.invoke(app, ["verify", "--yaml", "tests/fixtures/metadata.yaml",
                              "--dry-run", "--format", "html"])
    assert res.exit_code == 0 and "<style>" in res.output and "Pages analysis" not in res.output
    assert "ASC" in res.output or "Review Gate" in res.output  # masthead present

def test_pages_format_html_emits_report(tmp_path):
    import json
    d = tmp_path / "pages"; d.mkdir(); (d / "pages.json").write_text(json.dumps({}))
    res = runner.invoke(app, ["pages", "--yaml", "tests/fixtures/metadata.yaml",
                              "--pages-dir", str(d), "--format", "html"])
    assert "<style>" in res.output and "page-unreachable" in res.output
```

For the code command (needs the `[code]` extra), add:

```python
def test_code_format_html_emits_report(tmp_path):
    import plistlib
    import pytest
    pytest.importorskip("tree_sitter_language_pack")
    (tmp_path / "App").mkdir()
    (tmp_path / "App/View.swift").write_text("let w = UIWebView()\n")
    (tmp_path / "App/Info.plist").write_bytes(plistlib.dumps({"ITSAppUsesNonExemptEncryption": False}))
    res = runner.invoke(app, ["code", str(tmp_path), "--format", "html"])
    assert "<style>" in res.output and "uiwebview-usage" in res.output
```

- [ ] **Step 2: Run to verify fail** — `uv run pytest tests/test_html_report_cli.py -q` → FAIL (html not a valid `--format` value / no HTML branch).

- [ ] **Step 3: Implement** — in `cli.py`:

- Add `html = "html"` to `class OutputFormat`.
- Import at top: `from asc_metadata_verifier.html_report import render_html`.
- In `verify`, before the existing `if output_format is OutputFormat.json:` block, add:

```python
    if output_format is OutputFormat.html:
        stamped = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        typer.echo(render_html(report, app_id=meta.app_id or "—",
                               locale=meta.primary_locale or "—", generated_at=stamped,
                               fail_on=fail_on.value))
        # persistence still runs below via the shared tail; keep control flow — see note
```

  Since `verify` has a single render branch followed by degradation/persistence/exit,
  restructure the render selection as: `html` → `render_html(...)`; `json` →
  `render_json`; else `render_markdown`. Keep the subsequent degradation note,
  persistence, and `raise typer.Exit(code=exit_code(report))` unchanged (the HTML
  path shares them). Concretely, replace the `if json / else md` echo block with a
  three-way branch and leave everything after it intact.

- In `code`, replace the `if output_format is OutputFormat.json: … else …` echo with:

```python
    if output_format is OutputFormat.html:
        from asc_metadata_verifier.gate import evaluate
        stamped = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        gate_report = evaluate([], [], fail_on=fail_on.value, code_findings=findings)
        typer.echo(render_html(gate_report, generated_at=stamped, fail_on=fail_on.value))
    elif output_format is OutputFormat.json:
        typer.echo(render_code_report_json(report))
    else:
        typer.echo(render_code_report_text(report))
```

- In `pages`, the same shape with `page_findings=findings` and
  `render_pages_report_json`/`render_pages_report_text` for the other branches.

- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_html_report_cli.py -q` → PASS; full suite `uv run pytest -q`; `uv run ruff check src tests`.

- [ ] **Step 5: Commit**

```bash
git add src/asc_metadata_verifier/cli.py tests/test_html_report_cli.py
git commit -m "feat(html): --format html on verify/code/pages"
```

---

### Task 6: Docs — README + BUILD_LOG

**Files:**
- Modify: `README.md` (add "HTML report (optional)" subsection), `BUILD_LOG.md` (sub-project E entry)

- [ ] **Step 1: README** — document `asc-verify verify … --format html > report.html` (and `code`/`pages --format html`); what the report contains (stamped verdict, severity filter, findings with evidence + fix, jury vote panels, per-section + master fix prompts, skip-to-fix, theme toggle); the honesty note (evidence-only, prompts/refs from real fields, `n/a` when no grounding); self-contained/offline/zero-new-deps; and that it uses system fonts (a real build could embed JetBrains Mono / IBM Plex Sans).

- [ ] **Step 2: BUILD_LOG** — sub-project E entry mirroring A–D: what shipped, honesty rules, honest open items (evidence-only diffs — no structured `replacement` yet; system fonts not embedded; HTML runs not persisted).

- [ ] **Step 3: Verify** — run `asc-verify verify tests/fixtures/... --dry-run --format html > /tmp/r.html` and open it once; run the full suite `uv run pytest -q` and `uv run ruff check .`.

- [ ] **Step 4: Commit**

```bash
git add README.md BUILD_LOG.md
git commit -m "docs(html): README + BUILD_LOG for sub-project E"
```

---

## Self-review notes (author)

- **Spec coverage:** `_Row` normalizer C1 → T1; renderer C2 (stamp/summary/controls/footer) → T2, (cards/evidence/jury) → T3, (fix prompts) → T4; CLI C3 → T5; honesty rules (evidence-only, escape, n/a, real votes, prompts-from-real-fields) → enforced in T1/T3/T4 code + asserted in their tests; determinism → T2 test; self-contained/no-external → T2 test; docs → T6. All covered.
- **Type consistency:** `_Row`, `_rows_from_report`, `render_html`, `_esc`, `_evidence_block`, `_jury_panel`, `_finding_card`, `_render_groups`, `_fix_prompt`, `_master_prompt`, `OutputFormat.html` names match across tasks. `render_html(report, *, app_id, locale, generated_at, fail_on)` signature is identical in T2 and T5.
- **Sequencing:** T2 ships a temporary `_render_groups -> ""`; T3 replaces it and ships a temporary `_fix_prompt -> ""`; T4 replaces that. Each task stays green.
- **Known real risks flagged in-plan:** transcribe `_CSS`/`_JS` verbatim from the template (T2/T3 note); the `pill` becomes a `<span>` (no href) to keep the no-external-link invariant (T3 note); the `verify` render branch must preserve the degradation/persistence/exit tail (T5 note).
