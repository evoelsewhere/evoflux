"""Tests for EDGE_IMPORTS emission from Python, TypeScript, Go, Rust parsers."""

from __future__ import annotations

from pathlib import Path

from app.services.code_graph.parsers.ecmascript import (
    JavaScriptParser,
    TypeScriptParser,
)
from app.services.code_graph.parsers.go import GoParser
from app.services.code_graph.parsers.python import PythonParser
from app.services.code_graph.parsers.rust import RustParser
from app.services.code_graph.types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


# ── Python imports ───────────────────────────────────────────────────────────


def test_python_from_import():
    source = b"""from pathlib import Path
from os.path import join, exists
"""
    result = PythonParser().parse(file_path="main.py", source=source)
    names = _import_names(result)
    assert "Path" in names
    assert "join" in names
    assert "exists" in names


def test_python_from_import_alias():
    source = b"""from collections import OrderedDict as OD
from ..models import Base as ModelBase
"""
    result = PythonParser().parse(file_path="main.py", source=source)
    names = _import_names(result)
    # We record the original name, not the alias
    assert "OrderedDict" in names
    assert "Base" in names
    aliases = {
        edge.dst_name: edge.local_name
        for edge in result.edges
        if edge.kind == EDGE_IMPORTS
    }
    assert aliases["OrderedDict"] == "OD"
    assert aliases["Base"] == "ModelBase"


def test_python_bare_import():
    source = b"""import os
import os.path
import json
"""
    result = PythonParser().parse(file_path="main.py", source=source)
    names = _import_names(result)
    assert "os" in names
    assert "path" in names
    assert "json" in names


def test_python_relative_import():
    source = b"""from . import sibling
from .utils import helper
"""
    result = PythonParser().parse(file_path="pkg/main.py", source=source)
    names = _import_names(result)
    assert "sibling" in names
    assert "helper" in names


# ── TypeScript/JavaScript imports ────────────────────────────────────────────


def test_ts_named_imports():
    source = b"""import { foo, bar } from './utils';
import { type Config } from './config';
"""
    result = TypeScriptParser().parse(file_path="main.ts", source=source)
    names = _import_names(result)
    assert "foo" in names
    assert "bar" in names
    assert "Config" in names


def test_ts_default_import():
    source = b"""import React from 'react';
import App from './App';
"""
    result = TypeScriptParser().parse(file_path="main.ts", source=source)
    names = _import_names(result)
    assert "React" in names
    assert "App" in names


def test_ts_namespace_import():
    source = b"""import * as path from 'path';
"""
    result = TypeScriptParser().parse(file_path="main.ts", source=source)
    names = _import_names(result)
    assert "path" in names


def test_ts_aliased_import():
    source = b"""import { useState as useStateHook } from 'react';
"""
    result = TypeScriptParser().parse(file_path="main.ts", source=source)
    names = _import_names(result)
    # Should capture the original name 'useState'
    assert "useState" in names
    edge = next(edge for edge in result.edges if edge.kind == EDGE_IMPORTS)
    assert edge.local_name == "useStateHook"


def test_js_imports():
    source = b"""import { readFile } from 'fs/promises';
import express from 'express';
"""
    result = JavaScriptParser().parse(file_path="app.js", source=source)
    names = _import_names(result)
    assert "readFile" in names
    assert "express" in names


# ── Go imports ───────────────────────────────────────────────────────────────


def test_go_import_single():
    source = b"""package main

import "fmt"
"""
    result = GoParser().parse(file_path="main.go", source=source)
    names = _import_names(result)
    assert "fmt" in names


def test_go_import_group():
    source = b"""package main

import (
    "fmt"
    "os"
    "net/http"
)
"""
    result = GoParser().parse(file_path="main.go", source=source)
    names = _import_names(result)
    assert "fmt" in names
    assert "os" in names
    assert "http" in names


def test_go_import_alias():
    source = b"""package main

import (
    mylog "github.com/user/logger"
)
"""
    result = GoParser().parse(file_path="main.go", source=source)
    edge = next(edge for edge in result.edges if edge.kind == EDGE_IMPORTS)
    assert edge.dst_name == "logger"
    assert edge.local_name == "mylog"


def test_rust_import_alias_keeps_target_and_local_names():
    source = b"""use crate::models::{Post as AliasPost};
"""
    result = RustParser().parse(file_path="lib.rs", source=source)
    edge = next(edge for edge in result.edges if edge.kind == EDGE_IMPORTS)
    assert edge.dst_name == "Post"
    assert edge.local_name == "AliasPost"


# ── Rust imports ─────────────────────────────────────────────────────────────


def test_rust_use_single():
    source = b"""use std::collections::HashMap;
use std::io::Result;
"""
    result = RustParser().parse(file_path="main.rs", source=source)
    names = _import_names(result)
    assert "HashMap" in names
    assert "Result" in names


def test_rust_use_list():
    source = b"""use crate::models::{User, Post};
"""
    result = RustParser().parse(file_path="main.rs", source=source)
    names = _import_names(result)
    assert "User" in names
    assert "Post" in names


def test_rust_use_super():
    source = b"""use super::utils;
use crate::config;
"""
    result = RustParser().parse(file_path="lib.rs", source=source)
    names = _import_names(result)
    assert "utils" in names
    assert "config" in names


# ── Cross-file resolution via indexer ────────────────────────────────────────


