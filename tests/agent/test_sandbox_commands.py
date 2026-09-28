"""Tests for :meth:`SandboxConfig.check_command` — best-effort scan of
shell commands for arguments inside denied roots or matching deny
patterns.

The scanner is documented as best-effort: it tokenises the command with
:mod:`shlex` and checks tokens that look path-like.  Adversarial
constructs (``$VAR``, ``$(...)``, base64) are explicitly out of scope.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent import sandbox as sandbox_mod
from app.agent.sandbox import CommandViolation, SandboxConfig, _looks_path_like
from app.core.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make(
    tmp_path: Path,
    *,
    denied_roots: list[Path] | None = None,
    denied_patterns: list[str] | None = None,
) -> SandboxConfig:
    return SandboxConfig(
        workspace=str(tmp_path / "ws"),
        denied_roots=denied_roots if denied_roots is not None else [],
        denied_patterns=denied_patterns if denied_patterns is not None else [],
    )


def test_shell_command_scanner_still_checks_denied_paths(tmp_path):
    sandbox = SandboxConfig(
        workspace=str(tmp_path / "ws"),
        denied_roots=[Path("/etc")],
        denied_patterns=["**/.env"],
    )

    hit = sandbox.check_command("cat /etc/passwd ~/.ssh/id_rsa")
    assert hit is not None


# ---------------------------------------------------------------------------
# _looks_path_like — token classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "/etc/passwd",
        "/Users/alice/.env",
        "~/.ssh/id_rsa",
        ".env",
        "./config",
        "../foo",
        "secrets/key",
        "a/b/c",
        r"C:\Users\alice\.env",
        r"secrets\key",
    ],
)
def test_looks_path_like_positive(token: str) -> None:
    assert _looks_path_like(token) is True


@pytest.mark.parametrize(
    "token",
    [
        "",
        "cat",
        "ls",
        "echo",
        "42",
        "--flag",
        "-a",
        "hello",
        "key=value",
    ],
)
def test_looks_path_like_negative(token: str) -> None:
    assert _looks_path_like(token) is False


# ---------------------------------------------------------------------------
# check_command — pattern matches
# ---------------------------------------------------------------------------


def test_blocks_absolute_path_under_denied_root(tmp_path: Path) -> None:
    forbidden = tmp_path / "secrets"
    forbidden.mkdir()
    sandbox = _make(tmp_path, denied_roots=[forbidden])

    hit = sandbox.check_command(f"cat {forbidden}/key.pem")
    assert hit is not None
    resolved, denied = hit
    assert resolved == forbidden / "key.pem"
    assert str(forbidden) in denied


def test_blocks_pattern_match_anywhere(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sandbox = _make(tmp_path, denied_patterns=["**/.env"])

    hit = sandbox.check_command(f"cat {project}/.env")
    assert hit is not None
    _, denied = hit
    assert denied == "**/.env"


def test_expands_tilde_against_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tokens starting with ~ are expanded — shells expand them before exec."""
    fake_home = tmp_path / "home" / "alice"
    fake_home.mkdir(parents=True)
    # Windows expanduser prefers USERPROFILE; POSIX uses HOME.
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    secrets = fake_home / ".aws" / "credentials"
    secrets.parent.mkdir()
    secrets.touch()

    sandbox = _make(tmp_path, denied_patterns=["**/.aws/**"])
    hit = sandbox.check_command("cat ~/.aws/credentials")
    assert hit is not None
    resolved, _ = hit
    assert resolved == secrets


def test_relative_path_resolves_against_workspace(tmp_path: Path) -> None:
    """A relative path outside the workspace mustn't slip past the denylist."""
    sandbox = _make(tmp_path, denied_patterns=["**/secrets/**"])
    workspace = tmp_path / "ws"
    (workspace / "secrets").mkdir()

    # Sensitive patterns remain enforced even inside the workspace.
    assert sandbox.check_command("cat secrets/key.pem") is not None

    # An absolute path to a non-workspace `secrets/` SHOULD match.
    other = tmp_path / "other_proj" / "secrets" / "key.pem"
    other.parent.mkdir(parents=True)
    hit = sandbox.check_command(f"cat {other}")
    assert hit is not None


def test_quoted_path_is_tokenised_properly(tmp_path: Path) -> None:
    """shlex unquotes "‹path›" so a quoted denied path still matches."""
    forbidden = tmp_path / "secrets"
    forbidden.mkdir()
    sandbox = _make(tmp_path, denied_roots=[forbidden])

    hit = sandbox.check_command(f"cat '{forbidden}/key with spaces.txt'")
    assert hit is not None


