"""Path-aware intra-repo import resolution.

Resolves ``EDGE_IMPORTS`` edges by following the import path to a target file
instead of relying on workspace-global name search. This is the primary fix
for the cross-file import resolution gap: a relative import like ``./utils``
resolves to the exact sibling file deterministically, rather than being
dropped as "ambiguous" by the flat name search that ``_resolve_qualified``
uses.

Per-ecosystem file resolution:
- **Relative** (``.``/``..`` prefix): universal, resolved against the
  importing file's directory.
- **Python absolute**: indexed top-level modules and packages, including
    ``src/`` layouts.
- **Go absolute**: ``go.mod`` module path prefix; resolves to a directory.
- **TS path aliases**: ``tsconfig.json`` ``compilerOptions.baseUrl``/``paths``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.services.code_graph.manifest import read_go_module_path


@dataclass(frozen=True, slots=True)
class RepoContext:
    """Per-repo layout hints built once per indexer invocation."""

    root: Path
    py_top_level_packages: frozenset[str]
    go_module_path: str | None
    ts_base_url: str | None
    ts_path_aliases: dict[str, list[str]]


@dataclass(frozen=True, slots=True)
class ResolvedImport:
    """A single resolved import edge."""

    src_key: str
    dst_file_path: str | None
    dst_key: str | None
    imported_name: str
    local_name: str


@dataclass(slots=True)
class ModuleResolution:
    """Aggregated resolution results for all import edges in a workspace."""

    by_import_edge: dict[tuple[str, str, str | None, str | None], ResolvedImport] = (
        field(default_factory=dict)
    )
    imports_by_file: dict[str, dict[str, ResolvedImport]] = field(default_factory=dict)


# --- Repo context builder ----------------------------------------------------


def build_repo_context(root: Path) -> RepoContext:
    return RepoContext(
        root=root,
        py_top_level_packages=_detect_python_top_level(root),
        go_module_path=read_go_module_path(root),
        ts_base_url=_read_ts_base_url(root),
        ts_path_aliases=_read_ts_path_aliases(root),
    )


def _detect_python_top_level(root: Path) -> frozenset[str]:
    """Find top-level Python packages in this repo.

    Scans for directories containing ``__init__.py`` at the root level and
    under ``src/`` (the src-layout convention).
    """
    packages: set[str] = set()
    for child in root.iterdir():
        if child.is_dir() and (child / "__init__.py").is_file():
            packages.add(child.name)
    src = root / "src"
    if src.is_dir():
        for child in src.iterdir():
            if child.is_dir() and (child / "__init__.py").is_file():
                packages.add(child.name)
    return frozenset(packages)


def _read_tsconfig(root: Path) -> dict:
    """Read the current TypeScript config for an index pass.

    Indexing is long-lived inside the desktop backend, so a process-global
    cache made edits to ``tsconfig.json`` invisible until restart.  The repo
    context is already built only once per index invocation; reading this
    small file here keeps path-alias resolution correct without meaningful
    extra work.
    """
    tsconfig = root / "tsconfig.json"
    if not tsconfig.is_file():
        return {}
    try:
        data = json.loads(tsconfig.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_ts_base_url(root: Path) -> str | None:
    co = _read_tsconfig(root).get("compilerOptions")
    if not isinstance(co, dict):
        return None
    bu = co.get("baseUrl")
    return bu if isinstance(bu, str) and bu else None


def _read_ts_path_aliases(root: Path) -> dict[str, list[str]]:
    co = _read_tsconfig(root).get("compilerOptions")
    if not isinstance(co, dict):
        return {}
    paths = co.get("paths")
    if not isinstance(paths, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, vals in paths.items():
        if isinstance(vals, list):
            out[key] = [v for v in vals if isinstance(v, str)]
    return out


# --- Module path resolver -----------------------------------------------------


def resolve_module_paths(
    raw_edges: list[
        tuple[
            str,
            str | None,
            str | None,
            str,
            int | None,
            str | None,
            str | None,
        ]
    ],
    symbols_by_file: dict[str, dict[str, list[str]]],
    known_files: frozenset[str],
    repo_ctx: RepoContext,
) -> ModuleResolution:
    """Resolve ``EDGE_IMPORTS`` raw edges to target files.

    Returns a :class:`ModuleResolution` mapping ``(src_key, module_path)``
    pairs to resolved targets. Non-import edges are ignored.
    """
    resolution = ModuleResolution()
    for (
        src_key,
        _dst_local,
        dst_name,
        kind,
        _line,
        module_path,
        local_name,
    ) in raw_edges:
        if kind != "imports" or not module_path:
            continue
        src_file = src_key.split("::", 1)[0] if "::" in src_key else ""
        target_file = None
        # ``from package import submodule`` binds the submodule, not the
        # package's ``__init__.py``. Prefer that precise Python target when it
        # exists so qualified callbacks such as ``submodule.run`` stay scoped.
        if (
            Path(src_file).suffix.lower() in _PYTHON_EXTENSIONS
            and dst_name
            and not module_path.startswith(".")
        ):
            target_file = _resolve_python_absolute(
                f"{module_path}.{dst_name}", known_files, repo_ctx
            )
        if target_file is None:
            target_file = _resolve_module_path_to_file(
                module_path, src_file, known_files, repo_ctx
            )
        imported_name = dst_name or module_path.rsplit(".", 1)[-1].split("/", 1)[-1]
        binding_name = local_name or imported_name
        dst_key = (
            _find_symbol_in_file(imported_name, target_file, symbols_by_file)
            if target_file is not None
            else None
        )
        resolved = ResolvedImport(
            src_key=src_key,
            dst_file_path=target_file,
            dst_key=dst_key,
            imported_name=imported_name,
            local_name=binding_name,
        )
        resolution.by_import_edge[(src_key, module_path, dst_name, local_name)] = (
            resolved
        )
        file_imports = resolution.imports_by_file.setdefault(src_file, {})
        file_imports[binding_name] = resolved
    return resolution


def _resolve_module_path_to_file(
    module_path: str,
    src_file: str,
    known_files: frozenset[str],
    repo_ctx: RepoContext,
) -> str | None:
    """Resolve a module path to a file path in the workspace.

    Returns the relative POSIX path of the target file, or ``None`` if the
    path can't be resolved within this workspace.
    """
    if module_path.startswith(".") or module_path.startswith(".."):
        return _resolve_relative(module_path, src_file, known_files, repo_ctx)

    ext = Path(src_file).suffix.lower()
    if ext in _PYTHON_EXTENSIONS:
        return _resolve_python_absolute(module_path, known_files, repo_ctx)
    if ext in _GO_EXTENSIONS:
        return _resolve_go_absolute(module_path, known_files, repo_ctx)
    if ext in _TS_EXTENSIONS:
        return _resolve_ts_path(module_path, src_file, known_files, repo_ctx)
    return None


def _resolve_relative(
    module_path: str,
    src_file: str,
    known_files: frozenset[str],
    repo_ctx: RepoContext,
) -> str | None:
    src_dir = str(Path(src_file).parent)
    # Normalize ./ and ../ using POSIX path arithmetic
    parts = module_path.replace("\\", "/").split("/")
    src_parts = (
        src_dir.replace("\\", "/").split("/") if src_dir and src_dir != "." else []
    )
    target_parts = list(src_parts)
    for part in parts:
        if part == ".":
            continue
        elif part == "..":
            if target_parts:
                target_parts.pop()
        else:
            target_parts.append(part)
    base = "/".join(target_parts)

    ext = Path(src_file).suffix.lower()
    candidates = _candidate_paths(base, ext, repo_ctx)
    for candidate in candidates:
        if candidate in known_files:
            return candidate
    return None


def _resolve_python_absolute(
    module_path: str,
    known_files: frozenset[str],
    repo_ctx: RepoContext,
) -> str | None:
    segments = module_path.split(".")
    if not segments:
        return None
    rel = "/".join(segments)

    for base in (rel, f"src/{rel}"):
        candidates = _candidate_paths(base, ".py", repo_ctx)
        for candidate in candidates:
            if candidate in known_files:
                return candidate
    return None


def _resolve_go_absolute(
    module_path: str,
    known_files: frozenset[str],
    repo_ctx: RepoContext,
) -> str | None:
    if not repo_ctx.go_module_path:
        return None
    if not module_path.startswith(repo_ctx.go_module_path):
        return None
    suffix = module_path[len(repo_ctx.go_module_path) :].lstrip("/")
    if not suffix:
        return "__dir__:"
    rel_dir = suffix.replace(".", "/")
    prefix = f"{rel_dir}/"
    for f in known_files:
        if f.startswith(prefix) and f.endswith(".go"):
            return f"{rel_dir}/"
    return None


def _resolve_ts_path(
    module_path: str,
    src_file: str,
    known_files: frozenset[str],
    repo_ctx: RepoContext,
) -> str | None:
    if repo_ctx.ts_base_url:
        base_from_url = f"{repo_ctx.ts_base_url}/{module_path}".replace("//", "/")
        candidates = _candidate_paths(base_from_url, ".ts", repo_ctx)
        for candidate in candidates:
            if candidate in known_files:
                return candidate

    for pattern, targets in repo_ctx.ts_path_aliases.items():
        matched_prefix = _match_ts_alias_prefix(module_path, pattern)
        if matched_prefix is None:
            continue
        for target_template in targets:
            resolved_base = target_template.replace("*", matched_prefix)
            candidates = _candidate_paths(resolved_base, ".ts", repo_ctx)
            for candidate in candidates:
                if candidate in known_files:
                    return candidate

    return _resolve_relative(module_path, src_file, known_files, repo_ctx)


def _match_ts_alias_prefix(module_path: str, pattern: str) -> str | None:
    if "*" not in pattern:
        return module_path if module_path == pattern else None
    prefix = pattern.split("*", 1)[0]
    if module_path.startswith(prefix):
        return module_path[len(prefix) :]
    return None


_PYTHON_EXTENSIONS = (".py", ".pyi")
_GO_EXTENSIONS = (".go",)
_TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def _candidate_paths(base: str, importing_ext: str, repo_ctx: RepoContext) -> list[str]:
    """Generate candidate file paths for a resolved base path."""
    if importing_ext in _PYTHON_EXTENSIONS:
        return [
            f"{base}.py",
            f"{base}/__init__.py",
            f"{base}.pyi",
        ]
    if importing_ext in _GO_EXTENSIONS:
        return [f"{base}.go"]
    if importing_ext in _TS_EXTENSIONS:
        candidates = [
            base,
            f"{base}.ts",
            f"{base}.tsx",
            f"{base}.js",
            f"{base}.jsx",
            f"{base}.mjs",
            f"{base}.cjs",
            f"{base}/index.ts",
            f"{base}/index.tsx",
            f"{base}/index.js",
            f"{base}/index.jsx",
        ]
        return candidates
    return [base]


def _find_symbol_in_file(
    name: str,
    file_path: str,
    symbols_by_file: dict[str, dict[str, list[str]]],
) -> str | None:
    """Find a symbol by name within a specific file's node keys.

    Returns the node key if exactly one match is found, ``None`` otherwise.
    """
    file_symbols = symbols_by_file.get(file_path, {})
    matches = file_symbols.get(name, [])
    if len(matches) == 1:
        return matches[0]
    file_nodes = file_symbols.get(file_path, [])
    if not matches and len(file_nodes) == 1:
        return file_nodes[0]
    return None
