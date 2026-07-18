"""The currently-driving workflow execution id, as a context variable.

Set by :class:`~app.workflow.runner.WorkflowRunner` around an execution's
drive loop so inline tool nodes (e.g. ``aim_compare``/``aim_units``) can stamp
the execution onto the rows they write, without threading the id through every
tool signature. ``None`` outside a workflow run — a plain slash-command call
records no execution id, which is correct.

Note: this propagates only to code running in the runner's own task (the
headless/tool-node path). Agent turns run in the team's task and won't see it;
those rows are still traceable via their ``session_id``.
"""

from __future__ import annotations

import contextvars

current_execution_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "workflow_execution_id", default=None
)
