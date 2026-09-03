"""Exact behavioral contracts for Ruby graph extraction."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import cast

from tree_sitter import Node

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_DECORATED_BY,
    EDGE_IMPORTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_METHOD,
    NODE_MODULE,
    NODE_PROPERTY,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.ruby import (
    RubyParser,
    _collect_ruby_constant_types,
    _ruby_constant_path,
    _ruby_expression_path,
)


@dataclass
class _FakeNode:
    type: str
    start_byte: int = 0
    end_byte: int = 0
    parent: _FakeNode | None = None
    prev_named_sibling: _FakeNode | None = None
    children: list[_FakeNode] = field(default_factory=list)
    fields: dict[str, _FakeNode] = field(default_factory=dict)

    @property
    def named_children(self) -> list[_FakeNode]:
        return self.children

    def child_by_field_name(self, name: str) -> _FakeNode | None:
        return self.fields.get(name)


def _descendants(node: Node):
    for child in node.named_children:
        yield child
        yield from _descendants(child)


def _nodes_of_type(parser: RubyParser, source: bytes, node_type: str):
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


def _named_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], edge.dst_name)
        for edge in result.edges
        if edge.kind == kind and edge.dst_name is not None
    ]


def test_ruby_symbols_types_calls_mixins_docs_and_modifiers_are_exact() -> None:
    source = b"""require "active_support/deep/core_ext"
# User docs
class Admin::User < Core::Record
  include Trackable
  extend Factory
  CONST = Config.new
  attr_reader :name, "age"
  attr_accessor :email
  attr_writer :secret
  self.attr_reader :ignored
  sig { params(repo: Repo, input: Types::Input, flag: T::Boolean, yes: TrueClass, no: FalseClass).returns(Result) }
  final
  private
  # visibility marker
  def run(repo)
    helper(); client.api.call(); self.local(); Core::Factory.create()
  end
  def self.build(name); new(name); end
end
module Utils
  module_function
  def helper; puts "x"; end
end
VALUE = Config.new
"""
    result = RubyParser().parse(file_path="user.rb", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter(
        (node.kind, node.qualified_name) for node in result.nodes
    ) == Counter(
        {
            ("file", "user.rb"): 1,
            (NODE_CLASS, "Admin.User"): 1,
            (NODE_PROPERTY, "Admin.User.CONST"): 1,
            (NODE_METHOD, "Admin.User.name"): 1,
            (NODE_METHOD, "Admin.User.age"): 1,
            (NODE_METHOD, "Admin.User.email"): 1,
            (NODE_METHOD, "Admin.User.email="): 1,
            (NODE_METHOD, "Admin.User.secret="): 1,
            (NODE_METHOD, "Admin.User.run"): 1,
            (NODE_METHOD, "Admin.User.build"): 1,
            (NODE_MODULE, "Utils"): 1,
            (NODE_METHOD, "Utils.helper"): 1,
            (NODE_VARIABLE, "VALUE"): 1,
        }
    )
    assert nodes["Admin.User"].docstring == "User docs"
    assert _named_edges(result, EDGE_IMPORTS) == [("user.rb", "core_ext")]
    assert _named_edges(result, EDGE_INHERITS) == [("Admin.User", "Core.Record")]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("Admin.User", "Trackable"),
        ("Admin.User", "Factory"),
        ("Admin.User.run", "Repo"),
        ("Admin.User.run", "Types.Input"),
        ("Admin.User.run", "Result"),
    ]
    assert _named_edges(result, EDGE_DECORATED_BY) == [
        ("Admin.User.run", "private"),
        ("Admin.User.run", "final"),
        ("Utils.helper", "module_function"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("Admin.User.CONST", "Config.new"),
        ("Admin.User.run", "helper"),
        ("Admin.User.run", "client.api.call"),
        ("Admin.User.run", "client.api"),
        ("Admin.User.run", "this.local"),
        ("Admin.User.run", "Core.Factory.create"),
        ("Admin.User.build", "new"),
        ("Utils.helper", "puts"),
        ("VALUE", "Config.new"),
    ]


def test_ruby_top_level_methods_constants_and_namespaces_are_exact() -> None:
    source = b"""TOP = 1
