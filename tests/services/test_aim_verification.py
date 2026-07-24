from pathlib import Path
from uuid import uuid7

import pytest

from app.services.aim.kb_store import write_unit
from app.services.aim.verification import (
    VerificationError,
    has_conversion_evidence,
    verify_target_conversion,
)


@pytest.mark.asyncio
async def test_verify_target_conversion_writes_attempt_evidence(tmp_path: Path):
    kb_root = tmp_path / "kb"
    target_root = tmp_path / "target"
    command = kb_root / "mapping" / "core" / "Pay.verify.command"
    command.parent.mkdir(parents=True)
    command.write_text('test -f "$AIM_TARGET_ROOT/build.ok"\n', encoding="utf-8")
    target_root.mkdir()
    (target_root / "build.ok").write_text("ok\n")
    write_unit(
        kb_root,
        "core",
        "Pay",
        kind="component",
        phase="designed",
        target_paths=["build.ok"],
    )
    execution_id = uuid7()

    evidence = await verify_target_conversion(
        kb_root,
        target_root,
        "core/Pay",
        execution_id=str(execution_id),
    )

    assert evidence.is_file()
    assert has_conversion_evidence(
        kb_root, "core/Pay", str(execution_id), target_root=target_root
    )

    (target_root / "build.ok").write_text("changed after verification\n")
    assert not has_conversion_evidence(
        kb_root, "core/Pay", str(execution_id), target_root=target_root
    )


@pytest.mark.asyncio
async def test_verify_target_conversion_requires_command(tmp_path: Path):
    kb_root = tmp_path / "kb"
    target_root = tmp_path / "target"
    kb_root.mkdir()
    target_root.mkdir()

    with pytest.raises(VerificationError, match="verification command is missing"):
        await verify_target_conversion(
            kb_root,
            target_root,
            "core/Pay",
            execution_id=str(uuid7()),
        )


@pytest.mark.asyncio
async def test_verify_target_conversion_rejects_missing_target_path(tmp_path: Path):
    kb_root = tmp_path / "kb"
    target_root = tmp_path / "target"
    command = kb_root / "mapping/core/Pay.verify.command"
    command.parent.mkdir(parents=True)
    command.write_text("true\n")
    target_root.mkdir()
    write_unit(
        kb_root,
        "core",
        "Pay",
        kind="component",
        phase="designed",
        target_paths=["src/missing.rs"],
    )

    with pytest.raises(VerificationError, match="target path does not exist"):
        await verify_target_conversion(
            kb_root,
            target_root,
            "core/Pay",
            execution_id=str(uuid7()),
        )
