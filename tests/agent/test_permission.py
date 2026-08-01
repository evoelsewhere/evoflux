"""Tests for app/agent/permission.py — rules engine and permission service."""

from __future__ import annotations

import asyncio

import pytest

from app.agent.permission import (
    PermissionDeniedError,
    PermissionRejectedError,
    PermissionService,
    Rule,
    command_always_pattern,
    evaluate,
    get_permission_service,
    get_service_for_session,
    get_services_for_stream,
    reset_permission_service,
    ruleset_from_config,
    set_permission_service,
)


# ---------------------------------------------------------------------------
# evaluate() — rule engine
# ---------------------------------------------------------------------------


def test_evaluate_no_rules_returns_ask():
    rule = evaluate("shell", "git status")
    assert rule.action == "ask"


def test_evaluate_allow_wildcard():
    rules = [Rule(permission="*", pattern="*", action="allow")]
    rule = evaluate("shell", "git status", rules)
    assert rule.action == "allow"


def test_evaluate_deny_specific_tool():
    rules = [Rule(permission="shell", pattern="*", action="deny")]
    rule = evaluate("shell", "git status", rules)
    assert rule.action == "deny"


def test_evaluate_last_rule_wins():
    """More specific rule appended later overrides broad wildcard."""
    rules = [
        Rule(permission="*", pattern="*", action="deny"),
        Rule(permission="shell", pattern="git *", action="allow"),
    ]
    rule = evaluate("shell", "git status", rules)
    assert rule.action == "allow"


def test_evaluate_pattern_glob_matching():
    rules = [Rule(permission="shell", pattern="git *", action="allow")]
    # Matches
    assert evaluate("shell", "git status", rules).action == "allow"
    assert evaluate("shell", "git commit -m 'msg'", rules).action == "allow"
    # Does not match (falls through to default ask)
    assert evaluate("shell", "rm -rf /", rules).action == "ask"


def test_evaluate_permission_glob():
    """Wildcard permission glob matches multiple tools."""
    rules = [Rule(permission="*", pattern="ls *", action="allow")]
    assert evaluate("shell", "ls -la", rules).action == "allow"
    assert evaluate("read", "ls -la", rules).action == "allow"


def test_evaluate_multiple_rulesets():
    base = [Rule(permission="*", pattern="*", action="ask")]
    session = [Rule(permission="shell", pattern="git status", action="allow")]
    rule = evaluate("shell", "git status", base, session)
    assert rule.action == "allow"


def test_evaluate_deny_wins_when_last():
    rules = [
        Rule(permission="shell", pattern="*", action="allow"),
        Rule(permission="shell", pattern="rm *", action="deny"),
    ]
    assert evaluate("shell", "rm file.txt", rules).action == "deny"
    assert evaluate("shell", "ls -la", rules).action == "allow"


# ---------------------------------------------------------------------------
# PermissionDeniedError
# ---------------------------------------------------------------------------


def test_permission_denied_error_message():
    rules = [Rule(permission="shell", pattern="*", action="deny")]
    err = PermissionDeniedError("shell", "rm file", rules)
    assert "shell" in str(err)
    assert "rm file" in str(err)


# ---------------------------------------------------------------------------
# PermissionService.ask()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_allow_returns_immediately():
    service = PermissionService(
        session_id="s1",
        base_ruleset=[Rule(permission="shell", pattern="*", action="allow")],
    )
    # Should not raise or block
    await service.ask("shell", ["git status"])


@pytest.mark.asyncio
async def test_ask_deny_raises_denied_error():
    service = PermissionService(
        session_id="s1",
        base_ruleset=[Rule(permission="shell", pattern="*", action="deny")],
    )
    with pytest.raises(PermissionDeniedError):
        await service.ask("shell", ["git status"])


@pytest.mark.asyncio
async def test_ask_and_reply_once():
    """ask() blocks until reply() is called with 'once'."""
    service = PermissionService(session_id="s1")

    async def _reply_later():
        await asyncio.sleep(0.01)
        reqs = service.list_pending()
        assert len(reqs) == 1
        service.reply(reqs[0].id, "once")

    asyncio.create_task(_reply_later())
    await service.ask("shell", ["git status"])  # should not raise


@pytest.mark.asyncio
async def test_ask_and_reply_always_adds_to_session_ruleset():
    """reply('always') adds pattern to session ruleset so next call is auto-allowed."""
    service = PermissionService(session_id="s1")

    async def _reply_always():
        await asyncio.sleep(0.01)
        reqs = service.list_pending()
        service.reply(reqs[0].id, "always")

    asyncio.create_task(_reply_always())
    await service.ask("shell", ["git status"], always_patterns=["git *"])

    # Second call should auto-allow (session_ruleset has git * → allow)
    await service.ask("shell", ["git commit"])  # no reply needed


