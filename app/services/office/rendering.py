"""Rasterises Office files through LibreOffice so output can be inspected.

Both the DOCX pipeline and the PPTX round-trip check need to see what an Office
file actually looks like once written, rather than trusting the HTML or the
in-memory document model it was produced from.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Final

from app.services.office.runtime import (
    codex_runtime_dependencies,
    resolve_executable,
)

SOFFICE_BIN_ENV: Final = "EVOFLUX_SOFFICE_BIN"
PDFTOPPM_BIN_ENV: Final = "EVOFLUX_PDFTOPPM_BIN"
_SOFFICE_NAMES: Final = ("soffice", "libreoffice")
_PDFTOPPM_NAMES: Final = ("pdftoppm",)
_CONVERSION_TIMEOUT_SECONDS: Final = 180


def find_render_binary(env_name: str, names: tuple[str, ...]) -> str:
    return resolve_executable(
        env_name,
        names,
        fallback_dirs=(codex_runtime_dependencies() / "bin" / "override",),
        requirement=(
            f"Required rendering binary is unavailable: {', '.join(names)}. "
            f"Set {env_name} to an executable path."
        ),
    )


def renderer_available() -> bool:
    """Reports whether both rendering binaries can be resolved right now.

    Lets callers treat rasterisation as optional evidence instead of making
    every Office export depend on a LibreOffice install.
    """

    try:
        find_render_binary(SOFFICE_BIN_ENV, _SOFFICE_NAMES)
        find_render_binary(PDFTOPPM_BIN_ENV, _PDFTOPPM_NAMES)
    except RuntimeError:
        return False
    return True


def render_pages(
    source: Path,
    render_dir: Path,
    *,
    code_prefix: str,
    dpi: int = 144,
) -> tuple[list[Path], list[dict[str, Any]]]:
    """Converts ``source`` to PDF then to one PNG per page.

    Returns the page images alongside error-severity issues, so a rendering
    failure is reported rather than raised.
    """

    render_dir.mkdir(parents=True, exist_ok=True)
    soffice = find_render_binary(SOFFICE_BIN_ENV, _SOFFICE_NAMES)
    pdftoppm = find_render_binary(PDFTOPPM_BIN_ENV, _PDFTOPPM_NAMES)
    with tempfile.TemporaryDirectory(
        prefix=f"evoflux-{code_prefix}-render-", dir=render_dir
    ) as temp:
        temp_dir = Path(temp)
        profile = temp_dir / "profile"
        profile.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(profile)
        env["TMPDIR"] = str(temp_dir)
        conversion = subprocess.run(
            [
                soffice,
                "--headless",
                f"-env:UserInstallation={profile.resolve().as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(temp_dir),
                str(source),
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=_CONVERSION_TIMEOUT_SECONDS,
            check=False,
        )
        pdf = temp_dir / f"{source.stem}.pdf"
        if conversion.returncode != 0 or not pdf.is_file():
            message = (
                conversion.stderr.strip()
                or conversion.stdout.strip()
                or "LibreOffice did not produce a PDF"
            )
            return [], [
                {
                    "severity": "error",
                    "code": f"{code_prefix}-render-failed",
                    "message": message,
                }
            ]
        prefix = temp_dir / "page"
        raster = subprocess.run(
            [pdftoppm, "-png", "-r", str(dpi), str(pdf), str(prefix)],
            capture_output=True,
            text=True,
            timeout=_CONVERSION_TIMEOUT_SECONDS,
            check=False,
        )
        pages = sorted(temp_dir.glob("page-*.png"))
        if raster.returncode != 0 or not pages:
            return [], [
                {
                    "severity": "error",
                    "code": f"{code_prefix}-raster-failed",
                    "message": raster.stderr.strip() or "pdftoppm produced no pages",
                }
            ]
        outputs = []
        for index, page in enumerate(pages, start=1):
            destination = render_dir / f"page-{index:03d}.png"
            shutil.copy2(page, destination)
            outputs.append(destination)
        return outputs, []


__all__ = [
    "PDFTOPPM_BIN_ENV",
    "SOFFICE_BIN_ENV",
    "find_render_binary",
    "render_pages",
    "renderer_available",
]
