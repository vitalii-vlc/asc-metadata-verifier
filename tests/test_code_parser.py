"""Tests for the tree-sitter parser backend (v2 sub-project C, Task 3).

Requires the `[code]` extra; skipped cleanly when tree-sitter is absent."""

import pytest

pytest.importorskip("tree_sitter_language_pack")

from asc_metadata_verifier.code.parser import build_parser  # noqa: E402
from asc_metadata_verifier.code.project import SourceFile  # noqa: E402


def _ast(text, lang="swift"):
    return build_parser().parse(SourceFile(path="A.swift", language=lang, text=text))


def test_symbols_include_type_reference():
    ast = _ast("import UIKit\nlet w = UIWebView()\n")
    assert "UIWebView" in ast.symbols()
    assert "UIKit" in ast.imports()


def test_symbol_in_comment_is_not_reported():
    ast = _ast("// UIWebView is deprecated\nlet x = 1\n")
    assert "UIWebView" not in ast.symbols()  # AST beats regex: comments excluded


def test_string_literals_carry_value_and_line():
    ast = _ast('let u = "http://insecure.example.com"\n')
    lits = [s.value for s in ast.string_literals()]
    assert any("http://insecure.example.com" in v for v in lits)
    assert ast.string_literals()[0].line >= 1


def test_objc_string_literal_has_clean_value():
    ast = _ast('NSString *u = @"http://x.com";\n', lang="objc")
    assert any(v.startswith("http://x.com") for v in [s.value for s in ast.string_literals()])


def test_calls_match_by_callee_name():
    ast = _ast("canOpenURL(url)\n")
    assert [c.name for c in ast.calls("canOpenURL")] == ["canOpenURL"]


def test_backend_name_and_available():
    p = build_parser()
    assert p.backend_name == "tree-sitter" and p.available() is True
