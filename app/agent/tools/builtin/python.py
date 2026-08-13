"""Python execution tool — cross-platform, structured output.

Runs Python code via ``sys.executable`` (the same interpreter running
EvoFlux).  Unlike the shell tool, this works reliably on Windows and
gives the agent access to the full Python ecosystem (win32com, requests,
pandas, PIL, etc.) for data processing, API calls, and automation.

Output format::

    [Succeeded]

    <stdout + stderr>

Or on failure::

    [Failed — exit code N]

    <stdout + stderr>
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated

from loguru import logger
from pydantic import Field

from app.agent.artifacts import shell_output_dir
from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import InjectedArg, Tool

_DEFAULT_TIMEOUT_SECONDS = 120
_OUTPUT_MAX_BYTES = 131_072  # 128 KB


async def _emit_tool_output(
    callback: Callable[[str], Awaitable[None]] | None,
    text: str,
) -> None:
    if callback is None or not text:
        return
    try:
        await callback(text)
    except Exception:
        pass


async def _python(
    code: Annotated[
        str,
        Field(
            description=(
                "Python code to execute. Multi-line supported. "
                "Runs via the same Python interpreter that hosts EvoFlux. "
                "All installed packages are available. "
                "Use for data processing, API calls, automation, calculations, "
                "file parsing, and anything complex that would be awkward in shell."
            )
        ),
    ],
    description: Annotated[
        str,
        Field(
            description=(
                "Clear, concise description of what this code does in 5-10 words. "
                "Example: 'Parse CSV and compute stats', 'Call Outlook COM API'."
            )
        ),
    ] = "",
    timeout_seconds: Annotated[
        int | None,
        Field(
            description=(
                "Timeout in seconds. Defaults to 120. "
                "Increase for long-running data processing."
            )
        ),
    ] = None,
    _tool_output: Annotated[
        Callable[[str], Awaitable[None]] | None,
        InjectedArg(),
    ] = None,
) -> str:
    """Execute Python code and return combined stdout+stderr.

    Cross-platform: uses ``sys.executable`` so it works on Windows, macOS,
    and Linux without requiring a POSIX shell.  All packages installed in
    the EvoFlux environment are available to the code.
    """
    if not code.strip():
        return "[Succeeded]\n\n"

    timeout = (
        timeout_seconds if timeout_seconds is not None else _DEFAULT_TIMEOUT_SECONDS
    )
    sandbox = get_sandbox()
    cwd = sandbox.workspace_root

    # Write code to a temp file to avoid shell escaping issues and to
    # support multi-line scripts without heredoc gymnastics.
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
        encoding="utf-8",
        dir=str(cwd),
    )
    try:
        tmp.write(code)
        tmp.flush()
        tmp_path = tmp.name
    finally:
        tmp.close()

    try:
        from app.agent.tools.builtin.shell import _scrubbed_env

        env = _scrubbed_env(inherit=sandbox.inherit_shell_environment)
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                tmp_path,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(cwd),
                env=env,
            )

            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                logger.warning("python_execute_timeout timeout={}", timeout)
                return f"[Failed — timed out after {timeout}s]\n\nThe code took too long. Simplify it or increase timeout_seconds."

            raw_output = stdout
            returncode = proc.returncode or 0

        except NotImplementedError:
            # Windows SelectorEventLoop does not support asyncio subprocess.
            # Fall back to synchronous subprocess.run() in a thread.
            logger.debug("python_execute_thread_fallback reason=NotImplementedError")

            def _run_sync() -> subprocess.CompletedProcess[bytes]:
                return subprocess.run(  # noqa: S603
                    [sys.executable, "-u", tmp_path],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=str(cwd),
                    env=env,
                    timeout=timeout,
                )

            try:
                completed = await asyncio.to_thread(_run_sync)
            except subprocess.TimeoutExpired:
                logger.warning("python_execute_timeout timeout={}", timeout)
                return f"[Failed — timed out after {timeout}s]\n\nThe code took too long. Simplify it or increase timeout_seconds."
            raw_output = completed.stdout
            returncode = completed.returncode

        output = (raw_output or b"").decode(errors="replace").rstrip()

        if returncode == 0:
            if not output:
                return "[Succeeded]\n\n(No output)"
            if len(output.encode()) > _OUTPUT_MAX_BYTES:
                # Spill large output
                spill_dir = shell_output_dir()
                spill_dir.mkdir(parents=True, exist_ok=True)
                import uuid as _uuid

                spill = spill_dir / f"python-{_uuid.uuid4().hex[:8]}.txt"
                spill.write_text(output, encoding="utf-8")
                head = output[:2000]
                return f"[Succeeded]\n\n{head}\n\n...output truncated (full output saved to {spill})"
            return f"[Succeeded]\n\n{output}"
        else:
            return f"[Failed — exit code {returncode}]\n\n{output}"

    finally:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass


python_tool = Tool(
    _python,
    name="python",
    deferred=True,
    deferred_summary="Execute Python for data processing, parsing, calculations, or automation.",
    search_aliases=(
        "script",
        "compute",
        "calculate",
        "math",
        "csv",
        "json",
        "pandas",
        "numpy",
        "benchmark",
    ),
    description=(
        "Execute Python code. Cross-platform, works on Windows/macOS/Linux. "
        "All installed packages available. "
        "Use for: data processing, API calls (requests/httpx), file parsing "
        "(CSV/JSON/XML/Excel), calculations, automation (win32com, pyautogui), "
        "image processing (PIL), and any complex logic. "
        "Prefer this over shell for non-trivial tasks."
    ),
)
