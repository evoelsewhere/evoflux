"""Exact behavioral contracts for Objective-C graph extraction."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import cast

from tree_sitter import Node

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_CONTAINS,
    EDGE_DECORATED_BY,
    EDGE_IMPLEMENTS,
    EDGE_IMPORTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_PROPERTY,
)
from app.services.code_index.parsers.objc import (
    ObjCParser,
    _collect_objc_type_ids,
    _declarator_name,
    _property_accessors,
    _property_name,
    _strip_objc_doc,
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


def _nodes_of_type(parser: ObjCParser, source: bytes, node_type: str):
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


def _named_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], edge.dst_name)
        for edge in result.edges
        if edge.kind == kind and edge.dst_name is not None
    ]


def test_objc_symbols_types_calls_heritage_docs_and_coalescing_are_exact() -> None:
    source = b"""#import <Foundation/Foundation.h>
/** Child docs */
@protocol Child <Parent, Logging>
- (Result *)run:(Input *)input config:(Config *)config;
@end
/** User docs */
@interface User : NSObject <Child>
@property (nonatomic, copy, getter=displayName, setter=setDisplayName:) Config *name;
@property (readonly) BOOL active;
@end
@implementation User
- (Result *)run:(Input *)input config:(Config *)config {
  helper(); [client execute:input]; [Factory create];
}
@end
Result *top(Input *input) { helper(); return nil; }
"""
    result = ObjCParser().parse(file_path="Models.m", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter(
        (node.kind, node.qualified_name) for node in result.nodes
    ) == Counter(
        {
            ("file", "Models.m"): 1,
            (NODE_INTERFACE, "Child"): 1,
            (NODE_METHOD, "Child.runconfig"): 1,
            (NODE_CLASS, "User"): 1,
            (NODE_PROPERTY, "User.name"): 1,
            (NODE_METHOD, "User.displayName"): 1,
            (NODE_METHOD, "User.setDisplayName"): 1,
            (NODE_PROPERTY, "User.active"): 1,
            (NODE_METHOD, "User.active"): 1,
            (NODE_METHOD, "User.runconfig"): 1,
            (NODE_FUNCTION, "top"): 1,
        }
    )
    assert nodes["Child"].docstring == "Child docs"
    assert nodes["User"].docstring == "User docs"
    assert _named_edges(result, EDGE_IMPORTS) == [("Models.m", "Foundation")]
    assert _named_edges(result, EDGE_INHERITS) == [
        ("Child", "Parent"),
        ("Child", "Logging"),
        ("User", "NSObject"),
    ]
    assert _named_edges(result, EDGE_IMPLEMENTS) == [("User", "Child")]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("Child.runconfig", "Result"),
        ("Child.runconfig", "Input"),
        ("Child.runconfig", "Config"),
        ("User.name", "Config"),
        ("User.runconfig", "Result"),
        ("User.runconfig", "Input"),
        ("User.runconfig", "Config"),
        ("top", "Result"),
        ("top", "Input"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("User.runconfig", "helper"),
        ("User.runconfig", "execute"),
        ("User.runconfig", "create"),
        ("top", "helper"),
    ]
    local_ids = {node.local_id for node in result.nodes}
    assert all(
        edge.dst_local_id is None or edge.dst_local_id in local_ids
        for edge in result.edges
    )
    assert len(result.edges) == len(set(result.edges))
    assert any(
        edge.kind == EDGE_CONTAINS
        and edge.src_local_id == nodes["User"].local_id
        and edge.dst_local_id == nodes["User.runconfig"].local_id
        for edge in result.edges
    )


def test_objc_categories_and_distinct_classes_keep_exact_ownership() -> None:
    source = b"""@interface NSString (Uppercase)
- (NSString *)uppercase;
@end
@implementation NSString (Uppercase)
- (NSString *)uppercase { return [self uppercaseString]; }
@end
@interface Other : NSObject @end
@implementation Other @end
"""
    result = ObjCParser().parse(file_path="Categories.m", source=source)
    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "Categories.m"),
        (NODE_CLASS, "NSString+Uppercase"),
        (NODE_METHOD, "NSString+Uppercase.uppercase"),
        (NODE_CLASS, "Other"),
    }
    assert _named_edges(result, EDGE_CALLS) == [
        ("NSString+Uppercase.uppercase", "uppercaseString")
    ]


def test_objc_property_type_and_document_helpers_are_exact() -> None:
    source = b"""@interface Item
@property (getter = isReady, setter = markReady:) Config *ready;
@property (readonly) Repo *repo;
@property Config *title;
@end
"""
    parser = ObjCParser()
    properties = _nodes_of_type(parser, source, "property_declaration")
    first_name = _property_name(properties[0], source)
    second_name = _property_name(properties[1], source)
    third_name = _property_name(properties[2], source)
    out: list[str] = []
    _collect_objc_type_ids(properties[0], source, out)

    assert first_name == "ready"
    assert second_name == "repo"
    assert third_name == "title"
    assert _property_accessors(properties[0], first_name, source) == (
        "isReady",
        "markReady",
    )
    assert _property_accessors(properties[1], second_name, source) == (
        "repo",
        None,
    )
    assert _property_accessors(properties[2], third_name, source) == (
        "title",
        "setTitle",
    )
    assert out == ["Config"]
    assert _strip_objc_doc("/**X docs X*/") == "X docs X"
    assert (
        _strip_objc_doc("/**\n * Summary\n * @param value ignored\n * Detail\n */")
        == "Summary\nDetail"
    )


def test_objc_declarator_and_non_matching_hooks_are_exact() -> None:
    source = b"Result *top(Input *input) { return nil; }"
    parser = ObjCParser()
    function = _nodes_of_type(parser, source, "function_definition")[0]
    declarator = function.child_by_field_name("declarator")
    root = parser._get_parser().parse(source).root_node
    assert declarator is not None
    assert _declarator_name(declarator, source) == "top"
    assert _declarator_name(root, source) == "top"
    assert parser.classify(root, source, inside_class=False) is None
    assert parser.synthetic_definitions(root, source, inside_class=False) == []
    assert parser.call_target(root, source) is None
    assert parser.supertypes(root, source) == []
    assert parser.import_refs(root, source) == []
    assert parser.decorators(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None
    assert parser.identifier_reference_targets(root, source) == []


def test_objc_gnu_and_availability_attributes_are_exact() -> None:
    source = b"""__attribute__((cold)) Result *top(void) { return nil; }
API_AVAILABLE(ios(13.0)) @interface Modern @end
"""
    result = ObjCParser().parse(file_path="Attributes.m", source=source)
    assert _named_edges(result, EDGE_DECORATED_BY) == [
        ("top", "cold"),
        ("Modern", "availability"),
    ]


def test_objc_deep_local_import_and_malformed_property_are_exact() -> None:
    result = ObjCParser().parse(
        file_path="Import.m",
        source=b'#import "one/two/MyHeader.h"',
    )
    assert _named_edges(result, EDGE_IMPORTS) == [("Import.m", "MyHeader.h")]
    assert _property_name(cast(Node, _FakeNode("property_declaration")), b"") is None
