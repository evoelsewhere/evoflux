"""Package/module identity, and explicit local-path dependencies, for
cross-repo reference matching.

``read_manifests``/``PackageManifest`` (identity) answer "what does this repo
call itself" — the cross-repo resolver's Tier A pass matches an unresolved
import's raw specifier against *every* sibling's identity, which is the only
option when the referencing repo's own manifest says nothing about where the
dependency lives.

``read_path_dependencies``/``PathDependency`` answer the opposite, stronger
question: "does this repo's *own* manifest explicitly point at a sibling by
relative path" (npm ``file:``/``link:``/``workspace:``, uv/poetry ``path=``,
Go ``replace``, Cargo ``path=``). When it does, that's a free, unambiguous
signal — no cross-sibling identity search needed, so the resolver tries it
first.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import yaml

# --- Ecosystem identifiers ---------------------------------------------------
ECOSYSTEM_NPM = "npm"
ECOSYSTEM_PYTHON = "python"
ECOSYSTEM_GO = "go"
ECOSYSTEM_CARGO = "cargo"


@dataclass(frozen=True, slots=True)
class PackageManifest:
    ecosystem: str
    package_name: str


@dataclass(frozen=True, slots=True)
class PathDependency:
    """An explicit local-path dependency declared in a repo's own manifest.

    ``alias`` is the identifier used to reference the dependency in import
    statements (a package name, a Go module path, …). ``relative_path`` is
    exactly as declared in the manifest, resolved against the manifest
    file's own directory.
    """

    ecosystem: str
    alias: str
    relative_path: str


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


def read_path_dependencies(root_path: str | Path) -> list[PathDependency]:
    """Read explicit local-path dependencies declared at the root of ``root_path``.

    A repo can declare more than one (e.g. several ``file:`` deps in one
    ``package.json``) — callers should try matching against all of them.
    """
    root = Path(root_path)
    out: list[PathDependency] = []

    pkg_json = root / "package.json"
    if pkg_json.is_file():
        out.extend(_read_npm_path_deps(root, pkg_json))

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        out.extend(_read_python_path_deps(pyproject))

    go_mod = root / "go.mod"
    if go_mod.is_file():
        out.extend(_read_go_mod_replace(go_mod))

    cargo_toml = root / "Cargo.toml"
    if cargo_toml.is_file():
        out.extend(_read_cargo_path_deps(cargo_toml))

    return out


def match_path_dependency(
    raw_reference: str, path_dependencies: list[PathDependency]
) -> PathDependency | None:
    """Longest-alias-prefix match, mirroring ``match_reference_to_package``.

    Returns ``None`` on no match or an ambiguous tie — a repo with two path
    dependencies whose aliases both prefix-match is a manifest-authoring
    oddity we shouldn't guess through.
    """
    if raw_reference.startswith(".") or raw_reference.startswith("/"):
        return None

    candidates = [
        d
        for d in path_dependencies
        if raw_reference == d.alias
        or any(raw_reference.startswith(d.alias + sep) for sep in ("/", ".", "::"))
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda d: len(d.alias), reverse=True)
    best_len = len(candidates[0].alias)
    tied = [d for d in candidates if len(d.alias) == best_len]
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


# --- Per-ecosystem path-dependency readers -----------------------------------

_NPM_LOCAL_PROTOCOLS = ("file:", "link:")
_NPM_DEP_SECTIONS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
)


def _read_npm_path_deps(root: Path, pkg_json: Path) -> list[PathDependency]:
    try:
        pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(pkg, dict):
        return []

    out: list[PathDependency] = []
    workspace_members: dict[str, Path] | None = None
    for section in _NPM_DEP_SECTIONS:
        deps = pkg.get(section)
        if not isinstance(deps, dict):
            continue
        for alias, spec in deps.items():
            if not isinstance(spec, str):
                continue
            matched_local = False
            for proto in _NPM_LOCAL_PROTOCOLS:
                if spec.startswith(proto):
                    rel = spec[len(proto) :]
                    if rel:
                        out.append(PathDependency(ECOSYSTEM_NPM, alias, rel))
                    matched_local = True
                    break
            if matched_local or not spec.startswith("workspace:"):
                continue
            # "workspace:*" — resolve via this repo's own workspace glob
            # members (only meaningful if this root is itself a workspace
            # root; lazily computed since most manifests won't need it).
            if workspace_members is None:
                workspace_members = _npm_workspace_members(root, pkg)
            member_dir = workspace_members.get(alias)
            if member_dir is not None:
                out.append(
                    PathDependency(ECOSYSTEM_NPM, alias, _relpath(member_dir, root))
                )
    return out


def _npm_workspace_members(root: Path, pkg: dict) -> dict[str, Path]:
    """Resolve a workspace root's member glob to ``{package_name: member_dir}``."""
    members: dict[str, Path] = {}
    for pattern in _npm_workspace_globs(root, pkg):
        if pattern.startswith("!"):
            continue  # exclusion pattern, not a member glob
        for candidate in root.glob(pattern):
            member_json = candidate / "package.json"
            if not member_json.is_file():
                continue
            name = _read_package_json_name(member_json)
            if name:
                members[name] = candidate
    return members


