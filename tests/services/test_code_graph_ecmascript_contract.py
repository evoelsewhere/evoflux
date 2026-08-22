"""Exact behavioral contracts for JavaScript, TypeScript, and TSX graphs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest
from tree_sitter import Node

from app.services.code_index.graph_types import (
    EDGE_DECORATED_BY,
    EDGE_IMPLEMENTS,
    EDGE_IMPORTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_NAMESPACE,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.base import Definition, node_text
from app.services.code_index.parsers.ecmascript import (
    JavaScriptParser,
    TsxParser,
    TypeScriptParser,
    _module_ref_name,
    _static_value_name,
    _string_content,
)


@dataclass
class _FakeNode:
    type: str
    start_byte: int = 0
    end_byte: int = 0
    children: list[_FakeNode] = field(default_factory=list)
    fields: dict[str, _FakeNode] = field(default_factory=dict)

    def child_by_field_name(self, name: str) -> _FakeNode | None:
        return self.fields.get(name)

    @property
    def named_children(self) -> list[_FakeNode]:
        return self.children


def _descendants(node: Node):
    for child in node.named_children:
        yield child
        yield from _descendants(child)


def _nodes_of_type(parser, source: bytes, node_type: str) -> list[Node]:
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


@pytest.mark.parametrize(
    ("source", "node_type", "inside_class", "expected"),
    [
        (
            b"namespace API {}",
            "internal_module",
            False,
            Definition(NODE_NAMESPACE, "API", False),
        ),
        (
            b"abstract class Base {}",
            "abstract_class_declaration",
            False,
            Definition(NODE_CLASS, "Base", True),
        ),
        (
            b"interface Service {}",
            "interface_declaration",
            False,
            Definition(NODE_INTERFACE, "Service", False),
        ),
        (
            b"type Handler = () => void;",
            "type_alias_declaration",
            False,
            Definition(NODE_CLASS, "Handler", False),
        ),
        (
            b"enum State { Idle }",
            "enum_declaration",
            False,
            Definition(NODE_ENUM, "State", True),
        ),
        (
            b"function run() {}",
            "function_declaration",
            False,
            Definition(NODE_FUNCTION, "run", False),
        ),
        (
            b"function* stream() {}",
            "generator_function_declaration",
            False,
            Definition(NODE_FUNCTION, "stream", False),
        ),
        (
            b"declare function load(): void;",
            "function_signature",
            False,
            Definition(NODE_FUNCTION, "load", False),
        ),
        (
            b"class Worker { run() {} }",
            "method_definition",
            True,
            Definition(NODE_METHOD, "run", False),
        ),
        (
            b"const value = 1;",
            "variable_declarator",
            False,
            Definition(NODE_VARIABLE, "value", False),
        ),
        (
            b"const callback = memo(() => {});",
            "variable_declarator",
            False,
            Definition(NODE_FUNCTION, "callback", False),
        ),
        (
            b"const callback = memo(() => value);",
            "variable_declarator",
            False,
            Definition(NODE_FUNCTION, "callback", False),
        ),
        (
            b"const object = { pair: () => {} };",
            "pair",
            False,
            Definition(NODE_METHOD, "pair", False),
        ),
        (
            b"Thing.prototype.run = function() {};",
            "assignment_expression",
            False,
            Definition(NODE_METHOD, "run", False, "Thing."),
        ),
    ],
)
def test_typescript_classification_contract(
    source: bytes,
    node_type: str,
    inside_class: bool,
    expected: Definition,
) -> None:
    parser = TypeScriptParser()
    node = _nodes_of_type(parser, source, node_type)[0]

    assert parser.classify(node, source, inside_class=inside_class) == expected


def test_javascript_object_and_assignment_shapes_match_shared_contract() -> None:
    source = b'''const object = {
  arrow: () => {},
  classic: function() {},
  shorthand() {},
};
Registry.handlers.run = () => {};
'''

    result = JavaScriptParser().parse(file_path="contract.js", source=source)

    assert {
        (node.kind, node.qualified_name)
        for node in result.nodes
        if node.kind != "file"
    } == {
        (NODE_VARIABLE, "object"),
        (NODE_METHOD, "object.arrow"),
        (NODE_METHOD, "object.classic"),
        (NODE_METHOD, "object.shorthand"),
        (NODE_METHOD, "Registry.handlers.run"),
    }


def test_this_assignment_is_owned_by_the_enclosing_class() -> None:
    source = b"class Worker { configure() { this.dynamic = () => {}; } }"

    result = TypeScriptParser().parse(file_path="worker.ts", source=source)

    assert (NODE_METHOD, "Worker.dynamic") in {
        (node.kind, node.qualified_name) for node in result.nodes
    }

    abstract = TypeScriptParser().parse(
        file_path="abstract.ts",
        source=b"abstract class Base { configure() { this.dynamic = () => {}; } }",
    )
    assert (NODE_METHOD, "Base.dynamic") in {
        (node.kind, node.qualified_name) for node in abstract.nodes
    }


def test_non_function_shapes_do_not_become_methods_or_callbacks() -> None:
    source = b'''const plain = factory(value);
const object = { pair: 1 };
Thing.prototype.run = 1;
const { destructured } = source;
const { callback } = memo(() => value);
'''

    result = TypeScriptParser().parse(file_path="negative.ts", source=source)
    symbols = {(node.kind, node.qualified_name) for node in result.nodes}

    assert (NODE_VARIABLE, "plain") in symbols
    assert (NODE_FUNCTION, "plain") not in symbols
    assert (NODE_METHOD, "object.pair") not in symbols
    assert (NODE_METHOD, "Thing.run") not in symbols
    assert {
        node.qualified_name for node in result.nodes if node.kind != "file"
    } == {"plain", "object"}

    raw = b"Thing.run = () => {}"
    owner = _FakeNode("identifier", 0, 5)
    prop = _FakeNode("identifier", 6, 9)
    left = _FakeNode(
        "member_expression",
        0,
        9,
        fields={"object": owner, "property": prop},
    )
    right = _FakeNode("arrow_function", 12, len(raw))
    assignment = _FakeNode(
        "assignment_expression",
        0,
        len(raw),
        fields={"left": left, "right": right},
    )
    assert TypeScriptParser().classify(
        cast(Node, assignment), raw, inside_class=False
    ) is None


def test_call_targets_keep_static_member_qualification() -> None:
    source = b'''function run() {
  direct();
  object.deep.method();
  this.local();
  getFactory().nested();
  new Service();
  new NS.Widget();
}
'''
    parser = TypeScriptParser()
    calls = _nodes_of_type(parser, source, "call_expression")
    constructors = _nodes_of_type(parser, source, "new_expression")

    assert {
        node_text(node, source): parser.call_target(node, source) for node in calls
    } == {
        "direct()": "direct",
        "object.deep.method()": "object.deep.method",
        "this.local()": "this.local",
        "getFactory().nested()": "nested",
        "getFactory()": "getFactory",
    }
    assert {
        node_text(node, source): parser.call_target(node, source)
        for node in constructors
    } == {
        "new Service()": "Service",
        "new NS.Widget()": "NS.Widget",
    }


def test_callback_and_tsx_reference_targets_keep_qualified_names() -> None:
    source = b'''function View() {
  register(callback, object.handler, () => inline());
  return <UI.Widget onClick={handleClick} onHover={handlers.hover} />;
}
'''
    parser = TsxParser()
    calls = _nodes_of_type(parser, source, "call_expression")
    attributes = _nodes_of_type(parser, source, "jsx_attribute")
    opening = _nodes_of_type(parser, source, "jsx_self_closing_element")[0]

    register = next(node for node in calls if node_text(node, source).startswith("register"))
    assert parser.reference_targets(register, source) == [
        "callback",
        "object.handler",
    ]
    assert {
        node_text(node, source): parser.reference_targets(node, source)
        for node in attributes
    } == {
        "onClick={handleClick}": ["handleClick"],
        "onHover={handlers.hover}": ["handlers.hover"],
    }
    assert parser.reference_targets(opening, source) == ["UI.Widget"]

    paired = b"function Pair() { return <Widget></Widget>; }"
    opening = _nodes_of_type(parser, paired, "jsx_opening_element")[0]
    assert parser.reference_targets(opening, paired) == ["Widget"]

    plain_attribute = b"function Plain() { return <Widget title=\"text\" />; }"
    attribute = _nodes_of_type(parser, plain_attribute, "jsx_attribute")[0]
    assert parser.reference_targets(attribute, plain_attribute) == []
    assert parser.reference_targets(
        cast(Node, _FakeNode("jsx_opening_element")), b""
    ) == []


def test_heritage_decorators_jsdoc_and_signature_are_exact() -> None:
    source = b'''/** Service docs. */
@framework.sealed()
class Service extends ns.Base implements First, ns.Second {
  /** Run docs.
   *More detail.
   */
  @first
  @framework.route("/")
  run(): void {}
}
interface API extends Parent, ns.Other {}
'''
    parser = TypeScriptParser()
    result = parser.parse(file_path="heritage.ts", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert nodes["Service"].signature == "class Service extends ns.Base implements First, ns.Second {"
    assert nodes["Service"].docstring == "Service docs."
    assert nodes["Service.run"].docstring == "Run docs.\nMore detail."

    relation_rows = [
        (edge.src_local_id, edge.kind, edge.dst_name, edge.line)
        for edge in result.edges
        if edge.kind
        in {EDGE_INHERITS, EDGE_IMPLEMENTS, EDGE_DECORATED_BY}
    ]
    assert relation_rows == [
        ("Service#2", EDGE_INHERITS, "Base", 2),
        ("Service#2", EDGE_IMPLEMENTS, "First", 2),
        ("Service#2", EDGE_IMPLEMENTS, "Second", 2),
        ("Service#2", EDGE_DECORATED_BY, "framework.sealed", 2),
        ("Service.run#9", EDGE_DECORATED_BY, "first", 9),
        ("Service.run#9", EDGE_DECORATED_BY, "framework.route", 9),
        ("API#11", EDGE_INHERITS, "Parent", 11),
        ("API#11", EDGE_INHERITS, "Other", 11),
    ]
    assert not any(
        edge.kind == EDGE_REFERENCES and edge.dst_name == "ns"
        for edge in result.edges
    )


def test_bare_member_decorator_and_exported_compact_jsdoc() -> None:
    source = b'''/* ordinary comment */
class Plain {}
/**Docs*/
export class Exported {}
@framework.sealed
class Bare {}
/**
 *  Middle
 *Last
 */
class Spaced {}
'''

    result = TypeScriptParser().parse(file_path="docs.ts", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert nodes["Plain"].docstring is None
    assert nodes["Exported"].docstring == "Docs"
    assert nodes["Spaced"].docstring == "Middle\nLast"
    assert any(
        edge.kind == EDGE_DECORATED_BY
        and edge.src_local_id == nodes["Bare"].local_id
        and edge.dst_name == "framework.sealed"
        for edge in result.edges
    )


def test_import_export_and_dynamic_import_metadata_are_exact() -> None:
    source = b'''import Default from "./default.ts";
import { Foo, Bar as Baz } from "./named.ts";
import * as NS from "./namespace.ts";
import "./side-effect.ts";
export { Foo, Bar as PublicBar } from "./reexport.ts";
export * from "./star.ts";
const lazy = import("./lazy.tsx");
'''

    result = TypeScriptParser().parse(file_path="imports.ts", source=source)
    imports = [
        (
            edge.src_local_id,
            edge.dst_name,
            edge.line,
            edge.module_path,
            edge.local_name,
        )
        for edge in result.edges
        if edge.kind == EDGE_IMPORTS
    ]

    assert imports == [
        ("<file>", "Default", 1, "./default.ts", "Default"),
        ("<file>", "Foo", 2, "./named.ts", "Foo"),
        ("<file>", "Bar", 2, "./named.ts", "Baz"),
        ("<file>", "NS", 3, "./namespace.ts", "NS"),
        ("<file>", "side-effect", 4, "./side-effect.ts", "side-effect"),
        ("<file>", "Foo", 5, "./reexport.ts", "Foo"),
        ("<file>", "Bar", 5, "./reexport.ts", "PublicBar"),
        ("<file>", "*", 6, "./star.ts", "*"),
        ("lazy#7", "lazy", 7, "./lazy.tsx", "lazy"),
    ]


@pytest.mark.parametrize(
    ("module_path", "expected"),
    [
        ("@scope/deep/component.d.ts", "component"),
        ("deep/component.tsx", "component"),
        ("deep/component.ts", "component"),
        ("deep/component.jsx", "component"),
        ("deep/component.js", "component"),
        ("deep/component.mjs", "component"),
        ("deep/component.cjs", "component"),
        ("deep/package/", "package"),
        ("package", "package"),
        ("/", "/"),
    ],
)
def test_module_reference_names_cover_every_supported_suffix(
    module_path: str, expected: str
) -> None:
    assert _module_ref_name(module_path) == expected


def test_dynamic_import_rejects_calls_and_nonliteral_specifiers() -> None:
    source = b"fn(); import(path);"
    parser = TypeScriptParser()
    calls = _nodes_of_type(parser, source, "call_expression")

    assert all(parser.import_refs(node, source) == [] for node in calls)
    assert parser.import_refs(
        cast(Node, _FakeNode("call_expression")), b""
    ) == []


def test_type_alias_variable_and_callable_type_refs_are_exact() -> None:
    source = b'''type Handler = (value: Input) => Promise<Output>;
const service: Service = external;
class Worker {
  field: FieldType;
  run(input: Request): Promise<Response> { return service.run(input); }
}
'''
    parser = TypeScriptParser()
    result = parser.parse(file_path="types.ts", source=source)
    node_names = {node.local_id: node.qualified_name for node in result.nodes}
    refs: dict[str, list[str]] = {}
    for edge in result.edges:
        if edge.kind != EDGE_REFERENCES or edge.dst_name is None:
            continue
        refs.setdefault(node_names[edge.src_local_id], []).append(edge.dst_name)

    assert refs["Handler"] == ["Input", "Promise", "Output"]
    assert refs["service"] == ["Service", "external"]
    assert refs["Worker.field"] == ["FieldType"]
    assert refs["Worker.run"] == ["Request", "Promise", "Response", "input"]


def test_javascript_and_generic_heritage_names_are_retained() -> None:
    javascript = JavaScriptParser().parse(
        file_path="child.js", source=b"class Child extends Base {}"
    )
    typescript = TypeScriptParser().parse(
        file_path="generic.ts",
        source=b"interface Child extends Parent<Arg> {}",
    )

    assert [
        edge.dst_name for edge in javascript.edges if edge.kind == EDGE_INHERITS
    ] == ["Base"]
    assert [
        edge.dst_name for edge in typescript.edges if edge.kind == EDGE_INHERITS
    ] == ["Parent"]


def test_static_value_name_handles_incomplete_member_nodes() -> None:
    source = b"owner.member"
    owner = _FakeNode("identifier", 0, 5)
    prop = _FakeNode("property_identifier", 6, 12)

    assert _static_value_name(
        cast(Node, _FakeNode("member_expression", fields={"property": prop})),
        source,
    ) is None
    assert _static_value_name(
        cast(Node, _FakeNode("member_expression", fields={"object": owner})),
        source,
    ) is None


def test_heritage_without_a_keyword_does_not_emit_an_invalid_edge() -> None:
    ident = _FakeNode("identifier", 0, 4)
    heritage = _FakeNode("class_heritage", 0, 4, children=[ident])

    assert TypeScriptParser()._heritage(cast(Node, heritage), b"Base") == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"abc", "abc"),
        (b"'abc\"", "'abc\""),
        (b'""', ""),
        (b"''", ""),
        (b'"quoted"', "quoted"),
    ],
)
def test_string_content_only_strips_matching_quotes(
    raw: bytes, expected: str
) -> None:
    node = _FakeNode("string", 0, len(raw))
    assert _string_content(cast(Node, node), raw) == expected


def test_decorated_signature_is_lossy_utf8_safe_and_has_exact_limit() -> None:
    parser = TypeScriptParser()
    decorator = _FakeNode("decorator", start_byte=0, end_byte=3)
    exact = b"@d\n" + b"x" * 240
    invalid = b"@d\nclass \xffBad {}"

    exact_node = _FakeNode(
        "class_declaration",
        end_byte=len(exact),
        children=[decorator],
    )
    invalid_node = _FakeNode(
        "class_declaration",
        end_byte=len(invalid),
        children=[decorator],
    )

    assert parser._signature(cast(Node, exact_node), exact) == "x" * 240
    assert parser._signature(cast(Node, invalid_node), invalid) == "class �Bad {}"


def test_non_matching_nodes_do_not_emit_language_specific_hooks() -> None:
    source = b"const value = 1;"
    parser = TypeScriptParser()
    program = parser._get_parser().parse(source).root_node

    assert parser.classify(program, source, inside_class=False) is None
    assert parser.call_target(program, source) is None
    assert parser.reference_targets(program, source) == []
    assert parser.import_refs(program, source) == []
    assert parser.supertypes(program, source) == []
    assert parser.decorators(program, source) == []
    assert parser.type_refs(program, source) == []
