"""Tests for PHP, Ruby, Scala, Dart, ObjC, Lua, R, Pascal, web component parsers."""

from __future__ import annotations

import pytest

from app.services.code_index.parsers.dart import DartParser
from app.services.code_index.parsers.lua import LuaParser, LuauParser
from app.services.code_index.parsers.objc import ObjCParser
from app.services.code_index.parsers.pascal import PascalParser
from app.services.code_index.parsers.php import PhpParser
from app.services.code_index.parsers.r_lang import RParser
from app.services.code_index.parsers.registry import default_registry
from app.services.code_index.parsers.ruby import RubyParser
from app.services.code_index.parsers.scala import ScalaParser
from app.services.code_index.parsers.web_components import (
    AstroParser,
    LiquidParser,
    SvelteParser,
    VueParser,
)
from app.services.code_index.graph_types import (
    EDGE_CALLS,
    EDGE_IMPLEMENTS,
    EDGE_IMPORTS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_ENUM,
    NODE_FUNCTION,
    NODE_INTERFACE,
    NODE_METHOD,
    NODE_MODULE,
    NODE_PROPERTY,
    NODE_STRUCT,
    NODE_VARIABLE,
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
    assert "obj.run" in calls
    assert "Animal.create" in calls


def test_php_namespace_qualifies_classes_functions_and_methods():
    source = b"""<?php
namespace App\\Billing;
class Service { function run() {} }
function top() {}
"""
    result = PhpParser().parse(file_path="Service.php", source=source)
    qualified = {node.name: node.qualified_name for node in result.nodes}

    assert qualified["Service"] == "App.Billing.Service"
    assert qualified["run"] == "App.Billing.Service.run"
    assert qualified["top"] == "App.Billing.top"


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


def test_ruby_attribute_macros_emit_implicit_methods():
    source = b"""class User
  attr_reader :name, :age
  attr_writer :secret
  attr_accessor :email, :phone
end
"""
    result = RubyParser().parse(file_path="user.rb", source=source)
    methods = {node.qualified_name for node in result.nodes if node.kind == NODE_METHOD}

    assert methods == {
        "User.name",
        "User.age",
        "User.secret=",
        "User.email",
        "User.email=",
        "User.phone",
        "User.phone=",
    }
    assert not {"attr_reader", "attr_writer", "attr_accessor"}.intersection(
        _edge_names(result.edges, EDGE_CALLS)
    )


def test_ruby_compact_namespace_preserves_owner_and_superclass():
    source = b"""class Admin::Account < Core::Record
    def self.build; end
end
"""
    result = RubyParser().parse(file_path="account.rb", source=source)
    qualified = {node.name: node.qualified_name for node in result.nodes}

    assert qualified["Account"] == "Admin.Account"
    assert qualified["build"] == "Admin.Account.build"
    assert _edge_names(result.edges, EDGE_INHERITS) == ["Core.Record"]


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


def test_scala_package_qualifies_declarations():
    source = b"""package com.acme.billing
class Service { def run(): Unit = {} }
def top(): Unit = {}
"""
    result = ScalaParser().parse(file_path="Service.scala", source=source)
    qualified = {node.name: node.qualified_name for node in result.nodes}

    assert qualified["Service"] == "com.acme.billing.Service"
    assert qualified["run"] == "com.acme.billing.Service.run"
    assert qualified["top"] == "com.acme.billing.top"


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


def test_dart_extracts_function_constructor_and_method_calls():
    source = b"""void test() {
  helper();
  final animal = Animal();
  final named = Animal.named();
  animal.run();
  Service.instance.execute<String>();
  await fetchData();
}
"""
    result = DartParser().parse(file_path="main.dart", source=source)
    calls = set(_edge_names(result.edges, EDGE_CALLS))

    assert calls == {
        "helper",
        "Animal",
        "Animal.named",
        "animal.run",
        "Service.instance.execute",
        "fetchData",
    }


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


def test_objc_properties_emit_implicit_accessors():
    source = b"""@interface User : NSObject
@property (nonatomic, copy) NSString *name;
@property (readonly) BOOL active;
@end
"""
    result = ObjCParser().parse(file_path="User.h", source=source)
    methods = {node.qualified_name for node in result.nodes if node.kind == NODE_METHOD}
    properties = {
        node.qualified_name for node in result.nodes if node.kind == NODE_PROPERTY
    }

    assert properties == {"User.name", "User.active"}
    assert methods == {"User.name", "User.setName", "User.active"}


def test_objc_categories_protocol_inheritance_calls_and_type_coalescing():
    source = b"""@protocol Child <Parent, Logging>
- (void)run;
@end
@interface NSString (Uppercase) <Logging>
- (NSString *)uppercase;
@end
@implementation NSString (Uppercase)
- (NSString *)uppercase { return [self uppercaseString]; }
@end
@interface User : NSObject
@end
@implementation User
@end
"""
    result = ObjCParser().parse(file_path="Models.m", source=source)
    classes = [node for node in result.nodes if node.kind == NODE_CLASS]
    qualified = {node.name: node.qualified_name for node in result.nodes}

    assert [node.qualified_name for node in classes] == [
        "NSString+Uppercase",
        "User",
    ]
    assert qualified["uppercase"] == "NSString+Uppercase.uppercase"
    assert set(_edge_names(result.edges, EDGE_INHERITS)) == {
        "Parent",
        "Logging",
        "NSObject",
    }
    assert "Logging" in _edge_names(result.edges, EDGE_IMPLEMENTS)
    assert "uppercaseString" in _edge_names(result.edges, EDGE_CALLS)


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


@pytest.mark.parametrize("parser", [LuaParser(), LuauParser()])
def test_lua_function_values_and_deep_method_owners(parser):
    source = b"""local first = function() helper() end
second = function() end
M.run = function() end
function M.Sub.deep() end
"""
    result = parser.parse(file_path=f"main{parser.extensions[0]}", source=source)
    qualified = {node.name: node.qualified_name for node in result.nodes}

    assert qualified["first"] == "first"
    assert qualified["second"] == "second"
    assert qualified["run"] == "M.run"
    assert qualified["deep"] == "M.Sub.deep"
    first = next(node for node in result.nodes if node.name == "first")
    assert any(
        edge.kind == EDGE_CALLS
        and edge.src_local_id == first.local_id
        and edge.dst_name == "helper"
        for edge in result.edges
    )


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


def test_r_member_calls_and_right_assigned_functions():
    source = b"""obj$run()
(function(x) x) -> handler
"""
    result = RParser().parse(file_path="main.R", source=source)

    assert "obj.run" in _edge_names(result.edges, EDGE_CALLS)
    functions = {node.name for node in result.nodes if node.kind == NODE_FUNCTION}
    assert "handler" in functions


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


def test_pascal_nested_procedure_keeps_lexical_owner():
    source = b"""program Main;
procedure Outer;
  procedure Inner;
  begin
  end;
begin
  Inner;
end;
begin
  Outer;
end.
"""
    result = PascalParser().parse(file_path="main.pas", source=source)
    qualified = {node.name: node.qualified_name for node in result.nodes}

    assert qualified["Outer"] == "Outer"
    assert qualified["Inner"] == "Outer.Inner"


def test_pascal_unit_types_properties_inheritance_and_calls():
    source = b"""unit Billing.Service;
interface
type
  TState = (Idle, Running);
  TRecord = record Value: Integer; end;
  TService = class(TObject, IRunner)
    property Name: String read FName write FName;
    procedure Run(input: TInput): TResult;
  end;
implementation
procedure TService.Run(input: TInput): TResult;
begin
  Helper();
  Utils.Work();
end;
end.
"""
    result = PascalParser().parse(file_path="Billing.Service.pas", source=source)
    by_kind = {
        kind: {node.qualified_name for node in result.nodes if node.kind == kind}
        for kind in (NODE_MODULE, NODE_ENUM, NODE_STRUCT, NODE_CLASS, NODE_PROPERTY)
    }

    assert by_kind[NODE_MODULE] == {"Billing.Service"}
    assert by_kind[NODE_ENUM] == {"Billing.Service.TState"}
    assert by_kind[NODE_STRUCT] == {"Billing.Service.TRecord"}
    assert "Billing.Service.TService" in by_kind[NODE_CLASS]
    assert by_kind[NODE_PROPERTY] == {"Billing.Service.TService.Name"}
    assert "TObject" in _edge_names(result.edges, EDGE_INHERITS)
    assert "IRunner" in _edge_names(result.edges, EDGE_IMPLEMENTS)
    assert {"Helper", "Work"}.issubset(_edge_names(result.edges, EDGE_CALLS))
    assert {"TInput", "TResult"}.issubset(_edge_names(result.edges, EDGE_REFERENCES))


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


def test_svelte_merges_script_blocks_with_absolute_locations():
    source = b"""<h1>Title</h1>
<script module lang="ts">
import type { Config } from './types';
export function load(config: Config) {}
</script>
<script lang="ts">
function click(): Result { return run(); }
</script>
"""
    result = SvelteParser().parse(file_path="App.svelte", source=source)
    functions = {
        node.name: node.line_start
        for node in result.nodes
        if node.kind == NODE_FUNCTION
    }

    assert result.language == "svelte"
    assert functions == {"load": 4, "click": 7}
    assert _edge_names(result.edges, EDGE_IMPORTS) == ["Config"]
    assert set(_edge_names(result.edges, EDGE_REFERENCES)) == {"Config", "Result"}


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


def test_vue_merges_normal_and_setup_scripts():
    source = b"""<template><button /></template>
<script lang="ts">
export function shared(config: Config): SharedResult { return build(); }
</script>
<script setup lang="ts">
import type { Props } from './types';
function setup(props: Props): SetupResult { return mount(); }
</script>
"""
    result = VueParser().parse(file_path="App.vue", source=source)
    functions = {
        node.name: node.line_start
        for node in result.nodes
        if node.kind == NODE_FUNCTION
    }

    assert result.language == "vue"
    assert functions == {"shared": 3, "setup": 7}
    assert _edge_names(result.edges, EDGE_IMPORTS) == ["Props"]
    assert set(_edge_names(result.edges, EDGE_REFERENCES)) == {
        "Config",
        "SharedResult",
        "Props",
        "SetupResult",
    }


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


def test_astro_preserves_frontmatter_language_and_locations():
    source = b"""---
import type { Layout } from './Layout';
function render(layout: Layout): Result { return build(); }
---
<main />
"""
    result = AstroParser().parse(file_path="Page.astro", source=source)
    render = next(node for node in result.nodes if node.name == "render")

    assert result.language == "astro"
    assert render.line_start == 3
    assert _edge_names(result.edges, EDGE_IMPORTS) == ["Layout"]
    assert set(_edge_names(result.edges, EDGE_REFERENCES)) == {"Layout", "Result"}


def test_liquid_variable_tags_emit_definitions():
    source = b"""{% assign title = product.title %}
{% capture body %}Hi{% endcapture %}
{% increment counter %}
{% decrement remaining %}
"""
    result = LiquidParser().parse(file_path="card.liquid", source=source)
    variables = {node.name for node in result.nodes if node.kind == NODE_VARIABLE}

    assert variables == {"title", "body", "counter", "remaining"}


def test_liquid_loop_bindings_and_template_dependencies():
    source = b"""{% for item in items %}{{ item }}{% endfor %}
{% tablerow product in products %}{{ product.name }}{% endtablerow %}
{% include 'shared' %}
{% render 'isolated' %}
"""
    result = LiquidParser().parse(file_path="collection.liquid", source=source)

    variables = {node.name for node in result.nodes if node.kind == NODE_VARIABLE}
    assert variables == {"item", "product"}
    assert _edge_names(result.edges, EDGE_CALLS) == ["shared", "isolated"]
    assert [
        (edge.dst_name, edge.module_path)
        for edge in result.edges
        if edge.kind == EDGE_IMPORTS
    ] == [("shared", "shared"), ("isolated", "isolated")]


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
