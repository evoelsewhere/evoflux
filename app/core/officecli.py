"""Ensure the bundled OfficeCLI binary (if present) is reachable via PATH.

OfficeCLI (https://github.com/iOfficeAI/OfficeCLI) is a self-contained CLI
for editing .xlsx/.pptx/.docx files — the xlsx and pptx skills
(``app/agent/builtin_skills/{xlsx,pptx}/SKILL.md``) shell out to it
directly instead of writing openpyxl/python-pptx code. The desktop sidecar
bundles a platform binary under ``<bundle_root>/bin/officecli(.exe)`` (see
``scripts/build_sidecar.py``); this module locates that binary and
prepends its directory to ``PATH`` so the shell tool's subprocesses — which
inherit ``os.environ`` minus a few leak keys, see
``app/agent/tools/builtin/shell.py::_scrubbed_env`` — can invoke it by name.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

_BIN_NAME = "officecli.exe" if sys.platform == "win32" else "officecli"


def _bundle_root() -> Path | None:
    """Return the sidecar bundle root, or ``None`` outside the bundled runtime.

    Mirrors the layout ``scripts/build_sidecar.py`` produces:
    ``<bundle>/python/python.exe`` (Windows) or
    ``<bundle>/python/bin/python3.X`` (Unix) — so the bundle root is two
    levels up from ``sys.executable`` on Windows, three on Unix.
    """
    exe = Path(sys.executable).resolve()
    root = exe.parents[1] if sys.platform == "win32" else exe.parents[2]
    return root if (root / "bin").is_dir() else None


def officecli_bin_dir() -> Path | None:
    """Return the directory containing the bundled ``officecli`` binary, if any.

    ``EVOFLUX_OFFICECLI_DIR`` overrides discovery — set it in dev/CI to
    point at a manually-installed binary without a full sidecar build.
    Returns ``None`` when no bundled/overridden binary is found, meaning
    the skill falls back to whatever ``officecli`` is already on PATH.
    """
    override = os.environ.get("EVOFLUX_OFFICECLI_DIR")
    if override:
        candidate = Path(override)
        return candidate if (candidate / _BIN_NAME).is_file() else None

    root = _bundle_root()
    if root is None:
        return None
    candidate = root / "bin"
    return candidate if (candidate / _BIN_NAME).is_file() else None


def ensure_officecli_on_path() -> None:
    """Prepend the bundled OfficeCLI's directory to ``PATH``, if found.

    No-op outside the bundled sidecar (and no ``EVOFLUX_OFFICECLI_DIR``
    override) — the xlsx/pptx skills then fall back to whatever
    ``officecli`` is already on the user's PATH, if anything.
    """
    bin_dir = officecli_bin_dir()
    if bin_dir is None:
        return
    bin_dir_str = str(bin_dir)
    current = os.environ.get("PATH", "")
    if bin_dir_str in current.split(os.pathsep):
        return
    os.environ["PATH"] = (
        os.pathsep.join([bin_dir_str, current]) if current else bin_dir_str
    )
    logger.info("officecli_bin_added_to_path dir={}", bin_dir_str)