# ---------------------------------------------------------------------------
# check_command — non-matches
# ---------------------------------------------------------------------------


def test_no_path_tokens_means_no_match(tmp_path: Path) -> None:
    sandbox = _make(tmp_path, denied_patterns=["**/.env"])
    assert sandbox.check_command("echo hello world") is None
    assert sandbox.check_command("date") is None
    assert sandbox.check_command("") is None


def test_workspace_paths_still_honor_sensitive_patterns(tmp_path: Path) -> None:
    sandbox = _make(tmp_path, denied_patterns=["**/.env"])
    workspace = tmp_path / "ws"
    (workspace / ".env").touch()

    assert sandbox.check_command(f"cat {workspace}/.env") is not None
    assert sandbox.check_command("cat .env") is not None


def test_unbalanced_quotes_do_not_raise(tmp_path: Path) -> None:
    """Malformed shell syntax should fall through, not crash the wrapper."""
    sandbox = _make(tmp_path, denied_patterns=["**/.env"])
    # shlex.split raises ValueError on unbalanced quotes; we swallow it
    # and let the shell itself handle the syntax error.
    assert sandbox.check_command("cat 'unclosed") is None


def test_no_patterns_still_blocks_external_paths(tmp_path: Path) -> None:
    sandbox = _make(tmp_path)
    hit = sandbox.check_command("cat /etc/passwd")
    assert hit is not None
    assert hit[1] == "outside allowed sandbox roots"


def test_state_logs_are_exempt_from_denied_roots(tmp_path: Path) -> None:
    logs_root = Path(settings.EVOFLUX_STATE_DIR).resolve() / "logs"
    log_path = logs_root / "app" / "app.log"
    sandbox = _make(tmp_path, denied_roots=[Path(settings.EVOFLUX_STATE_DIR)])

    assert sandbox.check_command(f"tail -n 220 {log_path}") is None


def test_other_state_paths_remain_denied(tmp_path: Path) -> None:
    state_root = Path(settings.EVOFLUX_STATE_DIR).resolve()
    sandbox = _make(tmp_path, denied_roots=[state_root])

    hit = sandbox.check_command(f"cat {state_root / 'secrets' / 'token'}")
    assert hit is not None


# ---------------------------------------------------------------------------
# check_command — known limitations
# ---------------------------------------------------------------------------


def test_dollar_var_evasion_is_documented(tmp_path: Path) -> None:
    """Documented limitation: $VAR expansion is NOT evaluated.

    This test exists to lock in the contract — if someone later adds
    variable expansion, the test will fail and the doc must be updated.
    """
    forbidden = tmp_path / "secrets"
    forbidden.mkdir()
    sandbox = _make(tmp_path, denied_roots=[forbidden])

    # `$HIDDEN` is not expanded; the literal token "$HIDDEN" doesn't
    # resolve under a denied root.
    assert sandbox.check_command("HIDDEN=secrets/key.pem cat $HIDDEN") is None


# ---------------------------------------------------------------------------
# command_violations — shell structure
# ---------------------------------------------------------------------------


def _outside(tmp_path: Path, name: str = "outside") -> Path:
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_reports_every_violation_not_just_the_first(tmp_path: Path) -> None:
    a, b = _outside(tmp_path, "a"), _outside(tmp_path, "b")
    sandbox = _make(tmp_path)

    found = [
        v.resolved for v in sandbox.command_violations(f"ls {a}; ls {b} && ls {a}")
    ]
    assert found == [a, b]


def test_operators_are_not_glued_to_paths(tmp_path: Path) -> None:
    outside = _outside(tmp_path)
    sandbox = _make(tmp_path)

    hit = sandbox.check_command(f"cd {outside}; pwd")
    assert hit is not None
    assert hit[0] == outside


def test_relative_operands_follow_cd(tmp_path: Path) -> None:
    outside = _outside(tmp_path)
    sandbox = _make(tmp_path, denied_patterns=["**/.env"])

    violations = sandbox.command_violations(f"cd {outside} && cat .config/.env")
    assert [v.resolved for v in violations] == [outside, outside / ".config" / ".env"]
    assert violations[1].kind == "denied_pattern"


def test_relative_operands_resolve_against_cwd(tmp_path: Path) -> None:
    outside = _outside(tmp_path)
    sandbox = _make(tmp_path)

    hit = sandbox.check_command("cat docs/notes.txt", cwd=outside)
    assert hit is not None
    assert hit[0] == outside / "docs" / "notes.txt"


