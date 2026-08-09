"""External runtime plumbing shared by the Office document pipelines.

The pipelines share source hashing and executable discovery. PPTX template and
XLSX authoring additionally drive Node workers over JSON request files and use
``@oai/artifact-tool``. Keeping that plumbing here prevents their dependency
lookup rules from drifting apart.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import sys
from typing import Any, Final

ARTIFACT_TOOL_ENTRYPOINT_ENV: Final = "EVOFLUX_ARTIFACT_TOOL_ENTRYPOINT"
CHROMIUM_BIN_ENV: Final = "EVOFLUX_CHROMIUM_BIN"
DOCUMENT_RUNTIME_DIR_ENV: Final = "EVOFLUX_DOCUMENT_RUNTIME_DIR"
NODE_BIN_ENV: Final = "EVOFLUX_NODE_BIN"

DEFAULT_WORKER_TIMEOUT_SECONDS: Final = 300

_HASH_CHUNK_BYTES: Final = 1024 * 1024
_ARTIFACT_TOOL_PACKAGE: Final = ("node_modules", "@oai", "artifact-tool")
_DOCUMENT_RUNTIME_MANIFEST: Final = "manifest.json"


@dataclass(frozen=True, slots=True)
class DocumentRuntimePaths:
    """Resolved, relocatable paths declared by a document runtime manifest."""

    root: Path
    manifest: dict[str, Any]
    node: Path
    artifact_tool: Path
    soffice: Path
    pdftoppm: Path
    pdfinfo: Path
    chromium: Path
    fonts: Path
    fontconfig: Path


def file_sha256(path: Path) -> str:
    """Hash *path* in bounded chunks so large Office packages stay streamable."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_root() -> Path:
    """Return the EvoFlux checkout root.

    Anchored on this file at ``app/services/office/runtime.py``; update the
    index if the module moves.
    """
    return Path(__file__).resolve().parents[3]


def codex_runtime_dependencies() -> Path:
    """Return the Codex primary-runtime dependency root.

    EvoFlux does not own this layout, so callers must treat it as a last-resort
    fallback behind the environment overrides and the repository's own
    ``node_modules``. Resolved per call so tests can relocate ``HOME``.
    """
    return (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
    )


def host_binary_dirs() -> tuple[Path, ...]:
    """Return common user-level binary directories missed by desktop GUI PATHs.

    Apps launched from Finder and some Windows shortcuts inherit a much smaller
    ``PATH`` than an interactive shell. These locations let an explicitly
    installed host tool remain discoverable without copying it into EvoFlux.
    """
    if sys.platform == "darwin":
        candidates = (
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
            Path("/opt/local/bin"),
        )
    elif sys.platform == "win32":
        candidates = tuple(
            path
            for path in (
                Path(os.environ["ProgramFiles"]) / "nodejs"
                if os.environ.get("ProgramFiles")
                else None,
                Path(os.environ["LOCALAPPDATA"]) / "Programs" / "nodejs"
                if os.environ.get("LOCALAPPDATA")
                else None,
                Path(os.environ["ChocolateyInstall"]) / "bin"
                if os.environ.get("ChocolateyInstall")
                else None,
                Path(os.environ["USERPROFILE"]) / "scoop" / "shims"
                if os.environ.get("USERPROFILE")
                else None,
            )
            if path is not None
        )
    else:
        candidates = (
            Path("/usr/local/bin"),
            Path("/usr/bin"),
            Path("/snap/bin"),
        )
    return tuple(path for path in candidates if path.is_dir())


def _host_platform() -> str:
    return {
        "darwin": "darwin",
        "linux": "linux",
        "win32": "windows",
    }.get(sys.platform, sys.platform)


def _host_architecture() -> str:
    return {
        "aarch64": "arm64",
        "arm64": "arm64",
        "amd64": "x86_64",
        "x86_64": "x86_64",
    }.get(platform.machine().lower(), platform.machine().lower())


