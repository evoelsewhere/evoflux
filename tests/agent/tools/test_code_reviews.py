from app.agent.loader import _default_tool_registry


def test_code_review_api_tools_are_coding_only_and_deferred():
    registry = _default_tool_registry()

    names = (
        "list_code_reviews",
        "get_code_review",
        "create_pull_request",
        "add_code_review_comment",
        "add_code_review_inline_comment",
        "reply_code_review_thread",
        "resolve_code_review_thread",
        "reopen_code_review_thread",
        "submit_code_review",
        "update_code_review",
        "get_code_review_checks",
        "merge_code_review",
        "close_code_review",
        "reopen_code_review",
    )
    for name in names:
        tool = registry[name]
        assert tool.deferred is True
        assert tool.deferred_summary
        assert tool.tiers == frozenset({"coding"})

    assert registry["get_code_review"].read_only is True
    assert registry["get_code_review_checks"].read_only is True
    assert registry["merge_code_review"].read_only is False
    assert registry["close_code_review"].read_only is False
