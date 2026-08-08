"""Model-facing code-index search contract."""

from __future__ import annotations


def test_code_search_is_bounded_deferred_discovery() -> None:
    from app.agent.tools.builtin.code_search import code_search

    assert code_search.deferred is True
    assert code_search.read_only is True
    assert code_search.deduplicate_in_batch is True
    assert "parser-aligned" in code_search.description
    assert "code_graph" in code_search.description
    schema = code_search.definition["function"]["parameters"]
    assert schema["required"] == ["query"]
    assert set(schema["properties"]) == {
        "query",
        "repository",
        "path",
        "language",
        "freshness_policy",
        "limit",
    }
    assert schema["properties"]["limit"]["maximum"] == 50
    assert schema["properties"]["freshness_policy"]["default"] == "fast"