def resolve_document_runtime_root() -> Path | None:
    """Locate the bundled runtime without consulting ``PATH`` or user caches."""
    explicit = os.environ.get(DOCUMENT_RUNTIME_DIR_ENV)
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not (root / _DOCUMENT_RUNTIME_MANIFEST).is_file():
            raise RuntimeError(
                f"{DOCUMENT_RUNTIME_DIR_ENV} does not contain "
                f"{_DOCUMENT_RUNTIME_MANIFEST}: {root}"
            )
        return root

    # Packaged layout: sidecar/python/bin/python sits next to
    # sidecar/document-runtime. Walking ancestors keeps the lookup relocatable.
    executable = Path(sys.executable).resolve()
    for ancestor in executable.parents:
        candidate = ancestor / "document-runtime"
        if (candidate / _DOCUMENT_RUNTIME_MANIFEST).is_file():
            return candidate.resolve()

    # Checkout-only convenience for running a locally staged desktop bundle.
    candidate = _repo_root() / "desktop" / "sidecar-bundle" / "document-runtime"
    if (candidate / _DOCUMENT_RUNTIME_MANIFEST).is_file():
        return candidate.resolve()
    return None


def _manifest_path(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"document runtime manifest field {label} is missing")
    relative = Path(value)
    if relative.is_absolute():
        raise RuntimeError(f"document runtime manifest field {label} must be relative")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise RuntimeError(f"document runtime manifest field {label} escapes its root")
    if not resolved.is_file():
        raise RuntimeError(f"document runtime file is missing for {label}: {resolved}")
    return resolved


def resolve_document_runtime() -> DocumentRuntimePaths:
    """Load and validate the complete runtime manifest for the current host."""
    root = resolve_document_runtime_root()
    if root is None:
        raise RuntimeError(
            "The bundled EvoFlux document runtime is unavailable. "
            f"Set {DOCUMENT_RUNTIME_DIR_ENV} to a verified runtime directory."
        )
    manifest_path = root / _DOCUMENT_RUNTIME_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid document runtime manifest: {exc}") from exc
    if manifest.get("schema_version") != 2:
        raise RuntimeError(
            f"Unsupported document runtime schema: {manifest.get('schema_version')!r}"
        )
    target = manifest.get("target")
    if not isinstance(target, dict):
        raise RuntimeError("Document runtime manifest has no target")
    actual_target = (target.get("platform"), target.get("architecture"))
    expected_target = (_host_platform(), _host_architecture())
    if actual_target != expected_target:
        raise RuntimeError(
            "Document runtime target mismatch: "
            f"expected {expected_target[0]}/{expected_target[1]}, "
            f"got {actual_target[0]}/{actual_target[1]}"
        )
    components = manifest.get("components")
    if not isinstance(components, dict):
        raise RuntimeError("Document runtime manifest has no components")
    try:
        node = components["node"]
        artifact_tool = components["artifact_tool"]
        libreoffice = components["libreoffice"]
        poppler = components["poppler"]
        chromium = components["chromium"]
        fonts = components["fonts"]
    except KeyError as exc:
        raise RuntimeError(
            f"Document runtime component is missing: {exc.args[0]}"
        ) from exc
    records = {
        "node": node,
        "artifact_tool": artifact_tool,
        "libreoffice": libreoffice,
        "poppler": poppler,
        "chromium": chromium,
        "fonts": fonts,
    }
    if not all(isinstance(record, dict) for record in records.values()):
        raise RuntimeError("Document runtime component records must be objects")
    if artifact_tool.get("distribution_authorized") is not True:
        raise RuntimeError(
            "Document runtime artifact-tool is not distribution-authorized"
        )
    fonts_root_value = fonts.get("root")
    if not isinstance(fonts_root_value, str) or not fonts_root_value:
        raise RuntimeError("Document runtime font root is missing")
    fonts_root = root / fonts_root_value
    fonts_root = fonts_root.resolve()
    if not fonts_root.is_relative_to(root) or not fonts_root.is_dir():
        raise RuntimeError("Document runtime font root is invalid")
    return DocumentRuntimePaths(
        root=root,
        manifest=manifest,
        node=_manifest_path(root, node.get("executable"), "components.node.executable"),
        artifact_tool=_manifest_path(
            root,
            artifact_tool.get("entrypoint"),
            "components.artifact_tool.entrypoint",
        ),
        soffice=_manifest_path(
            root, libreoffice.get("executable"), "components.libreoffice.executable"
        ),
        pdftoppm=_manifest_path(
            root, poppler.get("pdftoppm"), "components.poppler.pdftoppm"
        ),
        pdfinfo=_manifest_path(
            root, poppler.get("pdfinfo"), "components.poppler.pdfinfo"
        ),
        chromium=_manifest_path(
            root, chromium.get("executable"), "components.chromium.executable"
        ),
        fonts=fonts_root,
        fontconfig=_manifest_path(
            root, fonts.get("fontconfig"), "components.fonts.fontconfig"
        ),
    )


