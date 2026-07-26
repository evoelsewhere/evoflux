"""Tests for P5: Reference edges from type annotations."""

from __future__ import annotations

from app.services.code_graph.parsers.csharp import CSharpParser
from app.services.code_graph.parsers.ecmascript import TypeScriptParser
from app.services.code_graph.parsers.go import GoParser
from app.services.code_graph.parsers.java import JavaParser
from app.services.code_graph.parsers.lua import LuauParser
from app.services.code_graph.parsers.python import PythonParser
from app.services.code_graph.types import EDGE_REFERENCES


_py = PythonParser()
_ts = TypeScriptParser()
_java = JavaParser()
_go = GoParser()
_csharp = CSharpParser()
_luau = LuauParser()


def _refs(source: str, parser) -> list[tuple[str, str]]:
    """Return (src_name, dst_type_name) pairs for EDGE_REFERENCES."""
    result = parser.parse(
        file_path=f"test{parser.extensions[0]}", source=source.encode()
    )
    node_names = {n.local_id: n.name for n in result.nodes}
    out: list[tuple[str, str]] = []
    for e in result.edges:
        if e.kind == EDGE_REFERENCES:
            src_name = node_names.get(e.src_local_id, e.src_local_id or "?")
            out.append((src_name, e.dst_name or "?"))
    return out


# ── Python ──────────────────────────────────────────────────────────────────


class TestPythonTypeRefs:
    def test_param_annotation(self) -> None:
        src = """\
def greet(name: str, config: AppConfig) -> Response:
    pass
"""
        refs = _refs(src, _py)
        # str is a builtin → skipped
        assert ("greet", "AppConfig") in refs
        assert ("greet", "Response") in refs
        assert ("greet", "str") not in refs

    def test_generic_type(self) -> None:
        src = """\
def process(items: list[Item], mapping: dict[str, Config]) -> None:
    pass
"""
        refs = _refs(src, _py)
        assert ("process", "Item") in refs
        assert ("process", "Config") in refs
        # list, dict, str, None are builtins
        assert ("process", "list") not in refs
        assert ("process", "dict") not in refs

    def test_union_type(self) -> None:
        src = """\
def handle(data: Request | None) -> Result | Error:
    pass
"""
        refs = _refs(src, _py)
        assert ("handle", "Request") in refs
        assert ("handle", "Result") in refs
        assert ("handle", "Error") in refs

    def test_no_annotation(self) -> None:
        src = """\
def plain(x, y):
    pass
"""
        refs = _refs(src, _py)
        assert refs == []


# ── TypeScript ──────────────────────────────────────────────────────────────


class TestTypeScriptTypeRefs:
    def test_param_and_return(self) -> None:
        src = """\
function greet(name: string, config: AppConfig): Response {
}
"""
        refs = _refs(src, _ts)
        assert ("greet", "AppConfig") in refs
        assert ("greet", "Response") in refs
        assert ("greet", "string") not in refs

    def test_method_types(self) -> None:
        src = """\
class Svc {
    handle(req: Request): Promise<Result> {}
}
"""
        refs = _refs(src, _ts)
        assert ("handle", "Request") in refs
        assert ("handle", "Result") in refs

    def test_optional_param(self) -> None:
        src = """\
function load(id: number, opts?: Options): void {
}
"""
        refs = _refs(src, _ts)
        assert ("load", "Options") in refs
        assert ("load", "number") not in refs
        assert ("load", "void") not in refs


# ── Luau ───────────────────────────────────────────────────────────────────


class TestLuauTypeRefs:
    def test_aliases_and_typed_functions(self) -> None:
        src = """\
export type User = { friend: Other?, mapper: (Input) -> Result }
type Mapper<T> = (T) -> Result
local function typed(x: Input, count: number): Result return x end
local callback: (Input) -> Result = function(x: Input): Result return x end
"""
        refs = _refs(src, _luau)

        assert ("User", "Other") in refs
        assert ("User", "Input") in refs
        assert ("User", "Result") in refs
        assert ("Mapper", "Result") in refs
        assert ("Mapper", "T") not in refs
        assert ("typed", "Input") in refs
        assert ("typed", "Result") in refs
        assert ("callback", "Input") in refs
        assert ("callback", "Result") in refs


# ── Java ────────────────────────────────────────────────────────────────────


class TestJavaTypeRefs:
    def test_method_params_and_return(self) -> None:
        src = """\
public class Svc {
    public Response handle(Request req, Config cfg) {}
}
"""
        refs = _refs(src, _java)
        assert ("handle", "Response") in refs
        assert ("handle", "Request") in refs
        assert ("handle", "Config") in refs

    def test_void_skipped(self) -> None:
        src = """\
public class Svc {
    public void run() {}
}
"""
        refs = _refs(src, _java)
        # void is builtin
        assert refs == []

    def test_string_skipped(self) -> None:
        src = """\
public class Svc {
    public String getName() {}
}
"""
        refs = _refs(src, _java)
        assert refs == []


# ── Go ──────────────────────────────────────────────────────────────────────


class TestGoTypeRefs:
    def test_func_params_and_return(self) -> None:
        src = """\
package main

func Handle(req *Request, cfg Config) Response {
}
"""
        refs = _refs(src, _go)
        assert ("Handle", "Request") in refs
        assert ("Handle", "Config") in refs
        assert ("Handle", "Response") in refs

    def test_builtin_skipped(self) -> None:
        src = """\
package main

func Add(a int, b int) int {
}
"""
        refs = _refs(src, _go)
        assert refs == []

    def test_method_types(self) -> None:
        src = """\
package main

func (s *Server) Listen(addr string) error {
}
"""
        refs = _refs(src, _go)
        # string and error are builtins
        assert ("Listen", "Server") not in refs  # receiver not a type ref
        assert refs == []


# ── C# ──────────────────────────────────────────────────────────────────────


class TestCSharpTypeRefs:
    def test_nested_generic_nullable_and_array_types(self) -> None:
        src = """\
public class UserService {
    public Task<Result<User[]>> Handle(Request? request, int limit) {}
}
"""
        refs = _refs(src, _csharp)
        assert ("Handle", "Task") in refs
        assert ("Handle", "Result") in refs
        assert ("Handle", "User") in refs
        assert ("Handle", "Request") in refs
        assert ("Handle", "int") not in refs

    def test_constructor_parameter_types(self) -> None:
        src = """\
public class UserService {
    public UserService(IRepository<User> repository) {}
}
"""
        refs = _refs(src, _csharp)
        assert ("UserService", "IRepository") in refs
        assert ("UserService", "User") in refs
