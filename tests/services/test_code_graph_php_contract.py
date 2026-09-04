"""Exact behavioral contracts for PHP graph extraction."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import cast

from tree_sitter import Node

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_DECORATED_BY,
    EDGE_IMPLEMENTS,
    EDGE_IMPORTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FIELD,
    NODE_METHOD,
    NODE_NAMESPACE,
    NODE_PROPERTY,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.php import (
    PhpParser,
    _php_expression_path,
    _php_namespace_name,
    _php_promoted_property_prefix,
    _strip_phpdoc,
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


def _nodes_of_type(parser: PhpParser, source: bytes, node_type: str):
    root = parser._get_parser().parse(source).root_node
    return [node for node in _descendants(root) if node.type == node_type]


def _named_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], edge.dst_name)
        for edge in result.edges
        if edge.kind == kind and edge.dst_name is not None
    ]


def test_php_symbols_types_traits_calls_docs_and_attributes_are_exact() -> None:
    source = rb"""<?php
namespace App\Billing;
use Vendor\Repo as R;
/** Processor docs */
#[Vendor\Service]
class Processor extends Core\Base implements Contract, Vendor\OtherContract {
 use Logs, Vendor\Metrics;
 /** Field docs */
 #[FieldAttr] public ?Config $config, $other;
 public const VERSION = 1, NAME = 'x';
 #[Inject]
 public function __construct(private readonly Repo $repo, Config $cfg) {}
 public function run(Input|Other $input): Result&Jsonable {
   helper();
   Vendor\util();
   $this->client->api()->call();
   self::make();
   static::late();
   parent::base();
   new Core\Widget();
   new Widget();
 }
}
enum Status: string implements Label {
 public const CODE = 1;
 case Ready = 'ready';
 case Done;
}
const GLOBAL = 1;
"""
    result = PhpParser().parse(file_path="Service.php", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter(
        (node.kind, node.qualified_name) for node in result.nodes
    ) == Counter(
        {
            ("file", "Service.php"): 1,
            (NODE_NAMESPACE, "App.Billing"): 1,
            (NODE_CLASS, "App.Billing.Processor"): 1,
            (NODE_FIELD, "App.Billing.Processor.config"): 1,
            (NODE_FIELD, "App.Billing.Processor.other"): 1,
            (NODE_PROPERTY, "App.Billing.Processor.VERSION"): 1,
            (NODE_PROPERTY, "App.Billing.Processor.NAME"): 1,
            (NODE_METHOD, "App.Billing.Processor.__construct"): 1,
            (NODE_FIELD, "App.Billing.Processor.repo"): 1,
            (NODE_METHOD, "App.Billing.Processor.run"): 1,
            (NODE_ENUM, "App.Billing.Status"): 1,
            (NODE_PROPERTY, "App.Billing.Status.CODE"): 1,
            (NODE_PROPERTY, "App.Billing.Status.Ready"): 1,
            (NODE_PROPERTY, "App.Billing.Status.Done"): 1,
            (NODE_VARIABLE, "App.Billing.GLOBAL"): 1,
        }
    )
    assert nodes["App.Billing.Processor"].docstring == "Processor docs"
    assert nodes["App.Billing.Processor.config"].docstring == "Field docs"
    assert nodes["App.Billing.Processor.other"].docstring == "Field docs"
    assert _named_edges(result, EDGE_IMPORTS) == [("Service.php", "Repo")]
    assert _named_edges(result, EDGE_INHERITS) == [("App.Billing.Processor", "Base")]
    assert _named_edges(result, EDGE_IMPLEMENTS) == [
        ("App.Billing.Processor", "Contract"),
        ("App.Billing.Processor", "OtherContract"),
        ("App.Billing.Status", "Label"),
    ]
    assert _named_edges(result, EDGE_DECORATED_BY) == [
        ("App.Billing.Processor", "Service"),
        ("App.Billing.Processor.config", "FieldAttr"),
        ("App.Billing.Processor.other", "FieldAttr"),
        ("App.Billing.Processor.__construct", "Inject"),
    ]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("App.Billing.Processor", "Logs"),
        ("App.Billing.Processor", "Vendor.Metrics"),
        ("App.Billing.Processor.config", "Config"),
        ("App.Billing.Processor.other", "Config"),
        ("App.Billing.Processor.__construct", "Repo"),
        ("App.Billing.Processor.__construct", "Config"),
        ("App.Billing.Processor.repo", "Repo"),
        ("App.Billing.Processor.run", "Input"),
        ("App.Billing.Processor.run", "Other"),
        ("App.Billing.Processor.run", "Result"),
        ("App.Billing.Processor.run", "Jsonable"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("App.Billing.Processor.run", "helper"),
        ("App.Billing.Processor.run", "Vendor.util"),
        ("App.Billing.Processor.run", "this.client.api.call"),
        ("App.Billing.Processor.run", "this.client.api"),
        ("App.Billing.Processor.run", "this.make"),
        ("App.Billing.Processor.run", "this.late"),
        ("App.Billing.Processor.run", "this.base"),
        ("App.Billing.Processor.run", "Widget"),
        ("App.Billing.Processor.run", "Widget"),
    ]


def test_php_braced_namespaces_keep_symbols_in_their_exact_scope() -> None:
    source = rb"""<?php
