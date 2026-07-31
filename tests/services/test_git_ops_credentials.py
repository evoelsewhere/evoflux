from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services.git_ops import GitCredential, run_git_long


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX fake git executable")
@pytest.mark.asyncio
async def test_run_git_long_uses_ephemeral_credential_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_git = bin_dir / "git"
    fake_git.write_text(
        "#!/bin/sh\n"
        'printf "ARGS:%s\\n" "$*"\n'
        'printf "USER:%s\\n" "$EVOFLUX_GIT_USERNAME"\n'
        'printf "TOKEN:%s\\n" "$EVOFLUX_GIT_ACCESS_TOKEN"\n'
        'printf "NO_VERIFY:%s\\n" "$GIT_SSL_NO_VERIFY"\n',
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    result = await run_git_long(
        str(tmp_path),
        "push",
        timeout=5,
        credential=GitCredential(
            host="github.com",
            username="x-access-token",
            token="secret-token-value",
            verify_ssl=False,
        ),
    )

    assert result.ok
    args_line = result.stdout.splitlines()[0]
    assert "credential.helper=" in args_line
    assert "secret-token-value" not in args_line
    assert "USER:x-access-token" in result.stdout
    assert "secret-token-value" not in result.stdout
    assert "TOKEN:[REDACTED]" in result.stdout
    assert "NO_VERIFY:1" in result.stdout
