"""Tests for Go, Rust, Java, C# parsers."""

from __future__ import annotations

from pathlib import Path


from app.services.code_graph.parsers.csharp import CSharpParser
from app.services.code_graph.parsers.go import GoParser
from app.services.code_graph.parsers.java import JavaParser
from app.services.code_graph.parsers.registry import default_registry
from app.services.code_graph.parsers.rust import RustParser
from app.services.code_graph.types import (
    EDGE_CALLS,
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
)


def _by_kind(nodes, kind):
    return [n for n in nodes if n.kind == kind]


# ── Go parser ─────────────────────────────────────────────────────────────────


def test_go_parser_extracts_struct_interface_function():
    source = b"""package main

// Animal represents a living creature.
type Animal struct {
    Name string
}

type Runner interface {
    Run()
}

func helper() {}
"""
    result = GoParser().parse(file_path="main.go", source=source)

    classes = _by_kind(result.nodes, NODE_CLASS)
    interfaces = _by_kind(result.nodes, NODE_INTERFACE)
    functions = _by_kind(result.nodes, NODE_FUNCTION)

    assert [c.name for c in classes] == ["Animal"]
    assert classes[0].docstring is not None
    assert "living creature" in classes[0].docstring
    assert [i.name for i in interfaces] == ["Runner"]
    assert [f.name for f in functions] == ["helper"]


def test_go_parser_extracts_methods():
    source = b"""package main

func (a *Animal) Run() {
    fmt.Println(a.Name)
}
"""
    result = GoParser().parse(file_path="main.go", source=source)

    methods = _by_kind(result.nodes, NODE_METHOD)
    assert [m.name for m in methods] == ["Run"]


def test_go_parser_extracts_calls():
    source = b"""package main

func main() {
    a := Animal{}
    a.Run()
    helper()
}
"""
    result = GoParser().parse(file_path="main.go", source=source)

    calls = [e for e in result.edges if e.kind == EDGE_CALLS]
    call_names = {e.dst_name for e in calls}
    assert "a.Run" in call_names
    assert "helper" in call_names


def test_go_parser_interface_embedding():
    source = b"""package main

type ReadWriter interface {
    Reader
    Writer
}
"""
    result = GoParser().parse(file_path="main.go", source=source)

    implements = [e for e in result.edges if e.kind == EDGE_IMPLEMENTS]
    names = {e.dst_name for e in implements}
    assert "Reader" in names
    assert "Writer" in names


# ── Rust parser ───────────────────────────────────────────────────────────────


def test_rust_parser_extracts_struct_trait_function():
    source = b"""/// An animal in the zoo.
pub struct Animal {
    name: String,
}

pub trait Runner {
    fn run(&self);
}

fn helper() {}
"""
    result = RustParser().parse(file_path="lib.rs", source=source)

    classes = _by_kind(result.nodes, NODE_CLASS)
    interfaces = _by_kind(result.nodes, NODE_INTERFACE)
    functions = _by_kind(result.nodes, NODE_FUNCTION)

    assert [c.name for c in classes] == ["Animal"]
    assert classes[0].docstring is not None
    assert "animal in the zoo" in classes[0].docstring
    assert [i.name for i in interfaces] == ["Runner"]
    assert [f.name for f in functions] == ["helper"]


def test_rust_parser_extracts_impl_methods():
    source = b"""impl Animal {
    fn new(name: String) -> Self {
        Animal { name }
    }

    fn speak(&self) {
        println!("{}", self.name);
    }
}
"""
    result = RustParser().parse(file_path="lib.rs", source=source)

    classes = _by_kind(result.nodes, NODE_CLASS)
    methods = _by_kind(result.nodes, NODE_METHOD)

    assert [c.name for c in classes] == ["Animal"]
    assert set(m.name for m in methods) == {"new", "speak"}
    # Methods should be qualified under impl target
    assert any(m.qualified_name == "Animal.new" for m in methods)
    assert any(m.qualified_name == "Animal.speak" for m in methods)


def test_rust_parser_trait_impl_emits_implements():
    source = b"""impl Runner for Animal {
    fn run(&self) {}
}
"""
    result = RustParser().parse(file_path="lib.rs", source=source)

    implements = [e for e in result.edges if e.kind == EDGE_IMPLEMENTS]
    assert any(e.dst_name == "Runner" for e in implements)


def test_rust_parser_extracts_calls():
    source = b"""fn main() {
    let a = Animal::new("cat".into());
    a.run();
    helper();
}
"""
    result = RustParser().parse(file_path="main.rs", source=source)

    calls = [e for e in result.edges if e.kind == EDGE_CALLS]
    call_names = {e.dst_name for e in calls}
    assert "Animal.new" in call_names
    assert "a.run" in call_names
    assert "helper" in call_names


def test_rust_parser_enum():
    source = b"""pub enum Direction {
    North,
    South,
    East,
    West,
}
"""
    result = RustParser().parse(file_path="lib.rs", source=source)
    classes = _by_kind(result.nodes, NODE_CLASS)
    assert [c.name for c in classes] == ["Direction"]