@pytest.mark.asyncio
async def test_ask_and_reply_reject_raises():
    """reply('reject') causes ask() to raise PermissionRejectedError."""
    service = PermissionService(session_id="s1")

    async def _reject():
        await asyncio.sleep(0.01)
        reqs = service.list_pending()
        service.reply(reqs[0].id, "reject")

    asyncio.create_task(_reject())
    with pytest.raises(PermissionRejectedError):
        await service.ask("shell", ["rm file"])


@pytest.mark.asyncio
async def test_reply_unknown_request_returns_false():
    service = PermissionService(session_id="s1")
    result = service.reply("nonexistent-id", "always")
    assert result is False


# ---------------------------------------------------------------------------
# Mode-aware behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_mode_allows_without_blocking():
    service = PermissionService(session_id="s1", mode="auto")
    # Should return immediately without any reply and register nothing pending
    await service.ask("shell", ["git status"])
    await service.ask("shell", ["rm file.txt"])
    assert service.list_pending() == []


@pytest.mark.asyncio
async def test_important_action_still_confirms_in_auto_mode():
    service = PermissionService(session_id="s1", mode="auto")

    async def _reply_later():
        while not service.list_pending():
            await asyncio.sleep(0)
        service.reply(service.list_pending()[0].id, "once")

    asyncio.create_task(_reply_later())
    await service.ask(
        "merge_code_review",
        ["merge_code_review"],
        important=True,
    )


@pytest.mark.asyncio
async def test_auto_mode_still_denies_deny_rules():
    service = PermissionService(
        session_id="s1",
        base_ruleset=[Rule(permission="shell", pattern="sudo *", action="deny")],
        mode="auto",
    )
    with pytest.raises(PermissionDeniedError):
        await service.ask("shell", ["sudo rm -rf /"])

    # Other commands auto-allowed
    await service.ask("shell", ["git status"])


@pytest.mark.asyncio
async def test_bypass_mode_skips_even_deny_rules():
    service = PermissionService(
        session_id="s1",
        base_ruleset=[Rule(permission="*", pattern="*", action="deny")],
        mode="bypass",
    )
    await service.ask("shell", ["rm -rf /"])  # no raise, no pending
    assert service.list_pending() == []


@pytest.mark.asyncio
async def test_accept_edits_mode_allows_edit_tools_but_blocks_shell():
    service = PermissionService(session_id="s1", mode="accept-edits")
    # Edit tools pass without a reply
    await service.ask("edit", ["/tmp/file.py"])
    await service.ask("write", ["/tmp/file.py"])
    await service.ask("patch", ["/tmp/file.py"])

    # Shell still blocks until replied
    async def _reply_later():
        await asyncio.sleep(0.01)
        reqs = service.list_pending()
        assert len(reqs) == 1
        service.reply(reqs[0].id, "once")

    asyncio.create_task(_reply_later())
    await service.ask("shell", ["rm file.txt"])


@pytest.mark.asyncio
async def test_ask_mode_allows_safe_read_only_tools():
    """Read-only, coordination, and lazy-loader tools never block in ask mode."""
    service = PermissionService(session_id="s1", mode="ask")
    await service.ask("read", ["/etc/hosts"])
    await service.ask("grep", ["pattern"])
    await service.ask("team_handoff", ["team_handoff"])
    await service.ask("skill", ["skill"])
    await service.ask("load_tool", ["load_tool"])
    assert service.list_pending() == []


@pytest.mark.asyncio
async def test_blocking_ask_fires_on_ask_callback():
    fired = []

    def callback(req):
        fired.append(req)

    service = PermissionService(session_id="s1", mode="ask", on_ask=callback)

    async def _reply_later():
        await asyncio.sleep(0.01)
        service.reply(service.list_pending()[0].id, "once")

    asyncio.create_task(_reply_later())
    await service.ask("shell", ["git status"])
    assert len(fired) == 1
    assert fired[0].tool == "shell"
    assert "git status" in fired[0].patterns


# ---------------------------------------------------------------------------
# set_mode — live mode switching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_mode_to_auto_resolves_pending():
    """Switching ask → auto unblocks a waiting tool call."""
    service = PermissionService(session_id="s1", mode="ask")
    task = asyncio.create_task(service.ask("shell", ["rm file.txt"]))
    await asyncio.sleep(0.01)
    assert len(service.list_pending()) == 1

    resolved = service.set_mode("auto")
    assert len(resolved) == 1
    await task  # completes without raising
    assert service.mode == "auto"


@pytest.mark.asyncio
async def test_set_mode_to_accept_edits_resolves_only_edit_tools():
    service = PermissionService(session_id="s1", mode="ask")
    edit_task = asyncio.create_task(service.ask("edit", ["/tmp/f.py"]))
    shell_task = asyncio.create_task(service.ask("shell", ["rm -rf /tmp"]))
    await asyncio.sleep(0.01)
    assert len(service.list_pending()) == 2

    resolved = service.set_mode("accept-edits")
    assert len(resolved) == 1
    await edit_task  # unblocked

    # shell request still pending — resolve it to let the task finish
    assert len(service.list_pending()) == 1
    service.reply(service.list_pending()[0].id, "reject")
    with pytest.raises(PermissionRejectedError):
        await shell_task