def _optional_document_runtime() -> DocumentRuntimePaths | None:
    try:
        return resolve_document_runtime()
    except RuntimeError:
        if os.environ.get(DOCUMENT_RUNTIME_DIR_ENV):
            raise
        return None


def document_runtime_subprocess_env() -> dict[str, str]:
    """Environment that makes fonts and helper binaries deterministic."""
    runtime = _optional_document_runtime()
    if runtime is None:
        return {}
    path_dirs = (
        runtime.node.parent,
        runtime.soffice.parent,
        runtime.pdftoppm.parent,
        runtime.chromium.parent,
    )
    existing_path = os.environ.get("PATH", "")
    return {
        DOCUMENT_RUNTIME_DIR_ENV: str(runtime.root),
        CHROMIUM_BIN_ENV: str(runtime.chromium),
        "FONTCONFIG_FILE": str(runtime.fontconfig),
        "FONTCONFIG_PATH": str(runtime.fontconfig.parent),
        "SAL_FONTPATH": str(runtime.fonts),
        "PATH": os.pathsep.join(
            [*(str(directory) for directory in path_dirs), existing_path]
        ).rstrip(os.pathsep),
    }


def document_runtime_diagnostics() -> dict[str, Any]:
    """Return redacted runtime health and pinned component versions."""
    try:
        runtime = resolve_document_runtime()
    except RuntimeError as exc:
        return {"available": False, "error": str(exc)}
    components = runtime.manifest["components"]
    return {
        "available": True,
        "root": str(runtime.root),
        "bundle_version": runtime.manifest.get("bundle_version"),
        "payload_sha256": runtime.manifest.get("payload_sha256"),
        "target": runtime.manifest.get("target"),
        "components": {
            name: {"version": record.get("version")}
            for name, record in components.items()
        },
    }


def resolve_executable(
    env_var: str,
    names: tuple[str, ...],
    *,
    preferred_candidates: tuple[Path, ...] = (),
    fallback_dirs: tuple[Path, ...] = (),
    requirement: str,
) -> str:
    """Locate an external executable, preferring an explicit env override.

    Args:
        env_var: Environment variable holding an explicit absolute path.
        names: Candidate executable names to look up on ``PATH``, in order.
        fallback_dirs: Directories searched only after ``PATH`` misses.
        requirement: Message raised when nothing matches.

    Raises:
        RuntimeError: if no candidate resolves to an existing file.
    """
    explicit = os.environ.get(env_var)
    if explicit and Path(explicit).is_file():
        return str(Path(explicit).resolve())
    for candidate in preferred_candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    for name in names:
        if found := shutil.which(name):
            return found
    for directory in fallback_dirs:
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError(requirement)


def resolve_node_binary(*, purpose: str) -> str:
    """Return a Node executable able to run the Office workers."""
    runtime = _optional_document_runtime()
    return resolve_executable(
        NODE_BIN_ENV,
        ("node",),
        preferred_candidates=(runtime.node,) if runtime else (),
        fallback_dirs=(
            *host_binary_dirs(),
            codex_runtime_dependencies() / "node" / "bin",
        ),
        requirement=(
            f"Node.js 20+ is required for {purpose}. "
            f"Set {NODE_BIN_ENV} to a Node 20+ executable."
        ),
    )


def resolve_chromium_binary(*, purpose: str) -> str:
    """Return the bundled headless Chromium used for deterministic HTML shells."""
    runtime = _optional_document_runtime()
    application_candidates: tuple[Path, ...] = ()
    if sys.platform == "darwin":
        application_candidates = (
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path(
                "/Applications/Google Chrome for Testing.app/Contents/MacOS/"
                "Google Chrome for Testing"
            ),
        )
    elif sys.platform == "win32":
        application_candidates = tuple(
            root / "Google" / "Chrome" / "Application" / "chrome.exe"
            for root in (
                Path(value)
                for value in (
                    os.environ.get("ProgramFiles"),
                    os.environ.get("ProgramFiles(x86)"),
                    os.environ.get("LOCALAPPDATA"),
                )
                if value
            )
        )
    return resolve_executable(
        CHROMIUM_BIN_ENV,
        (
            "chromium",
            "chromium-browser",
            "google-chrome",
            "google-chrome-stable",
            "chrome",
            "chrome.exe",
        ),
        preferred_candidates=(
            *((runtime.chromium,) if runtime else ()),
            *application_candidates,
        ),
        fallback_dirs=host_binary_dirs(),
        requirement=(
            f"Chromium is required for {purpose}. "
            f"Set {CHROMIUM_BIN_ENV} to a compatible Chromium executable."
        ),
    )


