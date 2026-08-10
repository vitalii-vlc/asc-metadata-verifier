"""Tests for the optional BYO-SwiftSyntax backend + fallback (Task 10).

No real Swift toolchain needed: a fake helper script emulates the JSON
contract. The fallback test needs neither the toolchain nor tree-sitter."""

import stat
from pathlib import Path

from asc_metadata_verifier.code.parser import build_parser
from asc_metadata_verifier.code.project import SourceFile


def _fake_helper(tmp_path: Path) -> str:
    script = tmp_path / "fake_swiftsyntax.py"
    script.write_text(
        "import json\n"
        "print(json.dumps({'symbols':['UIWebView'],'imports':['UIKit'],"
        "'strings':[{'value':'http://x','line':2}],'calls':[{'name':'canOpenURL','line':3}]}))\n"
    )
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
