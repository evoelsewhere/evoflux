import subprocess
from pathlib import Path
from uuid import uuid7

import pytest

from app.agent.tools.builtin.shell_runtime import BashNotFoundError
from app.services.aim.kb_store import write_unit
from app.services.aim.verification import (
    VerificationError,
    has_conversion_evidence,
    verify_target_conversion,
)


def _commit_target(target_root: Path) -> None:
    subprocess.run(["git", "-C", str(target_root), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(target_root), "config", "user.email", "aim@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(target_root), "config", "user.name", "AIM Test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(target_root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(target_root), "commit", "-qm", "target baseline"],
        check=True,
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
    _commit_target(target_root)
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
async def test_verify_target_conversion_rejects_dirty_target(tmp_path: Path):
    kb_root = tmp_path / "kb"
    target_root = tmp_path / "target"
    command = kb_root / "mapping/core/Pay.verify.command"
    command.parent.mkdir(parents=True)
    command.write_text("true\n")
    target_root.mkdir()
    (target_root / "build.ok").write_text("committed\n")
    _commit_target(target_root)
    (target_root / "build.ok").write_text("uncommitted\n")
    write_unit(
        kb_root,
        "core",
        "Pay",
        kind="component",
        phase="designed",
        target_paths=["build.ok"],
    )

    with pytest.raises(VerificationError, match="must be clean before verification"):
        await verify_target_conversion(
            kb_root,
            target_root,
            "core/Pay",
            execution_id=str(uuid7()),
        )


@pytest.mark.asyncio
async def test_verify_target_conversion_rejects_command_that_dirties_target(
    tmp_path: Path,
):
    kb_root = tmp_path / "kb"
    target_root = tmp_path / "target"
    command = kb_root / "mapping/core/Pay.verify.command"
    command.parent.mkdir(parents=True)
    command.write_text('printf changed >> "$AIM_TARGET_ROOT/build.ok"\n')
    target_root.mkdir()
    (target_root / "build.ok").write_text("committed\n")
    _commit_target(target_root)
    write_unit(
        kb_root,
        "core",
        "Pay",
        kind="component",
        phase="designed",
        target_paths=["build.ok"],
    )

    with pytest.raises(VerificationError, match="left the target repository dirty"):
        await verify_target_conversion(
            kb_root,
            target_root,
            "core/Pay",
            execution_id=str(uuid7()),
        )


@pytest.mark.asyncio
async def test_conversion_evidence_is_bound_to_exact_target_revision(tmp_path: Path):
    kb_root = tmp_path / "kb"
    target_root = tmp_path / "target"
    command = kb_root / "mapping/core/Pay.verify.command"
    command.parent.mkdir(parents=True)
    command.write_text("true\n")
    target_root.mkdir()
    (target_root / "build.ok").write_text("committed\n")
    _commit_target(target_root)
    write_unit(
        kb_root,
        "core",
        "Pay",
        kind="component",
        phase="designed",
        target_paths=["build.ok"],
    )
    execution_id = str(uuid7())

    await verify_target_conversion(
        kb_root, target_root, "core/Pay", execution_id=execution_id
    )
    assert has_conversion_evidence(
        kb_root, "core/Pay", execution_id, target_root=target_root
    )

    (target_root / "unrelated.txt").write_text("new revision\n")
    subprocess.run(["git", "-C", str(target_root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(target_root), "commit", "-qm", "unrelated change"],
        check=True,
    )
    assert not has_conversion_evidence(
        kb_root, "core/Pay", execution_id, target_root=target_root
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


@pytest.mark.asyncio
async def test_verify_target_conversion_requires_usable_bash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    kb_root = tmp_path / "kb"
    target_root = tmp_path / "target"
    command = kb_root / "mapping/core/Pay.verify.command"
    command.parent.mkdir(parents=True)
    command.write_text("true\n")
    target_root.mkdir()
    (target_root / "build.ok").write_text("ok\n")
    _commit_target(target_root)
    write_unit(
        kb_root,
        "core",
        "Pay",
        kind="component",
        phase="designed",
        target_paths=["build.ok"],
    )

    def _no_bash() -> str:
        raise BashNotFoundError("No usable bash found for AIM runners/verification.")

    monkeypatch.setattr("app.services.aim.verification.require_bash", _no_bash)

    with pytest.raises(VerificationError, match="No usable bash"):
        await verify_target_conversion(
            kb_root,
            target_root,
            "core/Pay",
            execution_id=str(uuid7()),
        )
