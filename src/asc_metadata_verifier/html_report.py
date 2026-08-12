"""Render a GateReport as a self-contained, offline, deterministic HTML report.

Pure string building (like report.py); no time/randomness (the caller passes
`generated_at`). Honesty: evidence-only (no fabricated before/after), prompts
from real fields, everything model-derived is html.escape'd, guideline_ref None
-> "n/a", jury panels show real votes. CSS/JS ported verbatim from the approved
template."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape as _escape

from asc_metadata_verifier.gate import (
    _code_level,
    _finding_level,
    _page_level,
    _verdict_level,
)
from asc_metadata_verifier.html_report_assets import CSS as _CSS
from asc_metadata_verifier.html_report_assets import JS as _JS
from asc_metadata_verifier.models import GateReport, PanelVerdict

_SEV_LABEL = {"block": "Block", "warn": "Warn"}


def _esc(text) -> str:
    return _escape(str(text), quote=True)


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


# --- SVG icons (inline, from the approved template) ---
_ICON_SHIELD = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 '
                '6 8 10 8 10Z"/></svg>')
_STAMP_ICON = {
    "BLOCK": ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
              'stroke-linecap="round" stroke-linejoin="round"><polygon points="7.86 2 16.14 2 22 7.86 '
              '22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/>'
              '<line x1="12" y1="16" x2="12.01" y2="16"/></svg>'),
    "WARN": ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 '
             '3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" y1="9" x2="12" '
             'y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'),
    "PASS": ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>'
             '<path d="m9 11 3 3L22 4"/></svg>'),
}
_STAMP_CLASS = {"BLOCK": "", "WARN": "sev-warn", "PASS": "sev-pass"}
_STAMP_EXIT = {"BLOCK": "do not submit · exit 1", "WARN": "review before submit · exit 0",
               "PASS": "safe to submit · exit 0"}


def _counts(rows):
    blocking = sum(1 for r in rows if r.level == "block")
    warnings = sum(1 for r in rows if r.level == "warn")
    subsystems = len({r.subsystem for r in rows})
    return blocking, warnings, subsystems


def _passed(report):
    if report.panels:
        return sum(1 for p in report.panels if p.consensus.verdict == "pass")
    return sum(1 for v in report.verdicts if v.verdict == "pass")


def _verdict_stamp(status):
    cls = _STAMP_CLASS.get(status, "")
    icon = _STAMP_ICON.get(status, _STAMP_ICON["BLOCK"])
    exit_line = _STAMP_EXIT.get(status, "")
    return (f'<div class="stamp {cls}" role="status" aria-label="Overall gate result: {_esc(status)}">'
            f'<div class="word">{icon}{_esc(status)}</div>'
            f'<div class="exit">{_esc(exit_line)}</div></div>')


def _lead(blocking, warnings):
    if blocking:
        s = f"<b>{blocking} blocking issue{'s' if blocking != 1 else ''}</b> would get this build rejected"
        if warnings:
            s += f", plus <b>{warnings} warning{'s' if warnings != 1 else ''}</b> worth fixing"
        s += (" — spanning metadata, app code, and the linked web pages. "
              "Each finding cites its guideline and a concrete fix.")
    elif warnings:
        s = (f"<b>{warnings} warning{'s' if warnings != 1 else ''}</b> worth reviewing — nothing "
             "blocking. Each cites its guideline and a fix.")
    else:
        s = "No rejection risks found across metadata, code, and pages — the gate passed."
    return f'<p style="margin:0 0 1.1rem; font-size:1rem; color:var(--text); max-width:60ch;">{s}</p>'


def _masthead(report, app_id, locale, generated_at, fail_on, blocking, warnings):
    meta = (f'<span><b>app</b> {_esc(app_id)}</span>'
            f'<span><b>locale</b> {_esc(locale)}</span>'
            f'<span><b>run</b> {_esc(generated_at)}</span>'
            f'<span><b>fail-on</b> {_esc(fail_on)}</span>')
    return (f'<div class="eyebrow">{_ICON_SHIELD} App Store Review Gate · asc-verify</div>'
            f'<div class="masthead"><div class="subject"><h1>App Store submission</h1>'
            f'<div class="meta">{meta}</div></div>{_verdict_stamp(report.status)}</div>'
            f'{_lead(blocking, warnings)}')


def _summary(blocking, warnings, passed, subsystems):
    passed_label = "Passed" if passed else "Passed · no LLM"
    p_flex = max(passed, 1)
    return (f'<div class="summary">'
            f'<div class="stat block"><div class="n tnum">{blocking}</div><div class="k">Blocking</div></div>'
            f'<div class="stat warn"><div class="n tnum">{warnings}</div><div class="k">Warnings</div></div>'
            f'<div class="stat pass"><div class="n tnum">{passed}</div><div class="k">{passed_label}</div></div>'
            f'<div class="stat"><div class="n tnum">{subsystems}</div><div class="k">Subsystems</div></div>'
            f'</div>'
            f'<div class="sevbar" aria-hidden="true"><span class="b" style="flex:{blocking}"></span>'
            f'<span class="w" style="flex:{warnings}"></span><span class="p" style="flex:{p_flex}"></span></div>')


def _controls(blocking, warnings, total):
    theme_icon = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                  'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/>'
                  '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 '
                  '1.4M19.1 4.9l-1.4 1.4"/></svg>')
    skip_icon = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                 'stroke-linecap="round" stroke-linejoin="round"><path d="m7 6 5 5 5-5M7 13l5 5 5-5"/></svg>')
    return (f'<div class="controls"><div class="chips" role="group" aria-label="Filter findings by severity">'
            f'<button class="chip" data-filter="all" aria-pressed="true">All <span class="tnum">{total}</span></button>'
            f'<button class="chip" data-filter="block" aria-pressed="false"><span class="dot b"></span>'
            f'Blocking <span class="tnum">{blocking}</span></button>'
            f'<button class="chip" data-filter="warn" aria-pressed="false"><span class="dot w"></span>'
            f'Warnings <span class="tnum">{warnings}</span></button></div><span class="spacer"></span>'
            f'<a class="skip" href="#fix-all" aria-label="Skip findings and jump to the fix-everything prompt">'
            f'{skip_icon} Skip to fix</a>'
            f'<button class="toggle" id="themeBtn" aria-label="Toggle light or dark theme">{theme_icon}'
            f'<span id="themeLbl">Theme</span></button></div>')


_CAVEAT_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 '
                '3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" y1="9" x2="12" y2="13"/>'
                '<line x1="12" y1="17" x2="12.01" y2="17"/></svg>')


def _footer(report, app_id, locale, generated_at):
    if report.guidelines_available:
        gl = ("Guideline references were resolved against the live App Store Review Guidelines fetched "
              "at run time. When the fetch fails, refs read <code>n/a</code> rather than being invented.")
    else:
        gl = ("Guidelines were unavailable this run (offline) — guideline references read <code>n/a</code> "
              "and were not invented.")
    gen = (f"Generated by asc-verify · Pydantic-stack LLM-as-judge gate · app {_esc(app_id)} · "
           f"{_esc(locale)} · {_esc(generated_at)}")
    return (f'<footer><div class="caveats">'
            f'<div class="caveat">{_CAVEAT_ICON}<span>Jury findings are LLM judgments (shown with every '
            f'vote), not deterministic facts. The static rule catalog and denylists are curated and '
            f'non-exhaustive — treat this as a strong pre-submission signal, not a guarantee of approval.'
            f'</span></div>'
            f'<div class="caveat">{_CAVEAT_ICON}<span>{gl}</span></div></div>'
            f'<div class="gen">{gen}</div></footer>')


_SEV_ICON = {
    "block": ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4">'
              '<polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/></svg>'),
    "warn": ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
             'stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 '
             '3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/></svg>'),
}
_GROUP_META = [
    ("Metadata",
     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
     'stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h10M7 12h6M7 16h8"/></svg>',
     "App Store Connect text — judged against the live Review Guidelines."),
    ("Code",
     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
     'stroke-linejoin="round"><path d="m16 18 4-4-4-4M8 6l-4 4 4 4M14 4l-4 16"/></svg>',
     "Deep AST analysis of the app project — symbols correlated against Info.plist & PrivacyInfo.xcprivacy."),
    ("Pages",
     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
     'stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/></svg>',
     "Privacy / support / marketing URLs — reachability + privacy-policy↔code cross-reference."),
]
_CHEV = ('<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
         'stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>')
_CHECK = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
          'stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>')


def _evidence_block(row):
    if not row.evidence:
        return ""
    return ('<div class="diff" aria-label="Offending value">'
            f'<div class="row del"><span class="g">-</span><span class="l">{_esc(row.evidence)}</span></div>'
            '</div>')


def _jury_panel(panel):
    if panel is None:
        return ""
    votes = []
    for vote in panel.votes:
        if vote.status == "voted" and vote.verdict is not None:
            detail = f"{_esc(vote.verdict.severity)} · conf {vote.verdict.confidence:.2f}"
            votes.append(f'<div class="vote"><span class="j">{_esc(vote.judge)}</span>'
                         f'<span class="v {_esc(vote.verdict.verdict)}">{_esc(vote.verdict.verdict)}</span>'
                         f'<span class="c">{detail}</span></div>')
        else:
            votes.append(f'<div class="vote"><span class="j">{_esc(vote.judge)}</span>'
                         f'<span class="v">{_esc(vote.status)}</span>'
                         f'<span class="c">{_esc(vote.error or "")}</span></div>')
    agr = "—" if panel.agreement is None else f"{panel.agreement:.2f}"
    cons = (f'<div class="consensus"><span><b>consensus</b> {_esc(panel.consensus.verdict)} / '
            f'{_esc(panel.consensus.severity)}</span><span><b>agreement</b> {agr}</span>'
            f'<span><b>policy</b> {_esc(panel.policy)}</span></div>')
    return (f'<details class="jury"><summary>{_CHEV}Jury deliberation — consensus '
            f'<b>{_esc(panel.consensus.verdict)}</b> (policy: {_esc(panel.policy)})</summary>'
            f'<div class="votes">{"".join(votes)}{cons}</div></details>')


def _finding_card(row):
    card_cls = "card" if row.level == "block" else "card sev-warn"
    guideline = _esc(row.guideline_ref) if row.guideline_ref else "n/a"
    src_cls = "src jury" if row.source == "jury" else "src"
    src_label = "jury" if row.source == "jury" else "static"
    fix = ""
    if row.suggested_fix:
        fix = (f'<div class="fix">{_CHECK}<div><span class="k">Fix</span><br>'
               f'{_esc(row.suggested_fix)}</div></div>')
    return (f'<article class="{card_cls}" data-sev="{row.level}">'
            f'<div class="fhead"><span class="sev">{_SEV_ICON[row.level]}{row.sev_label}</span>'
            f'<span class="rule">{_esc(row.rule_label)}</span>'
            f'<span class="pill">{guideline}</span>'
            f'<span class="anchor">{_esc(row.anchor)}</span>'
            f'<span class="spacer"></span><span class="{src_cls}">{src_label}</span></div>'
            f'<p class="rationale">{_esc(row.rationale)}</p>'
            f'{_evidence_block(row)}{fix}{_jury_panel(row.panel)}</article>')


def _fix_prompt(subsystem, rows):  # replaced in Task 4
    return ""


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


def _master_prompt(rows):  # replaced in Task 4
    return ""


def render_html(report, *, app_id="—", locale="—", generated_at="—", fail_on="fail"):
    rows = _rows_from_report(report)
    blocking, warnings, subsystems = _counts(rows)
    passed = _passed(report)
    total = blocking + warnings
    parts = [
        "<style>", _CSS, "</style>",
        '<div class="wrap">',
        _masthead(report, app_id, locale, generated_at, fail_on, blocking, warnings),
        _summary(blocking, warnings, passed, subsystems),
        _controls(blocking, warnings, total),
        _render_groups(rows),
        _master_prompt(rows),
        _footer(report, app_id, locale, generated_at),
        "</div>",
        "<script>", _JS, "</script>",
    ]
    return "\n".join(parts)
