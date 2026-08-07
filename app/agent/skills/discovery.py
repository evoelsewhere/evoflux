"""Skill root discovery and metadata parsing.

The loader is deliberately metadata-only. It never returns the ``SKILL.md``
body, which keeps discovery cheap and prevents accidental eager prompt
injection. Runtime activation lives in :mod:`app.agent.skills.activation`.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import yaml
from loguru import logger

from app.agent.builtin_skills.catalog import bundled_skill_modes
from app.agent.skills.models import SkillDiagnostic, SkillRecord
from app.core.skill_scope import (
    SKILL_SCOPE_FILENAME,
    read_skill_modes_with_diagnostic,
)
from app.core.skill_settings import (
    SkillRuntimeSettings,
    read_skill_runtime_settings_snapshot,
    skill_settings_id,
    skill_settings_signature,
)


MAX_DISCOVERY_DEPTH = 6
MAX_DISCOVERY_DIRECTORIES = 2_000
MAX_DISCOVERY_ENTRIES = 20_000
MAX_DESCRIPTION_CHARS = 1_024
MAX_SKILL_FILE_BYTES = 512 * 1024
MAX_OPENAI_METADATA_BYTES = 256 * 1024
MAX_DEPENDENCY_RECORDS = 64
RECOMMENDED_SKILL_LINES = 500
OPENAI_INTERFACE_FIELD_LIMITS = {
    "display_name": 128,
    "short_description": 1_024,
    "default_prompt": 4_096,
    "icon_small": 1_024,
    "icon_large": 1_024,
    "brand_color": 64,
}
_PORTABLE_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LEGACY_NAME_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*$"
)
_RESOURCE_DIR_NAMES = {
    "agents",
    "assets",
    "evals",
    "evaluations",
    "examples",
    "reference",
    "references",
    "scripts",
    "templates",
}


def _bounded_directory_entries(
    directory: Path,
    *,
    limit: int,
) -> tuple[list[tuple[Path, bool, bool]], bool]:
    """Read at most *limit* entries and return a deterministically sorted batch.

    ``Path.iterdir()``, ``list(scandir(...))``, and ``os.walk`` all materialize a
    complete wide directory before callers can apply a limit. Project skill
    roots are repository-controlled, so enforce the cap while consuming the
    scandir iterator. The boolean reports that at least one entry was omitted.
    """

    if limit <= 0:
        return [], True
    entries: list[tuple[Path, bool, bool]] = []
    truncated = False
    try:
        with os.scandir(directory) as iterator:
            for entry in iterator:
                if len(entries) >= limit:
                    truncated = True
                    break
                try:
                    is_symlink = entry.is_symlink()
                    is_directory = entry.is_dir(follow_symlinks=True)
                except OSError:
                    is_symlink = False
                    is_directory = False
                entries.append((Path(entry.path), is_directory, is_symlink))
    except OSError:
        return [], False
    entries.sort(key=lambda item: item[0].name)
    return entries, truncated


def _bounded_bundle_walk(
    directory: Path,
    *,
    max_entries: int | None = None,
) -> Iterator[tuple[Path, list[Path], list[Path]]]:
    """Yield a bounded, deterministic bundle tree without following symlinks."""

    if max_entries is None:
        max_entries = MAX_DISCOVERY_ENTRIES
    stack = [directory]
    entries_seen = 0
    while stack:
        current = stack.pop()
        remaining = max_entries - entries_seen
        if remaining <= 0:
            logger.warning(
                "skill_bundle_entry_limit root={} limit={}", directory, max_entries
            )
            return
        entries, truncated = _bounded_directory_entries(current, limit=remaining)
        entries_seen += len(entries)
        directories = [
            path
            for path, is_directory, is_symlink in entries
            if is_directory and not is_symlink and not path.name.startswith(".")
        ]
        files = [
            path for path, is_directory, _is_symlink in entries if not is_directory
        ]
        yield current, directories, files
        if truncated:
            logger.warning(
                "skill_bundle_entry_limit root={} limit={}", directory, max_entries
            )
            return
        stack.extend(reversed(directories))


def builtin_skills_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "builtin_skills"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a portable ``SKILL.md`` into YAML metadata and Markdown body.

    A missing frontmatter block remains a recoverable validation problem:
    callers receive an empty mapping and can surface a precise diagnostic.
    Malformed YAML is allowed to raise ``yaml.YAMLError`` so one broken bundle
    can be marked invalid without hiding the rest of the catalog.
    """

    match = re.match(
        r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)$",
        text,
        re.DOTALL,
    )
    if not match:
        return {}, text.strip()
    try:
        loaded = yaml.safe_load(match.group(1))
    except RecursionError as exc:
        raise ValueError("Frontmatter nesting is too deep.") from exc
    if loaded is None:
        metadata: dict[str, Any] = {}
    elif not isinstance(loaded, dict):
        raise ValueError("Frontmatter must be a YAML mapping.")
    else:
        metadata = loaded
    return metadata, match.group(2).strip()


