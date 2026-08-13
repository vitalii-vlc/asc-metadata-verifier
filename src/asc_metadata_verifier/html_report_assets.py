"""Verbatim CSS + JS for the HTML report, ported from the approved template.

Generated once from the design template; edit here (this is the source of truth).
Kept in a separate module so html_report.py stays focused on logic."""

CSS = """  :root {
    --bg: #f6f7f9; --surface: #ffffff; --surface-2: #eef1f5; --border: #dde2ea;
    --text: #171b22; --text-2: #56606f;
    --accent: #3350c9; --accent-weak: #e9edfb;
    --block: #b7332a; --block-bg: #fbeceb; --block-stripe: #d64a3e;
    --warn: #9a5400; --warn-bg: #fbf2e4; --warn-stripe: #d98a24;
    --pass: #16794f; --pass-bg: #e7f4ee; --pass-stripe: #2ba06d;
    --del-bg: #fbe9e7; --del-text: #9e281c; --del-gutter: #f0c8c3;
    --add-bg: #e6f4ea; --add-text: #12683f; --add-gutter: #b9e2c9;
    --shadow: 0 1px 2px rgba(20,27,40,.04), 0 8px 24px rgba(20,27,40,.05);
    --mono: ui-monospace, "SF Mono", "JetBrains Mono", "IBM Plex Mono", Menlo, Consolas, monospace;
    --sans: system-ui, -apple-system, "Segoe UI", "IBM Plex Sans", Roboto, Helvetica, sans-serif;
    color-scheme: light;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f1218; --surface: #161a22; --surface-2: #1d222c; --border: #2a313d;
      --text: #e8ebf1; --text-2: #98a2b1;
      --accent: #8ea3ff; --accent-weak: #1a2133;
      --block: #f2705f; --block-bg: #271513; --block-stripe: #cf5140;
      --warn: #f2b552; --warn-bg: #271e12; --warn-stripe: #b9832f;
      --pass: #58d59a; --pass-bg: #10241b; --pass-stripe: #2f8c60;
      --del-bg: #271513; --del-text: #f4aaa0; --del-gutter: #4d2620;
      --add-bg: #10241b; --add-text: #79d9a6; --add-gutter: #234a36;
      --shadow: 0 1px 2px rgba(0,0,0,.3), 0 10px 30px rgba(0,0,0,.35);
      color-scheme: dark;
    }
  }
  :root[data-theme="light"] {
    --bg: #f6f7f9; --surface: #ffffff; --surface-2: #eef1f5; --border: #dde2ea;
    --text: #171b22; --text-2: #56606f; --accent: #3350c9; --accent-weak: #e9edfb;
    --block: #b7332a; --block-bg: #fbeceb; --block-stripe: #d64a3e;
    --warn: #9a5400; --warn-bg: #fbf2e4; --warn-stripe: #d98a24;
    --pass: #16794f; --pass-bg: #e7f4ee; --pass-stripe: #2ba06d;
    --del-bg: #fbe9e7; --del-text: #9e281c; --del-gutter: #f0c8c3;
    --add-bg: #e6f4ea; --add-text: #12683f; --add-gutter: #b9e2c9;
    --shadow: 0 1px 2px rgba(20,27,40,.04), 0 8px 24px rgba(20,27,40,.05);
    color-scheme: light;
  }
  :root[data-theme="dark"] {
    --bg: #0f1218; --surface: #161a22; --surface-2: #1d222c; --border: #2a313d;
    --text: #e8ebf1; --text-2: #98a2b1; --accent: #8ea3ff; --accent-weak: #1a2133;
    --block: #f2705f; --block-bg: #271513; --block-stripe: #cf5140;
    --warn: #f2b552; --warn-bg: #271e12; --warn-stripe: #b9832f;
    --pass: #58d59a; --pass-bg: #10241b; --pass-stripe: #2f8c60;
    --del-bg: #271513; --del-text: #f4aaa0; --del-gutter: #4d2620;
    --add-bg: #10241b; --add-text: #79d9a6; --add-gutter: #234a36;
    --shadow: 0 1px 2px rgba(0,0,0,.3), 0 10px 30px rgba(0,0,0,.35);
    color-scheme: dark;
  }

  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: var(--sans); line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 62rem; margin: 0 auto; padding: clamp(1rem, 3vw, 2.5rem) clamp(1rem, 3vw, 2rem) 4rem; }

  a { color: var(--accent); }
  code, .mono { font-family: var(--mono); font-variant-ligatures: none; }
  .tnum { font-variant-numeric: tabular-nums; }
  :focus-visible { outline: 2.5px solid var(--accent); outline-offset: 2px; border-radius: 4px; }

  /* ---- masthead ---- */
  .eyebrow {
    font-family: var(--mono); font-size: .72rem; letter-spacing: .16em;
    text-transform: uppercase; color: var(--text-2); display: flex; align-items: center; gap: .5rem;
  }
  .eyebrow svg { width: 15px; height: 15px; }
  .masthead { display: flex; flex-wrap: wrap; gap: 1.5rem 2rem; align-items: flex-end;
    justify-content: space-between; margin: 1.25rem 0 1.75rem; }
  .subject h1 { font-size: 1.5rem; margin: .55rem 0 .3rem; letter-spacing: -.01em; text-wrap: balance; }
  .subject .meta { font-family: var(--mono); font-size: .8rem; color: var(--text-2); display: flex;
    flex-wrap: wrap; gap: .2rem .9rem; }
  .subject .meta b { color: var(--text); font-weight: 600; }

  /* ---- verdict stamp (the hero) ---- */
  .stamp {
    --sc: var(--block); --sbg: var(--block-bg); --sstripe: var(--block-stripe);
    border: 2px solid var(--sc); background: var(--sbg); color: var(--sc);
    border-radius: 12px; padding: .85rem 1.2rem; text-align: center; min-width: 12.5rem;
    box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--sc) 22%, transparent);
  }
  .stamp.sev-warn { --sc: var(--warn); --sbg: var(--warn-bg); --sstripe: var(--warn-stripe); }
  .stamp.sev-pass { --sc: var(--pass); --sbg: var(--pass-bg); --sstripe: var(--pass-stripe); }
  .stamp .word { font-family: var(--mono); font-weight: 700; font-size: clamp(2.4rem, 7vw, 3.4rem);
    line-height: 1; letter-spacing: .06em; display: flex; align-items: center; justify-content: center; gap: .55rem; }
  .stamp .word svg { width: .82em; height: .82em; }
  .stamp .exit { font-family: var(--mono); font-size: .72rem; letter-spacing: .1em; margin-top: .5rem;
    text-transform: uppercase; opacity: .85; }

  /* ---- summary ---- */
  .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr)); gap: .75rem;
    margin-bottom: 1.1rem; }
  .stat { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: .8rem .95rem; box-shadow: var(--shadow); }
  .stat .n { font-family: var(--mono); font-size: 1.7rem; font-weight: 700; line-height: 1; }
  .stat .k { font-size: .74rem; letter-spacing: .05em; text-transform: uppercase; color: var(--text-2);
    margin-top: .35rem; }
  .stat.block .n { color: var(--block); } .stat.warn .n { color: var(--warn); } .stat.pass .n { color: var(--pass); }

  .sevbar { display: flex; height: 8px; border-radius: 999px; overflow: hidden; margin: 0 0 1.6rem;
    border: 1px solid var(--border); }
  .sevbar span { display: block; }
  .sevbar .b { background: var(--block-stripe); } .sevbar .w { background: var(--warn-stripe); }
  .sevbar .p { background: var(--pass-stripe); }

  /* ---- controls ---- */
  .controls { position: sticky; top: 0; z-index: 20; background: color-mix(in srgb, var(--bg) 88%, transparent);
    backdrop-filter: blur(8px); border-bottom: 1px solid var(--border);
    display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; padding: .7rem 0; margin-bottom: 1.4rem; }
  .chips { display: flex; flex-wrap: wrap; gap: .4rem; }
  .chip { font-family: var(--mono); font-size: .76rem; padding: .32rem .7rem; border-radius: 999px;
    border: 1px solid var(--border); background: var(--surface); color: var(--text-2); cursor: pointer;
    display: inline-flex; align-items: center; gap: .4rem; transition: background .15s, color .15s, border-color .15s; }
  .chip:hover { border-color: var(--accent); color: var(--text); }
  .chip .dot { width: 8px; height: 8px; border-radius: 999px; }
  .chip .dot.b { background: var(--block-stripe); } .chip .dot.w { background: var(--warn-stripe); }
  .chip .dot.p { background: var(--pass-stripe); }
  .chip[aria-pressed="true"] { background: var(--accent-weak); border-color: var(--accent); color: var(--text); }
  .spacer { flex: 1 1 auto; }
  .toggle { font-family: var(--mono); font-size: .76rem; padding: .32rem .6rem; border-radius: 8px;
    border: 1px solid var(--border); background: var(--surface); color: var(--text-2); cursor: pointer;
    display: inline-flex; align-items: center; gap: .4rem; }
  .toggle:hover { border-color: var(--accent); color: var(--text); }
  .toggle svg { width: 15px; height: 15px; }
  .skip { font-family: var(--mono); font-size: .76rem; padding: .34rem .72rem; border-radius: 8px;
    border: 1px solid var(--accent); background: var(--accent-weak); color: var(--accent); cursor: pointer;
    text-decoration: none; display: inline-flex; align-items: center; gap: .4rem; white-space: nowrap;
    transition: background .15s; }
  .skip:hover { background: color-mix(in srgb, var(--accent) 16%, var(--surface)); }
  .skip svg { width: 15px; height: 15px; }

  /* ---- groups & findings ---- */
  .group { margin: 2rem 0 0; }
  .group > h2 { font-size: 1.02rem; margin: 0 0 .2rem; display: flex; align-items: center; gap: .55rem;
    letter-spacing: -.01em; }
  .group > h2 svg { width: 18px; height: 18px; color: var(--text-2); }
  .group > h2 .count { font-family: var(--mono); font-size: .74rem; color: var(--text-2); font-weight: 500;
    background: var(--surface-2); border-radius: 999px; padding: .1rem .5rem; margin-left: .1rem; }
  .group > .gsub { font-size: .82rem; color: var(--text-2); margin: 0 0 .9rem; }

  .cards { display: flex; flex-direction: column; gap: .85rem; }
  .card {
    --sc: var(--block); --sbg: var(--block-bg); --sstripe: var(--block-stripe);
    background: var(--surface); border: 1px solid var(--border); border-left: 4px solid var(--sstripe);
    border-radius: 10px; padding: .95rem 1.05rem; box-shadow: var(--shadow); }
  .card.sev-warn { --sc: var(--warn); --sbg: var(--warn-bg); --sstripe: var(--warn-stripe); }
  .card.sev-pass { --sc: var(--pass); --sbg: var(--pass-bg); --sstripe: var(--pass-stripe); }

  .fhead { display: flex; flex-wrap: wrap; align-items: center; gap: .45rem .55rem; }
  .sev { font-family: var(--mono); font-size: .68rem; font-weight: 700; letter-spacing: .07em;
    text-transform: uppercase; color: var(--sc); background: var(--sbg); border: 1px solid color-mix(in srgb, var(--sc) 30%, transparent);
    border-radius: 6px; padding: .18rem .45rem; display: inline-flex; align-items: center; gap: .3rem; }
  .sev svg { width: 12px; height: 12px; }
  .rule { font-family: var(--mono); font-size: .84rem; font-weight: 600; color: var(--text); }
  .pill { font-family: var(--mono); font-size: .72rem; color: var(--accent); background: var(--accent-weak);
    border-radius: 6px; padding: .16rem .45rem; text-decoration: none; }
  .anchor { font-family: var(--mono); font-size: .75rem; color: var(--text-2); }
  .src { font-family: var(--mono); font-size: .66rem; letter-spacing: .06em; text-transform: uppercase;
    color: var(--text-2); border: 1px dashed var(--border); border-radius: 6px; padding: .12rem .4rem; }
  .src.jury { color: var(--accent); border-style: solid; border-color: color-mix(in srgb, var(--accent) 45%, transparent); }
  .fhead .spacer { flex: 1 1 auto; }

  .rationale { margin: .6rem 0 0; color: var(--text); font-size: .93rem; }
  .rationale .q { font-family: var(--mono); font-size: .86em; background: var(--surface-2); padding: .05rem .3rem;
    border-radius: 4px; }

  /* ---- diff ---- */
  .diff { margin: .75rem 0 0; border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
    font-family: var(--mono); font-size: .8rem; }
  .diff .row { display: grid; grid-template-columns: 1.6rem 1fr; align-items: baseline; }
  .diff .row .g { text-align: center; user-select: none; color: var(--text-2); padding: .28rem 0; font-weight: 600; }
  .diff .row .l { padding: .28rem .6rem .28rem .2rem; white-space: pre-wrap; word-break: break-word; }
  .diff .del { background: var(--del-bg); color: var(--del-text); } .diff .del .g { background: var(--del-gutter); }
  .diff .add { background: var(--add-bg); color: var(--add-text); } .diff .add .g { background: var(--add-gutter); }

  .fix { margin: .75rem 0 0; display: flex; align-items: flex-start; gap: .55rem; font-size: .9rem;
    background: var(--surface-2); border-radius: 8px; padding: .55rem .7rem; }
  .fix svg { width: 16px; height: 16px; color: var(--pass); flex: none; margin-top: .15rem; }
  .fix .k { font-family: var(--mono); font-size: .68rem; letter-spacing: .06em; text-transform: uppercase;
    color: var(--text-2); }
  .fix .spacer { flex: 1 1 auto; }
  .copy { font-family: var(--mono); font-size: .72rem; border: 1px solid var(--border); background: var(--surface);
    color: var(--text-2); border-radius: 6px; padding: .2rem .5rem; cursor: pointer; display: inline-flex;
    align-items: center; gap: .3rem; white-space: nowrap; }
  .copy:hover { border-color: var(--accent); color: var(--text); }
  .copy svg { width: 13px; height: 13px; }

  /* ---- fix prompts ---- */
  .promptbox { margin: 1.1rem 0 0; border: 1px solid var(--border); border-left: 3px solid var(--accent);
    border-radius: 10px; background: var(--surface-2); overflow: hidden; }
  .phead { display: flex; align-items: center; gap: .5rem; padding: .55rem .75rem;
    font-family: var(--mono); font-size: .74rem; letter-spacing: .03em; color: var(--text-2);
    border-bottom: 1px solid var(--border); }
  .phead svg.wand { width: 15px; height: 15px; color: var(--accent); flex: none; }
  .phead b { color: var(--text); font-weight: 600; }
  .phead .spacer { flex: 1 1 auto; }
  .ptext { margin: 0; padding: .8rem .9rem; font-family: var(--mono); font-size: .78rem; line-height: 1.7;
    color: var(--text); white-space: pre-wrap; word-break: break-word; overflow-x: auto; }
  .copy-prompt { font-family: var(--mono); font-size: .72rem; border: 1px solid var(--border);
    background: var(--surface); color: var(--text-2); border-radius: 6px; padding: .24rem .6rem;
    cursor: pointer; display: inline-flex; align-items: center; gap: .35rem; white-space: nowrap;
    transition: background .15s, color .15s, border-color .15s; }
  .copy-prompt:hover { border-color: var(--accent); color: var(--text); }
  .copy-prompt svg { width: 13px; height: 13px; }

  .promptbox.master { margin-top: 2.6rem; border: 1.5px solid var(--accent); border-left-width: 3px;
    background: var(--accent-weak); box-shadow: var(--shadow); scroll-margin-top: 5rem; }
  .promptbox.master .phead { border-bottom-color: color-mix(in srgb, var(--accent) 32%, transparent);
    font-size: .82rem; }
  .promptbox.master .phead b { font-size: .98rem; }
  .promptbox.master .master-lead { font-size: .88rem; color: var(--text-2); font-family: var(--sans);
    padding: .8rem .9rem 0; margin: 0; }
  .promptbox.master .ptext { margin: .8rem; background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; max-height: 24rem; overflow: auto; }

  /* ---- jury panel ---- */
  details.jury { margin: .75rem 0 0; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-2); }
  details.jury > summary { cursor: pointer; list-style: none; padding: .5rem .7rem; font-family: var(--mono);
    font-size: .77rem; color: var(--text-2); display: flex; align-items: center; gap: .5rem; }
  details.jury > summary::-webkit-details-marker { display: none; }
  details.jury > summary .chev { transition: transform .18s; width: 14px; height: 14px; }
  details.jury[open] > summary .chev { transform: rotate(90deg); }
  details.jury > summary b { color: var(--text); font-weight: 600; }
  .votes { padding: 0 .7rem .7rem; display: flex; flex-direction: column; gap: .4rem; }
  .vote { display: grid; grid-template-columns: 7.5rem auto 1fr; align-items: center; gap: .5rem;
    font-family: var(--mono); font-size: .76rem; }
  .vote .j { color: var(--text-2); }
  .vote .v { font-weight: 700; text-transform: uppercase; letter-spacing: .05em; font-size: .68rem;
    border-radius: 5px; padding: .1rem .4rem; }
  .v.fail { color: var(--block); background: var(--block-bg); }
  .v.warn { color: var(--warn); background: var(--warn-bg); }
  .v.pass { color: var(--pass); background: var(--pass-bg); }
  .vote .c { color: var(--text-2); }
  .consensus { margin-top: .2rem; padding-top: .5rem; border-top: 1px solid var(--border);
    font-family: var(--mono); font-size: .74rem; color: var(--text-2); display: flex; flex-wrap: wrap; gap: .3rem 1rem; }
  .consensus b { color: var(--text); }

  /* ---- footer ---- */
  footer { margin-top: 2.75rem; padding-top: 1.25rem; border-top: 1px solid var(--border);
    font-size: .8rem; color: var(--text-2); }
  footer .caveats { display: flex; flex-direction: column; gap: .4rem; }
  footer .caveat { display: flex; gap: .5rem; align-items: flex-start; }
  footer .caveat svg { width: 15px; height: 15px; flex: none; margin-top: .15rem; color: var(--warn); }
  footer .gen { font-family: var(--mono); font-size: .74rem; margin-top: 1rem; opacity: .8; }
  .hidden { display: none !important; }

  @media (prefers-reduced-motion: reduce) { * { transition: none !important; } .chev { transition: none !important; }
    html { scroll-behavior: auto !important; } }
  @media (max-width: 560px) {
    .masthead { align-items: flex-start; }
    .vote { grid-template-columns: 6rem auto; }
    .vote .c { grid-column: 1 / -1; }
  }"""

