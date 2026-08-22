"""High-signal symbol coverage contracts for the primary EvoFlux languages."""

from __future__ import annotations

from collections import Counter

from app.services.code_index.graph_types import EDGE_REFERENCES
from app.services.code_index.parsers.ecmascript import TsxParser, TypeScriptParser
from app.services.code_index.parsers.rust import RustParser


def _symbols(result) -> set[tuple[str, str]]:
    return {
        (node.kind, node.qualified_name)
        for node in result.nodes
        if node.kind != "file"
    }


def test_typescript_extracts_api_surface_leaf_symbols_and_details() -> None:
    source = b"""
interface Service {
  readonly id: string;
  "display-name": string;
  run(input: Input): Promise<Output>;
  optional?: number;
}
abstract class Base { abstract execute(): void; }
type Handler = (value: Input) => Output;
enum State { Idle, Running = 2 }
class Worker {
  private count = 0;
  constructor(public client: Client) {}
  async run(input: Input): Promise<Output> { return this.client.send(input); }
}
const helper = (x: Input) => x;
"""

    result = TypeScriptParser().parse(file_path="service.ts", source=source)

    assert _symbols(result) == {
        ("interface", "Service"),
        ("property", "Service.id"),
        ("property", "Service.display-name"),
        ("method", "Service.run"),
        ("property", "Service.optional"),
        ("class", "Base"),
        ("method", "Base.execute"),
        ("class", "Handler"),
        ("enum", "State"),
        ("property", "State.Idle"),
        ("property", "State.Running"),
        ("class", "Worker"),
        ("field", "Worker.count"),
        ("method", "Worker.constructor"),
        ("method", "Worker.run"),
        ("function", "helper"),
    }
    signatures = {
        node.qualified_name: node.signature
        for node in result.nodes
        if node.kind != "file"
    }
    assert signatures["Service.run"] == "run(input: Input): Promise<Output>"
    assert signatures["Worker.count"] == "private count = 0"
    reference_names = {
        edge.dst_name
        for edge in result.edges
        if edge.kind == EDGE_REFERENCES and edge.dst_name
    }
    assert {"Input", "Output", "Promise", "Client"} <= reference_names


def test_tsx_object_types_expose_properties_and_callback_methods() -> None:
    source = b"""
type Props = {
  title: string;
  onSave(value: string): void;
};
export function Card({ title, onSave }: Props) {
  return <button onClick={() => onSave(title)}>{title}</button>;
}
"""

    result = TsxParser().parse(file_path="Card.tsx", source=source)

    assert _symbols(result) == {
        ("class", "Props"),
        ("property", "Props.title"),
        ("method", "Props.onSave"),
        ("function", "Card"),
    }


def test_same_line_union_members_keep_unique_stable_local_ids() -> None:
    source = (
        b"type Row = { type: 'header' } | { type: 'command' }"
        b" | { type: 'separator' };"
    )

    result = TypeScriptParser().parse(file_path="rows.ts", source=source)
    row_types = [
        node
        for node in result.nodes
        if node.qualified_name == "Row.type"
    ]

    assert [node.local_id for node in row_types] == [
        "Row.type#1",
        "Row.type#1:2",
        "Row.type#1:3",
    ]
    assert len({node.local_id for node in result.nodes}) == len(result.nodes)
    assert {node.signature for node in row_types} == {
        "type: 'header'",
        "type: 'command'",
        "type: 'separator'",
    }


def test_rust_extracts_fields_variants_associated_types_and_macros() -> None:
    source = b"""
pub struct User { pub id: u64, name: String }
pub enum State {
    Idle,
    Running { since: u64 },
    Failed(String),
}
pub trait Store {
    type Error;
    const NAME: &'static str;
    fn get(&self, id: u64) -> Result<User, Self::Error>;
}
macro_rules! make_store { () => {} }
impl Store for User {
    type Error = String;
    const NAME: &'static str = "user";
    fn get(&self, id: u64) -> Result<User, Self::Error> { todo!() }
}
"""

    result = RustParser().parse(file_path="store.rs", source=source)
    symbols = _symbols(result)

    assert {
        ("struct", "User"),
        ("field", "User.id"),
        ("field", "User.name"),
        ("enum", "State"),
        ("property", "State.Idle"),
        ("property", "State.Running"),
        ("field", "State.Running.since"),
        ("property", "State.Failed"),
        ("interface", "Store"),
        ("class", "Store.Error"),
        ("variable", "Store.NAME"),
        ("method", "Store.get"),
        ("function", "make_store"),
        ("class", "User.Error"),
        ("variable", "User.NAME"),
        ("method", "User.get"),
    } <= symbols
    kinds = Counter(node.kind for node in result.nodes if node.kind != "file")
    assert kinds["field"] == 3
    assert kinds["property"] == 3
    assert kinds["function"] == 1
    reference_names = {
        edge.dst_name
        for edge in result.edges
        if edge.kind == EDGE_REFERENCES and edge.dst_name
    }
    assert {"String", "Result", "User", "Error"} <= reference_names