def _repo_ancestors(start: Path) -> list[Path]:
    """Return *start* through its nearest Git root, deepest first."""

    resolved = start.resolve()
    chain: list[Path] = []
    current = resolved
    while True:
        chain.append(current)
        if (current / ".git").exists():
            break
        if current.parent == current:
            # Do not scan arbitrary ancestors when the selected workspace is
            # not a repository. The workspace itself is the trust boundary.
            return [resolved]
        current = current.parent
    return chain


def standard_skill_roots(
    *,
    workspace_roots: Sequence[Path],
    evoflux_global: Path,
) -> list[Path]:
    """Build the deterministic Codex/Claude-compatible discovery roots.

    Project roots precede user/admin/bundled roots. EvoFlux-native and legacy
    compatibility roots are retained, while ``.agents/skills`` is the portable
    Agent Skills location and ``.claude/skills`` enables safe bundle reuse.
    """

    roots: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = os.path.normcase(str(path.absolute()))
        if key not in seen:
            seen.add(key)
            roots.append(path)

    for workspace in workspace_roots:
        for ancestor in _repo_ancestors(workspace):
            add(ancestor / ".evoflux" / "skills")
            add(ancestor / ".agents" / "skills")
            add(ancestor / ".claude" / "skills")
            add(ancestor / ".opencode" / "skills")

    add(evoflux_global)
    add(Path.home() / ".agents" / "skills")
    add(Path.home() / ".claude" / "skills")
    add(Path.home() / ".config" / "opencode" / "skills")
    add(Path("/etc/codex/skills"))
    add(builtin_skills_dir())
    return roots


def _walk_skill_paths(directory: Path) -> Iterator[tuple[Path, str]]:
    """Yield bounded skill files without descending into bundle resources."""

    if not directory.is_dir():
        return

    visited_targets: set[str] = set()
    root_entries, root_truncated = _bounded_directory_entries(
        directory, limit=MAX_DISCOVERY_ENTRIES
    )
    entries_seen = len(root_entries)
    stack: list[tuple[Path, int]] = [
        (path, 1)
        for path, is_directory, _is_symlink in reversed(root_entries)
        if is_directory and not path.name.startswith(".")
    ]
    directories_seen = 0
    traversal_exhausted = root_truncated
    if root_truncated:
        logger.warning(
            "skill_discovery_entry_limit root={} limit={}",
            directory,
            MAX_DISCOVERY_ENTRIES,
        )

    while stack:
        current, depth = stack.pop()
        directories_seen += 1
        if directories_seen > MAX_DISCOVERY_DIRECTORIES:
            logger.warning(
                "skill_discovery_directory_limit root={} limit={}",
                directory,
                MAX_DISCOVERY_DIRECTORIES,
            )
            return
        try:
            target_key = os.path.normcase(str(current.resolve()))
        except OSError:
            continue
        if target_key in visited_targets:
            continue
        visited_targets.add(target_key)

        skill_file = current / "SKILL.md"
        if skill_file.is_file():
            stem = current.relative_to(directory).as_posix()
            yield skill_file, stem

        if depth >= MAX_DISCOVERY_DEPTH:
            continue
        if traversal_exhausted:
            continue
        remaining = MAX_DISCOVERY_ENTRIES - entries_seen
        entries, truncated = _bounded_directory_entries(current, limit=remaining)
        entries_seen += len(entries)
        children = [
            path
            for path, is_directory, _is_symlink in reversed(entries)
            if is_directory
            and not path.name.startswith(".")
            and path.name not in _RESOURCE_DIR_NAMES
        ]
        if truncated:
            traversal_exhausted = True
            logger.warning(
                "skill_discovery_entry_limit root={} limit={}",
                directory,
                MAX_DISCOVERY_ENTRIES,
            )
        stack.extend((child, depth + 1) for child in children)