JS = """  (function () {
    // severity filter
    var chips = document.querySelectorAll('.chip[data-filter]');
    var cards = document.querySelectorAll('.card[data-sev]');
    var groups = document.querySelectorAll('section[data-group]');
    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        var f = chip.getAttribute('data-filter');
        chips.forEach(function (c) { c.setAttribute('aria-pressed', c === chip ? 'true' : 'false'); });
        cards.forEach(function (card) {
          card.classList.toggle('hidden', !(f === 'all' || card.getAttribute('data-sev') === f));
        });
        groups.forEach(function (g) {
          var any = g.querySelectorAll('.card:not(.hidden)').length > 0;
          g.classList.toggle('hidden', !any);
        });
      });
    });

    // copy-fix
    document.querySelectorAll('.copy[data-copy]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var txt = btn.getAttribute('data-copy');
        var done = function () {
          var label = btn.lastChild;
          var prev = label.nodeValue;
          label.nodeValue = 'Copied';
          setTimeout(function () { label.nodeValue = prev; }, 1400);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(txt).then(done).catch(done);
        } else { done(); }
      });
    });

    // copy full fix prompts
    document.querySelectorAll('.copy-prompt').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var box = btn.closest('.promptbox');
        var pre = box ? box.querySelector('.ptext') : null;
        var txt = pre ? pre.textContent : '';
        var label = btn.querySelector('.lbl');
        var done = function () {
          if (!label) return;
          var prev = label.textContent;
          label.textContent = 'Copied to clipboard';
          setTimeout(function () { label.textContent = prev; }, 1500);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(txt).then(done).catch(done);
        } else { done(); }
      });
    });

    // theme toggle
    var root = document.documentElement;
    var btn = document.getElementById('themeBtn');
    var lbl = document.getElementById('themeLbl');
    function current() {
      return root.getAttribute('data-theme')
        || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    }
    function sync() { lbl.textContent = current() === 'dark' ? 'Dark' : 'Light'; }
    btn.addEventListener('click', function () {
      root.setAttribute('data-theme', current() === 'dark' ? 'light' : 'dark');
      sync();
    });
    sync();
  })();"""
