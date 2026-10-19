"""Trust and precedence tests for the lifecycle hook dispatcher."""

from pathlib import Path

import pytest

from app.agent.plugins.hook_contract import (
    HookDefinition,
    HookEvent,
    HookFailurePolicy,
    HookMatcher,
    HookRegistration,
    HookSettingsPolicy,
    HookSource,
)
from app.agent.plugins.hook_dispatcher import dispatch_hooks
from app.agent.plugins.hook_runner import UnavailableHookIsolationBackend


def _registration(
    hook_id: str,
    *,
    source: HookSource = HookSource.MANAGED_PLUGIN,
    trusted: bool = True,
    failure_policy: HookFailurePolicy = HookFailurePolicy.FAIL_OPEN,
) -> HookRegistration:
    definition = HookDefinition(
        hook_id=hook_id,
        event=HookEvent.SESSION_START,
        command=("./hooks/startup.py",),
        timeout_seconds=5,
        input_fields=("source",),
        output_fields=("context", "deny", "reason"),
        failure_policy=failure_policy,
    )
    return HookRegistration(
        hook_id=hook_id,
        plugin_id="example" if source is HookSource.MANAGED_PLUGIN else None,
        event=HookEvent.SESSION_START,
        source=source,
        definition=definition,
        digest="a" * 64,
        trusted=trusted,
    )


@pytest.mark.asyncio
async def test_dispatch_skips_untrusted_and_reports_isolation_block(
    tmp_path: Path,
) -> None:
    trusted = _registration("trusted")
    untrusted = _registration("untrusted", trusted=False)

    result = await dispatch_hooks(
        HookEvent.SESSION_START,
        {"session_id": "s1", "source": "new"},
        settings_policy=HookSettingsPolicy(),
        settings_registrations=(),
        plugin_registrations=(untrusted, trusted),
        plugin_roots={
            (item.source.value, item.plugin_id, item.hook_id): tmp_path
            for item in (trusted, untrusted)
        },
        backend=UnavailableHookIsolationBackend(),
    )

    assert result.decision.denied is True
    assert result.decision.reason == "hook isolation is unavailable"
    assert result.statuses["example:untrusted"] == "awaiting_trust"
    assert result.statuses["example:trusted"] == "blocked_isolation_unavailable"


@pytest.mark.asyncio
async def test_missing_isolation_is_always_a_denial_even_for_fail_open_hook(
    tmp_path: Path,
) -> None:
    registration = _registration(
        "context-only", failure_policy=HookFailurePolicy.FAIL_OPEN
    )

    result = await dispatch_hooks(
        HookEvent.SESSION_START,
        {"session_id": "s1", "source": "new"},
        settings_policy=HookSettingsPolicy(),
        settings_registrations=(),
        plugin_registrations=(registration,),
        plugin_roots={
            (
                registration.source.value,
                registration.plugin_id,
                registration.hook_id,
            ): tmp_path
        },
        backend=UnavailableHookIsolationBackend(),
    )

    assert result.decision.denied is True
    assert result.decision.reason == "hook isolation is unavailable"


@pytest.mark.asyncio
async def test_fail_closed_hook_failure_becomes_denial(tmp_path: Path) -> None:
    registration = _registration(
        "critical", failure_policy=HookFailurePolicy.FAIL_CLOSED
    )

    result = await dispatch_hooks(
        HookEvent.SESSION_START,
        {"session_id": "s1", "source": "new"},
        settings_policy=HookSettingsPolicy(),
        settings_registrations=(),
        plugin_registrations=(registration,),
        plugin_roots={
            (
                registration.source.value,
                registration.plugin_id,
                registration.hook_id,
            ): tmp_path
        },
        backend=UnavailableHookIsolationBackend(),
    )

    assert result.decision.denied is True
    assert result.decision.reason == "hook isolation is unavailable"


@pytest.mark.asyncio
async def test_isolation_launch_error_is_sticky_denial_even_for_fail_open_hook(
    tmp_path: Path,
) -> None:
    from app.plugin_platform.hook_inspection import hook_digest

    executable = tmp_path / "hooks" / "startup.py"
    executable.parent.mkdir()
    executable.write_text("print('{}')\n", encoding="utf-8")
    registration = _registration(
        "launch-error", failure_policy=HookFailurePolicy.FAIL_OPEN
    )
    registration = registration.model_copy(
        update={"digest": hook_digest(tmp_path, registration.definition)}
    )

    class FailingBackend:
        def supports(self, _profile: str) -> bool:
            return True

        async def launch(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise OSError("Job Object could not be assigned")

    result = await dispatch_hooks(
        HookEvent.SESSION_START,
        {"session_id": "s1", "source": "new"},
        settings_policy=HookSettingsPolicy(),
        settings_registrations=(),
        plugin_registrations=(registration,),
        plugin_roots={
            (
                registration.source.value,
                registration.plugin_id,
                registration.hook_id,
            ): tmp_path
        },
        backend=FailingBackend(),
    )

    assert result.decision.denied is True
    assert result.decision.reason == "hook isolation is unavailable"
    assert result.statuses["example:launch-error"] == "blocked_isolation_unavailable"


@pytest.mark.asyncio
async def test_dispatch_obeys_simple_event_matcher(tmp_path: Path) -> None:
    registration = _registration("matched")
    registration = registration.model_copy(
        update={
            "definition": registration.definition.model_copy(
                update={"matcher": HookMatcher(source="resume")}
            )
        }
    )

    result = await dispatch_hooks(
        HookEvent.SESSION_START,
        {"session_id": "s1", "source": "new"},
        settings_policy=HookSettingsPolicy(),
        settings_registrations=(),
        plugin_registrations=(registration,),
        plugin_roots={
            (
                registration.source.value,
                registration.plugin_id,
                registration.hook_id,
            ): tmp_path
        },
    )

    assert result.statuses["example:matched"] == "matcher_not_matched"