Outer::Inner::SCOPED = 3
def execute; service.run; end
module Outer
  class Inner
    VALUE = 2
  end
end
module Admin::Tools; end
"""
    result = RubyParser().parse(file_path="main.rb", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}
    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "main.rb"),
        (NODE_VARIABLE, "TOP"),
        (NODE_VARIABLE, "Outer.Inner.SCOPED"),
        ("function", "execute"),
        (NODE_MODULE, "Outer"),
        (NODE_CLASS, "Outer.Inner"),
        (NODE_PROPERTY, "Outer.Inner.VALUE"),
        (NODE_MODULE, "Admin.Tools"),
    }
    assert nodes["Outer.Inner.SCOPED"].name == "SCOPED"
    assert nodes["Admin.Tools"].name == "Tools"
    assert _named_edges(result, EDGE_CALLS) == [("execute", "service.run")]


def test_ruby_constant_and_expression_helpers_are_exact() -> None:
    source = b"::Core::Types::Input; client.api.call; self.local"
    parser = RubyParser()
    scope = _nodes_of_type(parser, source, "scope_resolution")[0]
    calls = _nodes_of_type(parser, source, "call")
    root = parser._get_parser().parse(source).root_node
    out: list[str] = []
    _collect_ruby_constant_types(scope, source, out)

    assert _ruby_constant_path(scope, source) == "Core.Types.Input"
    assert _ruby_constant_path(root, source) is None
    assert out == ["Core.Types.Input"]
    assert _ruby_expression_path(calls[0], source) == "client.api.call"
    assert _ruby_expression_path(calls[-1], source) == "this.local"
    assert _ruby_expression_path(root, source) is None


def test_ruby_multiline_docs_keep_source_order_and_boundaries() -> None:
    source = b"""#X first X
#X second X
class Documented; end
"""
    result = RubyParser().parse(file_path="docs.rb", source=source)
    node = next(node for node in result.nodes if node.name == "Documented")
    assert node.docstring == "X first X\nX second X"


def test_ruby_non_matching_nodes_do_not_emit_language_hooks() -> None:
    parser = RubyParser()
    source = b"1 + 2"
    root = parser._get_parser().parse(source).root_node
    assert parser.classify(root, source, inside_class=False) is None
    assert parser.synthetic_definitions(root, source, inside_class=False) == []
    assert parser.call_target(root, source) is None
    assert parser.reference_targets(root, source) == []
    assert parser.import_refs(root, source) == []
    assert parser.supertypes(root, source) == []
    assert parser.decorators(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None
    assert parser.identifier_reference_targets(root, source) == []


def test_ruby_malformed_macros_and_dynamic_requires_fail_closed() -> None:
    parser = RubyParser()
    malformed_call = _FakeNode("call")
    unknown = _FakeNode("unknown")
    assert (
        parser.synthetic_definitions(cast(Node, malformed_call), b"", inside_class=True)
        == []
    )
    assert (
        parser.synthetic_definitions(cast(Node, unknown), b"", inside_class=False) == []
    )

    result = parser.parse(
        file_path="dynamic.rb",
        source=b'require "#{dynamic_name}"',
    )
    assert _named_edges(result, EDGE_IMPORTS) == []


def test_ruby_dynamic_require_does_not_hide_later_static_require() -> None:
    result = RubyParser().parse(
        file_path="mixed.rb",
        source=b'require "#{dynamic_name}", "static/path"',
    )
    assert _named_edges(result, EDGE_IMPORTS) == [("mixed.rb", "path")]


def test_ruby_non_sig_call_does_not_create_type_references() -> None:
    source = b"""class Plain
  configure(Repo)
  def run; end
end
"""
    parser = RubyParser()
    method = _nodes_of_type(parser, source, "method")[0]
    assert parser.type_refs(method, source) == []
