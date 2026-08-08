"""Tests for Java dependency-injection field edges (EDGE_USES)."""

from __future__ import annotations

from app.services.code_index.parsers.java import JavaParser
from app.services.code_index.graph_types import EDGE_USES

_java = JavaParser()


def _uses_edges(source: str) -> list[tuple[str, str]]:
    """Parse source and return (src_name, dst_name) for EDGE_USES."""
    result = _java.parse(file_path="Test.java", source=source.encode())
    node_names = {n.local_id: n.name for n in result.nodes}
    return [
        (node_names.get(e.src_local_id, e.src_local_id or "?"), e.dst_name or "?")
        for e in result.edges
        if e.kind == EDGE_USES
    ]


def test_autowired_field_is_di_edge() -> None:
    src = """\
public class OrderResource {
    @Autowired
    private OrderService orderService;
}
"""
    assert _uses_edges(src) == [("OrderResource", "OrderService")]


def test_inject_and_resource_annotations_are_di_edges() -> None:
    src = """\
public class OrderResource {
    @Inject
    private OrderService orderService;
    @Resource
    private AuditLogger auditLogger;
}
"""
    assert set(_uses_edges(src)) == {
        ("OrderResource", "OrderService"),
        ("OrderResource", "AuditLogger"),
    }


def test_uninitialized_final_field_is_di_edge_without_annotation() -> None:
    """Lombok's @RequiredArgsConstructor generates the constructor, so the
    field itself often carries no @Autowired — an uninitialized final field
    can only be set by some constructor, so it's a real dependency either way."""
    src = """\
public class OrderResource {
    private final OrderService orderService;
}
"""
    assert _uses_edges(src) == [("OrderResource", "OrderService")]


def test_final_field_with_initializer_is_not_di_edge() -> None:
    """A final field assigned inline is a constant/eagerly-built value, not
    something a constructor injects."""
    src = """\
public class OrderResource {
    private final OrderService orderService = new OrderServiceImpl();
}
"""
    assert _uses_edges(src) == []


def test_plain_mutable_field_is_not_di_edge() -> None:
    """No annotation and not final — too weak a signal to call it DI."""
    src = """\
public class OrderResource {
    private OrderService orderService;
}
"""
    assert _uses_edges(src) == []


def test_final_primitive_field_is_not_di_edge() -> None:
    src = """\
public class OrderResource {
    private static final int MAX_RESULTS = 50;
}
"""
    assert _uses_edges(src) == []


def test_constructor_and_setter_params_are_unaffected() -> None:
    """Constructor/setter parameter types already flow through type_refs() as
    EDGE_REFERENCES — uses_target() must not double-emit them as EDGE_USES."""
    src = """\
public class OrderResource {
    private final OrderService orderService;

    @Autowired
    public OrderResource(OrderService orderService) {
        this.orderService = orderService;
    }
}
"""
    # The field itself still yields exactly one DI edge; the constructor
    # parameter is not a field_declaration and must not add a second one.
    assert _uses_edges(src) == [("OrderResource", "OrderService")]
