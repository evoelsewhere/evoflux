"""Behavioral contracts for the shared tree-sitter graph walker."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

import pytest
from tree_sitter import Node

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_CONTAINS,
    EDGE_DECORATED_BY,
    EDGE_IMPORTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    EDGE_USES,
    ExtractedEdge,
    ExtractedNode,
    NODE_VARIABLE,
)
from app.services.code_index.parsers import base as base_parser
from app.services.code_index.parsers.base import (
    Definition,
    TreeSitterParser,
    _contains,
    _is_reference_identifier,
    node_text,
)
from app.services.code_index.parsers.python import PythonParser


class _IdentifierParser(TreeSitterParser):
    name = "contract"
    extensions = (".py",)
    grammar = "python"

    def classify(self, node, source: bytes, *, inside_class: bool):
        if node.type == "identifier":
            return Definition(kind=NODE_VARIABLE, name=node_text(node, source))
        return None


class _SyntheticParser(PythonParser):
    def root_prefix(self, root, source: bytes) -> str:
        return "pkg."

    def synthetic_definitions(self, node, source: bytes, *, inside_class: bool):
        if (
            inside_class is False
            and node.type == "identifier"
            and node_text(node, source) == "marker"
        ):
            return [
                Definition(kind=NODE_VARIABLE, name="implicit_a"),
                Definition(kind=NODE_VARIABLE, name="implicit_b"),
            ]
        return []


class _StrictContextParser(_IdentifierParser):
    def classify(self, node, source: bytes, *, inside_class: bool):
        if inside_class is False:
            return super().classify(node, source, inside_class=inside_class)
        return None


class _OverridePrefixParser(_IdentifierParser):
    def classify(self, node, source: bytes, *, inside_class: bool):
        definition = super().classify(node, source, inside_class=inside_class)
        if definition is None:
            return None
        return Definition(
            kind=definition.kind,
            name=definition.name,
            prefix="override.",
        )


class _UsesParser(PythonParser):
    def uses_target(self, node, source: bytes) -> str | None:
        if node.type == "identifier" and node_text(node, source) == "injected":
            return "Dependency"
        return None


@dataclass
class _FakeNode:
    type: str
    start_byte: int = 0
    end_byte: int = 1
    parent: _FakeNode | None = None
    fields: dict[str, _FakeNode] = field(default_factory=dict)

    def child_by_field_name(self, name: str) -> _FakeNode | None:
        return self.fields.get(name)


def _under(*ancestor_types: str) -> _FakeNode:
    node = _FakeNode("identifier", start_byte=4, end_byte=10)
    child = node
    for node_type in ancestor_types:
        parent = _FakeNode(node_type, start_byte=0, end_byte=20)
        child.parent = parent
        child = parent
    return node


def _is_reference(node: _FakeNode) -> bool:
    return _is_reference_identifier(cast(Node, node))


def _contains_fake(outer: _FakeNode | None, inner: _FakeNode) -> bool:
    return _contains(cast(Node | None, outer), cast(Node, inner))


def test_python_parse_result_is_an_exact_graph_contract() -> None:
    source = b'''from remote.pkg import Imported as Alias

@decorate
class Service(Base):
    """service docs"""
    def run(self, value: Input) -> Output:
        """run docs"""
        current = external
        helper(value)
        dispatcher.submit(callback)
'''

    result = PythonParser().parse(file_path="contract.py", source=source)

    assert result.language == "python"
    assert result.file_path == "contract.py"
    assert result.nodes == [
        ExtractedNode(
            local_id="<file>",
            kind="file",
            name="contract.py",
            qualified_name="contract.py",
            line_start=1,
            line_end=11,
        ),
        ExtractedNode(
            local_id="Service#4",
            kind="class",
            name="Service",
            qualified_name="Service",
            line_start=4,
            line_end=10,
            signature="class Service(Base):",
            docstring="service docs",
        ),
        ExtractedNode(
            local_id="Service.run#6",
            kind="method",
            name="run",
            qualified_name="Service.run",
            line_start=6,
            line_end=10,
            signature="def run(self, value: Input) -> Output:",
            docstring="run docs",
        ),
    ]
    assert result.edges == [
        ExtractedEdge(
            src_local_id="<file>",
            kind=EDGE_IMPORTS,
            dst_name="Imported",
            line=1,
            module_path="remote.pkg",
            local_name="Alias",
        ),
        ExtractedEdge(
            src_local_id="<file>",
            kind=EDGE_REFERENCES,
            dst_name="decorate",
            line=3,
        ),
        ExtractedEdge(
            src_local_id="<file>",
            kind=EDGE_CONTAINS,
            dst_local_id="Service#4",
            line=4,
        ),
        ExtractedEdge(
            src_local_id="Service#4",
            kind=EDGE_INHERITS,
            dst_name="Base",
            line=4,
        ),
        ExtractedEdge(
            src_local_id="Service#4",
            kind=EDGE_DECORATED_BY,
            dst_name="decorate",
            line=4,
        ),
        ExtractedEdge(
            src_local_id="Service#4",
            kind=EDGE_REFERENCES,
            dst_name="Base",
            line=4,
        ),
        ExtractedEdge(
            src_local_id="Service#4",
            kind=EDGE_CONTAINS,
            dst_local_id="Service.run#6",
            line=6,
        ),
        ExtractedEdge(
            src_local_id="Service.run#6",
            kind=EDGE_REFERENCES,
            dst_name="Input",
            line=6,
        ),
        ExtractedEdge(
            src_local_id="Service.run#6",
            kind=EDGE_REFERENCES,
            dst_name="Output",
            line=6,
        ),
        ExtractedEdge(
            src_local_id="Service.run#6",
            kind=EDGE_REFERENCES,
            dst_name="external",
            line=8,
        ),
        ExtractedEdge(
            src_local_id="Service.run#6",
            kind=EDGE_CALLS,
            dst_name="helper",
            line=9,
        ),
        ExtractedEdge(
            src_local_id="Service.run#6",
            kind=EDGE_REFERENCES,
            dst_name="value",
            line=9,
        ),
        ExtractedEdge(
            src_local_id="Service.run#6",
            kind=EDGE_CALLS,
            dst_name="dispatcher.submit",
            line=10,
        ),
        ExtractedEdge(
            src_local_id="Service.run#6",
            kind=EDGE_REFERENCES,
            dst_name="callback",
            line=10,
        ),
    ]


def test_node_text_replaces_invalid_utf8() -> None:
    node = SimpleNamespace(start_byte=1, end_byte=4)
    assert node_text(cast(Node, node), b"0\xffab9") == "�ab"


def test_signature_keeps_exact_limit_and_truncates_only_overflow() -> None:
    exact_name = "f" * 233
    overflow_name = "g" * 234
    source = (
        f"def {exact_name}():\n    pass\n"
        f"def {overflow_name}():\n    pass\n"
    ).encode()

    result = PythonParser().parse(file_path="signatures.py", source=source)
    signatures = {node.name: node.signature for node in result.nodes[1:]}

    assert signatures[exact_name] == f"def {exact_name}():"
    assert len(signatures[exact_name] or "") == base_parser._MAX_SIGNATURE_LEN
    assert signatures[overflow_name] == f"def {overflow_name}()…"
    assert len(signatures[overflow_name] or "") == base_parser._MAX_SIGNATURE_LEN + 1


def test_signature_removes_trailing_space_before_ellipsis() -> None:
    source = ("x" * (base_parser._MAX_SIGNATURE_LEN - 1) + " tail").encode()
    node = SimpleNamespace(start_byte=0, end_byte=len(source))

    assert TreeSitterParser()._signature(cast(Node, node), source) == (
        "x" * (base_parser._MAX_SIGNATURE_LEN - 1) + "…"
    )


def test_definition_prefix_override_wins_over_root_context() -> None:
    result = _OverridePrefixParser().parse(
        file_path="prefix.py", source=b"target\n"
    )

    assert result.nodes[1].local_id == "override.target#1"
    assert result.nodes[1].qualified_name == "override.target"


def test_root_context_is_a_real_boolean() -> None:
    result = _StrictContextParser().parse(
        file_path="context.py", source=b"target\n"
    )

    assert [node.name for node in result.nodes] == ["context.py", "target"]


def test_uses_hook_emits_owned_dependency_edge() -> None:
    result = _UsesParser().parse(file_path="uses.py", source=b"\ninjected\n")

    assert result.edges == [
        ExtractedEdge(
            src_local_id="<file>",
            kind=EDGE_USES,
            dst_name="Dependency",
            line=2,
        ),
        ExtractedEdge(
            src_local_id="<file>",
            kind=EDGE_REFERENCES,
            dst_name="injected",
            line=2,
        ),
    ]


def test_import_line_uses_row_not_column() -> None:
    result = PythonParser().parse(
        file_path="imports.py",
        source=b"\nfrom remote.pkg import Imported as Alias\n",
    )

    imports = [edge for edge in result.edges if edge.kind == EDGE_IMPORTS]
    assert imports == [
        ExtractedEdge(
            src_local_id="<file>",
            kind=EDGE_IMPORTS,
            dst_name="Imported",
            line=2,
            module_path="remote.pkg",
            local_name="Alias",
        )
    ]


def test_synthetic_symbols_have_stable_suffixes_and_ownership() -> None:
    result = _SyntheticParser().parse(file_path="synthetic.py", source=b"marker\n")

    assert [node.local_id for node in result.nodes] == [
        "<file>",
        "pkg.implicit_a#1:implicit:0",
        "pkg.implicit_b#1:implicit:1",
    ]
    assert [
        (edge.src_local_id, edge.kind, edge.dst_local_id, edge.dst_name, edge.line)
        for edge in result.edges
    ] == [
        ("<file>", EDGE_REFERENCES, None, "marker", 1),
        ("<file>", EDGE_CONTAINS, "pkg.implicit_a#1:implicit:0", None, 1),
        ("<file>", EDGE_CONTAINS, "pkg.implicit_b#1:implicit:1", None, 1),
    ]


def test_depth_guard_includes_boundary_and_stops_beyond_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(base_parser, "_MAX_DEPTH", 1)

    at_boundary = _IdentifierParser().parse(file_path="depth.py", source=b"target\n")
    beyond_boundary = _IdentifierParser().parse(
        file_path="depth.py", source=b"(target)\n"
    )

    assert [node.name for node in at_boundary.nodes] == ["depth.py", "target"]
    assert [node.name for node in beyond_boundary.nodes] == ["depth.py"]


def test_node_limit_is_a_hard_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base_parser, "_MAX_NODES_PER_FILE", 2)

    result = _IdentifierParser().parse(
        file_path="limit.py", source=b"first\nsecond\n"
    )
    synthetic = _SyntheticParser().parse(file_path="limit.py", source=b"marker\n")

    assert [node.name for node in result.nodes] == ["limit.py", "first"]
    assert [node.name for node in synthetic.nodes] == ["limit.py", "implicit_a"]


def test_reference_identifier_rejects_syntax_owners_at_any_depth() -> None:
    assert not _is_reference(_FakeNode("string"))
    assert not _is_reference(_FakeNode("identifier"))
    assert not _is_reference(
        _under("generic_type", "tuple_type", "annotation", "wrapper", "module")
    )
    assert not _is_reference(_under("annotation", "wrapper", "module"))
    assert not _is_reference(_under("attribute_item", "source_file"))
    assert not _is_reference(_under("lambda_parameters", "lambda"))
    assert not _is_reference(
        _under("dotted_name", "aliased_import", "import_statement", "module")
    )
    assert not _is_reference(
        _under("scoped_identifier", "use_declaration", "source_file")
    )
    assert not _is_reference(
        _under("qualified_name", "using_directive", "compilation_unit")
    )
    for field_name in ("name", "declarator", "pattern", "alias"):
        identifier = _under("declaration", "module")
        owner = identifier.parent
        assert owner is not None
        owner.fields[field_name] = _FakeNode(
            "identifier",
            start_byte=identifier.start_byte,
            end_byte=identifier.end_byte,
            parent=owner,
        )
        assert not _is_reference(identifier)


def test_reference_identifier_distinguishes_assignment_reads_and_direct_callees() -> None:
    left = _under("assignment", "expression_statement", "module")
    assignment = left.parent
    assert assignment is not None
    assignment.fields["left"] = _FakeNode(
        "identifier",
        start_byte=left.start_byte,
        end_byte=left.end_byte,
        parent=assignment,
    )
    assert not _is_reference(left)

    right = _under("assignment", "expression_statement", "module")
    right_assignment = right.parent
    assert right_assignment is not None
    right_assignment.fields["left"] = _FakeNode(
        "identifier", start_byte=0, end_byte=3, parent=right_assignment
    )
    assert _is_reference(right)

    for field_name in ("function", "constructor", "name"):
        callee = _under("member_expression", "arguments", "call_expression", "module")
        call = callee.parent
        while call is not None and call.type != "call_expression":
            call = call.parent
        assert call is not None
        call.fields[field_name] = _FakeNode("member_expression", 4, 10, parent=call)
        assert not _is_reference(callee)

    argument = _under("arguments", "call_expression", "module")
    call = argument.parent
    assert call is not None
    call.fields["function"] = _FakeNode("identifier", 0, 3, parent=call)
    assert _is_reference(argument)


def test_python_attribute_reads_remain_runtime_references() -> None:
    result = PythonParser().parse(
        file_path="attributes.py",
        source=b"def read():\n    return config.value\n",
    )

    assert [
        edge.dst_name
        for edge in result.edges
        if edge.kind == EDGE_REFERENCES
    ] == ["config", "value"]


def test_contains_includes_exact_span_boundaries() -> None:
    inner = _FakeNode("identifier", start_byte=4, end_byte=10)

    assert _contains_fake(_FakeNode("member", start_byte=4, end_byte=10), inner)
    assert _contains_fake(_FakeNode("member", start_byte=0, end_byte=20), inner)
    assert not _contains_fake(None, inner)
    assert not _contains_fake(
        _FakeNode("member", start_byte=5, end_byte=20), inner
    )
    assert not _contains_fake(
        _FakeNode("member", start_byte=0, end_byte=9), inner
    )
