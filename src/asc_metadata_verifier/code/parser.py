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