def test_import_edge_resolves_in_indexer():
    """Import edges resolve to target definitions in the workspace index."""
    from app.services.code_graph.indexer import index_files
    from app.services.code_graph.parsers.registry import default_registry
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create two files: utils.py defines helper, main.py imports it
        os.makedirs(os.path.join(tmpdir, "pkg"))
        utils_path = os.path.join(tmpdir, "pkg", "utils.py")
        main_path = os.path.join(tmpdir, "pkg", "main.py")

        with open(utils_path, "w") as f:
            f.write("def helper():\n    pass\n")
        with open(main_path, "w") as f:
            f.write("from .utils import helper\n\ndef run():\n    helper()\n")

        registry = default_registry()
        result = index_files(
            tmpdir,
            ["pkg/utils.py", "pkg/main.py"],
            registry=registry,
        )

        # The import edge from main.py should resolve to helper in utils.py
        import_edges = [e for e in result.edges if e.kind == EDGE_IMPORTS]
        assert len(import_edges) == 1
        assert "utils.py" in import_edges[0].dst_key
        assert "helper" in import_edges[0].dst_key


def test_ts_named_imports_resolve_to_distinct_symbols(tmp_path: Path):
    """Imports sharing one module path must not overwrite each other."""
    from app.services.code_graph.indexer import index_workspace

    (tmp_path / "lib.ts").write_text(
        "export class First {}\nexport class Second {}\n", encoding="utf-8"
    )
    (tmp_path / "main.ts").write_text(
        "import { First, Second } from './lib';\n", encoding="utf-8"
    )

    result = index_workspace(tmp_path)
    destinations = {
        edge.dst_key
        for edge in result.edges
        if edge.kind == EDGE_IMPORTS and edge.src_key.startswith("main.ts::")
    }

    assert len(destinations) == 2
    assert any("First" in key for key in destinations)
    assert any("Second" in key for key in destinations)


def test_python_import_alias_resolves_calls(tmp_path: Path):
    from app.services.code_graph.indexer import index_workspace
    from app.services.code_graph.types import EDGE_CALLS

    (tmp_path / "lib.py").write_text("class Original:\n    pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from lib import Original as Alias\n\n"
        "def build():\n"
        "    return Alias()\n",
        encoding="utf-8",
    )

    result = index_workspace(tmp_path)
    call_edges = [edge for edge in result.edges if edge.kind == EDGE_CALLS]

    assert len(call_edges) == 1
    assert "lib.py::Original" in call_edges[0].dst_key


def test_ts_import_alias_resolves_calls(tmp_path: Path):
    from app.services.code_graph.indexer import index_workspace
    from app.services.code_graph.types import EDGE_CALLS

    (tmp_path / "lib.ts").write_text(
        "export class Original {}\n", encoding="utf-8"
    )
    (tmp_path / "main.ts").write_text(
        "import { Original as Alias } from './lib';\n"
        "export function build() { return new Alias(); }\n",
        encoding="utf-8",
    )

    result = index_workspace(tmp_path)
    call_edges = [edge for edge in result.edges if edge.kind == EDGE_CALLS]

    assert len(call_edges) == 1
    assert "lib.ts::Original" in call_edges[0].dst_key


def test_incremental_import_scope_uses_definition_file_metadata(tmp_path: Path):
    from app.services.code_graph.indexer import ExistingDef, index_files
    from app.services.code_graph.types import EDGE_CALLS, NODE_CLASS, NODE_FILE

    (tmp_path / "main.py").write_text(
        "import lib as alias\n\n"
        "def build():\n"
        "    return alias.Original()\n",
        encoding="utf-8",
    )
    existing_defs = [
        ExistingDef(
            key="lib-file-uuid",
            name="lib.py",
            kind=NODE_FILE,
            file_path="lib.py",
        ),
        ExistingDef(
            key="lib-node-uuid",
            name="Original",
            kind=NODE_CLASS,
            file_path="lib.py",
        ),
        ExistingDef(
            key="other-node-uuid",
            name="Original",
            kind=NODE_CLASS,
            file_path="other.py",
        ),
    ]

    result = index_files(
        tmp_path,
        ["main.py"],
        existing_defs=existing_defs,
        known_file_paths=frozenset({"lib.py", "other.py", "main.py"}),
    )
    call_edges = [edge for edge in result.edges if edge.kind == EDGE_CALLS]

    assert len(call_edges) == 1
    assert call_edges[0].dst_key == "lib-node-uuid"


def test_go_import_scope_resolves_across_package_directory(tmp_path: Path):
    from app.services.code_graph.indexer import index_workspace
    from app.services.code_graph.types import EDGE_CALLS

    (tmp_path / "go.mod").write_text("module example.com/app\n", encoding="utf-8")
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    (tmp_path / "first" / "worker.go").write_text(
        "package first\n\nfunc Work() {}\n", encoding="utf-8"
    )
    (tmp_path / "second" / "worker.go").write_text(
        "package second\n\nfunc Work() {}\n", encoding="utf-8"
    )
    (tmp_path / "main.go").write_text(
        'package main\n\nimport worker "example.com/app/first"\n\n'
        "func Run() { worker.Work() }\n",
        encoding="utf-8",
    )

    result = index_workspace(tmp_path)
    call_edges = [edge for edge in result.edges if edge.kind == EDGE_CALLS]

    assert len(call_edges) == 1
    assert call_edges[0].dst_key.startswith("first/worker.go::")
    assert result.unresolved_references == []
