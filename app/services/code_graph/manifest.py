"""Package/module identity, explicit local-path dependencies, and
external-dependency filtering, for cross-repo reference matching.

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

``read_declared_dependencies``/``is_likely_external`` answer a third,
different question: "is this reference almost certainly a THIRD-PARTY
library, not a candidate cross-repo reference at all". Without this, every
unresolved import in a large codebase — including ordinary JDK/stdlib/
well-known-library imports — becomes a permanent, never-resolvable
``CrossRepoEdge`` candidate (observed in practice: a 4-repo Java+JS project
produced 27,744 such rows, almost all imports of libraries like Liquibase
that exist in none of the sibling repos). This is a pre-filter applied
*before* a candidate is ever persisted, not a resolution tier.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import yaml

# --- Ecosystem identifiers ---------------------------------------------------
ECOSYSTEM_NPM = "npm"
ECOSYSTEM_PYTHON = "python"
ECOSYSTEM_GO = "go"
ECOSYSTEM_CARGO = "cargo"
ECOSYSTEM_MAVEN = "maven"
ECOSYSTEM_GRADLE = "gradle"
ECOSYSTEM_COMPOSER = "composer"
ECOSYSTEM_GEM = "gem"
ECOSYSTEM_PUB = "pub"
ECOSYSTEM_NUGET = "nuget"
ECOSYSTEM_COCOAPODS = "cocoapods"
ECOSYSTEM_SWIFTPM = "swiftpm"
ECOSYSTEM_DOCKER = "docker"
ECOSYSTEM_HELM = "helm"
ECOSYSTEM_TERRAFORM = "terraform"


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
                out.append(
                    PackageManifest(ecosystem=ECOSYSTEM_PYTHON, package_name=name)
                )

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

    pom_xml = root / "pom.xml"
    if pom_xml.is_file():
        name = _read_pom_identity(pom_xml)
        if name:
            out.append(PackageManifest(ecosystem=ECOSYSTEM_MAVEN, package_name=name))

    gradle_name = _read_gradle_identity(root)
    if gradle_name:
        out.append(
            PackageManifest(ecosystem=ECOSYSTEM_GRADLE, package_name=gradle_name)
        )

    composer_json = root / "composer.json"
    if composer_json.is_file():
        out.extend(_read_composer_identities(composer_json))

    gemspec = _find_glob_file(root, "*.gemspec")
    if gemspec is not None:
        name = _read_gemspec_name(gemspec)
        if name:
            out.append(PackageManifest(ecosystem=ECOSYSTEM_GEM, package_name=name))

    pubspec = root / "pubspec.yaml"
    if pubspec.is_file():
        name = _read_pubspec_name(pubspec)
        if name:
            out.append(PackageManifest(ecosystem=ECOSYSTEM_PUB, package_name=name))

    csproj = _find_glob_file(root, "*.csproj")
    if csproj is not None:
        name = _read_csproj_identity(csproj)
        if name:
            out.append(PackageManifest(ecosystem=ECOSYSTEM_NUGET, package_name=name))

    podspec = _find_glob_file(root, "*.podspec")
    if podspec is not None:
        name = _read_podspec_name(podspec)
        if name:
            out.append(
                PackageManifest(ecosystem=ECOSYSTEM_COCOAPODS, package_name=name)
            )

    package_swift = root / "Package.swift"
    if package_swift.is_file():
        name = _read_package_swift_name(package_swift)
        if name:
            out.append(PackageManifest(ecosystem=ECOSYSTEM_SWIFTPM, package_name=name))

    chart_yaml = root / "Chart.yaml"
    if chart_yaml.is_file():
        name = _read_helm_chart_name(chart_yaml)
        if name:
            out.append(PackageManifest(ecosystem=ECOSYSTEM_HELM, package_name=name))

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
            raw_reference.startswith(m.package_name + sep) for sep in ("/", ".", "::")
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

    settings_gradle = _find_gradle_settings(root)
    if settings_gradle is not None:
        out.extend(_read_gradle_path_deps(settings_gradle))

    composer_json = root / "composer.json"
    if composer_json.is_file():
        out.extend(_read_composer_path_deps(root, composer_json))

    gemfile = root / "Gemfile"
    if gemfile.is_file():
        out.extend(_read_gemfile_path_deps(gemfile, ecosystem=ECOSYSTEM_GEM))

    pubspec = root / "pubspec.yaml"
    if pubspec.is_file():
        out.extend(_read_pubspec_path_deps(root, pubspec))

    for csproj in root.glob("*.csproj"):
        out.extend(_read_csproj_path_deps(root, csproj))

    podfile = root / "Podfile"
    if podfile.is_file():
        out.extend(
            _read_gemfile_path_deps(
                podfile, ecosystem=ECOSYSTEM_COCOAPODS, method="pod"
            )
        )

    package_swift = root / "Package.swift"
    if package_swift.is_file():
        out.extend(_read_package_swift_path_deps(root, package_swift))

    for compose_name in (
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    ):
        compose_file = root / compose_name
        if compose_file.is_file():
            out.extend(_read_compose_path_deps(compose_file))
            break  # only one compose file convention per repo

    chart_yaml = root / "Chart.yaml"
    if chart_yaml.is_file():
        out.extend(_read_helm_path_deps(chart_yaml))

    out.extend(_read_terraform_path_deps(root))

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


def compute_importable_id(
    file_path: str,
    qualified_name: str,
    *,
    language: str,
    root_prefix: str | None,
    separator: str = ".",
) -> str | None:
    """Compute a cross-repo-importable identifier for a node.

    Combines a repo-level root prefix (package name, Go module path, etc.)
    with the relative module path and the symbol's qualified name suffix.

    Returns ``None`` when the ecosystem/layout doesn't support it — the
    caller falls through to manifest-package matching.
    """
    if not root_prefix:
        return None

    rel = file_path.replace("\\", "/")
    if language in ("python",):
        if rel.endswith("/__init__.py"):
            rel = rel[: -len("/__init__.py")]
        elif rel.endswith(".py"):
            rel = rel[: -len(".py")]
        elif rel.endswith(".pyi"):
            rel = rel[: -len(".pyi")]
        else:
            return None
        module_part = rel.replace("/", ".")
    elif language in ("javascript", "typescript"):
        for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
            if rel.endswith(ext):
                rel = rel[: -len(ext)]
                break
        if rel.endswith("/index"):
            rel = rel[: -len("/index")]
        module_part = rel.replace("/", ".")
    elif language == "go":
        # Go imports are directory-level, not file-level.
        parts = rel.rsplit("/", 1)
        module_part = parts[0] if len(parts) > 1 else ""
    else:
        return None

    if module_part:
        full = f"{root_prefix}{separator}{module_part}"
    else:
        full = root_prefix

    # If the node is the module/file itself, don't append the qualified name.
    if qualified_name and qualified_name != file_path:
        return f"{full}{separator}{qualified_name}"
    return full


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


def read_go_module_path(root_path: str | Path) -> str | None:
    """Read the ``module`` directive from ``go.mod`` at ``root_path``."""
    return _read_go_mod_module(Path(root_path) / "go.mod")


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


def _pom_local_tag(elem: ET.Element) -> str:
    """Strip the Maven POM XML namespace (``{http://maven.apache.org/...}``)."""
    return elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag


def _pom_child(elem: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in elem if _pom_local_tag(c) == name), None)


def _pom_children(elem: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in elem if _pom_local_tag(c) == name]


def _pom_child_text(elem: ET.Element, name: str) -> str | None:
    child = _pom_child(elem, name)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text if text else None


def _read_pom_identity(path: Path) -> str | None:
    """``groupId:artifactId`` (falling back to the ``<parent>``'s groupId,
    which Maven allows a child module to omit its own ``<groupId>`` for)."""
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError):
        return None
    artifact_id = _pom_child_text(root, "artifactId")
    if not artifact_id:
        return None
    group_id = _pom_child_text(root, "groupId")
    if group_id is None:
        parent = _pom_child(root, "parent")
        if parent is not None:
            group_id = _pom_child_text(parent, "groupId")
    return f"{group_id}:{artifact_id}" if group_id else artifact_id


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


