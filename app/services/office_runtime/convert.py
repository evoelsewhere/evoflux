"""Headless Office-to-PDF conversion with the installed LibreOffice runtime.

Conversions share one hardened user profile (macros disabled, untrusted
remote references blocked, external links never refreshed) and are
serialized, because a LibreOffice profile can only be used by one process at a
time. A conversion that exceeds its timeout has its whole process tree killed.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

from loguru import logger

from app.services.office_runtime.installer import installed_runtime, runtime_home

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_CREATE_NEW_PROCESS_GROUP = 0x00000200 if sys.platform == "win32" else 0
CONVERSION_TIMEOUT_SECONDS = 180.0
_RESTART_REQUIRED = 81
_conversion_lock = threading.Lock()

#: LibreOffice export filter per source format. Workbooks export one page per
#: sheet so a sheet reads as a whole instead of being cut into print pages.
_FILTERS = {
    ".docx": "pdf:writer_pdf_Export",
    ".pptx": "pdf:impress_pdf_Export",
    ".xlsx": (
        'pdf:calc_pdf_Export:{"SinglePageSheets":{"type":"boolean","value":"true"}}'
    ),
}

_PROFILE_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry"
 xmlns:xs="http://www.w3.org/2001/XMLSchema"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop></item>
<item oor:path="/org.openoffice.Office.Calc/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>1</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="FirstRun" oor:op="fuse"><value>false</value></prop></item>
</oor:items>
"""


class ConversionError(RuntimeError):
    """LibreOffice could not convert the document."""


def supports(suffix: str) -> bool:
    return suffix.lower() in _FILTERS


def _profile_dir() -> Path:
    profile = runtime_home() / "profile"
    user = profile / "user"
    user.mkdir(parents=True, exist_ok=True)
    settings_file = user / "registrymodifications.xcu"
    if not settings_file.exists():
        settings_file.write_text(_PROFILE_SETTINGS, encoding="utf-8")
    return profile


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                creationflags=_CREATE_NO_WINDOW,
                check=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def convert_to_pdf(
    source: Path,
    workdir: Path,
    *,
    timeout: float = CONVERSION_TIMEOUT_SECONDS,
) -> Path:
    """Convert ``source`` to PDF inside ``workdir`` and return the PDF path."""
    runtime = installed_runtime()
    if runtime is None:
        raise ConversionError("The LibreOffice runtime is not installed.")
    suffix = source.suffix.lower()
    export_filter = _FILTERS.get(suffix)
    if export_filter is None:
        raise ConversionError(f"{suffix} cannot be converted by the runtime.")
    workdir.mkdir(parents=True, exist_ok=True)
    # A fixed ASCII name keeps LibreOffice away from awkward user file names
    # and makes the output name predictable.
    staged = workdir / f"document{suffix}"
    shutil.copyfile(source, staged)
    output_dir = workdir / "pdf"
    output_dir.mkdir(exist_ok=True)
    command = [
        str(runtime.executable),
        "--headless",
        "--invisible",
        "--norestore",
        "--nolockcheck",
        "--nologo",
        "--nodefault",
        f"-env:UserInstallation={_profile_dir().resolve().as_uri()}",
        "--convert-to",
        export_filter,
        "--outdir",
        str(output_dir),
        str(staged),
    ]
    environment = dict(os.environ)
    if sys.platform.startswith("linux"):
        # No display server on most Linux hosts; macOS and Windows headless
        # mode needs no plugin override.
        environment["SAL_USE_VCLPLUGIN"] = "svp"
    pdf = output_dir / "document.pdf"
    with _conversion_lock:
        for _attempt in range(2):
            returncode, stderr = _run(command, environment, timeout)
            # A fresh profile makes LibreOffice initialise it and exit without
            # converting: E_RESTART (81) on Linux/macOS, a silent 0 on
            # Windows. The second run, on the initialised profile, converts.
            converted = pdf.is_file() and pdf.stat().st_size > 0
            if converted or returncode not in {0, _RESTART_REQUIRED}:
                break
    if returncode != 0 or not pdf.is_file() or pdf.stat().st_size == 0:
        detail = stderr.decode("utf-8", "replace").strip()[-400:]
        logger.warning(
            "office_runtime_conversion_failed file={} code={} detail={}",
            source.name,
            returncode,
            detail,
        )
        raise ConversionError("LibreOffice could not convert this document.")
    return pdf


def _run(
    command: list[str], environment: dict[str, str], timeout: float
) -> tuple[int, bytes]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        creationflags=_CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP,
        start_new_session=sys.platform != "win32",
    )
    try:
        _stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_tree(process)
        raise ConversionError(
            f"LibreOffice did not finish within {int(timeout)} seconds."
        ) from exc
    return process.returncode, stderr


__all__ = [
    "CONVERSION_TIMEOUT_SECONDS",
    "ConversionError",
    "convert_to_pdf",
    "supports",
]
