"""Package/module identity for cross-repo reference matching.

Identity only — this reads a repo's manifest just to learn its own
package/module name, never to resolve its dependency graph. The cross-repo
resolver's Tier A (static, free) pass uses that identity to match an
unresolved import's raw specifier against sibling repos in the same project.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

# --- Ecosystem identifiers ---------------------------------------------------
ECOSYSTEM_NPM = "npm"
ECOSYSTEM_PYTHON = "python"
ECOSYSTEM_GO = "go"
ECOSYSTEM_CARGO = "cargo"


@dataclass(frozen=True, slots=True)
class PackageManifest:
    ecosystem: str
    package_name: str


def read_manifests(root_path: str | Path) -> list[PackageManifest]:
    """Read every recognized manifest at the root of ``root_path``.

    A repo can plausibly have more than one identity (e.g. a Python service
    with a package.json for frontend tooling) — callers should try matching
    against all of them, not pick just one.
    """
    root = Path(root_path)
    out: list[PackageManifest] = []

    pkg_json = root / "package.json"
    if pkg_json.is_file():
        name = _read_package_json_name(pkg_json)
        if name:
            out.append(PackageManifest(ecosystem=ECOSYSTEM_NPM, package_name=name))

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        name = _read_pyproject_name(pyproject)
        if name:
            out.append(PackageManifest(ecosystem=ECOSYSTEM_PYTHON, package_name=name))
    else:
        setup_py = root / "setup.py"
        if setup_py.is_file():
            name = _read_setup_py_name(setup_py)
            if name:
                out.append(PackageManifest(ecosystem=ECOSYSTEM_PYTHON, package_name=name))

    go_mod = root / "go.mod"
    if go_mod.is_file():
        name = _read_go_mod_module(go_mod)
        if name:
            out.append(PackageManifest(ecosystem=ECOSYSTEM_GO, package_name=name))

    cargo_toml = root / "Cargo.toml"
    if cargo_toml.is_file():
        name = _read_cargo_toml_name(cargo_toml)
        if name:
            out.append(PackageManifest(ecosystem=ECOSYSTEM_CARGO, package_name=name))

    return out


def match_reference_to_package(
    raw_reference: str, manifests: list[PackageManifest]
) -> PackageManifest | None:
    """Longest-prefix match an import specifier against known package names.

    E.g. ``raw_reference="@company/lib/utils"`` matches
    ``package_name="@company/lib"`` (a subpath import). Relative imports
    (starting with ``.`` or ``/``) never match — they're intra-repo by
    construction. Returns ``None`` on no match or an ambiguous tie (two
    candidate packages of the same specificity) — better to leave a
    reference unresolved than guess wrong.
    """
    if raw_reference.startswith(".") or raw_reference.startswith("/"):
        return None

    candidates = [
        m
        for m in manifests
        if raw_reference == m.package_name
        or any(
            raw_reference.startswith(m.package_name + sep)
            for sep in ("/", ".", "::")
        )
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda m: len(m.package_name), reverse=True)
    best_len = len(candidates[0].package_name)
    tied = [m for m in candidates if len(m.package_name) == best_len]
    return tied[0] if len(tied) == 1 else None


# --- Per-ecosystem readers ---------------------------------------------------


def _read_package_json_name(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    name = data.get("name") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name else None


def _read_pyproject_name(path: Path) -> str | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    name = data.get("project", {}).get("name")
    if isinstance(name, str) and name:
        return name
    # Older Poetry-style layout — still common.
    name = data.get("tool", {}).get("poetry", {}).get("name")
    return name if isinstance(name, str) and name else None


_SETUP_PY_NAME_RE = re.compile(r"""name\s*=\s*['"]([^'"]+)['"]""")


def _read_setup_py_name(path: Path) -> str | None:
    """Best-effort regex scrape. setup.py is executable Python, not data —
    deliberately not exec()'d."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _SETUP_PY_NAME_RE.search(text)
    return match.group(1) if match else None


_GO_MOD_MODULE_RE = re.compile(r"^\s*module\s+(\S+)", re.MULTILINE)


def _read_go_mod_module(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _GO_MOD_MODULE_RE.search(text)
    return match.group(1) if match else None


def _read_cargo_toml_name(path: Path) -> str | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    name = data.get("package", {}).get("name")
    return name if isinstance(name, str) and name else None