# ── Java parser ───────────────────────────────────────────────────────────────


def test_java_parser_extracts_class_interface_method():
    source = b"""package com.example;

/**
 * An animal in the zoo.
 */
public class Animal extends Base implements Runner {
    private String name;

    public Animal(String name) {
        this.name = name;
    }

    public void run() {
        System.out.println(name);
    }
}

interface Runner {
    void run();
}
"""
    result = JavaParser().parse(file_path="Animal.java", source=source)

    classes = _by_kind(result.nodes, NODE_CLASS)
    interfaces = _by_kind(result.nodes, NODE_INTERFACE)
    methods = _by_kind(result.nodes, NODE_METHOD)

    assert "Animal" in [c.name for c in classes]
    assert classes[0].docstring is not None
    assert "animal in the zoo" in classes[0].docstring
    assert [i.name for i in interfaces] == ["Runner"]
    assert "run" in [m.name for m in methods]
    assert "Animal" in [m.name for m in methods]  # constructor


def test_java_parser_extracts_inheritance():
    source = b"""public class Animal extends Base implements Runner, Serializable {}
"""
    result = JavaParser().parse(file_path="Animal.java", source=source)

    inherits = [e for e in result.edges if e.kind == EDGE_INHERITS]
    implements = [e for e in result.edges if e.kind == EDGE_IMPLEMENTS]

    assert any(e.dst_name == "Base" for e in inherits)
    assert any(e.dst_name == "Runner" for e in implements)
    assert any(e.dst_name == "Serializable" for e in implements)


def test_java_parser_extracts_calls():
    source = b"""public class Main {
    public void doStuff() {
        Animal a = new Animal("cat");
        a.run();
        helper();
    }
}
"""
    result = JavaParser().parse(file_path="Main.java", source=source)

    calls = [e for e in result.edges if e.kind == EDGE_CALLS]
    call_names = {e.dst_name for e in calls}
    assert "Animal" in call_names
    assert "run" in call_names
    assert "helper" in call_names


def test_java_parser_enum_and_record():
    source = b"""public enum Direction { NORTH, SOUTH }

public record Point(int x, int y) {}
"""
    result = JavaParser().parse(file_path="Types.java", source=source)
    classes = _by_kind(result.nodes, NODE_CLASS)
    names = {c.name for c in classes}
    assert "Direction" in names
    assert "Point" in names


# ── C# parser ─────────────────────────────────────────────────────────────────


def test_csharp_parser_extracts_class_interface_method():
    source = b"""using System;

namespace Animals {
    /// <summary>An animal in the zoo.</summary>
    public class Animal : Base, IRunner {
        private string _name;

        public Animal(string name) {
            _name = name;
        }

        public void Run() {
            Console.WriteLine(_name);
        }
    }

    public interface IRunner {
        void Run();
    }
}
"""
    result = CSharpParser().parse(file_path="Animal.cs", source=source)

    classes = _by_kind(result.nodes, NODE_CLASS)
    interfaces = _by_kind(result.nodes, NODE_INTERFACE)
    methods = _by_kind(result.nodes, NODE_METHOD)

    assert "Animal" in [c.name for c in classes]
    assert [i.name for i in interfaces] == ["IRunner"]
    assert "Run" in [m.name for m in methods]
    assert "Animal" in [m.name for m in methods]  # constructor


def test_csharp_parser_extracts_inheritance():
    source = b"""public class Animal : Base, IRunner, IDisposable {}
"""
    result = CSharpParser().parse(file_path="Animal.cs", source=source)

    inherits = [e for e in result.edges if e.kind == EDGE_INHERITS]
    implements = [e for e in result.edges if e.kind == EDGE_IMPLEMENTS]

    assert any(e.dst_name == "Base" for e in inherits)
    assert any(e.dst_name == "IRunner" for e in implements)
    assert any(e.dst_name == "IDisposable" for e in implements)


def test_csharp_parser_extracts_calls():
    source = b"""public class Main {
    public void DoStuff() {
        var a = new Animal("cat");
        a.Run();
        Helper();
    }
}
"""
    result = CSharpParser().parse(file_path="Main.cs", source=source)

    calls = [e for e in result.edges if e.kind == EDGE_CALLS]
    call_names = {e.dst_name for e in calls}
    assert "Animal" in call_names
    assert "Run" in call_names
    assert "Helper" in call_names


def test_csharp_parser_struct_enum_record():
    source = b"""public struct Point { public int X; public int Y; }
public enum Direction { North, South }
public record Person(string Name, int Age);
"""
    result = CSharpParser().parse(file_path="Types.cs", source=source)
    classes = _by_kind(result.nodes, NODE_CLASS)
    names = {c.name for c in classes}
    assert "Point" in names
    assert "Direction" in names
    assert "Person" in names


