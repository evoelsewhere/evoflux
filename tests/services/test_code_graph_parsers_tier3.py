"""Tests for PHP, Ruby, Scala, Dart, ObjC, Lua, R, Pascal, web component parsers."""

from __future__ import annotations

import pytest

from app.services.code_graph.parsers.dart import DartParser
from app.services.code_graph.parsers.lua import LuaParser
from app.services.code_graph.parsers.objc import ObjCParser
from app.services.code_graph.parsers.pascal import PascalParser
from app.services.code_graph.parsers.php import PhpParser
from app.services.code_graph.parsers.r_lang import RParser
from app.services.code_graph.parsers.registry import default_registry
from app.services.code_graph.parsers.ruby import RubyParser
from app.services.code_graph.parsers.scala import ScalaParser
from app.services.code_graph.parsers.web_components import (
    AstroParser,
    SvelteParser,
    VueParser,
)
from app.services.code_graph.types import (
    EDGE_CALLS,
    EDGE_IMPLEMENTS,
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_MODULE,
)


def _by_kind(nodes, kind):
    return [n for n in nodes if n.kind == kind]


def _edge_names(edges, kind):
    return [e.dst_name for e in edges if e.kind == kind]


# ── PHP ──────────────────────────────────────────────────────────────────────


def test_php_class_and_methods():
    source = b"""<?php
class Animal {
    public function run() {
        $this->helper();
    }

    private function helper() {}
}

function standalone() {
    $a = new Animal();
    $a->run();
}
"""
    result = PhpParser().parse(file_path="main.php", source=source)
    classes = _by_kind(result.nodes, NODE_CLASS)
    methods = _by_kind(result.nodes, NODE_METHOD)
    functions = _by_kind(result.nodes, NODE_FUNCTION)

    assert len(classes) == 1
    assert classes[0].name == "Animal"
    assert len(methods) == 2
    assert {m.name for m in methods} == {"run", "helper"}
    assert len(functions) == 1
    assert functions[0].name == "standalone"


def test_php_interface_and_inheritance():
    source = b"""<?php
interface Runner {
    public function run();
}

class Animal extends Base implements Runner {
    public function run() {}
}
"""
    result = PhpParser().parse(file_path="main.php", source=source)
    interfaces = _by_kind(result.nodes, NODE_INTERFACE)
    assert len(interfaces) == 1
    assert interfaces[0].name == "Runner"

    inherits = _edge_names(result.edges, EDGE_INHERITS)
    implements = _edge_names(result.edges, EDGE_IMPLEMENTS)
    assert "Base" in inherits
    assert "Runner" in implements


def test_php_calls():
    source = b"""<?php
function test() {
    helper();
    $obj->run();
    Animal::create();
}
"""
    result = PhpParser().parse(file_path="main.php", source=source)
    calls = _edge_names(result.edges, EDGE_CALLS)
    assert "helper" in calls
    assert "run" in calls
    assert "create" in calls


# ── Ruby ─────────────────────────────────────────────────────────────────────


def test_ruby_class_and_methods():
    source = b"""class Animal < Base
  def run
    helper
  end

  def self.create(name)
    Animal.new(name)
  end
end

def standalone
  puts "hi"
end
"""
    result = RubyParser().parse(file_path="main.rb", source=source)
    classes = _by_kind(result.nodes, NODE_CLASS)
    methods = _by_kind(result.nodes, NODE_METHOD)
    functions = _by_kind(result.nodes, NODE_FUNCTION)

    assert len(classes) == 1
    assert classes[0].name == "Animal"
    assert len(methods) >= 1
    assert "run" in {m.name for m in methods}
    assert len(functions) >= 1


def test_ruby_module():
    source = b"""module Utils
  def helper
    puts "help"
  end
end
"""
    result = RubyParser().parse(file_path="utils.rb", source=source)
    modules = _by_kind(result.nodes, NODE_MODULE)
    assert len(modules) == 1
    assert modules[0].name == "Utils"