namespace One {
 class First {
  public int $value;
  public function __construct(private Repo $repo) {}
 }
}
namespace Two\Deep { function work(): Result {} }
"""
    result = PhpParser().parse(file_path="Scopes.php", source=source)
    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "Scopes.php"),
        (NODE_NAMESPACE, "One"),
        (NODE_CLASS, "One.First"),
        (NODE_FIELD, "One.First.value"),
        (NODE_METHOD, "One.First.__construct"),
        (NODE_FIELD, "One.First.repo"),
        (NODE_NAMESPACE, "Two.Deep"),
        ("function", "Two.Deep.work"),
    }
    assert (
        PhpParser().root_prefix(
            PhpParser()._get_parser().parse(source).root_node, source
        )
        == ""
    )
    function = _nodes_of_type(PhpParser(), source, "function_definition")[0]
    assert PhpParser().type_refs(function, source) == ["Result"]


def test_php_single_braced_namespace_never_becomes_a_root_prefix() -> None:
    source = rb"""<?php
namespace Solo {
 class Box { public function __construct(private Repo $repo) {} }
}
"""
    parser = PhpParser()
    root = parser._get_parser().parse(source).root_node
    assert parser.root_prefix(root, source) == ""
    result = parser.parse(file_path="Solo.php", source=source)
    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "Solo.php"),
        (NODE_NAMESPACE, "Solo"),
        (NODE_CLASS, "Solo.Box"),
        (NODE_METHOD, "Solo.Box.__construct"),
        (NODE_FIELD, "Solo.Box.repo"),
    }


def test_php_interfaces_traits_and_qualified_supertypes_are_exact() -> None:
    source = rb"""<?php
namespace Domain;
interface Child extends BaseContract, Vendor\RemoteContract {
 public const FLAG = 1;
 public function execute(): Result;
}
trait TracksChanges {
 public Config $state;
 public function touch(): void {}
}
class Model extends BaseModel implements Child {}
"""
    result = PhpParser().parse(file_path="Types.php", source=source)
    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "Types.php"),
        (NODE_NAMESPACE, "Domain"),
        ("interface", "Domain.Child"),
        (NODE_PROPERTY, "Domain.Child.FLAG"),
        (NODE_METHOD, "Domain.Child.execute"),
        (NODE_CLASS, "Domain.TracksChanges"),
        (NODE_FIELD, "Domain.TracksChanges.state"),
        (NODE_METHOD, "Domain.TracksChanges.touch"),
        (NODE_CLASS, "Domain.Model"),
    }
    assert _named_edges(result, EDGE_INHERITS) == [
        ("Domain.Child", "BaseContract"),
        ("Domain.Child", "RemoteContract"),
        ("Domain.Model", "BaseModel"),
    ]
    assert _named_edges(result, EDGE_IMPLEMENTS) == [("Domain.Model", "Child")]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("Domain.Child.execute", "Result"),
        ("Domain.TracksChanges.state", "Config"),
    ]


def test_php_dnf_optional_and_builtin_type_hooks_are_exact() -> None:
    source = rb"""<?php