def test_csharp_parser_docstring():
    source = b"""public class Util {
    /// <summary>
    /// Helper function for testing.
    /// </summary>
    public void Helper() {}
}
"""
    result = CSharpParser().parse(file_path="Util.cs", source=source)
    methods = _by_kind(result.nodes, NODE_METHOD)
    assert methods[0].docstring is not None
    assert "Helper function" in methods[0].docstring


# ── Registry integration ──────────────────────────────────────────────────────


def test_registry_resolves_new_languages():
    registry = default_registry()
    assert registry.for_path("main.go").name == "go"
    assert registry.for_path("lib.rs").name == "rust"
    assert registry.for_path("Animal.java").name == "java"
    assert registry.for_path("Animal.cs").name == "csharp"


# ── Cross-file indexing with new languages ────────────────────────────────────


def test_go_cross_file_indexing(tmp_path: Path):
    from app.services.code_graph.indexer import index_workspace

    (tmp_path / "animal.go").write_text(
        "package main\n\ntype Animal struct{}\n\nfunc (a *Animal) Run() {}\n"
    )
    (tmp_path / "main.go").write_text(
        "package main\n\nfunc main() {\n    a := Animal{}\n    a.Run()\n}\n"
    )
    idx = index_workspace(tmp_path)
    # Animal.Run should be resolved from main.go call
    call_edges = [e for e in idx.edges if e.kind == "calls" and e.dst_key is not None]
    resolved_targets = {e.dst_key for e in call_edges}
    run_node = next((n for n in idx.nodes if n.name == "Run"), None)
    assert run_node is not None
    assert run_node.key in resolved_targets


def test_rust_cross_file_indexing(tmp_path: Path):
    from app.services.code_graph.indexer import index_workspace

    (tmp_path / "lib.rs").write_text(
        "pub struct Animal {}\nimpl Animal {\n    pub fn new() -> Self { Animal{} }\n}\n"
    )
    (tmp_path / "main.rs").write_text("fn main() {\n    let a = Animal::new();\n}\n")
    idx = index_workspace(tmp_path)
    call_edges = [e for e in idx.edges if e.kind == "calls" and e.dst_key is not None]
    resolved_targets = {e.dst_key for e in call_edges}
    new_node = next((n for n in idx.nodes if n.name == "new"), None)
    assert new_node is not None
    assert new_node.key in resolved_targets


# ── Coverage audit: Go ────────────────────────────────────────────────────────


def test_go_method_has_receiver_qualified_name():
    source = b"""package main

func (s *Server) Start() {}
func (s Server) Stop() {}
"""
    result = GoParser().parse(file_path="main.go", source=source)
    methods = _by_kind(result.nodes, NODE_METHOD)
    qnames = {m.qualified_name for m in methods}
    assert "Server.Start" in qnames
    assert "Server.Stop" in qnames


def test_go_type_alias():
    source = b"""package main

type HandlerFunc = func(int) error
"""
    result = GoParser().parse(file_path="main.go", source=source)
    classes = _by_kind(result.nodes, NODE_CLASS)
    assert [c.name for c in classes] == ["HandlerFunc"]


# ── Coverage audit: Rust ──────────────────────────────────────────────────────


def test_rust_union_item():
    source = b"""pub union FloatOrInt { f: f64, i: i64 }
"""
    result = RustParser().parse(file_path="lib.rs", source=source)
    classes = _by_kind(result.nodes, NODE_CLASS)
    assert [c.name for c in classes] == ["FloatOrInt"]


def test_rust_type_alias():
    source = b"""pub type Result<T> = std::result::Result<T, AppError>;
"""
    result = RustParser().parse(file_path="lib.rs", source=source)
    classes = _by_kind(result.nodes, NODE_CLASS)
    assert [c.name for c in classes] == ["Result"]


def test_rust_macro_invocations():
    source = b"""fn main() {
    println!("hello");
    vec![1, 2, 3];
}
"""
    result = RustParser().parse(file_path="main.rs", source=source)
    calls = [e for e in result.edges if e.kind == EDGE_CALLS]
    call_names = {e.dst_name for e in calls}
    assert "println" in call_names
    assert "vec" in call_names


# ── Coverage audit: C# ────────────────────────────────────────────────────────


def test_csharp_generic_base_types():
    source = b"""public class Server : AbstractServer, IHandler<Response>, IDisposable {}
"""
    result = CSharpParser().parse(file_path="Server.cs", source=source)
    inherits = [e for e in result.edges if e.kind == EDGE_INHERITS]
    implements = [e for e in result.edges if e.kind == EDGE_IMPLEMENTS]

    assert any(e.dst_name == "AbstractServer" for e in inherits)
    assert any(e.dst_name == "IHandler" for e in implements)
    assert any(e.dst_name == "IDisposable" for e in implements)


def test_csharp_properties_captured():
    source = b"""public class Foo {
    public string Name { get; set; }
    public bool IsOk => true;
}
"""
    result = CSharpParser().parse(file_path="Foo.cs", source=source)
    methods = _by_kind(result.nodes, NODE_METHOD)
    names = {m.name for m in methods}
    assert "Name" in names
    assert "IsOk" in names