# ---------------------------------------------------------------------------
# Session registry — HTTP endpoints resolve services out-of-context
# ---------------------------------------------------------------------------


def test_registry_set_and_reset():
    service = PermissionService(session_id="member-1", stream_session_id="lead-1")
    token = set_permission_service(service)
    try:
        assert get_service_for_session("member-1") is service
        assert get_services_for_stream("lead-1") == [service]
        assert get_services_for_stream("member-1") == [service]
        assert get_services_for_stream("other") == []
    finally:
        reset_permission_service(token, "member-1")
    assert get_service_for_session("member-1") is None
    assert get_services_for_stream("lead-1") == []


# ---------------------------------------------------------------------------
# command_always_pattern
# ---------------------------------------------------------------------------


def test_command_always_pattern_arity():
    assert command_always_pattern("git status -sb") == "git status *"
    assert command_always_pattern("git status") == "git status"
    assert command_always_pattern("rm -rf /tmp/x") == "rm *"
    assert command_always_pattern("ls") == "ls"
    assert command_always_pattern("npm run build") == "npm run *"


# ---------------------------------------------------------------------------
# ruleset_from_config
# ---------------------------------------------------------------------------


def test_ruleset_from_config_string_value():
    config = {"shell": "allow", "read": "deny"}
    rules = ruleset_from_config(config)
    # shell → allow *
    assert any(r.permission == "shell" and r.action == "allow" for r in rules)
    assert any(r.permission == "read" and r.action == "deny" for r in rules)


def test_ruleset_from_config_dict_value():
    config = {
        "shell": {
            "git *": "allow",
            "rm *": "deny",
        }
    }
    rules = ruleset_from_config(config)
    git_rule = next(
        r for r in rules if r.permission == "shell" and r.pattern == "git *"
    )
    assert git_rule.action == "allow"
    rm_rule = next(r for r in rules if r.permission == "shell" and r.pattern == "rm *")
    assert rm_rule.action == "deny"


def test_ruleset_from_config_wildcard_sorted_first():
    """Wildcard permission entries appear before specific ones."""
    config = {"shell": "allow", "*": "ask", "read": "deny"}
    rules = ruleset_from_config(config)
    # Wildcard (*) should appear before specific tools in the list
    wildcard_idx = next(i for i, r in enumerate(rules) if r.permission == "*")
    shell_idx = next(i for i, r in enumerate(rules) if r.permission == "shell")
    assert wildcard_idx < shell_idx


# ---------------------------------------------------------------------------
# Context-var integration
# ---------------------------------------------------------------------------


def test_get_permission_service_returns_default():
    """get_permission_service() returns a default service when no context is set."""
    service = get_permission_service()
    assert service is not None
    assert isinstance(service, PermissionService)


def test_set_permission_service_sets_context():
    """set_permission_service() makes the service accessible via get_permission_service()."""
    custom = PermissionService(session_id="test-ctx", mode="auto")
    token = set_permission_service(custom)
    try:
        retrieved = get_permission_service()
        assert retrieved is custom
    finally:
        reset_permission_service(token, "test-ctx")


# ---------------------------------------------------------------------------
# PermissionService.auto_allow_all_pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_allow_all_pending():
    """auto_allow_all_pending() resolves all pending futures."""
    service = PermissionService(session_id="s1")

    tasks = [asyncio.create_task(service.ask("shell", [f"cmd{i}"])) for i in range(3)]
    await asyncio.sleep(0.01)
    count = service.auto_allow_all_pending()
    assert count == 3

    # All tasks should complete now
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_interrupt_cancel_publishes_permission_replied():
    """Interrupt while blocked must dismiss the FE approval UI via SSE."""
    from unittest.mock import AsyncMock, patch

    service = PermissionService(
        session_id="member-1", stream_session_id="lead-1", mode="ask"
    )
    task = asyncio.create_task(service.ask("shell", ["rm -rf /tmp/x"]))
    for _ in range(100):
        if service.list_pending():
            break
        await asyncio.sleep(0.005)
    assert service.list_pending()
    request_id = service.list_pending()[0].id

    pushed: list = []

    async def _capture(session_id: str, envelope) -> None:
        pushed.append((session_id, envelope))

    with patch(
        "app.services.memory_stream_store.push_event",
        new=AsyncMock(side_effect=_capture),
    ):
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    replied = [
        (sid, env)
        for sid, env in pushed
        if getattr(env, "event", None) == "permission_replied"
    ]
    assert len(replied) == 1
    session_id, envelope = replied[0]
    assert session_id == "lead-1"
    assert envelope.data["request_id"] == request_id
    assert envelope.data["session_id"] == "member-1"
    assert envelope.data["reply"] == "reject"
    assert service.list_pending() == []