# --- Shared filesystem helpers ------------------------------------------------


def _find_glob_file(root: Path, pattern: str) -> Path | None:
    """Return the first match for ``pattern`` at the root of ``root``, if any."""
    return next(iter(root.glob(pattern)), None)


def _sibling_manifest_name(root: Path, relative_path: str) -> str | None:
    """Peek at a path-dependency target's OWN manifest for its self-declared
    name — used by ecosystems (Composer, NuGet, SwiftPM) whose local-path
    dependency syntax names a file/URL rather than the target's package
    identity directly, so the alias has to come from the target itself."""
    try:
        target = (root / relative_path).resolve()
    except (OSError, ValueError):
        return None
    if not target.is_dir():
        return None
    for manifest in read_manifests(target):
        return manifest.package_name
    return None


# --- Gradle (JVM, separate from Maven) ---------------------------------------

_GRADLE_ROOT_NAME_RE = re.compile(r"""rootProject\.name\s*=\s*['"]([^'"]+)['"]""")
_GRADLE_GROUP_RE = re.compile(r"""^\s*group\s*=?\s*['"]([^'"]+)['"]""", re.MULTILINE)
_GRADLE_INCLUDE_BUILD_RE = re.compile(r"""includeBuild\(\s*['"]([^'"]+)['"]\s*\)""")
# implementation("group:artifact:version") / implementation "group:artifact:version"
# / api(...) / testImplementation(...) / runtimeOnly(...) / compileOnly(...) —
# regex-based since Gradle build files are Groovy/Kotlin DSL code, not data.
_GRADLE_DEP_COORD_RE = re.compile(
    r"""(?:implementation|api|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly)"""
    r"""[\s(]+['"]([^:'"]+):([^:'"]+):[^'"]*['"]"""
)


