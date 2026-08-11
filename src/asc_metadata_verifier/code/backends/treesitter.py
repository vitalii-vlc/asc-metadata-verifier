"""Default offline parser backend. Lazy-imports tree-sitter so the base
install (no `[code]` extra) never needs it. The query surface walks the
syntax tree collecting identifier node texts (symbols), import identifiers,
call callees, and string-CONTENT node texts -- token-accurate, so a symbol
inside a comment or string is NOT a false positive (the win over regex).

Node types verified against tree-sitter-language-pack 1.14.3 (Swift +
Obj-C grammars): swift identifiers are `simple_identifier`; obj-c uses
`identifier`/`type_identifier`. String *content* lives in `line_str_text`
(swift) / `string_content` (obj-c) child nodes -- read those directly so
obj-c `@"..."` literals yield a clean value, not a `@"`-prefixed one."""

from __future__ import annotations

from functools import cache

from asc_metadata_verifier.code.parser import CallSite, SourceAST, StringLit
from asc_metadata_verifier.code.project import SourceFile

_IDENT_NODES = {"simple_identifier", "type_identifier", "identifier"}
_STRING_CONTENT_NODES = {"line_str_text", "string_content"}
_IMPORT_NODES = {"import_declaration", "preproc_include"}
_CALL_NODES = {"call_expression", "call_expr"}


@cache
def _language_parser(language: str):
    from tree_sitter_language_pack import get_parser

    return get_parser("swift" if language == "swift" else "objc")


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


class TreeSitterAST:
    def __init__(self, file: str, root, source_bytes: bytes):
        self.file = file
        self._root = root
        self._src = source_bytes

    def _text(self, node) -> str:
        return self._src[node.start_byte : node.end_byte].decode("utf-8", "replace")

    def symbols(self) -> set[str]:
        return {self._text(n) for n in _walk(self._root) if n.type in _IDENT_NODES}

    def imports(self) -> set[str]:
        out: set[str] = set()
        for node in _walk(self._root):
            if node.type in _IMPORT_NODES:
                for ident in _walk(node):
                    if ident.type in _IDENT_NODES:
                        out.add(self._text(ident))
        return out

    def calls(self, name: str) -> list[CallSite]:
        out: list[CallSite] = []
        for node in _walk(self._root):
            if node.type in _CALL_NODES and node.children:
                callee = self._text(node.children[0]).split("(")[0].split(".")[-1]
                if callee == name:
                    out.append(CallSite(name=name, file=self.file, line=node.start_point[0] + 1))
        return out

    def string_literals(self) -> list[StringLit]:
        out: list[StringLit] = []
        for node in _walk(self._root):
            if node.type in _STRING_CONTENT_NODES:
                out.append(
                    StringLit(value=self._text(node), file=self.file, line=node.start_point[0] + 1)
                )
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