def _npm_workspace_globs(root: Path, pkg: dict) -> list[str]:
    raw = pkg.get("workspaces")
    if isinstance(raw, list):
        return [g for g in raw if isinstance(g, str)]
    if isinstance(raw, dict):
        packages = raw.get("packages")
        if isinstance(packages, list):
            return [g for g in packages if isinstance(g, str)]

    pnpm_ws = root / "pnpm-workspace.yaml"
    if pnpm_ws.is_file():
        try:
            data = yaml.safe_load(pnpm_ws.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return []
        if isinstance(data, dict):
            packages = data.get("packages")
            if isinstance(packages, list):
                return [g for g in packages if isinstance(g, str)]
    return []


def _relpath(target: Path, root: Path) -> str:
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return str(target)


def _read_python_path_deps(pyproject: Path) -> list[PathDependency]:
    """``[tool.uv.sources] alias = { path = "../foo" }`` and
    ``[tool.poetry.dependencies] alias = { path = "../foo" }``.

    ``{ workspace = true }`` uv sources resolve within this repo's own
    ``[tool.uv.workspace]`` members — same-repo, not a cross-repo signal —
    so only literal ``path=`` entries are collected.
    """
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    tool = data.get("tool")
    tool = tool if isinstance(tool, dict) else {}

    out: list[PathDependency] = []
    uv = tool.get("uv")
    if isinstance(uv, dict):
        sources = uv.get("sources")
        if isinstance(sources, dict):
            out.extend(_python_path_deps_from(sources))

    poetry = tool.get("poetry")
    if isinstance(poetry, dict):
        deps = poetry.get("dependencies")
        if isinstance(deps, dict):
            out.extend(_python_path_deps_from(deps))

    return out


def _python_path_deps_from(deps: dict) -> list[PathDependency]:
    out: list[PathDependency] = []
    for alias, spec in deps.items():
        if isinstance(spec, dict):
            path = spec.get("path")
            if isinstance(path, str) and path:
                out.append(PathDependency(ECOSYSTEM_PYTHON, alias, path))
    return out


_GO_MOD_REPLACE_LINE_RE = re.compile(
    r"^\s*replace\s+(\S+)(?:\s+\S+)?\s*=>\s*(\S+)(?:\s+\S+)?\s*$"
)
_GO_MOD_REPLACE_BLOCK_START_RE = re.compile(r"^\s*replace\s*\(\s*$")
_GO_MOD_REPLACE_ENTRY_RE = re.compile(
    r"^\s*(\S+)(?:\s+\S+)?\s*=>\s*(\S+)(?:\s+\S+)?\s*$"
)
_GO_MOD_BLOCK_END_RE = re.compile(r"^\s*\)\s*$")


def _read_go_mod_replace(go_mod: Path) -> list[PathDependency]:
    """``replace <module> => ./local/dir`` (single-line or block form).

    Only local filesystem replacements are a cross-repo path signal — a
    replace pointing at another module@version is not a path at all.
    """
    try:
        lines = go_mod.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    out: list[PathDependency] = []
    in_block = False
    for raw_line in lines:
        line = raw_line.split("//", 1)[0]
        if in_block:
            if _GO_MOD_BLOCK_END_RE.match(line):
                in_block = False
                continue
            match = _GO_MOD_REPLACE_ENTRY_RE.match(line)
        else:
            if _GO_MOD_REPLACE_BLOCK_START_RE.match(line):
                in_block = True
                continue
            match = _GO_MOD_REPLACE_LINE_RE.match(line)
        if match is None:
            continue
        module_path, target = match.group(1), match.group(2)
        if target.startswith("./") or target.startswith("../"):
            out.append(PathDependency(ECOSYSTEM_GO, module_path, target))
    return out


_CARGO_DEP_SECTIONS = ("dependencies", "dev-dependencies", "build-dependencies")


def _read_cargo_path_deps(cargo_toml: Path) -> list[PathDependency]:
    try:
        data = tomllib.loads(cargo_toml.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []

    out: list[PathDependency] = []
    for section in _CARGO_DEP_SECTIONS:
        deps = data.get(section)
        if isinstance(deps, dict):
            out.extend(_cargo_path_deps_from(deps))

    target = data.get("target")
    if isinstance(target, dict):
        for target_spec in target.values():
            if not isinstance(target_spec, dict):
                continue
            for section in _CARGO_DEP_SECTIONS:
                deps = target_spec.get(section)
                if isinstance(deps, dict):
                    out.extend(_cargo_path_deps_from(deps))

    return out


def _cargo_path_deps_from(deps: dict) -> list[PathDependency]:
    out: list[PathDependency] = []
    for alias, spec in deps.items():
        if isinstance(spec, dict):
            path = spec.get("path")
            if isinstance(path, str) and path:
                out.append(PathDependency(ECOSYSTEM_CARGO, alias, path))
    return out
