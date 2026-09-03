"""Exact behavioral contracts for Lua and Luau graph extraction."""

from __future__ import annotations

from collections import Counter

import pytest

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_IMPORTS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.lua import LuaParser, LuauParser


def _named_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], edge.dst_name)
        for edge in result.edges
        if edge.kind == kind and edge.dst_name is not None
    ]


def test_lua_symbols_calls_imports_docs_and_ownership_are_exact() -> None:
    source = b"""local socket = require("socket.http")
--- Deep docs
--- second line
function M.Sub:deep(input)
  helper()
  client.api.call()
  self:localCall()
  local temporary = create()
end
function M.Sub.dot() end
local first = function() local hidden = 1; nested() end
second = function() end
M.Sub.value = 1
local global = Config.new()
"""
    result = LuaParser().parse(file_path="main.lua", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter(
        (node.kind, node.qualified_name) for node in result.nodes
    ) == Counter(
        {
            ("file", "main.lua"): 1,
            (NODE_VARIABLE, "socket"): 1,
            (NODE_METHOD, "M.Sub.deep"): 1,
            (NODE_METHOD, "M.Sub.dot"): 1,
            (NODE_FUNCTION, "first"): 1,
            (NODE_FUNCTION, "second"): 1,
            (NODE_VARIABLE, "M.Sub.value"): 1,
            (NODE_VARIABLE, "global"): 1,
        }
    )
    assert "temporary" not in nodes
    assert "hidden" not in nodes
    assert nodes["M.Sub.deep"].name == "deep"
    assert nodes["M.Sub.dot"].name == "dot"
    assert nodes["M.Sub.value"].name == "value"
    assert nodes["M.Sub.deep"].docstring == "Deep docs\nsecond line"
    assert _named_edges(result, EDGE_CALLS) == [
        ("M.Sub.deep", "helper"),
        ("M.Sub.deep", "client.api.call"),
        ("M.Sub.deep", "self.localCall"),
        ("M.Sub.deep", "create"),
        ("first", "nested"),
        ("global", "Config.new"),
    ]
    assert _named_edges(result, EDGE_IMPORTS) == [("socket", "socket")]
    imported = next(edge for edge in result.edges if edge.kind == EDGE_IMPORTS)
    assert imported.module_path == "socket.http"
    assert imported.local_name == "socket"
    assert _named_edges(result, EDGE_REFERENCES) == []


def test_luau_types_calls_imports_generics_and_docs_are_exact() -> None:
    source = b"""--- Result docs
export type Result<T> = { value: T, config: Config }
export type Handler = (Input) -> Output
--- Map docs
local function map<T, U>(input: Input<T>, fn: (T) -> U): Result<U>
  client.api.call()
  self:localCall()
  return nil
end
local function noReturn(input: InputOnly)
  client.runtime.execute()
end
local value: Map<Key, Value>? = make()
local repo: Repo = require(script.Parent.Repo)
local callback = function(input: CallbackInput): CallbackOutput return input end
"""
    result = LuauParser().parse(file_path="main.luau", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter(
        (node.kind, node.qualified_name) for node in result.nodes
    ) == Counter(
        {
            ("file", "main.luau"): 1,
            (NODE_CLASS, "Result"): 1,
            (NODE_CLASS, "Handler"): 1,
            (NODE_FUNCTION, "map"): 1,
            (NODE_FUNCTION, "noReturn"): 1,
            (NODE_VARIABLE, "value"): 1,
            (NODE_VARIABLE, "repo"): 1,
            (NODE_FUNCTION, "callback"): 1,
        }
    )
    assert nodes["Result"].docstring == "Result docs"
    assert nodes["map"].docstring == "Map docs"
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("Result", "Config"),
        ("Handler", "Input"),
        ("Handler", "Output"),
        ("map", "Input"),
        ("map", "Result"),
        ("noReturn", "InputOnly"),
        ("value", "Map"),
        ("value", "Key"),
        ("value", "Value"),
        ("repo", "Repo"),
        ("callback", "CallbackInput"),
        ("callback", "CallbackOutput"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("map", "client.api.call"),
        ("map", "self.localCall"),
        ("noReturn", "client.runtime.execute"),
        ("value", "make"),
    ]
    assert _named_edges(result, EDGE_IMPORTS) == [("repo", "repo")]
    imported = next(edge for edge in result.edges if edge.kind == EDGE_IMPORTS)
    assert imported.module_path == "script.Parent.Repo"
    assert imported.local_name == "repo"


@pytest.mark.parametrize("parser", [LuaParser(), LuauParser()])
def test_lua_dynamic_receiver_and_non_doc_comments_are_conservative(parser) -> None:
    source = b"""-- ordinary lead-in
---Compact docs
function plain() factory():run() end
-- ordinary comment
function undocumented() end
local a, b = 1
local c = 1, 2
"""
    result = parser.parse(file_path=f"main{parser.extensions[0]}", source=source)
    plain = next(node for node in result.nodes if node.qualified_name == "plain")

    undocumented = next(
        node for node in result.nodes if node.qualified_name == "undocumented"
    )

    assert plain.docstring == "Compact docs"
    assert undocumented.docstring is None
    assert _named_edges(result, EDGE_CALLS) == [
        ("plain", "run"),
        ("plain", "factory"),
    ]
    assert not any(node.qualified_name in {"a", "b", "c"} for node in result.nodes)


@pytest.mark.parametrize("parser", [LuaParser(), LuauParser()])
def test_lua_language_hooks_reject_unrelated_nodes(parser) -> None:
    source = b"return value"
    root = parser._get_parser().parse(source).root_node

    assert parser.classify(root, source, inside_class=False) is None
    assert parser.call_target(root, source) is None
    assert parser.import_refs(root, source) == []
    assert parser.supertypes(root, source) == []
    assert parser.docstring(root, source) is None
    assert parser.identifier_reference_targets(root, source) == []
    if isinstance(parser, LuauParser):
        assert parser.type_refs(root, source) == []