def _find_gradle_settings(root: Path) -> Path | None:
    for name in ("settings.gradle.kts", "settings.gradle"):
        path = root / name
        if path.is_file():
            return path
    return None


def _find_gradle_build(root: Path) -> Path | None:
    for name in ("build.gradle.kts", "build.gradle"):
        path = root / name
        if path.is_file():
            return path
    return None


def _read_gradle_identity(root: Path) -> str | None:
    settings = _find_gradle_settings(root)
    name: str | None = None
    if settings is not None:
        try:
            text = settings.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        match = _GRADLE_ROOT_NAME_RE.search(text)
        if match:
            name = match.group(1)
    if name is None:
        return None
    build = _find_gradle_build(root)
    if build is not None:
        try:
            text = build.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        match = _GRADLE_GROUP_RE.search(text)
        if match:
            return f"{match.group(1)}:{name}"
    return name


def _read_gradle_path_deps(settings_file: Path) -> list[PathDependency]:
    """Gradle composite builds (``includeBuild("../sibling")``) — the closest
    JVM analogue to npm ``workspace:``/Cargo ``path=``. No alias is declared
    here (Gradle auto-substitutes matching dependency coordinates against
    included builds at the project-dependency level, not by name in
    settings) — the placeholder alias falls through to Tier B identity
    matching against the target's own build.gradle ``group``/name, same
    pattern as Go's ``go.work`` "use" entries.
    """
    try:
        text = settings_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[PathDependency] = []
    for match in _GRADLE_INCLUDE_BUILD_RE.finditer(text):
        rel = match.group(1)
        out.append(PathDependency(ECOSYSTEM_GRADLE, rel, rel))
    return out


def _gradle_declared_deps(build_gradle: Path) -> list[str]:
    try:
        text = build_gradle.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [match.group(1) for match in _GRADLE_DEP_COORD_RE.finditer(text)]


# --- Composer (PHP) -----------------------------------------------------------


def _read_composer_identities(composer_json: Path) -> list[PackageManifest]:
    """``name`` (vendor/package) plus every PSR-4 autoload namespace prefix —
    the latter is an unusually strong, machine-exact identity signal (see
    documents/analysis/code-graph-cross-repo-implementation-plan.md): a
    ``use Acme\\Shared\\Foo;`` reference matches a sibling's declared PSR-4
    prefix directly, no groupId-style guessing needed."""
    data = _read_json_dict(composer_json)
    if data is None:
        return []
    out: list[PackageManifest] = []
    name = data.get("name")
    if isinstance(name, str) and name:
        out.append(PackageManifest(ECOSYSTEM_COMPOSER, name))
    autoload = data.get("autoload")
    psr4 = autoload.get("psr-4") if isinstance(autoload, dict) else None
    if isinstance(psr4, dict):
        for namespace in psr4:
            if isinstance(namespace, str) and namespace:
                out.append(PackageManifest(ECOSYSTEM_COMPOSER, namespace.rstrip("\\")))
    return out


def _read_composer_path_deps(root: Path, composer_json: Path) -> list[PathDependency]:
    data = _read_json_dict(composer_json)
    if data is None:
        return []
    repositories = data.get("repositories")
    if not isinstance(repositories, list):
        return []
    out: list[PathDependency] = []
    for repo in repositories:
        if not isinstance(repo, dict) or repo.get("type") != "path":
            continue
        url = repo.get("url")
        if not isinstance(url, str) or not url:
            continue
        alias = _sibling_manifest_name(root, url) or url
        out.append(PathDependency(ECOSYSTEM_COMPOSER, alias, url))
    return out


def _composer_declared_deps(composer_json: Path) -> list[str]:
    data = _read_json_dict(composer_json)
    if data is None:
        return []
    out: list[str] = []
    for section in ("require", "require-dev"):
        deps = data.get(section)
        if isinstance(deps, dict):
            out.extend(name for name in deps if isinstance(name, str) and name != "php")
    return out