@pytest.mark.parametrize(
    "command",
    [
        "curl -s -o /dev/null -w '%{http_code}' https://example.com/jira9/rest/api/2/myself",
        "curl -s \\n  -o /dev/null \\n  https://example.com/a/b",
        "find . \( -name '*.db' -o -name '*.sqlite' \) 2>/dev/null",
        "sed -E 's/=(.*)$/=<redacted>/' notes.txt",
        "echo $(cat VERSION) | tee out/version.txt",
        "python - <<'EOF'\nPATH = \"/jira9/rest/api/2/myself\"\nprint(PATH)\nEOF",
    ],
)
def test_non_path_words_are_not_flagged(tmp_path: Path, command: str) -> None:
    sandbox = _make(tmp_path)
    assert sandbox.command_violations(command) == []


def test_heredoc_body_is_data_for_non_interpreters(tmp_path: Path) -> None:
    outside = _outside(tmp_path)
    sandbox = _make(tmp_path)

    command = f"cat > notes.md <<'EOF'\nSee {outside.as_posix()} for details.\nEOF"
    assert sandbox.command_violations(command) == []


def test_interpreter_script_literals_that_exist_are_flagged(tmp_path: Path) -> None:
    secret = _outside(tmp_path, "state") / "app.db"
    secret.touch()
    sandbox = _make(tmp_path, denied_roots=[secret.parent])

    one_liner = (
        f'PYTHONUTF8=1 python -c "import sqlite3; '
        f"sqlite3.connect('file:{secret.as_posix()}?mode=ro', uri=True)\""
    )
    heredoc = f"python3 - <<'PY'\nopen('{secret.as_posix()}').read()\nPY"
    missing = f"python -c \"open('{(secret.parent / 'nope.db').as_posix()}')\""

    for command in (one_liner, heredoc):
        violations = sandbox.command_violations(command)
        assert [(v.resolved, v.kind) for v in violations] == [(secret, "denied_root")]
    assert sandbox.command_violations(missing) == []


def test_shell_dash_c_is_scanned_as_a_command(tmp_path: Path) -> None:
    outside = _outside(tmp_path)
    sandbox = _make(tmp_path)

    hit = sandbox.check_command(f"bash -c \"ls '{outside.as_posix()}'\"")
    assert hit is not None
    assert hit[0] == outside


def test_violation_reasons_name_the_rule(tmp_path: Path) -> None:
    path = tmp_path / "x"
    assert CommandViolation(path, "denied_root", "/data").reason == "denied root /data"
    assert (
        CommandViolation(path, "denied_pattern", "**/.env").reason
        == "denied pattern **/.env"
    )
    assert (
        CommandViolation(path, "read_only", "/uploads").reason
        == "redirect into read-only root /uploads"
    )
    assert (
        CommandViolation(path, "outside", "outside allowed sandbox roots").reason
        == "outside allowed sandbox roots"
    )


def test_audit_logs_each_violation(tmp_path: Path) -> None:
    from loguru import logger

    a, b = _outside(tmp_path, "a"), _outside(tmp_path, "b")
    sandbox = _make(tmp_path, denied_roots=[b])
    messages: list[str] = []
    sink = logger.add(messages.append, format="{message}", level="WARNING")
    try:
        sandbox.audit_command(f"ls {a} {b}", tool="shell")
    finally:
        logger.remove(sink)

    assert len(messages) == 2
    assert "reason=outside allowed sandbox roots" in messages[0]
    assert f"reason=denied root {b}" in messages[1]


# ---------------------------------------------------------------------------
# Windows / Git Bash normalisation (string-level, runs on every platform)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("/c/Users/alice", "C:/Users/alice"),
        ("/d", None),  # ambiguous with a cmd switch; treated as a switch
        ("/s", None),
        ("/AD", None),
        ("/dev/null", None),
        ("NUL", None),
        ("C:/Users/alice", "C:/Users/alice"),
        ("/etc/hosts", "/etc/hosts"),
    ],
)
def test_normalize_operand_on_windows(
    monkeypatch: pytest.MonkeyPatch, token: str, expected: str | None
) -> None:
    monkeypatch.setattr(sandbox_mod, "_IS_WINDOWS", True)
    assert sandbox_mod._normalize_operand(token) == expected


def test_windows_backslashes_keep_shell_escapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox_mod, "_IS_WINDOWS", True)
    tokens = sandbox_mod._shell_tokens(
        r"dir /s C:\Users\alice\*.md; find . \( -name \*.py \)"
    )
    assert tokens == [
        "dir", "/s", "C:/Users/alice/*.md", ";",
        "find", ".", "(", "-name", "*.py", ")",
    ]  # fmt: skip
