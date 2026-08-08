"""Tests for EDGE_IMPORTS emission from the Lua/Luau parsers."""

from __future__ import annotations

from app.services.code_index.parsers.lua import LuaParser, LuauParser
from app.services.code_index.graph_types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


def _import_module_paths(result):
    return [e.module_path for e in result.edges if e.kind == EDGE_IMPORTS]


def test_lua_local_require_assignment():
    source = b"""local socket = require("socket.http")
"""
    result = LuaParser().parse(file_path="main.lua", source=source)
    names = _import_names(result)
    assert "socket" in names
    assert "socket.http" in _import_module_paths(result)


def test_lua_bare_string_call_require():
    source = b"""require "mypkg.utils"
"""
    result = LuaParser().parse(file_path="main.lua", source=source)
    names = _import_names(result)
    module_paths = _import_module_paths(result)
    assert "mypkg.utils" in module_paths
    # No assignment target — falls back to the last dotted segment.
    assert "utils" in names


def test_lua_multi_assignment_require():
    source = b"""local a, b = require("foo.bar")
"""
    result = LuaParser().parse(file_path="main.lua", source=source)
    names = _import_names(result)
    module_paths = _import_module_paths(result)
    # First variable in the assignment list is the bound name.
    assert "a" in names
    assert "foo.bar" in module_paths


def test_lua_require_single_quotes():
    source = b"""local json = require('dkjson')
"""
    result = LuaParser().parse(file_path="main.lua", source=source)
    names = _import_names(result)
    module_paths = _import_module_paths(result)
    assert "json" in names
    assert "dkjson" in module_paths


def test_lua_non_require_call_not_treated_as_import():
    source = b"""print("hello")
"""
    result = LuaParser().parse(file_path="main.lua", source=source)
    names = _import_names(result)
    assert names == []


def test_luau_local_require_assignment():
    source = b"""local socket = require("socket.http")
"""
    result = LuauParser().parse(file_path="main.luau", source=source)
    names = _import_names(result)
    assert "socket" in names
    assert "socket.http" in _import_module_paths(result)


def test_luau_bare_string_call_require():
    source = b"""require "mypkg.utils"
"""
    result = LuauParser().parse(file_path="main.luau", source=source)
    names = _import_names(result)
    module_paths = _import_module_paths(result)
    assert "mypkg.utils" in module_paths
    assert "utils" in names


def test_luau_require_dotted_path_expression():
    source = b"""local Module = require(script.Parent.Module)
"""
    result = LuauParser().parse(file_path="main.luau", source=source)
    names = _import_names(result)
    module_paths = _import_module_paths(result)
    assert "Module" in names
    assert "script.Parent.Module" in module_paths


def test_luau_non_require_call_not_treated_as_import():
    source = b"""print("hello")
"""
    result = LuauParser().parse(file_path="main.luau", source=source)
    names = _import_names(result)
    assert names == []
