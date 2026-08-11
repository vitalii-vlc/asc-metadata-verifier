"""Optional higher-fidelity Swift backend via a BYO subprocess helper. There is
no importable SwiftSyntax pip package (it resolves through a Swift toolchain),
so -- like the BYO embedder in persistence -- the user supplies a command that
reads a source file (path on argv) and prints AST-surface JSON to stdout. Any
failure degrades to unavailable; the caller (build_parser) then falls back to
tree-sitter. Never fabricates an AST.

JSON contract (stdout):
  {"symbols": [...], "imports": [...],
   "strings": [{"value": str, "line": int}],
   "calls":   [{"name": str, "line": int}]}"""

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
        return [
            CallSite(name=name, file=self.file, line=int(c.get("line", 1)))
            for c in self._d.get("calls", [])
            if c.get("name") == name
        ]

    def string_literals(self) -> list[StringLit]:
        return [
            StringLit(value=str(s.get("value", "")), file=self.file, line=int(s.get("line", 1)))
            for s in self._d.get("strings", [])
        ]


class SwiftSyntaxParser:
    backend_name = "swiftsyntax"

    def __init__(self, swiftsyntax_cmd: str | None = None):
        self._cmd = swiftsyntax_cmd

    def available(self) -> bool:
        if not self._cmd:
            return False
        try:
            argv = shlex.split(self._cmd)
            if not argv:
                return False
            proc = subprocess.run(  # noqa: S603 - subprocess with a user-provided cmd IS the feature
                argv, input=b"", capture_output=True, timeout=10
            )
            return proc.returncode in (0, 1, 2)
        except (OSError, subprocess.SubprocessError):
            return False

    def parse(self, source: SourceFile) -> SourceAST:
        argv = [*shlex.split(self._cmd or ""), source.path]
        proc = subprocess.run(argv, capture_output=True, timeout=30)  # noqa: S603
        data = json.loads(proc.stdout.decode("utf-8", "replace"))
        return _JsonAST(source.path, data)
