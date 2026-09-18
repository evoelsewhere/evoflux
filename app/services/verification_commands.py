"""The allowlist of commands a verification phase may run on its own.

A verification command runs without a human in the loop, so it is parsed into
argv rather than handed to a shell, and it must name a program this module
recognizes. That closes two doors at once: shell composition cannot smuggle a
second command in behind a legitimate one, and an agent cannot nominate an
arbitrary binary as "the check" for a change.

The allowlist is intentionally a list of build and test tools. Anything that
mutates state, reaches the network, or takes a script name this module cannot
recognize as a check belongs to an approved task, not to automatic verification.
"""

from __future__ import annotations

import shlex
from pathlib import PurePosixPath

#: Program to the sub-actions it may take. `None` means the program's own
#: arguments are checked below rather than by a fixed set.
_VERIFICATION_PROGRAM_ACTIONS: dict[str, set[str] | None] = {
    "bun": {"run", "test"},
    "bundle": {"exec"},
    "cargo": {"check", "clippy", "fmt", "test"},
    "composer": {"check", "test"},
    "dotnet": {"build", "test"},
    "git": {"diff", "status"},
    "go": {"test"},
    "gradle": {"build", "check", "test"},
    "gradlew": {"build", "check", "test"},
    "make": None,
    "mvn": {"test", "verify"},
    "mvnw": {"test", "verify"},
    "npm": {"run", "test"},
    "phpunit": None,
    "pnpm": {"run", "test"},
    "pytest": None,
    "ruff": {"check", "format"},
    "swift": {"build", "test"},
    "ty": {"check"},
    "uv": {"run"},
    "xcodebuild": {"build", "test"},
}

_SCRIPT_VERBS = ("build", "check", "lint", "test", "typecheck", "verify")


def parse_verification_command(command: str) -> list[str]:
    """Parse one approved non-shell verification command into argv."""

    if not command.strip() or any(token in command for token in ("\n", "\r", "\x00")):
        raise ValueError("verification commands must be single non-blank lines")
    if any(operator in command for operator in ("&&", "||", ";", "|", ">", "<")):
        raise ValueError(
            "verification commands cannot contain shell composition or redirection"
        )
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise ValueError("verification command has invalid quoting") from exc
    if not parts:
        raise ValueError("verification command must not be blank")
    program = PurePosixPath(parts[0]).name
    if parts[0] != program and parts[0] not in {"./gradlew", "./mvnw"}:
        raise ValueError(
            "verification programs must use a PATH name or approved wrapper"
        )
    if program in {"python", "python3"}:
        if (
            len(parts) < 3
            or parts[1] != "-m"
            or parts[2] not in {"compileall", "pytest"}
        ):
            raise ValueError(
                "python verification commands require -m pytest/compileall"
            )
        return parts
    allowed_actions = _VERIFICATION_PROGRAM_ACTIONS.get(program)
    if program not in _VERIFICATION_PROGRAM_ACTIONS:
        raise ValueError(f"unsupported verification program: {program}")
    if allowed_actions is not None and (
        len(parts) < 2 or parts[1] not in allowed_actions
    ):
        raise ValueError(f"unsupported {program} verification action")
    if program in {"bun", "npm", "pnpm"} and parts[1] == "run":
        if len(parts) < 3 or not any(
            verb in parts[2].lower() for verb in _SCRIPT_VERBS
        ):
            raise ValueError(
                f"{program} verification scripts must be build/check/lint/test/verify"
            )
    if program == "bundle" and (len(parts) < 3 or parts[2] not in {"rspec", "rubocop"}):
        raise ValueError("bundle verification commands require exec rspec/rubocop")
    if program == "uv":
        if len(parts) < 3 or parts[2] not in {"pytest", "ruff", "ty"}:
            raise ValueError("uv verification commands require run pytest/ruff/ty")
    if program == "make" and (
        len(parts) < 2
        or not any(
            token in parts[1].lower() for token in ("test", "check", "lint", "verify")
        )
    ):
        raise ValueError("make verification target must be test/check/lint/verify")
    return parts


__all__ = ["parse_verification_command"]
