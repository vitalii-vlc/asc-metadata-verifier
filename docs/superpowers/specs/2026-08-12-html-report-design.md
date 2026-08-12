# HTML Report Generator — Design Spec (v2, sub-project E)

> Pre-registration commit — scope + design fixed **before** any feature code
> (honest-velocity method, mirroring v1 and sub-projects A–D). Date: 2026-08-12.
>
> Fifth and **final** v2 sub-project. Renders the gate result as a self-contained
> HTML report. The **visual design is already approved** — it is the template
> published earlier (stamped PASS/WARN/BLOCK verdict, severity summary + filter,
> findings grouped by subsystem with evidence / critical comments / suggestions,
> jury vote panels, per-section fix prompts, a master fix-all prompt, skip-to-fix,
> theme toggle, self-contained inline CSS/JS). This spec settles only the
> **data→HTML mapping** and the **honesty rules**, not the look.

**Goal:** add an **additive** `--format html` output that renders a `GateReport`
(and, via the same renderer, `CodeReport`/`PagesReport`) as a **self-contained,
offline, deterministic** HTML report matching the approved template — turning the
gate result into a shareable, actionable page with a copy-ready fix prompt per
subsystem plus one master "fix everything" prompt.

**Architecture (one line):** a new pure string-building module
`html_report.py` exposing `render_html(GateReport, …) -> str`; a `_Row` normalizer
collapses the four finding types (RubricVerdict/PanelVerdict, DeterministicFinding,
CodeFinding, PageFinding) into one uniform shape grouped by subsystem; the CLI
gains `html` in `OutputFormat`, and `code`/`pages --format html` wrap their
findings into a `GateReport` via the existing `evaluate(...)` so a single renderer
serves all three commands.

**Tech stack:** Python 3.11+ (uv) · stdlib `html.escape` (escaping) · pydantic v2
(the existing models) · typer (CLI). **No new dependencies** — pure string
building, exactly like `report.py`.

---

## Global constraints

- **Additive / backward compatible (hard):** `--format md` (default) and
  `--format json` are byte-unchanged. Adding `html` changes nothing about the
  existing paths; the full suite passes unchanged.
- **Self-contained & offline (hard):** the rendered HTML inlines all CSS and JS,
  uses **system-font stacks only** (no external fonts, no CDN, no network), and
  embeds no remote assets. It opens correctly from `file://` with no connectivity.
- **Deterministic (hard):** `render_html` performs **no** time or randomness — the
  timestamp is passed in by the caller. Identical `GateReport` + same context →
  **byte-identical** HTML.
- **Never fabricate (honesty invariant):**
  - No invented before/after diffs. The generator renders an **evidence highlight**
    (a red deletion-style line of the *actual* offending text) plus the finding's
    own prose fix. It emits a green "+" replacement line **only** when a finding
    carries a concrete replacement string — no current finding does, so that branch
    stays dormant (seam for a future structured field).
  - Fix prompts are built **only** from real finding fields (`rule_id`/`dimension`,
    `guideline_ref`, location, `suggested_fix` or `detail`). No invented specifics.
  - `guideline_ref == None` renders `n/a`, never an invented citation.
  - Jury panels show **real** votes (including error/abstain), consensus, agreement,
    and policy from the `PanelVerdict` — LLM judgment is never presented as fact.
- **Escape everything model-derived:** every model string reaching the HTML passes
  through `html.escape` (rationale, evidence, offending quotes, URLs, file paths,
  judge names, rule-ids). A finding containing `<` must never break the page.
- **Zero new core deps.**

---

## Component 1 — The `_Row` normalizer (`html_report.py`)

A single internal shape so rendering is uniform and the honesty rules live in one
place:

```python
@dataclass(frozen=True)
class _Row:
    subsystem: Literal["Metadata", "Code", "Pages"]
    level: Literal["block", "warn"]           # from the gate's existing classifiers
    sev_label: str                            # "Block" / "Warn"
    rule_label: str                           # rule_id or dimension
    guideline_ref: str | None
    anchor: str                               # "en-US · promotional_text" / "File.swift:42" / "support · <url>"
    source: Literal["static", "jury"]
    rationale: str                            # detail / rationale
    evidence: str | None                      # offending_quote / evidence / field value
    suggested_fix: str | None
    panel: PanelVerdict | None                # set iff source == "jury"
```

Normalizers (one per model type) build `list[_Row]`:

- **Metadata verdicts** — prefer `report.panels` when non-empty (jury run); else
  `report.verdicts` (single-judge). Include **non-pass only**
  (`verdict in {"warn","fail"}`). `level` via the gate's `_verdict_level`;
  `source="jury"` iff from a panel (carry the `PanelVerdict`); `anchor =
  "{locale} · {field}"`; `evidence = offending_quote`.
- **Deterministic** (`report.deterministic_findings`) → subsystem "Metadata",
  `level` via `_DETERMINISTIC_LEVEL` (skip `none`), `rule_label = kind`,
  `guideline_ref = None`, `anchor = "{locale} · {field}"`, `rationale = detail`,
  `source="static"`.
- **Code** (`report.code_findings`) → subsystem "Code", `level` via `_code_level`,
  `anchor = "{file}:{line}"` (or `file` when line is None), `evidence = evidence`,
  `source` from the finding, `panel` from the finding.
