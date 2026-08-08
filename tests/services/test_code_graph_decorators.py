"""Tests for P4: decorator/annotation edges."""

from __future__ import annotations

from app.services.code_index.parsers.ecmascript import TypeScriptParser
from app.services.code_index.parsers.java import JavaParser
from app.services.code_index.parsers.python import PythonParser
from app.services.code_index.graph_types import EDGE_DECORATED_BY

_py = PythonParser()
_ts = TypeScriptParser()
_java = JavaParser()


def _edges_of(source: str, parser) -> list[tuple[str, str, str]]:
    """Parse source and return (src_name, kind, dst_name) for EDGE_DECORATED_BY."""
    result = parser.parse(
        file_path=f"test{parser.extensions[0]}", source=source.encode()
    )
    out: list[tuple[str, str, str]] = []
    node_names = {n.local_id: n.name for n in result.nodes}
    for e in result.edges:
        if e.kind == EDGE_DECORATED_BY:
            src_name = node_names.get(e.src_local_id, e.src_local_id or "?")
            out.append((src_name, e.kind, e.dst_name or "?"))
    return out


# ── Python ──────────────────────────────────────────────────────────────────


class TestPythonDecorators:
    def test_simple_decorator(self) -> None:
        src = """\
@app.route
def handler():
    pass
"""
        edges = _edges_of(src, _py)
        assert ("handler", EDGE_DECORATED_BY, "app.route") in edges

    def test_decorator_with_args(self) -> None:
        src = """\
@login_required(redirect="/")
def view():
    pass
"""
        edges = _edges_of(src, _py)
        assert ("view", EDGE_DECORATED_BY, "login_required") in edges

    def test_multiple_decorators(self) -> None:
        src = """\
@staticmethod
@cache
def compute():
    pass
"""
        edges = _edges_of(src, _py)
        assert ("compute", EDGE_DECORATED_BY, "staticmethod") in edges
        assert ("compute", EDGE_DECORATED_BY, "cache") in edges

    def test_class_decorator(self) -> None:
        src = """\
@dataclass
class Config:
    name: str
"""
        edges = _edges_of(src, _py)
        assert ("Config", EDGE_DECORATED_BY, "dataclass") in edges

    def test_dotted_decorator_with_call(self) -> None:
        src = """\
@app.get("/api")
def endpoint():
    pass
"""
        edges = _edges_of(src, _py)
        assert ("endpoint", EDGE_DECORATED_BY, "app.get") in edges


# ── TypeScript ──────────────────────────────────────────────────────────────


class TestTypeScriptDecorators:
    def test_class_decorator(self) -> None:
        src = """\
@Injectable()
class Service {}
"""
        edges = _edges_of(src, _ts)
        assert ("Service", EDGE_DECORATED_BY, "Injectable") in edges

    def test_simple_class_decorator(self) -> None:
        src = """\
@sealed
class Greeter {}
"""
        edges = _edges_of(src, _ts)
        assert ("Greeter", EDGE_DECORATED_BY, "sealed") in edges

    def test_method_decorator(self) -> None:
        src = """\
class Ctrl {
    @Get("/")
    index() {}
}
"""
        edges = _edges_of(src, _ts)
        assert ("index", EDGE_DECORATED_BY, "Get") in edges


# ── Java ────────────────────────────────────────────────────────────────────


class TestJavaDecorators:
    def test_class_annotation(self) -> None:
        src = """\
@Entity
public class User {}
"""
        edges = _edges_of(src, _java)
        assert ("User", EDGE_DECORATED_BY, "Entity") in edges

    def test_annotation_with_args(self) -> None:
        src = """\
@Table(name = "users")
public class User {}
"""
        edges = _edges_of(src, _java)
        assert ("User", EDGE_DECORATED_BY, "Table") in edges

    def test_method_annotation(self) -> None:
        src = """\
public class Ctrl {
    @Override
    public void run() {}
}
"""
        edges = _edges_of(src, _java)
        assert ("run", EDGE_DECORATED_BY, "Override") in edges

    def test_multiple_annotations(self) -> None:
        src = """\
@Service
@Transactional
public class OrderService {}
"""
        edges = _edges_of(src, _java)
        assert ("OrderService", EDGE_DECORATED_BY, "Service") in edges
        assert ("OrderService", EDGE_DECORATED_BY, "Transactional") in edges
