"""User-defined plugin system.

Plugins are ``.py`` files placed under ``settings.EVOFLUX_PLUGINS_DIRS``
(default ``{EVOFLUX_CONFIG_DIR}/plugins``).  At agent-build time
:func:`load_plugin_hooks` discovers them, imports them, and converts
each into a list of :class:`~app.agent.hooks.BaseAgentHook` instances
ready to be slotted into the existing hook chain.

Two authoring contracts are supported:

1. **Functional** — export ``async def plugin() -> dict`` returning an
   event dict::

       async def plugin():
           return {
               "tool.before": before,
               "tool.after": after,
           }

   The dict is wrapped in a synthetic :class:`BaseAgentHook` adapter.

2. **Class-based** — subclass :class:`BaseAgentHook` and expose it as
   ``Plugin``.  Optional ``applies_to(agent_name, role) -> bool``
   filters per-agent.

Re-exports below are kept stable for plugin authors so they can write
``from app.agent.plugins import BaseAgentHook, RunContext`` regardless
of where those types live internally.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from app.agent.hooks.base import BaseAgentHook
from app.agent.plugins.events import (
    ToolAfterInput,
    ToolAfterOutput,
    ToolBeforeInput,
    ToolBeforeOutput,
)
from app.agent.plugins.hook_contract import (
    HookDefinition,
    HookEvent,
    HookFailurePolicy,
    HookMatcher,
    HookMode,
    HookRegistration,
    HookSettingsPolicy,
    HookSource,
    HookTarget,
    validate_event_input,
    validate_hook_output,
)
from app.agent.plugins.hook_resolution import (
    EffectiveHooks,
    EventDecision,
    HookOutcome,
    HookRegistrationStatus,
    merge_hook_outputs,
    resolve_event_hooks,
)
from app.agent.plugins.hook_dispatcher import HookDispatchResult, dispatch_hooks
from app.agent.plugins.hook_runner import (
    HookExecutionError,
    HookExecutionLimits,
    HookExecutionResult,
    HookIsolationBackend,
    HookIsolationUnavailable,
    UnavailableHookIsolationBackend,
    run_hook,
)
from app.agent.plugins.role import current_role, set_role
from app.agent.state import AgentState, ModelRequest, RunContext


async def load_plugin_hooks(
    dirs: Sequence[str | Path],
    *,
    agent_name: str,
    role: str,
    require_trust: bool = False,
) -> list[BaseAgentHook]:
    """Lazily import the legacy loader to avoid API-schema import cycles."""

    from app.agent.plugins.loader import load_plugin_hooks as load

    return await load(
        dirs,
        agent_name=agent_name,
        role=role,
        require_trust=require_trust,
    )


__all__ = [
    "AgentState",
    "BaseAgentHook",
    "EffectiveHooks",
    "EventDecision",
    "HookDefinition",
    "HookDispatchResult",
    "HookEvent",
    "HookExecutionError",
    "HookExecutionLimits",
    "HookExecutionResult",
    "HookFailurePolicy",
    "HookMatcher",
    "HookIsolationBackend",
    "HookIsolationUnavailable",
    "HookMode",
    "HookOutcome",
    "HookRegistration",
    "HookRegistrationStatus",
    "HookSettingsPolicy",
    "HookSource",
    "HookTarget",
    "ModelRequest",
    "RunContext",
    "ToolAfterInput",
    "ToolAfterOutput",
    "ToolBeforeInput",
    "ToolBeforeOutput",
    "UnavailableHookIsolationBackend",
    "current_role",
    "dispatch_hooks",
    "load_plugin_hooks",
    "merge_hook_outputs",
    "resolve_event_hooks",
    "run_hook",
    "set_role",
    "validate_event_input",
    "validate_hook_output",
]
