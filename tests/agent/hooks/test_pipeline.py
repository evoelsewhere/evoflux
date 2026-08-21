from __future__ import annotations

import pytest

from app.agent.hooks.base import BaseAgentHook
from app.agent.hooks.pipeline import HookPipeline, HookStage


class NamedHook(BaseAgentHook):
    def __init__(self, name: str) -> None:
        self.name = name


def test_pipeline_orders_by_stage_then_registration():
    pipeline = HookPipeline()
    pipeline.add(HookStage.WORKSPACE, "workspace", NamedHook("workspace"))
    pipeline.add(HookStage.BASE_CONTEXT, "clock", NamedHook("clock"))
    pipeline.add(HookStage.BASE_CONTEXT, "memory", NamedHook("memory"))
    pipeline.add(
        HookStage.PROMPT_FINALIZATION,
        "prompt-finalization",
        NamedHook("prompt-finalization"),
    )
    pipeline.add(
        HookStage.CONTEXT_CONTROL,
        "summarization",
        NamedHook("summarization"),
    )

    assert [hook.name for hook in pipeline.build()] == [
        "clock",
        "memory",
        "workspace",
        "prompt-finalization",
        "summarization",
    ]


def test_pipeline_rejects_duplicate_context_owner():
    pipeline = HookPipeline()
    pipeline.add(HookStage.WORKSPACE, "workspace", NamedHook("first"))

    with pytest.raises(RuntimeError, match="workspace"):
        pipeline.add(HookStage.WORKSPACE, "workspace", NamedHook("second"))
