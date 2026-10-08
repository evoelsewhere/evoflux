"""Tests for :meth:`SandboxConfig.check_command` — best-effort scan of
shell commands for arguments inside denied roots or matching deny
patterns.

The scanner is documented as best-effort: it tokenises the command with
:mod:`shlex` and checks tokens that look path-like.  Adversarial
constructs (``$VAR``, ``$(...)``, base64) are explicitly out of scope.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.agent.sandbox import SandboxConfig, _looks_path_like
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
    # A path that exists on every host; ``/etc/passwd`` has no Windows spelling.
    hit = sandbox.check_command(f"cat {tmp_path / 'outside' / 'passwd'}")
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
# Shell spellings the host does not share (Git Bash on Windows)
# ---------------------------------------------------------------------------

#: What the audit log recorded: an MSYS drive, a device, a curl format string.
_CURL_FORMAT = "\nHTTP:%{http_code}\n"


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("/c/Users/HungKV4/Workspace/x", "C:/Users/HungKV4/Workspace/x"),
        ("/D/data", "D:/data"),
        ("/c", "C:/"),
        ("/c/", "C:/"),
        # A POSIX location with no Windows spelling is not a host path.
        ("/usr/bin/env", None),
        ("/tmp/out.txt", None),
        ("/etc/passwd", None),
        # UNC and drive paths already mean the same thing.
        ("//server/share/x", "//server/share/x"),
        ("C:/Users/x", "C:/Users/x"),
        ("relative/dir", "relative/dir"),
    ],
)
def test_msys_operands_are_mapped_on_windows(
    token: str, expected: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agent import sandbox as sandbox_module

    monkeypatch.setattr(sandbox_module.sys, "platform", "win32")

    assert sandbox_module._host_path_operand(token) == expected


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
@pytest.mark.parametrize(
    "token", ["/dev/null", "/dev/stderr", "/dev/urandom", "/dev/tty"]
)
def test_benign_devices_are_never_operands(
    platform: str, token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agent import sandbox as sandbox_module

    monkeypatch.setattr(sandbox_module.sys, "platform", platform)

    assert sandbox_module._host_path_operand(token) is None


def test_other_devices_are_still_scanned_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the harmless character devices are exempt, not all of /dev."""
    from app.agent import sandbox as sandbox_module

    monkeypatch.setattr(sandbox_module.sys, "platform", "linux")

    assert sandbox_module._host_path_operand("/dev/sda") == "/dev/sda"


@pytest.mark.parametrize("platform", ["win32", "linux"])
@pytest.mark.parametrize(
    "token",
    [
        _CURL_FORMAT,
        "\nHTTP:%{http_code}",
        "]:20s} source={e.get(",
        "{a,b}/file",
        "$(pwd)/file",
        "`pwd`/file",
        "line one/\nline two",
    ],
)
def test_strings_and_format_specifiers_are_not_operands(
    platform: str, token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agent import sandbox as sandbox_module

    monkeypatch.setattr(sandbox_module.sys, "platform", platform)

    assert sandbox_module._host_path_operand(token) is None


def test_curl_with_a_format_string_and_dev_null_reports_nothing(
    tmp_path: Path,
) -> None:
    """The command shape behind the audit line ``resolved=C:/<newline>HTTP:...``."""
    sandbox = _make(tmp_path)

    command = f"curl -s -o /dev/null -w {_CURL_FORMAT!r} http://127.0.0.1:8000/docs"

    assert sandbox.check_command(command) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Git Bash drive spelling")
def test_msys_path_inside_the_workspace_is_allowed(tmp_path: Path) -> None:
    sandbox = _make(tmp_path)
    inside = (tmp_path / "ws" / "notes.txt").resolve()
    msys = f"/{inside.drive[0].lower()}{inside.as_posix()[2:]}"

    assert sandbox.check_command(f"cat {msys}") is None


@pytest.mark.skipif(sys.platform != "win32", reason="Git Bash drive spelling")
def test_msys_path_outside_the_workspace_reports_the_real_path(
    tmp_path: Path,
) -> None:
    """Not ``C:/c/Users/...`` — the path the shell would actually open."""
    sandbox = _make(tmp_path)
    outside = (tmp_path / "elsewhere" / "secret.txt").resolve()
    msys = f"/{outside.drive[0].lower()}{outside.as_posix()[2:]}"

    hit = sandbox.check_command(f"cat {msys}")

    assert hit is not None
    resolved, reason = hit
    assert resolved == outside
    assert reason == "outside allowed sandbox roots"