class Types {
 public ?Config $XconfigX;
 #[Vendor\Typed] public const Config ITEM = null;
 public function combine((Left&Right)|Other $value, INT $count): Vendor\Result|null {}
}
"""
    parser = PhpParser()
    field = _nodes_of_type(parser, source, "property_element")[0]
    method = _nodes_of_type(parser, source, "method_declaration")[0]
    assert parser.type_refs(field, source) == ["Config"]
    constant = _nodes_of_type(parser, source, "const_element")[0]
    assert parser.type_refs(constant, source) == ["Config"]
    assert parser.type_refs(method, source) == [
        "Left",
        "Right",
        "Other",
        "Result",
    ]
    result = parser.parse(file_path="Types.php", source=source)
    typed = next(node for node in result.nodes if node.name == "ITEM")
    assert typed.qualified_name == "Types.ITEM"
    assert _named_edges(result, EDGE_DECORATED_BY) == [("Types.ITEM", "Typed")]


def test_php_expression_and_document_helpers_keep_boundaries() -> None:
    source = rb"""<?php
Vendor\helper();
$this->client->run();
self::$factory;
"""
    parser = PhpParser()
    qualified = _nodes_of_type(parser, source, "qualified_name")[0]
    member = _nodes_of_type(parser, source, "member_call_expression")[0]
    scoped = _nodes_of_type(parser, source, "scoped_property_access_expression")[0]
    root = parser._get_parser().parse(source).root_node

    assert _php_expression_path(qualified, source) == "Vendor.helper"
    assert _php_expression_path(member, source) == "this.client.run"
    assert _php_expression_path(scoped, source) == "this.factory"
    assert _php_expression_path(root, source) is None
    assert _php_namespace_name(qualified, source) == "Vendor.helper"
    assert _strip_phpdoc("/**X docs X*/") == "X docs X"
    assert _strip_phpdoc("/**\n * Summary\n * @param X $x\n * Detail\n */") == (
        "Summary\nDetail"
    )


def test_php_non_matching_nodes_do_not_emit_language_hooks() -> None:
    parser = PhpParser()
    source = b"<?php echo 'ok';"
    root = parser._get_parser().parse(source).root_node
    assert parser.classify(root, source, inside_class=False) is None
    assert parser.import_refs(root, source) == []
    assert parser.call_target(root, source) is None
    assert parser.reference_targets(root, source) == []
    assert parser.supertypes(root, source) == []
    assert parser.docstring(root, source) is None
    assert parser.decorators(root, source) == []
    assert parser.type_refs(root, source) == []


def test_php_malformed_hook_inputs_fail_closed() -> None:
    parser = PhpParser()
    empty_namespace = _FakeNode("namespace_definition")
    fake_root = _FakeNode("program", children=[empty_namespace])
    group = _FakeNode("namespace_use_group")
    grouped_use = _FakeNode("namespace_use_declaration", children=[group])
    empty_clause = _FakeNode("namespace_use_clause")
    call = _FakeNode("function_call_expression")
    unknown = _FakeNode("unknown")

    assert parser.root_prefix(cast(Node, fake_root), b"") == ""
    assert parser.import_refs(cast(Node, grouped_use), b"") == []
    assert parser._use_clause_ref(cast(Node, empty_clause), b"", prefix="") is None
    assert parser.call_target(cast(Node, call), b"") is None
    assert parser._field_name(cast(Node, unknown), b"") is None
    assert _php_promoted_property_prefix(cast(Node, unknown), b"") is None


def test_php_expression_paths_fail_closed_when_receivers_are_missing() -> None:
    source = b"XnameX"
    name = _FakeNode("name", start_byte=0, end_byte=len(source))
    member = _FakeNode("member_call_expression", fields={"name": name})
    scoped = _FakeNode("scoped_call_expression", fields={"name": name})
    namespace = _FakeNode(
        "qualified_name",
        start_byte=0,
        end_byte=len(b"\\XRootX\\Thing\\"),
    )

    assert _php_expression_path(cast(Node, member), source) == "XnameX"
    assert _php_expression_path(cast(Node, scoped), source) == "XnameX"
    assert (
        _php_namespace_name(cast(Node, namespace), b"\\XRootX\\Thing\\")
        == "XRootX.Thing"
    )