def resolve_artifact_tool(
    workspace_root: Path, *, purpose: str, hint: str = ""
) -> Path:
    """Return the built ``@oai/artifact-tool`` entrypoint.

    Args:
        workspace_root: Active agent workspace, searched first.
        purpose: Pipeline description used in the failure message.
        hint: Extra guidance appended to the failure message.

    Raises:
        RuntimeError: if no built entrypoint exists.
    """
    explicit = os.environ.get(ARTIFACT_TOOL_ENTRYPOINT_ENV)
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    runtime = _optional_document_runtime()
    if runtime:
        candidates.append(runtime.artifact_tool)
    package_roots = (
        workspace_root.joinpath(*_ARTIFACT_TOOL_PACKAGE),
        _repo_root().joinpath(*_ARTIFACT_TOOL_PACKAGE),
        codex_runtime_dependencies().joinpath("node", *_ARTIFACT_TOOL_PACKAGE),
    )
    for package_root in package_roots:
        candidates.append(package_root / "dist" / "node" / "artifact_tool.mjs")
        candidates.append(package_root / "dist" / "artifact_tool.mjs")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    message = (
        f"@oai/artifact-tool is required for {purpose}. "
        f"Set {ARTIFACT_TOOL_ENTRYPOINT_ENV} to its built artifact_tool.mjs."
    )
    raise RuntimeError(f"{message} {hint}".strip())


@dataclass(frozen=True, slots=True)
class NodeWorkerRuntime:
    """One pipeline's Node worker, invoked over a JSON request file.

    Attributes:
        worker: Absolute path to the ``.mjs`` entrypoint.
        label: Short pipeline name used to prefix error messages.
        purpose: Longer description used when a runtime dependency is missing.
        requirement_hint: Extra guidance appended to dependency failures.
    """

    worker: Path
    label: str
    purpose: str
    requirement_hint: str = ""

    async def run(
        self,
        action: str,
        request: dict[str, Any],
        *,
        workspace_root: Path,
        work_dir: Path,
        timeout_seconds: int = DEFAULT_WORKER_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Run *action* and return the worker's JSON response object.

        The request is handed over as a file rather than stdin so the payload
        stays inspectable in the work directory after a failure.

        Raises:
            RuntimeError: on timeout, non-zero exit, or unparseable output.
        """
        work_dir.mkdir(parents=True, exist_ok=True)
        request_path = work_dir / f"{action}-request.json"
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        env = os.environ.copy()
        env.update(document_runtime_subprocess_env())
        env[ARTIFACT_TOOL_ENTRYPOINT_ENV] = str(
            resolve_artifact_tool(
                workspace_root,
                purpose=self.purpose,
                hint=self.requirement_hint,
            )
        )
        process = await asyncio.create_subprocess_exec(
            resolve_node_binary(purpose=self.purpose),
            str(self.worker),
            action,
            str(request_path),
            cwd=str(workspace_root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(
                f"{self.label} {action} exceeded {timeout_seconds} seconds"
            ) from None
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(message or f"{self.label} worker failed ({action})")
        for line in reversed(stdout.decode("utf-8", errors="replace").splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise RuntimeError(f"{self.label} worker returned invalid JSON")


__all__ = [
    "ARTIFACT_TOOL_ENTRYPOINT_ENV",
    "CHROMIUM_BIN_ENV",
    "DEFAULT_WORKER_TIMEOUT_SECONDS",
    "DOCUMENT_RUNTIME_DIR_ENV",
    "DocumentRuntimePaths",
    "NODE_BIN_ENV",
    "NodeWorkerRuntime",
    "codex_runtime_dependencies",
    "document_runtime_diagnostics",
    "document_runtime_subprocess_env",
    "file_sha256",
    "host_binary_dirs",
    "resolve_artifact_tool",
    "resolve_chromium_binary",
    "resolve_document_runtime",
    "resolve_document_runtime_root",
    "resolve_executable",
    "resolve_node_binary",
]
