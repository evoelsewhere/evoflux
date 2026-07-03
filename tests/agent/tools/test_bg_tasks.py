"""Tests for background shell task tools."""

from __future__ import annotations

import pytest


def _extract_task_id(text: str) -> str | None:
    """Extract the first bg_XXXXXXXX task id from a tool result string."""
    import re

    m = re.search(r"\bbg_[0-9a-f]{8}\b", text)
    return m.group(0) if m else None


@pytest.mark.asyncio
async def test_shell_bg_start_and_status():
    """shell_bg_start returns a task_id; shell_bg_status shows it as running."""
    from app.agent.tools.builtin.bg_tasks import (
        _registry,
        shell_bg_start,
        shell_bg_status,
    )

    # Start a long-running background command
    result = await shell_bg_start.arun(command="python -c \"import time; time.sleep(30)\"")
    assert "task_id" in result
    assert "bg_" in result

    task_id = _extract_task_id(result)
    assert task_id is not None
    assert task_id.startswith("bg_")
    assert task_id in _registry

    # Status should show it running
    status = await shell_bg_status.arun(task_id=task_id)
    assert "running" in status
    assert task_id in status

    # Cleanup
    task = _registry.get(task_id)
    if task and task._bg:
        await task._bg.stop()
    _registry.pop(task_id, None)


@pytest.mark.asyncio
async def test_shell_bg_wait_completion():
    """shell_bg_wait blocks until command exits and returns output."""
    from app.agent.tools.builtin.bg_tasks import _registry, shell_bg_start, shell_bg_wait

    result = await shell_bg_start.arun(command="echo hello_bg")
    task_id = _extract_task_id(result)
    assert task_id is not None

    wait_result = await shell_bg_wait.arun(task_id=task_id, timeout_seconds=10)
    assert "Succeeded" in wait_result or "hello_bg" in wait_result

    # Task should be removed from registry after successful wait
    assert task_id not in _registry


@pytest.mark.asyncio
async def test_shell_bg_status_unknown():
    """shell_bg_status returns error for unknown task_id."""
    from app.agent.tools.builtin.bg_tasks import shell_bg_status

    result = await shell_bg_status.arun(task_id="bg_nonexistent")
    assert "not found" in result.lower() or "Error" in result


@pytest.mark.asyncio
async def test_shell_bg_wait_timeout():
    """shell_bg_wait returns a timeout notice without killing the process."""
    from app.agent.tools.builtin.bg_tasks import _registry, shell_bg_start, shell_bg_wait

    result = await shell_bg_start.arun(command="python -c \"import time; time.sleep(30)\"")
    task_id = _extract_task_id(result)
    assert task_id is not None

    wait_result = await shell_bg_wait.arun(task_id=task_id, timeout_seconds=1)
    assert "Timeout" in wait_result or "still running" in wait_result.lower()

    # Task should still be in registry (not cleaned up on timeout)
    assert task_id in _registry

    # Cleanup
    task = _registry.get(task_id)
    if task and task._bg:
        await task._bg.stop()
    _registry.pop(task_id, None)
