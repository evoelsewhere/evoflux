"""Exact behavioral contracts for Pascal/Delphi graph extraction."""

from __future__ import annotations

from collections import Counter

from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_CONTAINS,
    EDGE_IMPORTS,
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FIELD,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_MODULE,
    NODE_PROPERTY,
    NODE_STRUCT,
    NODE_VARIABLE,
)
from app.services.code_index.parsers.pascal import PascalParser


def _named_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], edge.dst_name)
        for edge in result.edges
        if edge.kind == kind and edge.dst_name is not None
    ]


def _local_edges(result, kind: str):
    names = {node.local_id: node.qualified_name for node in result.nodes}
    return [
        (names[edge.src_local_id], names[edge.dst_local_id])
        for edge in result.edges
        if edge.kind == kind and edge.dst_local_id is not None
    ]


def test_pascal_symbols_types_calls_imports_docs_and_coalescing_are_exact() -> None:
    source = b"""///Billing module
unit Billing.Service;
interface
uses System.SysUtils, App.Types in 'src/Types.pas';
procedure GlobalHook;
const
  ///Default limit
  DefaultLimit: TLimit = 10;
var GlobalRepo: TRepository;
    GlobalConfig: Vendor.Types.TConfig;
type
  TAlias = specialize TList<TItem>;
  TState = (Idle, Running);
  TRecord = record
    Value: Integer;
    Config: TConfig;
  end;
  IService = interface(IBase, IAuditable)
    procedure Execute(input: TInput);
  end;
  TService = class(TObject, IService)
  private
    ///Repository dependency
    FRepo: TRepository;
  public
    property Name: TName read FName write FName;
    constructor Create(repo: TRepository);
    ///Run docs
    ///Second line
    function Run(input: TInput): TResult;
  end;
implementation
uses Math;
constructor TService.Create(repo: TRepository);
begin
  FRepo := repo;
end;
function TService.Run(input: TInput): TResult;
begin
  Helper();
  Utils.Work();
  FRepo.Save();
end;
end.
"""
    result = PascalParser().parse(file_path="Billing.Service.pas", source=source)
    nodes = {node.qualified_name: node for node in result.nodes}

    assert Counter(
        (node.kind, node.qualified_name) for node in result.nodes
    ) == Counter(
        {
            ("file", "Billing.Service.pas"): 1,
            (NODE_MODULE, "Billing.Service"): 1,
            ("function", "Billing.Service.GlobalHook"): 1,
            (NODE_VARIABLE, "Billing.Service.DefaultLimit"): 1,
            (NODE_VARIABLE, "Billing.Service.GlobalRepo"): 1,
            (NODE_VARIABLE, "Billing.Service.GlobalConfig"): 1,
            (NODE_CLASS, "Billing.Service.TAlias"): 1,
            (NODE_ENUM, "Billing.Service.TState"): 1,
            (NODE_PROPERTY, "Billing.Service.TState.Idle"): 1,
            (NODE_PROPERTY, "Billing.Service.TState.Running"): 1,
            (NODE_STRUCT, "Billing.Service.TRecord"): 1,
            (NODE_FIELD, "Billing.Service.TRecord.Value"): 1,
            (NODE_FIELD, "Billing.Service.TRecord.Config"): 1,
            (NODE_INTERFACE, "Billing.Service.IService"): 1,
            (NODE_METHOD, "Billing.Service.IService.Execute"): 1,
            (NODE_CLASS, "Billing.Service.TService"): 1,
            (NODE_FIELD, "Billing.Service.TService.FRepo"): 1,
            (NODE_PROPERTY, "Billing.Service.TService.Name"): 1,
            (NODE_METHOD, "Billing.Service.TService.Create"): 1,
            (NODE_METHOD, "Billing.Service.TService.Run"): 1,
        }
    )
    assert nodes["Billing.Service"].docstring == "Billing module"
    assert nodes["Billing.Service.DefaultLimit"].docstring == "Default limit"
    assert nodes["Billing.Service.TService.FRepo"].docstring == (
        "Repository dependency"
    )
    assert nodes["Billing.Service.TService.Run"].docstring == ("Run docs\nSecond line")
    implementation_line = (
        source[: source.index(b"function TService.Run")].count(b"\n") + 1
    )
    assert nodes["Billing.Service.TService.Run"].line_start == implementation_line
    contains = _local_edges(result, EDGE_CONTAINS)
    assert ("Billing.Service.TService", "Billing.Service.TService.Create") in contains
    assert ("Billing.Service.TService", "Billing.Service.TService.Run") in contains
    assert ("Billing.Service", "Billing.Service.TService.Run") not in contains
    assert _named_edges(result, EDGE_IMPORTS) == [
        ("Billing.Service", "SysUtils"),
        ("Billing.Service", "Types"),
        ("Billing.Service", "Math"),
    ]
    assert [
        (edge.dst_name, edge.module_path)
        for edge in result.edges
        if edge.kind == EDGE_IMPORTS
    ] == [
        ("SysUtils", "System.SysUtils"),
        ("Types", "src/Types.pas"),
        ("Math", "Math"),
    ]
    assert _named_edges(result, EDGE_INHERITS) == [
        ("Billing.Service.IService", "IBase"),
        ("Billing.Service.IService", "IAuditable"),
        ("Billing.Service.TService", "TObject"),
    ]
    assert _named_edges(result, EDGE_IMPLEMENTS) == [
        ("Billing.Service.TService", "IService")
    ]
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("Billing.Service.DefaultLimit", "TLimit"),
        ("Billing.Service.GlobalRepo", "TRepository"),
        ("Billing.Service.GlobalConfig", "Vendor.Types.TConfig"),
        ("Billing.Service.TAlias", "TList"),
        ("Billing.Service.TAlias", "TItem"),
        ("Billing.Service.TRecord.Config", "TConfig"),
        ("Billing.Service.IService.Execute", "TInput"),
        ("Billing.Service.TService.FRepo", "TRepository"),
        ("Billing.Service.TService.Name", "TName"),
        ("Billing.Service.TService.Create", "TRepository"),
        ("Billing.Service.TService.Run", "TInput"),
        ("Billing.Service.TService.Run", "TResult"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("Billing.Service.TService.Run", "Helper"),
        ("Billing.Service.TService.Run", "Utils.Work"),
        ("Billing.Service.TService.Run", "FRepo.Save"),
    ]


