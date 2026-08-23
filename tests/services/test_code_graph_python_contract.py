"""Exact behavioral contracts for Python graph extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest
from tree_sitter import Node

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_DECORATED_BY,
    EDGE_IMPORTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_METHOD,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.base import Definition
from app.services.code_index.parsers.python import (
    PythonParser,
    _qualified_value_name,
    _strip_py_string,
)


@dataclass
class _FakeNode:
    type: str
    start_byte: int = 0
    end_byte: int = 0
    parent: _FakeNode | None = None
    children: list[_FakeNode] = field(default_factory=list)
    fields: dict[str, _FakeNode] = field(default_factory=dict)

    def child_by_field_name(self, name: str) -> _FakeNode | None:
        return self.fields.get(name)


def _descendants(node: Node):
    for child in node.named_children:
        yield child
        yield from _descendants(child)


def _nodes_of_type(parser: PythonParser, source: bytes, node_type: str) -> list[Node]:
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


@pytest.mark.parametrize(
    ("source", "node_type", "inside_class", "expected"),
    [
        (
            b"class Service: pass",
            "class_definition",
            False,
            Definition(NODE_CLASS, "Service", True),
        ),
        (
            b"def run(): pass",
            "function_definition",
            False,
            Definition(NODE_FUNCTION, "run"),
        ),
        (
            b"class Service:\n def run(self): pass\n",
            "function_definition",
            True,
            Definition(NODE_METHOD, "run"),
        ),
        (
            b"VALUE = external",
            "assignment",
            False,
            Definition(NODE_VARIABLE, "VALUE"),
        ),
        (
            b"VALUE: Config = external",
            "assignment",
            False,
            Definition(NODE_VARIABLE, "VALUE"),
        ),
        (
            b"class Service:\n field = external\n",
            "assignment",
            True,
            Definition(NODE_FIELD, "field"),
        ),
        (
            b"class Service:\n field: FieldType\n",
            "assignment",
            True,
            Definition(NODE_FIELD, "field"),
        ),
    ],
)
def test_python_classification_contract(
    source: bytes,
    node_type: str,
    inside_class: bool,
    expected: Definition,
) -> None:
    parser = PythonParser()
    node = _nodes_of_type(parser, source, node_type)[0]

    assert parser.classify(node, source, inside_class=inside_class) == expected


def test_local_and_dunder_assignments_do_not_become_graph_symbols() -> None:
    source = b'''__all__ = ["VALUE"]
__private = 1
public__ = 2
def outer():
    local = 1
    return local
class Service:
    __slots__ = ()
    __private = 1
    public__ = 2
    left, right = (1, 2)
'''

    result = PythonParser().parse(file_path="negative.py", source=source)

    assert {
        node.qualified_name for node in result.nodes if node.kind != "file"
    } == {
        "__private",
        "public__",
        "outer",
        "Service",
        "Service.__private",
        "Service.public__",
    }


def test_python_call_targets_keep_nested_attribute_qualification() -> None:
    source = b'''class Child(Base):
 def run(self):
    super().base()
    direct()
    package.service.method()
    get_factory().nested()
    worker.submit(callback)
'''

    result = PythonParser().parse(file_path="calls.py", source=source)
    calls = [
        (edge.dst_name, edge.line)
        for edge in result.edges
        if edge.kind == EDGE_CALLS
    ]

    assert calls == [
        ("super.base", 3),
        ("direct", 4),
        ("package.service.method", 5),
        ("nested", 6),
        ("get_factory", 6),
        ("worker.submit", 7),
    ]


def test_python_dispatch_references_keep_callbacks_and_keyword_values() -> None:
    source = b'''def schedule():
    worker.submit(callback, package.handlers.on_event, 42, lambda: None, named=other.callback)
'''

    parser = PythonParser()
    call = next(
        node
        for node in _nodes_of_type(parser, source, "call")
        if parser.call_target(node, source) == "worker.submit"
    )

    assert parser.reference_targets(call, source) == [
        "callback",
        "package.handlers.on_event",
        "other.callback",
    ]


def test_python_heritage_supports_identifiers_attributes_and_generics() -> None:
    source = b"class Service(Base, package.Mixin, Generic[T]): pass"

    result = PythonParser().parse(file_path="heritage.py", source=source)

    assert [
        edge.dst_name for edge in result.edges if edge.kind == EDGE_INHERITS
    ] == ["Base", "Mixin", "Generic"]


def test_python_docs_and_decorators_use_language_semantics() -> None:
    source = b'''@first
@framework.route("/")
class Service:
    r"""Service docs.
        More detail.
    """
    def run(self):
        """Run docs."""
        return None
class Bytes:
    b"not a docstring"
class Formatted:
    f"not {value}"
class Commented:
    # comments do not block a real docstring
    """Commented docs."""
'''

    result = PythonParser().parse(file_path="docs.py", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}
    decorators = [
        (edge.src_local_id, edge.dst_name)
        for edge in result.edges
        if edge.kind == EDGE_DECORATED_BY
    ]

    assert nodes["Service"].docstring == "Service docs.\nMore detail."
    assert nodes["Service.run"].docstring == "Run docs."
    assert nodes["Bytes"].docstring is None
    assert nodes["Formatted"].docstring is None
    assert nodes["Commented"].docstring == "Commented docs."
    assert decorators == [
        (nodes["Service"].local_id, "first"),
        (nodes["Service"].local_id, "framework.route"),
    ]


def test_python_import_metadata_is_exact() -> None:
    source = b'''import os
import package.module
import deep.package.service as svc
from app.models import User, Order as Purchase
from ..shared.types import Config
'''

    result = PythonParser().parse(file_path="imports.py", source=source)
    imports = [
        (edge.dst_name, edge.line, edge.module_path, edge.local_name)
        for edge in result.edges
        if edge.kind == EDGE_IMPORTS
    ]

    assert imports == [
        ("os", 1, "os", "os"),
        ("module", 2, "package.module", "module"),
        ("service", 3, "deep.package.service", "svc"),
        ("User", 4, "app.models", "User"),
        ("Order", 4, "app.models", "Purchase"),
        ("Config", 5, "..shared.types", "Config"),
    ]


def test_python_type_refs_cover_functions_module_variables_and_class_fields() -> None:
    source = b'''VALUE: Config = external
class Service:
    field: FieldType
    def run(self, value: Input, model: package.Model = default) -> Result[Output]:
        return value
'''

    result = PythonParser().parse(file_path="types.py", source=source)
    node_names = {node.local_id: node.qualified_name for node in result.nodes}
    refs: dict[str, list[str]] = {}
    for edge in result.edges:
        if edge.kind != EDGE_REFERENCES or edge.dst_name is None:
            continue
        refs.setdefault(node_names[edge.src_local_id], []).append(edge.dst_name)

    assert refs["VALUE"] == ["Config", "external"]
    assert refs["Service.field"] == ["FieldType"]
    assert refs["Service.run"] == [
        "Input",
        "Model",
        "Result",
        "Output",
        "default",
        "value",
    ]


def test_lambda_binding_is_not_a_reference_but_its_body_read_is() -> None:
    result = PythonParser().parse(
        file_path="lambda.py",
        source=b"def make():\n    return lambda item: item\n",
    )

    assert [
        edge.dst_name
        for edge in result.edges
        if edge.kind == EDGE_REFERENCES
    ] == ["item"]


@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        ('"simple"', "simple"),
        ('r"raw\\nvalue"', "raw\\nvalue"),
        ('"""first\n    second"""', "first\nsecond"),
        ('b"bytes"', None),
        ('f"value {name}"', None),
        ('"unterminated', None),
    ],
)
def test_python_doc_literal_normalization(
    literal: str, expected: str | None
) -> None:
    assert _strip_py_string(literal) == expected


def test_qualified_value_name_handles_nested_and_incomplete_attributes() -> None:
    source = b"package.service.callback"
    package = _FakeNode("identifier", 0, 7)
    service = _FakeNode("identifier", 8, 15)
    callback = _FakeNode("identifier", 16, 24)
    inner = _FakeNode(
        "attribute",
        0,
        15,
        fields={"object": package, "attribute": service},
    )
    outer = _FakeNode(
        "attribute",
        0,
        24,
        fields={"object": inner, "attribute": callback},
    )

    assert _qualified_value_name(cast(Node, outer), source) == (
        "package.service.callback"
    )
    assert _qualified_value_name(
        cast(Node, _FakeNode("attribute", fields={"attribute": callback})),
        source,
    ) is None
    assert _qualified_value_name(
        cast(Node, _FakeNode("attribute", fields={"object": package})),
        source,
    ) is None


def test_assignment_helpers_reject_incomplete_or_wrong_owners() -> None:
    parser = PythonParser()
    left = _FakeNode("identifier", 0, 5)
    orphan = _FakeNode("assignment", fields={"left": left})
    function = _FakeNode("function_definition")
    block = _FakeNode("block", parent=function)
    nested = _FakeNode("assignment", parent=block, fields={"left": left})

    assert parser._module_level_assignment(cast(Node, orphan), b"VALUE") is None
    assert parser._class_level_assignment(cast(Node, orphan), b"VALUE") is None
    assert parser._class_level_assignment(cast(Node, nested), b"VALUE") is None


def test_non_matching_python_nodes_do_not_emit_language_hooks() -> None:
    source = b"value + 1"
    parser = PythonParser()
    root = parser._get_parser().parse(source).root_node

    assert parser.classify(root, source, inside_class=False) is None
    assert parser.call_target(root, source) is None
    assert parser.reference_targets(root, source) == []
    assert parser.supertypes(root, source) == []
    assert parser.import_refs(root, source) == []
    assert parser.decorators(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None
    empty_body = _FakeNode("block")
    incomplete = _FakeNode("function_definition", fields={"body": empty_body})
    assert parser.docstring(cast(Node, incomplete), b"") is None
