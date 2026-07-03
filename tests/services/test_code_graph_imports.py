"""Tests for EDGE_IMPORTS emission from Python, TypeScript, Go, Rust parsers."""

from __future__ import annotations

import pytest

from app.services.code_graph.parsers.ecmascript import TypeScriptParser, JavaScriptParser
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
    names = _import_names(result)
    # Aliased: use the alias name
    assert "mylog" in names


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