def test_pascal_program_nested_functions_and_array_types_are_exact() -> None:
    source = b"""program Demo;
uses Foo.Bar;
var Items: array of TItem;
type TWorker = class
  procedure Execute;
end;
procedure TWorker.Execute;
begin
  Service.Start();
end;
procedure Outer(value: TInput);
  procedure Inner(config: TConfig);
  begin
    Worker.Run();
  end;
begin
  Inner(nil);
end;
begin
  Outer(nil);
end.
"""
    result = PascalParser().parse(file_path="Demo.dpr", source=source)

    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "Demo.dpr"),
        (NODE_MODULE, "Demo"),
        (NODE_VARIABLE, "Demo.Items"),
        (NODE_CLASS, "Demo.TWorker"),
        (NODE_METHOD, "Demo.TWorker.Execute"),
        ("function", "Demo.Outer"),
        ("function", "Demo.Outer.Inner"),
    }
    assert _named_edges(result, EDGE_REFERENCES) == [
        ("Demo.Items", "TItem"),
        ("Demo.Outer", "TInput"),
        ("Demo.Outer.Inner", "TConfig"),
    ]
    assert _named_edges(result, EDGE_CALLS) == [
        ("Demo.TWorker.Execute", "Service.Start"),
        ("Demo.Outer.Inner", "Worker.Run"),
        ("Demo.Outer", "Inner"),
        ("Demo", "Outer"),
    ]


def test_pascal_overloads_coalesce_by_case_insensitive_signature() -> None:
    source = b"""unit Overloads;
interface
type TRun = class
  procedure Run;
end;
procedure Run ( value : Integer ); overload;
procedure Run(value: String); overload;
implementation
procedure TRun.Run;
begin
  ClassHandler();
end;
procedure run(value:integer);
begin
  IntegerHandler();
end;
procedure RUN(value:string);
begin
  StringHandler();
end;
end.
"""
    result = PascalParser().parse(file_path="Overloads.pas", source=source)
    runs = [node for node in result.nodes if node.qualified_name == "Overloads.Run"]
    class_runs = [
        node for node in result.nodes if node.qualified_name == "Overloads.TRun.Run"
    ]

    assert len(runs) == 2
    assert {node.name for node in runs} == {"Run"}
    assert {node.line_start for node in runs} == {13, 17}
    assert len(class_runs) == 1
    assert class_runs[0].name == "Run"
    assert class_runs[0].line_start == 9
    assert _named_edges(result, EDGE_CALLS) == [
        ("Overloads.TRun.Run", "ClassHandler"),
        ("Overloads.Run", "IntegerHandler"),
        ("Overloads.Run", "StringHandler"),
    ]


def test_pascal_library_root_is_a_module() -> None:
    result = PascalParser().parse(
        file_path="Toolkit.lpr",
        source=b"""library Toolkit;
type TTool = class
  procedure Run;
end;
procedure TTool.Run;
begin end;
begin end.
""",
    )

    assert {(node.kind, node.qualified_name) for node in result.nodes} == {
        ("file", "Toolkit.lpr"),
        (NODE_MODULE, "Toolkit"),
        (NODE_CLASS, "Toolkit.TTool"),
        (NODE_METHOD, "Toolkit.TTool.Run"),
    }


def test_pascal_language_hooks_reject_unrelated_nodes() -> None:
    parser = PascalParser()
    source = b"42"
    root = parser._get_parser().parse(source).root_node

    assert parser.classify(root, source, inside_class=False) is None
    assert parser.call_target(root, source) is None
    assert parser.import_refs(root, source) == []
    assert parser.supertypes(root, source) == []
    assert parser.type_refs(root, source) == []
    assert parser.docstring(root, source) is None
    assert parser.identifier_reference_targets(root, source) == []

    fragment = parser.parse(
        file_path="fragment.inc",
        source=b"procedure TTool.Run; begin end;",
    )
    assert {(node.kind, node.qualified_name) for node in fragment.nodes} == {
        ("file", "fragment.inc"),
        (NODE_METHOD, "TTool.Run"),
    }