def _path_contains_symlink(path: Path, root: Path) -> bool:
    # ``relative_to`` below only visits descendants. Check the discovery root
    # itself first so a root symlink cannot make every bundle appear editable.
    try:
        if root.absolute().is_symlink():
            return True
    except OSError:
        return True
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return True
    current = root.absolute()
    for part in relative.parts:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def _source_for_root(root: Path) -> str:
    resolved = root.absolute()
    builtin = builtin_skills_dir().absolute()
    if resolved == builtin:
        return "builtin"
    if resolved == Path("/etc/codex/skills"):
        return "admin-codex"
    if resolved == (Path.home() / ".agents" / "skills").absolute():
        return "global-agents"
    if resolved == (Path.home() / ".claude" / "skills").absolute():
        return "global-claude"
    if resolved == (Path.home() / ".config" / "opencode" / "skills").absolute():
        return "global-opencode"
    parts = resolved.parts
    if len(parts) >= 2 and parts[-2:] == (".agents", "skills"):
        return "project-agents"
    if len(parts) >= 2 and parts[-2:] == (".claude", "skills"):
        return "project-claude"
    if len(parts) >= 2 and parts[-2:] == (".opencode", "skills"):
        return "project-opencode"
    if len(parts) >= 2 and parts[-2:] == (".evoflux", "skills"):
        return "project-EvoFlux"
    try:
        from app.core.config import settings

        if resolved == Path(settings.SKILLS_DIR).absolute():
            return "global-EvoFlux"
    except Exception:
        pass
    return "custom"


def _count_resources(skill_dir: Path) -> int:
    count = 0
    for _base, _directories, files in _bounded_bundle_walk(skill_dir):
        for path in files:
            relative = path.relative_to(skill_dir).as_posix()
            if relative in {"SKILL.md", SKILL_SCOPE_FILENAME} or path.is_symlink():
                continue
            count += 1
            if count >= MAX_DISCOVERY_ENTRIES:
                return count
    return count