- **Pages** (`report.page_findings`) → subsystem "Pages", `level` via `_page_level`,
  `anchor = "{page_type} · {url}"`, `evidence = evidence`, `source`/`panel` from
  the finding.

Rows preserve the order their producers emit (already deterministic).

> **Plan must verify (double-count risk):** confirm empirically whether a jury
> run populates **both** `report.panels` and `report.verdicts` (with the same
> consensus verdicts) or only `panels`. The "prefer panels when non-empty, else
> verdicts" rule is correct **only if** panels-present means verdicts are the
> duplicated consensus (so skipping them avoids a double-listing). If verify
> populates them independently, the rule needs adjusting. Resolve this in the
> plan's first task with a quick check of `run_verify`'s jury path.

## Component 2 — The renderer (`html_report.py`)

```python
def render_html(
    report: GateReport,
    *,
    app_id: str = "—",
    locale: str = "—",
    generated_at: str = "—",
    fail_on: str = "fail",
) -> str: ...
```

Builds the page from the approved template, section helpers mirroring
`report.py`'s `_render_*` style:

- `_verdict_stamp(status)` — the big monospace PASS/WARN/BLOCK stamp, severity-tinted;
  the exit-code line (`0` / `1`).
- `_summary(rows)` — Blocking / Warnings / **Passed** / Subsystems stat cards +
  the severity bar. **Passed** = count of pass-verdicts (jury consensus or single
  verdicts) — honest; `0` (with a note) when no LLM ran.
- `_controls(counts)` — filter chips (All / Blocking / Warnings), Skip-to-fix,
  theme toggle.
- `_group(subsystem, rows)` — heading + count + `_finding_card` per row +
  `_fix_prompt(subsystem, rows)`. Omitted when the subsystem has no rows.
- `_finding_card(row)` — severity chip, rule-id (mono), guideline pill (`n/a` when
  None), anchor, source badge, rationale, `_evidence_block`, fix line, `_jury_panel`.
- `_evidence_block(row)` — the honest red deletion-style evidence line (only when
  `evidence` is present); **no green line** unless a real replacement exists.
- `_jury_panel(panel)` — `<details>` with per-judge rows (status/verdict/severity/
  confidence or the error string), consensus, agreement, policy.
- `_fix_prompt(subsystem, rows)` / `_master_prompt(all_rows)` — copy-ready prompts
  built from real fields only.
- `_footer(report)` — the honest caveats (jury = LLM judgment; catalog curated /
  non-exhaustive; guideline refs from live fetch → `n/a` if unavailable) + a
  generated-by line carrying `app_id` / `locale` / `generated_at`.

`_CSS` and `_JS` are module constants ported verbatim from the approved template
(theme-aware tokens, severity system, reduced-motion, filter/skip/copy/theme JS).

## Component 3 — CLI wiring (`cli.py`)

- Add `html = "html"` to `OutputFormat`.
- **`verify --format html`** → `render_html(report, app_id=meta.app_id or "—",
  locale=meta.primary_locale or "—", generated_at=<now, stamped by the CLI>,
  fail_on=fail_on.value)`, printed to stdout. (Users redirect `> report.html`.)
  The timestamp is produced in the CLI (`datetime.now(UTC)`), never inside the
  renderer, preserving determinism/testability.
- **`code --format html`** → build a `GateReport` via
  `evaluate([], [], code_findings=findings)` and `render_html` it.
- **`pages --format html`** → build a `GateReport` via
  `evaluate([], [], page_findings=findings)` and `render_html` it.
- No `--out` flag (stdout redirect suffices — YAGNI).

---

## Testing strategy

- **`render_html` (offline, constructed `GateReport`s):**
  - Contains the stamp status, and every finding's rule-label / guideline / anchor /
    **escaped** evidence.
  - Contains a per-subsystem fix prompt and the master prompt, both built from the
    findings' real fields.
  - Is self-contained: contains `<style>` and `<script>`, and **no** external
    font/CDN/`http(s)://…` asset link.
  - **Escaping:** a finding whose evidence is `<script>alert(1)</script>` renders as
    `&lt;script&gt;…`, never raw.
  - **Honesty:** a finding with only a prose `suggested_fix` produces **no** green
    "+"/addition line — evidence-only.
  - **`n/a`:** a verdict/finding with `guideline_ref = None` renders `n/a`.
  - **Jury panel:** a jury row renders its per-judge votes + consensus + agreement +
    policy from the `PanelVerdict`.
  - **Determinism:** rendering the same report twice yields byte-identical HTML.
- **CLI (offline):** `verify --format html` (via `--yaml … --dry-run`) emits HTML
  with the stamp + a known deterministic finding; `code --format html` (tree-sitter
  `importorskip`) and `pages --format html` (`--pages-dir`) each emit their HTML.
- **Backward-compat:** `--format md`/`json` output unchanged; the full existing
  suite passes.

---

## Out of scope (kept honest & tight)

- An `--out <file>` flag — stdout redirect covers it.
- Embedding real webfonts. The report uses deliberate **system-font stacks**
  (developer-mono + humanist-sans); a real build *could* embed JetBrains Mono /
  IBM Plex Sans since the generated file is not CSP-bound, but that bloats output
  and is deferred.
- The dormant structured-`replacement` field that would enable true before/after
  diffs — the seam exists in `_evidence_block`, the field does not.
- Persisting HTML runs via the repository (B); an interactive/served report.
