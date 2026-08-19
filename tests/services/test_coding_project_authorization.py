from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.coding_workspace_authorization import project_contains_workspace_path


@pytest.mark.asyncio
async def test_project_workspace_authorization_uses_canonical_member_paths(
    tmp_path: Path,
):
    member = tmp_path / "member"
    member.mkdir()
    db = SimpleNamespace()
    with patch(
        "app.services.coding_workspace_authorization.get_project_workspace_paths",
        new_callable=AsyncMock,
        return_value=[str(member)],
    ):
        assert await project_contains_workspace_path(db, uuid4(), member / ".")
        assert not await project_contains_workspace_path(
            db, uuid4(), tmp_path / "other"
        )