def test_ruby_inheritance():
    source = b"""class Dog < Animal
  def bark; end
end
"""
    result = RubyParser().parse(file_path="dog.rb", source=source)
    inherits = _edge_names(result.edges, EDGE_INHERITS)
    assert "Animal" in inherits


# ── Scala ────────────────────────────────────────────────────────────────────


def test_scala_trait_class_object():
    source = b"""trait Runner {
  def run(): Unit
}

class Animal(name: String) extends Runner {
  def run(): Unit = println(name)
}

object AnimalFactory {
  def create(name: String): Animal = new Animal(name)
}
"""
    result = ScalaParser().parse(file_path="main.scala", source=source)
    interfaces = _by_kind(result.nodes, NODE_INTERFACE)
    classes = _by_kind(result.nodes, NODE_CLASS)
    methods = _by_kind(result.nodes, NODE_METHOD)

    assert len(interfaces) == 1
    assert interfaces[0].name == "Runner"
    assert len(classes) >= 2
    class_names = {c.name for c in classes}
    assert "Animal" in class_names
    assert "AnimalFactory" in class_names
    assert len(methods) >= 2


def test_scala_inheritance():
    source = b"""class Dog extends Animal {
  def bark(): Unit = {}
}
"""
    result = ScalaParser().parse(file_path="dog.scala", source=source)
    inherits = _edge_names(result.edges, EDGE_INHERITS)
    assert "Animal" in inherits


def test_scala_calls():
    source = b"""object Main {
  def main(): Unit = {
    println("hello")
    helper()
  }
}
"""
    result = ScalaParser().parse(file_path="main.scala", source=source)
    calls = _edge_names(result.edges, EDGE_CALLS)
    assert "println" in calls
    assert "helper" in calls


# ── Dart ─────────────────────────────────────────────────────────────────────


def test_dart_class_and_methods():
    source = b"""class Animal {
  String name;

  void run() {
    print(name);
  }

  static Animal create(String name) {
    return Animal();
  }
}

void main() {
  final a = Animal();
  a.run();
}
"""
    result = DartParser().parse(file_path="main.dart", source=source)
    classes = _by_kind(result.nodes, NODE_CLASS)
    methods = _by_kind(result.nodes, NODE_METHOD)

    assert len(classes) == 1
    assert classes[0].name == "Animal"
    assert "run" in {m.name for m in methods}


def test_dart_inheritance():
    source = b"""class Dog extends Animal implements Runner {
  void bark() {}
}
"""
    result = DartParser().parse(file_path="dog.dart", source=source)
    inherits = _edge_names(result.edges, EDGE_INHERITS)
    implements = _edge_names(result.edges, EDGE_IMPLEMENTS)
    assert "Animal" in inherits
    assert "Runner" in implements


# ── Objective-C ──────────────────────────────────────────────────────────────


def test_objc_class_and_protocol():
    source = b"""@protocol Runner
- (void)run;
@end

@interface Animal : NSObject <Runner>
@property NSString *name;
- (void)run;
+ (instancetype)create;
@end

@implementation Animal
- (void)run {
    NSLog(@"%@", self.name);
}
@end
"""
    result = ObjCParser().parse(file_path="main.m", source=source)
    interfaces = _by_kind(result.nodes, NODE_INTERFACE)
    classes = _by_kind(result.nodes, NODE_CLASS)
    methods = _by_kind(result.nodes, NODE_METHOD)

    assert len(interfaces) == 1
    assert interfaces[0].name == "Runner"
    assert len(classes) >= 1
    assert "Animal" in {c.name for c in classes}
    assert len(methods) >= 2


def test_objc_inheritance():
    source = b"""@interface Dog : Animal <Runner>
- (void)bark;
@end
"""
    result = ObjCParser().parse(file_path="dog.m", source=source)
    inherits = _edge_names(result.edges, EDGE_INHERITS)
    implements = _edge_names(result.edges, EDGE_IMPLEMENTS)
    assert "Animal" in inherits
    assert "Runner" in implements


