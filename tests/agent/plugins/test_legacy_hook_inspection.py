from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.agent.plugins.hook_contract import HookEvent
from app.agent.plugins.legacy_hook_inspection import (
    inspect_legacy_hook_subscriptions,
)


def _trust(path: Path) -> None:
    (path.parent / ".trusted-hooks.json").write_text(
        json.dumps({path.name: hashlib.sha256(path.read_bytes()).hexdigest()}),
        encoding="utf-8",
    )


def test_inspects_class_based_agent_hook_without_importing_source(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "class_guide.py"
    plugin.write_text(
        "from app.agent.hooks import BaseAgentHook\n"
        "class Plugin(BaseAgentHook):\n"
        "    async def before_model(self, ctx, state, request):\n"
        "        return request\n",
        encoding="utf-8",
    )
    _trust(plugin)

    result = inspect_legacy_hook_subscriptions([tmp_path], [HookEvent.MODEL_BEFORE])

    assert len(result) == 1
    assert result[0]["event"] is HookEvent.MODEL_BEFORE
    assert result[0]["display_name"] == "class_guide.py"
    assert result[0]["certainty"] == "exact"


def test_ignores_untrusted_and_non_plugin_python_files(tmp_path: Path) -> None:
    untrusted = tmp_path / "untrusted.py"
    untrusted.write_text(
        "async def plugin():\n    return {'tool.before': handler}\n",
        encoding="utf-8",
    )
    unrelated = tmp_path / "utility.py"
    unrelated.write_text("VALUE = 1\n", encoding="utf-8")

    assert inspect_legacy_hook_subscriptions([tmp_path], [HookEvent.TOOL_BEFORE]) == []


def test_decorated_legacy_hook_is_reported_as_possible(tmp_path: Path) -> None:
    plugin = tmp_path / "decorated_guide.py"
    plugin.write_text(
        "def instrument(value):\n    return value\n"
        "@instrument\n"
        "async def plugin():\n    return {'tool.before': handler}\n",
        encoding="utf-8",
    )
    _trust(plugin)

    result = inspect_legacy_hook_subscriptions([tmp_path], [HookEvent.TOOL_BEFORE])

    assert len(result) == 1
    assert result[0]["certainty"] == "possible"
