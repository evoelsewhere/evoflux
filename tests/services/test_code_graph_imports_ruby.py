"""Tests for EDGE_IMPORTS emission from the Ruby parser."""

from __future__ import annotations

from app.services.code_index.parsers.ruby import RubyParser
from app.services.code_index.graph_types import EDGE_IMPORTS


def _import_names(result):
    return [e.dst_name for e in result.edges if e.kind == EDGE_IMPORTS]


def _import_module_paths(result):
    return [e.module_path for e in result.edges if e.kind == EDGE_IMPORTS]


def test_ruby_bare_require():
    source = b"""require 'json'
"""
    result = RubyParser().parse(file_path="main.rb", source=source)
    names = _import_names(result)
    assert "json" in names
    assert "json" in _import_module_paths(result)


def test_ruby_require_relative():
    source = b"""require_relative './helper'
"""
    result = RubyParser().parse(file_path="main.rb", source=source)
    names = _import_names(result)
    # Last path segment is used as the locally-used name
    assert "helper" in names
    assert "./helper" in _import_module_paths(result)


def test_ruby_require_nested_path():
    source = b"""require 'active_support/core_ext'
"""
    result = RubyParser().parse(file_path="main.rb", source=source)
    names = _import_names(result)
    assert "core_ext" in names
    assert "active_support/core_ext" in _import_module_paths(result)


def test_ruby_require_multiple_args():
    source = b"""require 'a', 'b'
"""
    result = RubyParser().parse(file_path="main.rb", source=source)
    names = _import_names(result)
    assert "a" in names
    assert "b" in names


def test_ruby_non_require_call_not_treated_as_import():
    source = b"""puts 'hello'
"""
    result = RubyParser().parse(file_path="main.rb", source=source)
    names = _import_names(result)
    assert names == []
