"""Tests for P3: Variable/constant definition capture."""

from __future__ import annotations

from app.services.code_graph.parsers.ecmascript import (
    JavaScriptParser,
    TypeScriptParser,
)
from app.services.code_graph.parsers.go import GoParser
from app.services.code_graph.parsers.python import PythonParser
from app.services.code_graph.parsers.rust import RustParser
from app.services.code_graph.types import NODE_FUNCTION, NODE_VARIABLE


def _vars(result):
    return [n for n in result.nodes if n.kind == NODE_VARIABLE]


# ── Python ───────────────────────────────────────────────────────────────────


def test_python_module_level_constants():
    source = b"""API_URL = "https://api.example.com"
MAX_RETRIES = 3
logger = getLogger(__name__)

def helper():
    local_var = 42
    return local_var
"""
    result = PythonParser().parse(file_path="config.py", source=source)
    variables = _vars(result)
    names = {v.name for v in variables}
    assert "API_URL" in names
    assert "MAX_RETRIES" in names
    assert "logger" in names
    # Local variables inside functions should NOT be captured
    assert "local_var" not in names


def test_python_typed_assignment():
    source = b"""VERSION: str = "1.0.0"
DEBUG: bool = False
"""
    result = PythonParser().parse(file_path="settings.py", source=source)
    variables = _vars(result)
    names = {v.name for v in variables}
    assert "VERSION" in names
    assert "DEBUG" in names


def test_python_skips_dunder():
    source = b"""__all__ = ["Foo", "Bar"]
__version__ = "1.0"
REAL_CONST = 42
"""
    result = PythonParser().parse(file_path="mod.py", source=source)
    variables = _vars(result)
    names = {v.name for v in variables}
    assert "__all__" not in names
    assert "__version__" not in names
    assert "REAL_CONST" in names


def test_python_skips_class_body_assignments():
    source = b"""class Config:
    timeout = 30
    retries = 3
"""
    result = PythonParser().parse(file_path="config.py", source=source)
    variables = _vars(result)
    # Class body assignments should not be captured as module-level variables
    assert len(variables) == 0


# ── TypeScript/JavaScript ────────────────────────────────────────────────────


def test_ts_top_level_const():
    source = b"""const API_URL = "https://api.example.com";
const MAX_RETRIES = 3;
let mutableState = null;

function helper() {
    const local = 42;
    return local;
}
"""
    result = TypeScriptParser().parse(file_path="config.ts", source=source)
    variables = _vars(result)
    names = {v.name for v in variables}
    assert "API_URL" in names
    assert "MAX_RETRIES" in names
    assert "mutableState" in names
    # Local const inside function should NOT be captured
    assert "local" not in names


def test_ts_export_const():
    source = b"""export const VERSION = "1.0.0";
export const config = { timeout: 30 };
"""
    result = TypeScriptParser().parse(file_path="index.ts", source=source)
    variables = _vars(result)
    names = {v.name for v in variables}
    assert "VERSION" in names
    assert "config" in names


def test_ts_function_values_still_functions():
    """Arrow functions / function expressions remain NODE_FUNCTION."""
    source = b"""const handler = () => {};
const helper = function() {};
const normalConst = 42;
"""
    result = TypeScriptParser().parse(file_path="utils.ts", source=source)
    functions = [n for n in result.nodes if n.kind == NODE_FUNCTION]
    variables = _vars(result)
    func_names = {f.name for f in functions}
    var_names = {v.name for v in variables}
    assert "handler" in func_names
    assert "helper" in func_names
    assert "normalConst" in var_names
    # Arrow/function values should NOT also be NODE_VARIABLE
    assert "handler" not in var_names
    assert "helper" not in var_names


def test_js_top_level_var():
    source = b"""var globalState = {};
const API_KEY = "abc123";
"""
    result = JavaScriptParser().parse(file_path="app.js", source=source)
    variables = _vars(result)
    names = {v.name for v in variables}
    assert "globalState" in names
    assert "API_KEY" in names


# ── Go ───────────────────────────────────────────────────────────────────────


def test_go_package_level_const():
    source = b"""package main

const MaxRetries = 3

var GlobalState = make(map[string]int)

func main() {
    x := 5
}
"""
    result = GoParser().parse(file_path="main.go", source=source)
    variables = _vars(result)
    names = {v.name for v in variables}
    assert "MaxRetries" in names
    assert "GlobalState" in names
    # Local variable inside function should NOT be captured
    assert "x" not in names


def test_go_const_inside_func_not_captured():
    """Go const/var inside functions should not be captured."""
    source = b"""package main

func helper() {
    const localConst = 42
    var localVar = "hi"
}
"""
    result = GoParser().parse(file_path="main.go", source=source)
    variables = _vars(result)
    # None should be captured since they're inside a function
    assert len(variables) == 0


# ── Rust ─────────────────────────────────────────────────────────────────────


def test_rust_const_and_static():
    source = b"""const MAX_SIZE: usize = 1024;
static GLOBAL_COUNT: u32 = 0;
static mut MUTABLE_STATE: i32 = 0;

fn main() {
    let local = 5;
}
"""
    result = RustParser().parse(file_path="main.rs", source=source)
    variables = _vars(result)
    names = {v.name for v in variables}
    assert "MAX_SIZE" in names
    assert "GLOBAL_COUNT" in names
    assert "MUTABLE_STATE" in names
    # let bindings inside functions should NOT be captured
    assert "local" not in names