def _read_json_dict(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# --- Gem (Ruby / Bundler) and CocoaPods (share a Ruby-DSL Gemfile/Podfile shape) --

_GEMSPEC_NAME_RE = re.compile(r"""\.name\s*=\s*['"]([^'"]+)['"]""")
_PODSPEC_NAME_RE = re.compile(r"""\.name\s*=\s*['"]([^'"]+)['"]""")
# gem 'foo', path: '../foo'  |  gem "foo", :path => "../foo"
_GEM_PATH_RE = re.compile(
    r"""gem\s+['"]([^'"]+)['"]\s*,.*?(?::path\s*=>|path:)\s*['"]([^'"]+)['"]"""
)
_GEM_NAME_RE = re.compile(r"""gem\s+['"]([^'"]+)['"]""")
# pod 'Name', :path => '../Name'  |  pod "Name", path: "../Name"
_POD_PATH_RE = re.compile(
    r"""pod\s+['"]([^'"]+)['"]\s*,.*?(?::path\s*=>|path:)\s*['"]([^'"]+)['"]"""
)
_POD_NAME_RE = re.compile(r"""pod\s+['"]([^'"]+)['"]""")


def _read_gemspec_name(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _GEMSPEC_NAME_RE.search(text)
    return match.group(1) if match else None


def _read_gemfile_path_deps(
    path: Path, *, ecosystem: str, method: str = "gem"
) -> list[PathDependency]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    pattern = _POD_PATH_RE if method == "pod" else _GEM_PATH_RE
    return [
        PathDependency(ecosystem, match.group(1), match.group(2))
        for match in pattern.finditer(text)
    ]


def _gemfile_declared_deps(gemfile: Path) -> list[str]:
    try:
        text = gemfile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [match.group(1) for match in _GEM_NAME_RE.finditer(text)]


def _podfile_declared_deps(podfile: Path) -> list[str]:
    try:
        text = podfile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [match.group(1) for match in _POD_NAME_RE.finditer(text)]


def _read_podspec_name(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _PODSPEC_NAME_RE.search(text)
    return match.group(1) if match else None


# --- Pub (Dart) ----------------------------------------------------------------

_PUB_DEP_SECTIONS = ("dependencies", "dev_dependencies")


def _read_pubspec_name(path: Path) -> str | None:
    data = _read_yaml_dict(path)
    if data is None:
        return None
    name = data.get("name")
    return name if isinstance(name, str) and name else None


def _read_pubspec_path_deps(root: Path, pubspec: Path) -> list[PathDependency]:
    data = _read_yaml_dict(pubspec)
    if data is None:
        return []
    out: list[PathDependency] = []
    for section in _PUB_DEP_SECTIONS:
        deps = data.get(section)
        if not isinstance(deps, dict):
            continue
        for alias, spec in deps.items():
            if isinstance(spec, dict):
                path = spec.get("path")
                if isinstance(path, str) and path:
                    out.append(PathDependency(ECOSYSTEM_PUB, alias, path))

    # Dart 3.6+ native pub workspaces: root pubspec.yaml declares explicit
    # member paths directly (globs are NOT supported by this feature).
    workspace = data.get("workspace")
    if isinstance(workspace, list):
        for member_rel in workspace:
            if not isinstance(member_rel, str) or not member_rel:
                continue
            member_name = _sibling_manifest_name(root, member_rel)
            if member_name:
                out.append(PathDependency(ECOSYSTEM_PUB, member_name, member_rel))
    return out


def _pubspec_declared_deps(pubspec: Path) -> list[str]:
    data = _read_yaml_dict(pubspec)
    if data is None:
        return []
    out: list[str] = []
    for section in _PUB_DEP_SECTIONS:
        deps = data.get(section)
        if isinstance(deps, dict):
            out.extend(
                name for name in deps if isinstance(name, str) and name != "flutter"
            )
    return out


def _read_yaml_dict(path: Path) -> dict | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


# --- NuGet (.NET/C#) -----------------------------------------------------------

_MSBUILD_PROJECT_REFERENCE = "ProjectReference"
_MSBUILD_PACKAGE_REFERENCE = "PackageReference"


def _read_csproj_identity(path: Path) -> str | None:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError):
        return None
    for tag in ("AssemblyName", "RootNamespace"):
        for elem in root.iter():
            if _pom_local_tag(elem) == tag and elem.text and elem.text.strip():
                return elem.text.strip()
    # SDK-style projects default both to the project file's own base name
    # ($(MSBuildProjectName)) when neither property is set explicitly.
    return path.stem


def _read_csproj_path_deps(root: Path, csproj: Path) -> list[PathDependency]:
    try:
        tree_root = ET.fromstring(csproj.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError):
        return []
    out: list[PathDependency] = []
    for elem in tree_root.iter():
        if _pom_local_tag(elem) != _MSBUILD_PROJECT_REFERENCE:
            continue
        include = elem.get("Include")
        if not include:
            continue
        # Include points at a sibling .csproj FILE, not a directory.
        rel_dir = str(Path(include.replace("\\", "/")).parent)
        target_dir = (csproj.parent / rel_dir).resolve()
        alias = None
        if target_dir.is_dir():
            for target_csproj in target_dir.glob("*.csproj"):
                alias = _read_csproj_identity(target_csproj)
                break
        alias = alias or Path(include.replace("\\", "/")).stem
        out.append(PathDependency(ECOSYSTEM_NUGET, alias, rel_dir))
    return out


def _csproj_declared_deps(csproj: Path) -> list[str]:
    try:
        tree_root = ET.fromstring(csproj.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError):
        return []
    out: list[str] = []
    for elem in tree_root.iter():
        if _pom_local_tag(elem) == _MSBUILD_PACKAGE_REFERENCE:
            include = elem.get("Include")
            if include:
                out.append(include)
    return out


# --- Swift Package Manager -----------------------------------------------------

# Package.swift is executable Swift, not data — regex-scraped like setup.py.
_SPM_PACKAGE_NAME_RE = re.compile(r"""Package\(\s*name:\s*"([^"]+)\"""")
_SPM_LOCAL_DEP_RE = re.compile(r"""\.package\(\s*path:\s*"([^"]+)\"""")
_SPM_REMOTE_DEP_RE = re.compile(
    r"""\.package\(\s*(?:name:\s*"[^"]+"\s*,\s*)?url:\s*"([^"]+)\""""
)


def _read_package_swift_name(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = _SPM_PACKAGE_NAME_RE.search(text)
    return match.group(1) if match else None


def _read_package_swift_path_deps(
    root: Path, package_swift: Path
) -> list[PathDependency]:
    try:
        text = package_swift.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[PathDependency] = []
    for match in _SPM_LOCAL_DEP_RE.finditer(text):
        rel = match.group(1)
        # SPM path deps carry no alias of their own in this syntax — peek at
        # the target's own Package.swift name, matching the Composer/NuGet
        # "resolve the target's self-declared identity" pattern.
        alias = _sibling_manifest_name(root, rel) or rel
        out.append(PathDependency(ECOSYSTEM_SWIFTPM, alias, rel))
    return out


def _package_swift_declared_deps(package_swift: Path) -> list[str]:
    try:
        text = package_swift.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[str] = []
    for match in _SPM_REMOTE_DEP_RE.finditer(text):
        url = match.group(1).rstrip("/")
        name = url.rsplit("/", 1)[-1]
        if name.endswith(".git"):
            name = name[: -len(".git")]
        if name:
            out.append(name)
    return out


# --- Docker Compose, Helm, Terraform (infra-as-code — no source-code parser --
# --- exists for these yet, so path-dependency data alone won't surface as a --
# --- resolvable cross-repo import edge without further work; still worth   --
# --- collecting so a linked "infra" repo's declared local references show  --
# --- up for a future dedicated resolution pass) -------------------------------


def _read_compose_path_deps(compose_file: Path) -> list[PathDependency]:
    data = _read_yaml_dict(compose_file)
    if data is None:
        return []
    services = data.get("services")
    if not isinstance(services, dict):
        return []
    out: list[PathDependency] = []
    for service_name, spec in services.items():
        if not isinstance(spec, dict):
            continue
        build = spec.get("build")
        context = build.get("context") if isinstance(build, dict) else build
        if isinstance(context, str) and (
            context.startswith("./") or context.startswith("../")
        ):
            out.append(PathDependency(ECOSYSTEM_DOCKER, str(service_name), context))
    return out


def _read_helm_chart_name(chart_yaml: Path) -> str | None:
    data = _read_yaml_dict(chart_yaml)
    if data is None:
        return None
    name = data.get("name")
    return name if isinstance(name, str) and name else None


def _read_helm_path_deps(chart_yaml: Path) -> list[PathDependency]:
    data = _read_yaml_dict(chart_yaml)
    if data is None:
        return []
    deps = data.get("dependencies")
    if not isinstance(deps, list):
        return []
    out: list[PathDependency] = []
    for dep in deps:
        if not isinstance(dep, dict):
            continue
        repository = dep.get("repository")
        name = dep.get("name")
        if isinstance(repository, str) and repository.startswith("file://") and name:
            out.append(
                PathDependency(ECOSYSTEM_HELM, str(name), repository[len("file://") :])
            )
    return out


# module "name" { source = "../relative/path" } — HCL isn't JSON/YAML/TOML, so
# this is a deliberately narrow regex covering the common single-line-ish
# case rather than a full HCL parser.
_TERRAFORM_MODULE_RE = re.compile(
    r"""module\s+"([^"]+)"\s*\{[^}]*?source\s*=\s*"(\.\.?/[^"]+)\"""",
    re.DOTALL,
)


def _read_terraform_path_deps(root: Path) -> list[PathDependency]:
    out: list[PathDependency] = []
    for tf_file in root.glob("*.tf"):
        try:
            text = tf_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _TERRAFORM_MODULE_RE.finditer(text):
            out.append(
                PathDependency(ECOSYSTEM_TERRAFORM, match.group(1), match.group(2))
            )
    return out


# --- External-dependency filtering -------------------------------------------


def read_declared_dependencies(root_path: str | Path) -> list[str]:
    """Read this repo's OWN manifest for its declared EXTERNAL dependencies.

    Unlike ``read_manifests``/``read_path_dependencies`` (which answer "what
    is this repo" and "what sibling does this repo point at"), this answers
    "what does this repo depend on that is NOT a sibling in this project" —
    raw material for ``is_likely_external``'s pre-filter. Best-effort: a
    mapping like Maven groupId -> Java package prefix isn't exact, so this is
    a heuristic supplement to ``is_likely_external``'s structural rules and
    bundled well-known-library list, not a source of truth on its own.

    Deliberately EXCLUDES anything also reported by ``read_path_dependencies``
    for the same root — an explicit local-path dependency (npm ``file:``,
    Cargo ``path=``, …) is precisely a potential CROSS-REPO candidate, the
    opposite of "external", even though it lives in the same manifest
    dependency section. Without this exclusion, every Tier A path-dependency
    test case would misclassify its own sibling as external before Tier A
    ever got a chance to resolve it.
    """
    root = Path(root_path)
    out: list[str] = []

    pkg_json = root / "package.json"
    if pkg_json.is_file():
        out.extend(_npm_declared_deps(pkg_json))

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        out.extend(_python_declared_deps(pyproject))

    go_mod = root / "go.mod"
    if go_mod.is_file():
        out.extend(_go_declared_deps(go_mod))

    cargo_toml = root / "Cargo.toml"
    if cargo_toml.is_file():
        out.extend(_cargo_declared_deps(cargo_toml))

    pom_xml = root / "pom.xml"
    if pom_xml.is_file():
        out.extend(_maven_declared_deps(pom_xml))

    settings_gradle = _find_gradle_settings(root)
    build_gradle = _find_gradle_build(root)
    if build_gradle is not None:
        out.extend(_gradle_declared_deps(build_gradle))
    _ = settings_gradle  # settings.gradle has no dependency declarations of its own

    composer_json = root / "composer.json"
    if composer_json.is_file():
        out.extend(_composer_declared_deps(composer_json))

    gemfile = root / "Gemfile"
    if gemfile.is_file():
        out.extend(_gemfile_declared_deps(gemfile))

    pubspec = root / "pubspec.yaml"
    if pubspec.is_file():
        out.extend(_pubspec_declared_deps(pubspec))

    for csproj in root.glob("*.csproj"):
        out.extend(_csproj_declared_deps(csproj))

    podfile = root / "Podfile"
    if podfile.is_file():
        out.extend(_podfile_declared_deps(podfile))

    package_swift = root / "Package.swift"
    if package_swift.is_file():
        out.extend(_package_swift_declared_deps(package_swift))

    path_dep_aliases = {d.alias for d in read_path_dependencies(root_path)}
    return [dep for dep in out if dep not in path_dep_aliases]


def _npm_declared_deps(pkg_json: Path) -> list[str]:
    try:
        pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(pkg, dict):
        return []
    out: list[str] = []
    for section in _NPM_DEP_SECTIONS:
        deps = pkg.get(section)
        if isinstance(deps, dict):
            out.extend(name for name in deps if isinstance(name, str) and name)
    return out


_REQUIREMENT_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")


def _parse_requirement_name(requirement: str) -> str:
    match = _REQUIREMENT_NAME_RE.match(requirement)
    return match.group(1) if match else ""


def _python_declared_deps(pyproject: Path) -> list[str]:
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    out: list[str] = []
    project = data.get("project")
    if isinstance(project, dict):
        deps = project.get("dependencies")
        if isinstance(deps, list):
            out.extend(_parse_requirement_name(d) for d in deps if isinstance(d, str))
        opt_deps = project.get("optional-dependencies")
        if isinstance(opt_deps, dict):
            for group in opt_deps.values():
                if isinstance(group, list):
                    out.extend(
                        _parse_requirement_name(d) for d in group if isinstance(d, str)
                    )
    poetry = (
        data.get("tool", {}).get("poetry")
        if isinstance(data.get("tool"), dict)
        else None
    )
    if isinstance(poetry, dict):
        deps = poetry.get("dependencies")
        if isinstance(deps, dict):
            out.extend(
                name
                for name in deps
                if isinstance(name, str) and name.lower() != "python"
            )
    return [d for d in out if d]


_GO_MOD_REQUIRE_LINE_RE = re.compile(r"^\s*require\s+(\S+)\s+\S+\s*$")
_GO_MOD_REQUIRE_BLOCK_START_RE = re.compile(r"^\s*require\s*\(\s*$")
_GO_MOD_REQUIRE_ENTRY_RE = re.compile(r"^\s*(\S+)\s+\S+\s*$")


def _go_declared_deps(go_mod: Path) -> list[str]:
    try:
        lines = go_mod.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[str] = []
    in_block = False
    for raw_line in lines:
        line = raw_line.split("//", 1)[0]
        if in_block:
            if _GO_MOD_BLOCK_END_RE.match(line):
                in_block = False
                continue
            match = _GO_MOD_REQUIRE_ENTRY_RE.match(line)
            if match:
                out.append(match.group(1))
            continue
        if _GO_MOD_REQUIRE_BLOCK_START_RE.match(line):
            in_block = True
            continue
        match = _GO_MOD_REQUIRE_LINE_RE.match(line)
        if match:
            out.append(match.group(1))
    return out


def _cargo_declared_deps(cargo_toml: Path) -> list[str]:
    try:
        data = tomllib.loads(cargo_toml.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    out: list[str] = []
    for section in _CARGO_DEP_SECTIONS:
        deps = data.get(section)
        if isinstance(deps, dict):
            out.extend(name for name in deps if isinstance(name, str) and name)
    return out


def _maven_declared_deps(pom_xml: Path) -> list[str]:
    """Maven ``<dependency><groupId>`` values — a best-effort Java package
    prefix signal (NOT 1:1: e.g. groupId ``org.liquibase`` ships package
    ``liquibase.*``, which is why ``_WELL_KNOWN_EXTERNAL_PREFIXES`` exists as
    a backstop for exactly this kind of mismatch)."""
    try:
        root = ET.fromstring(pom_xml.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError):
        return []
    out: list[str] = []
    deps_elem = _pom_child(root, "dependencies")
    if deps_elem is not None:
        for dep in _pom_children(deps_elem, "dependency"):
            group_id = _pom_child_text(dep, "groupId")
            if group_id:
                out.append(group_id)
    return out


# Every stdlib module name for the Python interpreter we're running under
# (3.10+) — always correct, zero maintenance, unlike a bundled list.
_PYTHON_STDLIB_MODULES = frozenset(getattr(sys, "stdlib_module_names", ()))

_JVM_EXTENSIONS = (".java", ".kt", ".kts", ".scala")
_GO_EXTENSIONS = (".go",)
_PYTHON_EXTENSIONS = (".py", ".pyi")
_CSHARP_EXTENSIONS = (".cs",)
_DART_EXTENSIONS = (".dart",)
_SWIFT_EXTENSIONS = (".swift",)
_OBJC_EXTENSIONS = (".m", ".mm")
_PHP_EXTENSIONS = (".php",)
_RUBY_EXTENSIONS = (".rb",)

# Apple SDK frameworks — always external for Swift `import Foundation` (whole
# raw_reference) and Objective-C `#import <Foundation/Foundation.h>` (first
# path segment of raw_reference), never a plausible sibling-repo package.
_APPLE_FRAMEWORKS = frozenset(
    {
        "Foundation",
        "UIKit",
        "SwiftUI",
        "Combine",
        "CoreData",
        "CoreGraphics",
        "CoreLocation",
        "AVFoundation",
        "MapKit",
        "WebKit",
        "StoreKit",
        "CloudKit",
        "CryptoKit",
        "Network",
        "Dispatch",
        "ObjectiveC",
        "XCTest",
        "os",
        "simd",
        "Security",
        "CoreBluetooth",
        "HealthKit",
        "Contacts",
        "EventKit",
        "Photos",
        "PhotosUI",
        "MessageUI",
        "GameKit",
        "SpriteKit",
        "SceneKit",
        "ARKit",
        "Metal",
        "MetalKit",
        "CoreImage",
        "CoreText",
        "QuartzCore",
        "CoreMotion",
        "LocalAuthentication",
        "UserNotifications",
        "WatchKit",
        "ClockKit",
        "Intents",
        "IntentsUI",
        "NaturalLanguage",
        "Vision",
        "CoreML",
        "CreateML",
        "Speech",
        "AuthenticationServices",
        "PassKit",
        "MultipeerConnectivity",
        "ExternalAccessory",
        "CoreTelephony",
        "SystemConfiguration",
        "Accelerate",
        "GLKit",
        "OpenGLES",
        "CoreAudio",
        "AudioToolbox",
        "AVKit",
        "PDFKit",
        "QuickLook",
        "Social",
        "Accounts",
        "CoreSpotlight",
        "CoreServices",
        "DeviceCheck",
    }
)

# Extremely well-known third-party library prefixes, bundled as a fast,
# always-on supplement to a repo's own declared dependencies — catches
# common libraries even when the manifest -> import-prefix mapping is
# imperfect (Maven groupId "org.liquibase" -> Java package "liquibase" is
# not derivable from any automatic heuristic). Matching also allows "/",
# "\\", or ":" as the delimiter after a prefix (not just "."), since Dart
# ("dart:async"), PHP ("Illuminate\\Support"), and Objective-C
# ("Foundation/Foundation.h") all use non-dot namespace separators.
_WELL_KNOWN_EXTERNAL_PREFIXES: tuple[str, ...] = (
    # JVM
    "liquibase",
    "org.springframework",
    "org.hibernate",
    "com.fasterxml",
    "org.apache",
    "org.slf4j",
    "com.google",
    "org.junit",
    "junit",
    "org.mockito",
    "org.testng",
    "com.zaxxer",
    "org.postgresql",
    "com.mysql",
    "org.aspectj",
    "io.swagger",
    "org.thymeleaf",
    "org.mybatis",
    "com.h2database",
    "org.json",
    "org.yaml",
    "com.squareup",
    "ch.qos.logback",
    "org.codehaus",
    # npm
    "react",
    "react-dom",
    "lodash",
    "express",
    "axios",
    "webpack",
    "typescript",
    "eslint",
    "jest",
    "vue",
    "vite",
    "rxjs",
    "core-js",
    "moment",
    "chalk",
    # Python
    "requests",
    "numpy",
    "pandas",
    "django",
    "flask",
    "boto3",
    "pytest",
    "sqlalchemy",
    "pydantic",
    "fastapi",
    "click",
    "yaml",
    "setuptools",
    "pip",
    "urllib3",
    "certifi",
    "six",
    "attrs",
    "jinja2",
    # Rust
    "serde",
    "tokio",
    "clap",
    "anyhow",
    "thiserror",
    "log",
    "reqwest",
    "rand",
    # PHP (Composer's declared vendor/package slug rarely matches the PSR-4
    # namespace prefix, e.g. "illuminate/support" -> `Illuminate\Support`, so
    # this bundled list carries the same load Maven's groupId mismatch does)
    "Illuminate",
    "Symfony",
    "Psr",
    "Doctrine",
    "GuzzleHttp",
    "Monolog",
    "PHPUnit",
    "Composer",
    "PhpParser",
    "Twig",
    "Laravel",
    "Zend",
    "Laminas",
    "Carbon",
    "Ramsey",
    "Nette",
    # Ruby (gem `require` strings are typically underscored, decoupled from
    # any Gemfile-declared-dependency matching)
    "active_support",
    "active_record",
    "action_pack",
    "action_view",
    "action_controller",
    "active_job",
    "active_model",
    "railties",
    "rails",
    "rspec",
    "rack",
    "sinatra",
    "bundler",
    "faraday",
    "nokogiri",
    "devise",
    "puma",
    "sidekiq",
    "factory_bot",
    "capybara",
    "pry",
    # Dart (published packages beyond the Flutter SDK itself, which is
    # handled structurally below via the "dart:" scheme check)
    "package:flutter",
    "package:flutter_test",
    "package:meta",
    "package:test",
)


def is_likely_external(
    raw_reference: str, *, file_path: str, declared_dependencies: list[str]
) -> bool:
    """Best-effort check: is ``raw_reference`` almost certainly a third-party
    library import that can never be a cross-repo reference?

    Combines three signals, cheapest/most-reliable first:

    1. Language-structural rules that are always correct for that file's
       extension (JDK/Kotlin/Scala namespace prefixes, Go's "no dot in the
       first path segment means standard library" convention, the actual
       Python stdlib module list — never a bundled guess).
    2. This repo's OWN manifest-declared dependencies (best-effort — a
       package-manager coordinate isn't always the source-level import
       prefix, so this can under-match but should essentially never
       over-match a real sibling).
    3. A small bundled list of extremely common third-party libraries, as a
       backstop for cases (2) can't reach (coordinate/package-prefix
       mismatches like Liquibase, or transitive dependencies never declared
       directly in this repo's own manifest).

    False negatives (an external import slipping through unfiltered) just
    mean one more harmless unresolved candidate; false positives (wrongly
    excluding a real cross-repo reference) would hide a genuine link, so
    every rule here is deliberately conservative — never used to reject an
    *already-resolved* match, only to skip attempting resolution at all.
    """
    if (
        not raw_reference
        or raw_reference.startswith(".")
        or raw_reference.startswith("/")
    ):
        return False  # relative imports are intra-repo by construction

    suffix = Path(file_path).suffix.lower()

    if suffix in _JVM_EXTENSIONS and raw_reference.startswith(
        ("java.", "javax.", "jakarta.", "kotlin.", "scala.")
    ):
        return True
    if suffix in _GO_EXTENSIONS and "." not in raw_reference.split("/", 1)[0]:
        # Go convention: a published (and thus potential cross-repo-candidate)
        # module path always starts with a domain-like segment containing a
        # dot (e.g. "github.com/..."); anything else ("fmt", "encoding/json")
        # is standard library by construction.
        return True
    if (
        suffix in _PYTHON_EXTENSIONS
        and raw_reference.split(".", 1)[0] in _PYTHON_STDLIB_MODULES
    ):
        return True
    if suffix in _CSHARP_EXTENSIONS and (
        raw_reference == "System" or raw_reference.startswith(("System.", "Microsoft."))
    ):
        return True
    if suffix in _DART_EXTENSIONS and raw_reference.startswith("dart:"):
        return True
    if suffix in _SWIFT_EXTENSIONS and raw_reference in _APPLE_FRAMEWORKS:
        return True
    if (
        suffix in _OBJC_EXTENSIONS
        and raw_reference.split("/", 1)[0] in _APPLE_FRAMEWORKS
    ):
        return True

    for dep in declared_dependencies:
        if not dep:
            continue
        if (
            raw_reference == dep
            or raw_reference.startswith(dep + ".")
            or raw_reference.startswith(dep + "/")
        ):
            return True
        normalized = dep.replace("-", "_")
        if normalized != dep and (
            raw_reference == normalized or raw_reference.startswith(normalized + ".")
        ):
            return True

    for prefix in _WELL_KNOWN_EXTERNAL_PREFIXES:
        if raw_reference == prefix:
            return True
        if raw_reference.startswith(prefix) and raw_reference[len(prefix)] in ".\\/:":
            return True

    return False
