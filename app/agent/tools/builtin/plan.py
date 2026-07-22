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

    Call ``exit_plan_mode`` with a markdown plan document when you have
    finished planning.  The user may approve (run all steps), request
    revisions (you stay in plan mode and adjust), or reject (abandon).

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
    plan: str,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Present the plan to the user for review and wait for their decision.

    Sends the markdown plan document plus all recorded steps to the user
    as a plan-review request and blocks until they respond.

    The user can reply in three ways:
    - ``approved`` — execute the plan; run each recorded step in order now.
    - ``revise`` — the user requests changes; their feedback is returned to
      you. You remain in plan mode: revise the plan (record additional
      steps if needed) and call ``exit_plan_mode`` again with the updated
      plan.
    - ``rejected`` — abandon the plan; do NOT execute any steps; explain
      and ask the user how they want to proceed.

    If the plan is empty and no steps were recorded, exits plan mode
    silently and returns approved immediately.

    Args:
        plan: The full plan as a markdown document shown to the user for
            review — goal, approach, and the concrete changes you intend
            to make. Write it for the user, not for yourself.
    """
    from app.agent.plan import get_plan_mode_service

    svc = get_plan_mode_service()

    n = svc.step_count
    logger.info("plan_mode_exit_requested session={} steps={}", svc.session_id, n)

    decision, feedback = await svc.request_approval(plan)

    if _state is not None:
        # ``revise`` keeps recording; approved/rejected end plan mode.
        _state.metadata["_plan_mode"] = decision == "revise"

    if decision == "approved":
        msg = (
            f"Plan approved by user. {n} step(s) are ready to execute. "
            "Proceed with executing each recorded step in order now."
        )
    elif decision == "revise":
        msg = (
            "User requested changes to the plan:\n\n"
            f"{feedback.strip() or '(no details provided)'}\n\n"
            "You are still in plan mode. Revise the plan (record additional "
            "steps if needed) and call exit_plan_mode again with the "
            "updated plan."
        )
    else:
        msg = (
            "Plan rejected by user. Do not execute any of the recorded steps. "
            "Inform the user and ask what they would like to do instead."
        )
        if feedback.strip():
            msg += f"\n\nUser's note: {feedback.strip()}"

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
    lead_only=True,
    deferred=True,
    deferred_summary="Enter interactive plan-review mode before making destructive changes.",
    description=(
        "Activate plan mode: subsequent destructive tool calls (edit, write, "
        "patch, rm, shell, python, bg) are recorded instead of executed. "
        "Call exit_plan_mode with a markdown plan document when ready to "
        "present the plan for review."
    ),
)

exit_plan_mode = Tool(
    _exit_plan_mode,
    name="exit_plan_mode",
    lead_only=True,
    deferred=True,
    deferred_summary="Present a recorded implementation plan for user approval.",
    description=(
        "Present your markdown plan (plus all recorded steps) to the user "
        "for review. Blocks until they respond: approved (execute steps), "
        "revise (their feedback is returned — update the plan and call "
        "again), or rejected (abandon the plan)."
    ),
)