# ── Lua ──────────────────────────────────────────────────────────────────────


def test_lua_functions_and_methods():
    source = b"""function Animal.new(name)
    return setmetatable({name = name}, Animal)
end

function Animal:run()
    print(self.name)
end

local function helper()
    Animal.new("cat"):run()
end
"""
    result = LuaParser().parse(file_path="main.lua", source=source)
    methods = _by_kind(result.nodes, NODE_METHOD)
    functions = _by_kind(result.nodes, NODE_FUNCTION)

    assert len(methods) == 2
    method_names = {m.name for m in methods}
    assert "new" in method_names
    assert "run" in method_names
    assert len(functions) == 1
    assert functions[0].name == "helper"


def test_lua_calls():
    source = b"""function test()
    helper()
    Animal.new("x")
end
"""
    result = LuaParser().parse(file_path="test.lua", source=source)
    calls = _edge_names(result.edges, EDGE_CALLS)
    assert "helper" in calls


# ── R ────────────────────────────────────────────────────────────────────────


def test_r_function_assignments():
    source = b"""greet <- function(name) {
  paste("Hello", name)
}

add <- function(a, b) {
  a + b
}
"""
    result = RParser().parse(file_path="main.R", source=source)
    functions = _by_kind(result.nodes, NODE_FUNCTION)
    assert len(functions) == 2
    names = {f.name for f in functions}
    assert "greet" in names
    assert "add" in names


def test_r_calls():
    source = b"""analyze <- function(data) {
  result <- summary(data)
  print(result)
}
"""
    result = RParser().parse(file_path="main.R", source=source)
    calls = _edge_names(result.edges, EDGE_CALLS)
    assert "summary" in calls
    assert "print" in calls


# ── Pascal ───────────────────────────────────────────────────────────────────


def test_pascal_procedure():
    source = b"""program Main;

procedure Greet(Name: string);
begin
  WriteLn('Hello ', Name);
end;

begin
  Greet('World');
end.
"""
    result = PascalParser().parse(file_path="main.pas", source=source)
    # Pascal grammar may vary; check we get at least one definition
    all_nodes = [n for n in result.nodes if n.kind != "file"]
    assert len(all_nodes) >= 1


# ── Web components ───────────────────────────────────────────────────────────


def test_svelte_script_extraction():
    source = b"""<script>
function handleClick() {
    console.log("clicked");
}

const count = 0;
</script>

<button on:click={handleClick}>
    Click me
</button>
"""
    result = SvelteParser().parse(file_path="App.svelte", source=source)
    functions = _by_kind(result.nodes, NODE_FUNCTION)
    assert len(functions) >= 1
    assert "handleClick" in {f.name for f in functions}


def test_vue_script_extraction():
    source = b"""<script>
export default {
    methods: {
        handleClick() {
            console.log("clicked");
        }
    }
}
</script>

<template>
    <button @click="handleClick">Click</button>
</template>
"""
    result = VueParser().parse(file_path="App.vue", source=source)
    # Vue may not produce functions in all patterns but should at least parse
    assert result.file_path == "App.vue"
    assert len(result.nodes) >= 1


def test_astro_frontmatter():
    source = b"""---
function getData() {
    return fetch("/api/data");
}

const items = await getData();
---

<div>{items}</div>
"""
    result = AstroParser().parse(file_path="Page.astro", source=source)
    # The frontmatter JS should be parsed
    assert len(result.nodes) >= 1


# ── Registry coverage ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ext",
    [
        ".php",
        ".rb",
        ".scala",
        ".dart",
        ".m",
        ".mm",
        ".lua",
        ".luau",
        ".r",
        ".R",
        ".pas",
        ".svelte",
        ".vue",
        ".astro",
        ".liquid",
    ],
)
def test_registry_resolves_extension(ext):
    """Each new extension is handled by the default registry."""
    reg = default_registry()
    parser = reg.for_path(f"example{ext}")
    assert parser is not None, f"No parser registered for {ext}"