def _render_metadata_tokens(text: str, skill_dir: Path) -> str:
    """Expand only EvoFlux's documented path placeholders in metadata."""

    if not text:
        return text
    try:
        from app.core.config import settings

        values = {
            "EVOFLUX_CONFIG_DIR": settings.EVOFLUX_CONFIG_DIR,
            "AGENTS_DIR": settings.AGENTS_DIR,
            "SKILLS_DIR": settings.SKILLS_DIR,
            "SKILL_DIR": str(skill_dir.resolve()),
        }
    except Exception:
        return text
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def _read_openai_metadata(
    record: SkillRecord,
) -> None:
    metadata_path = record.skill_dir / "agents" / "openai.yaml"
    if not metadata_path.is_file():
        return
    try:
        size = metadata_path.stat().st_size
        if size > MAX_OPENAI_METADATA_BYTES:
            record.add_diagnostic(
                "openai-metadata-too-large",
                "agents/openai.yaml is "
                f"{size} bytes; metadata is not read above the "
                f"{MAX_OPENAI_METADATA_BYTES}-byte limit.",
            )
            return
        with metadata_path.open("rb") as handle:
            payload = handle.read(MAX_OPENAI_METADATA_BYTES + 1)
        if len(payload) > MAX_OPENAI_METADATA_BYTES:
            record.add_diagnostic(
                "openai-metadata-too-large",
                "agents/openai.yaml changed while being read and now exceeds "
                f"the {MAX_OPENAI_METADATA_BYTES}-byte limit.",
            )
            return
        raw = yaml.safe_load(payload.decode("utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError, RecursionError) as exc:
        record.add_diagnostic(
            "invalid-openai-metadata",
            f"agents/openai.yaml could not be parsed: {exc}",
        )
        return
    if not isinstance(raw, dict):
        record.add_diagnostic(
            "invalid-openai-metadata",
            "agents/openai.yaml must contain a YAML mapping.",
        )
        return

    interface = raw.get("interface") or {}
    if not isinstance(interface, dict):
        record.add_diagnostic(
            "invalid-openai-interface",
            "agents/openai.yaml interface must be a mapping.",
        )
        interface = {}
    for key in ("display_name", "short_description"):
        if (
            not isinstance(interface.get(key), str)
            or not interface.get(key, "").strip()
        ):
            record.add_diagnostic(
                "missing-openai-interface-field",
                f"agents/openai.yaml interface.{key} is required when the file exists.",
            )
    for key, limit in OPENAI_INTERFACE_FIELD_LIMITS.items():
        value = interface.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            record.add_diagnostic(
                "invalid-openai-interface-field",
                f"agents/openai.yaml interface.{key} must be a string.",
            )
            continue
        if len(value) > limit:
            record.add_diagnostic(
                "openai-interface-field-too-long",
                f"agents/openai.yaml interface.{key} exceeds {limit} characters.",
            )
            continue
        setattr(record, key, value.strip() or None)

    policy = raw.get("policy") or {}
    if not isinstance(policy, dict):
        record.add_diagnostic(
            "invalid-openai-policy",
            "agents/openai.yaml policy must be a mapping.",
        )
    elif "allow_implicit_invocation" in policy:
        implicit = policy["allow_implicit_invocation"]
        if isinstance(implicit, bool):
            record.allow_implicit_invocation = implicit
        else:
            record.add_diagnostic(
                "invalid-openai-policy",
                "policy.allow_implicit_invocation must be a boolean.",
            )

    dependencies = raw.get("dependencies") or {}
    if not isinstance(dependencies, dict):
        record.add_diagnostic(
            "invalid-openai-dependencies",
            "agents/openai.yaml dependencies must be a mapping.",
        )
    else:
        tools = dependencies.get("tools") or []
        if not isinstance(tools, list):
            record.add_diagnostic(
                "invalid-openai-dependencies",
                "dependencies.tools must be a list of mappings.",
            )
        else:
            normalized_tools: list[dict[str, str]] = []
            for index, item in enumerate(tools[:MAX_DEPENDENCY_RECORDS]):
                if not isinstance(item, dict):
                    record.add_diagnostic(
                        "invalid-openai-dependency",
                        f"dependencies.tools[{index}] must be a mapping.",
                    )
                    continue
                dependency_type = item.get("type")
                value = item.get("value")
                if (
                    not isinstance(dependency_type, str)
                    or not dependency_type.strip()
                    or len(dependency_type.strip()) > 64
                    or not isinstance(value, str)
                    or not value.strip()
                    or len(value.strip()) > MAX_DESCRIPTION_CHARS
                ):
                    record.add_diagnostic(
                        "invalid-openai-dependency",
                        f"dependencies.tools[{index}] requires bounded string fields type and value.",
                    )
                    continue
                normalized: dict[str, str] = {
                    "type": " ".join(dependency_type.split()),
                    "value": " ".join(value.split()),
                }
                valid = True
                for key, limit in (
                    ("description", MAX_DESCRIPTION_CHARS),
                    ("transport", 64),
                    ("command", MAX_DESCRIPTION_CHARS),
                    ("url", MAX_DESCRIPTION_CHARS),
                ):
                    raw_value = item.get(key)
                    if raw_value is None:
                        continue
                    if not isinstance(raw_value, str) or len(raw_value.strip()) > limit:
                        record.add_diagnostic(
                            "invalid-openai-dependency",
                            f"dependencies.tools[{index}].{key} must be a bounded string.",
                        )
                        valid = False
                        break
                    if raw_value.strip():
                        normalized[key] = " ".join(raw_value.split())
                if valid:
                    normalized_tools.append(normalized)
            if len(tools) > MAX_DEPENDENCY_RECORDS:
                record.add_diagnostic(
                    "openai-dependencies-truncated",
                    f"Only the first {MAX_DEPENDENCY_RECORDS} tool dependencies are cataloged.",
                )
            record.dependencies = tuple(normalized_tools)


def _build_record(
    root: Path,
    skill_file: Path,
    stem: str,
) -> SkillRecord:
    source = _source_for_root(root)
    symlinked = skill_file.is_symlink() or _path_contains_symlink(
        skill_file.parent, root
    )
    is_builtin = root.absolute() == builtin_skills_dir().absolute()
    if is_builtin:
        modes = bundled_skill_modes(stem)
        scope_diagnostic = None
    else:
        modes, scope_diagnostic = read_skill_modes_with_diagnostic(skill_file.parent)
    fallback_name = stem
    record = SkillRecord(
        name=fallback_name,
        description="",
        skill_file=skill_file,
        root=root,
        source=source,
        modes=tuple(modes),
        editable=source not in {"builtin", "admin-codex"} and not symlinked,
        symlinked=symlinked,
        settings_id=skill_settings_id(source=source, root=root, stem=stem),
    )
    if scope_diagnostic:
        record.add_diagnostic("invalid-skill-scope", scope_diagnostic)

    try:
        size = skill_file.stat().st_size
        if size > MAX_SKILL_FILE_BYTES:
            record.add_diagnostic(
                "skill-file-too-large",
                f"SKILL.md is {size} bytes; the runtime limit is {MAX_SKILL_FILE_BYTES} bytes.",
                severity="error",
            )
            return record
        with skill_file.open("rb") as handle:
            payload = handle.read(MAX_SKILL_FILE_BYTES + 1)
        if len(payload) > MAX_SKILL_FILE_BYTES:
            record.add_diagnostic(
                "skill-file-too-large",
                "SKILL.md changed while being read and now exceeds "
                f"the {MAX_SKILL_FILE_BYTES}-byte runtime limit.",
                severity="error",
            )
            return record
        text = payload.decode("utf-8")
        metadata, body = parse_frontmatter(text)
    except (OSError, UnicodeError, yaml.YAMLError, ValueError, RecursionError) as exc:
        record.add_diagnostic(
            "invalid-skill-file",
            f"SKILL.md could not be parsed: {exc}",
            severity="error",
        )
        return record

    if not body:
        record.add_diagnostic(
            "empty-body",
            "SKILL.md instructions cannot be empty.",
            severity="error",
        )
    body_lines = len(body.splitlines())
    if body_lines > RECOMMENDED_SKILL_LINES:
        record.add_diagnostic(
            "skill-body-long",
            f"SKILL.md has {body_lines} body lines; keep it near {RECOMMENDED_SKILL_LINES} and move conditional detail to references.",
        )

    raw_name = metadata.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        record.name = raw_name.strip()
    else:
        record.add_diagnostic(
            "missing-name",
            "SKILL.md frontmatter requires a non-empty name.",
            severity="error",
        )

    raw_description = metadata.get("description")
    if isinstance(raw_description, str) and raw_description.strip():
        record.description = _render_metadata_tokens(
            raw_description.strip(), record.skill_dir
        )
    else:
        record.add_diagnostic(
            "missing-description",
            "SKILL.md frontmatter requires a non-empty description.",
            severity="error",
        )

    if len(record.name) > 64 or not _LEGACY_NAME_RE.fullmatch(record.name):
        record.add_diagnostic(
            "invalid-name",
            "Skill name must be 1–64 path-safe characters.",
            severity="error",
        )
    elif not _PORTABLE_NAME_RE.fullmatch(record.name):
        record.add_diagnostic(
            "legacy-name",
            "Name is accepted for compatibility but is not portable Agent Skills format (lowercase letters, digits, and hyphens).",
        )

    directory_name = skill_file.parent.name
    if record.name != directory_name:
        # Existing EvoFlux/opencode nested skills historically used
        # ``parent/child``. Keep them usable, but make the portability problem
        # visible instead of silently accepting it.
        if record.name != stem:
            record.add_diagnostic(
                "name-directory-mismatch",
                f"Frontmatter name '{record.name}' does not match directory '{directory_name}'.",
                severity="error",
            )
        else:
            record.add_diagnostic(
                "nested-legacy-skill",
                "Nested slash names are an EvoFlux compatibility extension; portable Agent Skills use the leaf directory name.",
            )

    if len(record.description) > MAX_DESCRIPTION_CHARS:
        record.add_diagnostic(
            "description-too-long",
            f"Description exceeds the {MAX_DESCRIPTION_CHARS}-character Agent Skills limit.",
            severity="error",
        )

    disable_model = metadata.get("disable-model-invocation")
    if isinstance(disable_model, bool) and disable_model:
        record.allow_implicit_invocation = False
    user_invocable = metadata.get("user-invocable")
    if isinstance(user_invocable, bool):
        record.user_invocable = user_invocable

    _read_openai_metadata(record)
    record.resource_count = _count_resources(record.skill_dir)
    return record


def _finalize_runtime_settings(
    record: SkillRecord,
    *,
    runtime_settings: dict[str, SkillRuntimeSettings],
    settings_diagnostics: dict[str, str],
) -> SkillRecord:
    """Apply the final user layer to every record, including early failures."""

    settings_diagnostic = settings_diagnostics.get(record.settings_id)
    if settings_diagnostic:
        record.add_diagnostic("invalid-runtime-settings", settings_diagnostic)
    runtime_override = runtime_settings.get(record.settings_id)
    if runtime_override is not None:
        record.modes = runtime_override.modes
        record.allow_implicit_invocation = runtime_override.allow_implicit_invocation
        record.user_invocable = runtime_override.user_invocable
        record.settings_overridden = True
    # Runtime preferences cannot make an unloadable bundle usable. Keep the
    # effective values observable, but disable UI/API mutation until the
    # underlying skill validates so Save can never silently partially apply.
    record.settings_editable = record.valid
    return record


def skills_tree_signature(directory: Path) -> int:
    """Return a bounded mtime fingerprint for catalog and bundle mutations."""

    try:
        maximum = directory.stat().st_mtime_ns
    except OSError:
        return 0
    for base, _directories, files in _bounded_bundle_walk(directory):
        try:
            maximum = max(maximum, base.stat().st_mtime_ns)
        except OSError:
            pass
        for path in files:
            if path.name not in {"SKILL.md", "openai.yaml", SKILL_SCOPE_FILENAME}:
                continue
            try:
                maximum = max(maximum, path.stat().st_mtime_ns)
            except OSError:
                pass
    return maximum


@lru_cache(maxsize=32)
def discover_skill_records_cached(
    directories: tuple[str, ...],
    signature: int | tuple[int, ...],
) -> dict[str, SkillRecord]:
    """Discover one precedence-ordered set of roots; first valid identity wins."""

    del signature  # cache-key only
    runtime_settings, settings_diagnostics = read_skill_runtime_settings_snapshot()
    selected: dict[str, SkillRecord] = {}
    for directory_string in directories:
        root = Path(directory_string)
        if not root.is_dir():
            continue
        try:
            candidates = _walk_skill_paths(root)
            for skill_file, stem in candidates:
                record = _finalize_runtime_settings(
                    _build_record(root, skill_file, stem),
                    runtime_settings=runtime_settings,
                    settings_diagnostics=settings_diagnostics,
                )
                previous = selected.get(record.name)
                if previous is None:
                    selected[record.name] = record
                    continue
                shadowed = str(record.skill_file)
                previous.shadowed_paths.append(shadowed)
                previous.alternates.append(record)
                previous.add_diagnostic(
                    "shadowed-duplicate",
                    f"A lower-precedence skill with the same name was ignored: {shadowed}",
                )
        except OSError as exc:
            logger.warning("skill_discovery_root_failed root={} error={}", root, exc)
    return selected


def discover_skill_records(roots: Iterable[Path]) -> dict[str, SkillRecord]:
    existing = [root for root in roots if root.is_dir()]
    if not existing:
        return {}
    directories = tuple(str(root) for root in existing)
    signature = (
        *(skills_tree_signature(root) for root in existing),
        *skill_settings_signature(),
    )
    return discover_skill_records_cached(directories, signature)


def select_skill_records_for_mode(
    records: dict[str, SkillRecord], mode: str
) -> dict[str, SkillRecord]:
    """Choose the highest-precedence valid candidate available in *mode*.

    Mode filtering must happen across collision candidates, not after a global
    first-wins projection; otherwise an out-of-mode project skill can hide a
    usable user/bundled skill with the same name.
    """

    resolved = "coding" if mode == "coding" else "work"
    selected: dict[str, SkillRecord] = {}
    for name, winner in records.items():
        candidates = [winner, *winner.alternates]
        match = next(
            (
                candidate
                for candidate in candidates
                if candidate.valid and resolved in candidate.modes
            ),
            None,
        )
        if match is not None:
            selected[name] = match
    return selected


def list_skill_resources(skill_dir: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    """Return a safe, bounded resource manifest without following symlinks."""

    resources: list[dict[str, Any]] = []
    for _base, _directories, files in _bounded_bundle_walk(skill_dir):
        for path in files:
            relative = path.relative_to(skill_dir).as_posix()
            if relative in {"SKILL.md", SKILL_SCOPE_FILENAME} or path.is_symlink():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            resources.append({"path": relative, "size": size})
            if len(resources) >= limit:
                return resources
    resources.sort(key=lambda item: str(item["path"]))
    return resources


__all__ = [
    "MAX_DESCRIPTION_CHARS",
    "MAX_DEPENDENCY_RECORDS",
    "MAX_OPENAI_METADATA_BYTES",
    "OPENAI_INTERFACE_FIELD_LIMITS",
    "MAX_SKILL_FILE_BYTES",
    "RECOMMENDED_SKILL_LINES",
    "SkillDiagnostic",
    "SkillRecord",
    "builtin_skills_dir",
    "discover_skill_records",
    "discover_skill_records_cached",
    "list_skill_resources",
    "parse_frontmatter",
    "skills_tree_signature",
    "select_skill_records_for_mode",
    "standard_skill_roots",
    "_walk_skill_paths",
]
