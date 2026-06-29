"""Plan-mode tools — enter/exit plan mode for batch user approval.

``enter_plan_mode``: activates plan mode; destructive tools are recorded
instead of executed.

``exit_plan_mode``: deactivates plan mode, presents the recorded steps to
the user for approval via a blocking SSE round-trip, and returns the
decision so the agent can act accordingly.
"""

from __future__ import annotations

from typing import Annotated, Any

from loguru import logger

from app.agent.tools.registry import InjectedArg, Tool


async def _enter_plan_mode(
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Activate plan mode to review destructive operations before executing them.

    While plan mode is active, the tools ``edit``, ``write``, ``patch``,
    ``rm``, ``shell``, ``python``, and ``bg`` are **recorded** instead of
    executed.  Each call returns a ``[PLAN]`` acknowledgement.

    Call ``exit_plan_mode`` when you have finished planning to present the
    full list of steps to the user.  They may approve (run all steps) or
    reject (abandon the plan).

    Use plan mode whenever a task involves multiple risky file or shell
    operations so the user can review the full scope before any changes land
    on disk.
    """
    from app.agent.plan import get_plan_mode_service

    svc = get_plan_mode_service()
    svc.enter()
    if _state is not None:
        _state.metadata["_plan_mode"] = True
    logger.info("plan_mode_entered session={}", svc.session_id)
    return (
        "Plan mode activated. The tools edit, write, patch, rm, shell, python, "
        "and bg will now be recorded instead of executed. "
        "Call exit_plan_mode when you have recorded all planned changes."
    )


async def _exit_plan_mode(
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Present the recorded plan to the user for approval and wait for their decision.

    Sends all recorded steps to the user as a plan-approval request and
    blocks until they respond.

    Returns one of:
    - ``"approved"`` — user accepted the plan; execute each step in order now.
    - ``"rejected"`` — user declined; do NOT execute any steps; explain and
      ask the user how they want to proceed.

    If no steps were recorded, exits plan mode silently and returns
    ``"approved"`` immediately.
    """
    from app.agent.plan import get_plan_mode_service

    svc = get_plan_mode_service()
    if _state is not None:
        _state.metadata["_plan_mode"] = False

    n = svc.step_count
    logger.info("plan_mode_exit_requested session={} steps={}", svc.session_id, n)

    decision = await svc.request_approval()

    if decision == "approved":
        msg = (
            f"Plan approved by user. {n} step(s) are ready to execute. "
            "Proceed with executing each recorded step in order now."
        )
    else:
        msg = (
            "Plan rejected by user. Do not execute any of the recorded steps. "
            "Inform the user and ask what they would like to do instead."
        )

    logger.info(
        "plan_mode_decision session={} steps={} decision={}",
        svc.session_id,
        n,
        decision,
    )
    return msg


enter_plan_mode = Tool(
    _enter_plan_mode,
    name="enter_plan_mode",
    description=(
        "Activate plan mode: subsequent destructive tool calls (edit, write, "
        "patch, rm, shell, python, bg) are recorded instead of executed. "
        "Call exit_plan_mode when ready to present the plan for approval."
    ),
)

exit_plan_mode = Tool(
    _exit_plan_mode,
    name="exit_plan_mode",
    description=(
        "Present all recorded plan steps to the user for approval. "
        "Blocks until the user approves or rejects. "
        "Returns 'approved' (execute steps) or 'rejected' (abandon plan)."
    ),
)
