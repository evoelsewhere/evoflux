"""Skill loader tool — lets agents dynamically load skill instructions.

Skills live in directory roots using the layout
``skills/{skill_name}/SKILL.md``.  Each ``SKILL.md`` has YAML frontmatter
(name, description) followed by a markdown body. Extra files (e.g.
``creating.md``, ``reference/``) may sit alongside ``SKILL.md`` for the
agent to read separately via file tools.

The ``load_skill`` tool reads the skill file and returns its content
so the LLM can apply the instructions in subsequent reasoning.
"""

from __future__ import annotations

import asyncio
import json
import re
import textwrap
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml

from loguru import logger
from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.tools.registry import InjectedArg, tool


def _default_skills_dir() -> Path:
    from app.core.config import settings

    return Path(settings.SKILLS_DIR)


_SKILLS_DIR: Path = _default_skills_dir()


def _project_root() -> Path:
    """Return the active project root for project-local skill discovery."""
    try:
        return get_sandbox().workspace_root
    except Exception:
        return Path.cwd()


def _iter_skill_roots() -> list[Path]:
    """Roots scanned by discovery, in precedence order.

    Mirrors the slash-command precedence so a user's curated library
    works in both tools:

    1. ``{workspace}/.evoflux/skills/``  (project, EvoFlux-native)
    2. ``{workspace}/.opencode/skills/``    (project, opencode reuse)
    3. ``_SKILLS_DIR``                     (global, EvoFlux — typically
                                             ``{EVOFLUX_CONFIG_DIR}/skills``)
    4. ``~/.config/opencode/skills/``      (global, opencode reuse)
    5. bundled EvoFlux skills           (read-only fallback)

    Earlier entries win on a name collision. ``_SKILLS_DIR`` is
    referenced indirectly (via the module-level binding) so existing
    tests that monkeypatch it keep working.
    """
    project_root = _project_root()
    return [
        project_root / ".evoflux" / "skills",
        project_root / ".opencode" / "skills",
        _SKILLS_DIR,
        Path.home() / ".config" / "opencode" / "skills",
        _builtin_skills_dir(),
    ]


def _builtin_skills_dir() -> Path:
    """Directory containing bundled read-only EvoFlux skills."""
    return Path(__file__).resolve().parents[2] / "builtin_skills"


def _render_tokens(text: str, *, skill_dir: Path | None = None) -> str:
    """Replace ``{EVOFLUX_CONFIG_DIR}`` / ``{SKILLS_DIR}`` / ``{AGENTS_DIR}`` /
    ``{SKILL_DIR}`` placeholders so the agent sees concrete paths it can
    hand straight to its file and shell tools.

    Only the four names below are substituted — anything else inside
    braces (JSON examples, format strings) is left untouched.
    """
    if not text:
        return text
    # Lazy import matches the existing convention in this module
    # (see ``_default_skills_dir``) — builtin tools avoid pulling
    # ``settings`` at import time.
    from app.core.config import settings

    tokens = {
        "EVOFLUX_CONFIG_DIR": settings.EVOFLUX_CONFIG_DIR,
        "AGENTS_DIR": settings.AGENTS_DIR,
        "SKILLS_DIR": settings.SKILLS_DIR,
    }
    if skill_dir is not None:
        tokens["SKILL_DIR"] = str(skill_dir.resolve())
    for name, value in tokens.items():
        text = text.replace("{" + name + "}", value)
    return text


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body.

    Returns ``(metadata_dict, body_str)``.  If no frontmatter is
    found, metadata is empty and body is the full text.
    """
    match = re.match(
        r"^---\s*\n(.*?)\n---\s*\n(.*)$",
        text,
        re.DOTALL,
    )
    if not match:
        return {}, text.strip()
    meta = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).strip()
    return meta, body


def extract_triggers(skill_dir: Path) -> list[str]:
    """Extract trigger keywords from a skill's description.

    Explicit ``Triggers on`` / ``Triggers include`` / ``Trigger when`` phrases
    in the description define automatic-routing terms. Other description prose
    is never interpreted as routing metadata.

    Returns a de-duplicated list of lowercase keyword strings.
    """
    skill_file = skill_dir / "SKILL.md"
    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError:
        return []
    meta, _ = _parse_frontmatter(text)
    description = meta.get("description", "")
    if not isinstance(description, str) or not description:
        return []

    triggers: list[str] = []
    for match in re.finditer(
        r"Trigger[s]?\s+(?:on|include|for|when)(?=\s|:|-)\s*[:\-]?\s*",
        description,
        re.IGNORECASE,
    ):
        rest = description[match.end() :].strip()
        chunk = re.split(r"\.(?:\s|$)", rest, maxsplit=1)[0]
        for item in re.split(r",\s*(?:or\s+)?|\s+or\s+", chunk):
            cleaned = item.strip().strip('"').strip("'").strip(",; ")
            if 1 < len(cleaned) <= 50 and cleaned.count(" ") <= 4:
                triggers.append(cleaned.lower())

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for t in triggers:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def discover_skills(
    skills_dir: Path | None = None,
) -> dict[str, dict]:
    """Discover all available skills and their metadata.

    Returns a dict mapping skill name → metadata dict.

    With ``skills_dir`` omitted, walks the roots in
    ``_iter_skill_roots()`` (project + global, EvoFlux + opencode) in
    precedence order, ending with bundled read-only EvoFlux skills —
    first source wins on a name collision. Pass an explicit
    ``skills_dir`` to scan a single root (used by tests).

    Uses an mtime-keyed cache so the next call after a skill is added,
    removed, or its ``SKILL.md`` edited returns the fresh listing
    without an explicit invalidation. The signature aggregates every
    root we scan, so a mutation in any one of them invalidates the
    cache.
    """
    if skills_dir is not None:
        if not skills_dir.is_dir():
            return {}
        return _discover_skills_cached(
            (str(skills_dir),), _skills_dir_signature(skills_dir)
        )

    roots = [r for r in _iter_skill_roots() if r.is_dir()]
    if not roots:
        return {}
    signature = tuple(_skills_dir_signature(r) for r in roots)
    return _discover_skills_cached(tuple(str(r) for r in roots), signature)


def _skills_dir_signature(directory: Path) -> int:
    """Cheap fingerprint that changes whenever any SKILL.md in the tree changes.

    ~1ms for a typical user's <20 skills.  Returns the max of the directory's
    own mtime_ns and every ``{name}/SKILL.md`` (flat) or
    ``{parent}/{sub}/SKILL.md`` (one nested level) mtime_ns we can stat — so
    in-place edits, additions, and removals all change the signature.
    """
    try:
        max_mtime = directory.stat().st_mtime_ns
    except OSError:
        return 0
    for subdir in directory.iterdir():
        if not subdir.is_dir():
            continue
        # Flat skill: {parent}/SKILL.md
        skill_file = subdir / "SKILL.md"
        try:
            mtime = skill_file.stat().st_mtime_ns
            if mtime > max_mtime:
                max_mtime = mtime
        except OSError:
            pass
        # One nested level: {parent}/{sub}/SKILL.md
        for nested in subdir.iterdir():
            if not nested.is_dir():
                continue
            nested_file = nested / "SKILL.md"
            try:
                mtime = nested_file.stat().st_mtime_ns
                if mtime > max_mtime:
                    max_mtime = mtime
            except OSError:
                continue
    return max_mtime


@lru_cache(maxsize=16)
def _discover_skills_cached(
    directories: tuple[str, ...], signature: int | tuple[int, ...]
) -> dict[str, dict]:
    """Cache keyed by ``(roots, mtime signature)``.

    *directories* is the ordered tuple of roots to walk; the first
    occurrence of a skill name wins. The signature changes on any
    add/remove/edit inside any root, so subsequent calls automatically
    pick up filesystem mutations.  Stale cache entries from prior
    signatures are evicted by the LRU bound.
    """
    skills: dict[str, dict] = {}
    for directory_str in directories:
        directory = Path(directory_str)
        for path, stem in _iter_skill_paths(directory):
            try:
                text = path.read_text(encoding="utf-8")
                meta, _ = _parse_frontmatter(text)
                name = meta.get("name", stem)
                description = _render_tokens(
                    meta.get("description", ""), skill_dir=path.parent
                )
            except OSError:
                # Keep unreadable skills discoverable by their path stem so UI
                # routes can surface the read error instead of the whole
                # catalog failing to load. ``format_available_skills`` filters
                # empty descriptions, so broken entries are not advertised to
                # agents in prompts.
                name = stem
                description = ""
            if name in skills:
                continue  # earlier root wins on collision
            skills[name] = {
                "name": name,
                "description": description,
                "file": path.relative_to(directory).as_posix(),
                # Absolute path to the skill's directory — needed by callers
                # that want to render {SKILL_DIR} in the body without a
                # second filesystem walk.
                "dir": str(path.parent),
            }
    return skills


def _short_description(description: str, *, max_len: int = 90) -> str:
    """Truncate a skill's full description to a single terse line.

    The tool description embeds one line per skill on every LLM call, so it
    uses this short form; ``discover_skills()`` and verbose rendering keep
    the full text for intent-matching (``extract_triggers``) and other
    consumers.  ``textwrap.shorten`` collapses embedded newlines/whitespace
    and truncates on word boundaries — no sentence-detection heuristic, so
    abbreviations like "e.g."/"etc." can't cause a premature cut.
    """
    return textwrap.shorten(description.strip(), width=max_len, placeholder="…")


def format_available_skills(*, verbose: bool = False) -> str:
    """Render discovered skills for prompt/tool-description context."""
    skills = [
        info
        for info in discover_skills().values()
        if str(info.get("description", "")).strip()
    ]
    if not skills:
        return "No skills are currently available."

    skills.sort(key=lambda info: str(info.get("name", "")))
    if verbose:
        lines = ["<available_skills>"]
        for info in skills:
            lines += [
                "  <skill>",
                f"    <name>{info['name']}</name>",
                f"    <description>{info['description']}</description>",
                f"    <location>{Path(str(info['dir'])).as_uri()}</location>",
                "  </skill>",
            ]
        lines.append("</available_skills>")
        return "\n".join(lines)

    return "\n".join(
        ["## Available Skills"]
        + [
            f"- **{info['name']}**: {_short_description(str(info['description']))}"
            for info in skills
        ]
    )


def _skill_tool_description() -> str:
    names = sorted(discover_skills())
    available = ", ".join(names) if names else "(none)"
    return (
        "List or load specialized skill instructions. The description keeps "
        "only skill names to minimize repeated schema tokens; call with "
        "action='list' for the full catalog. Call action='load' at most once "
        "per skill and reuse instructions already visible in the conversation.\n\n"
        f"Available skill names: {available}"
    )


def _iter_skill_paths(directory: Path):
    """Yield ``(skill_file_path, stem)`` for all skills in *directory*.

    Supports two layouts (one nested level maximum):

    * Flat:   ``skills/{name}/SKILL.md``          → stem ``name``
    * Nested: ``skills/{parent}/{sub}/SKILL.md``  → stem ``parent/sub``

    Sub-directories that contain *neither* a ``SKILL.md`` nor any
    nested ``{sub}/SKILL.md`` are silently skipped, so auxiliary files
    (``scripts/``, ``reference/``, …) sitting alongside the skill file
    are never exposed as skills themselves.

    Returns nothing for non-existent or non-directory paths so callers
    can pass roots that may not be present on this machine.
    """
    if not directory.is_dir():
        return
    for subdir in sorted(p for p in directory.iterdir() if p.is_dir()):
        skill_file = subdir / "SKILL.md"
        if skill_file.is_file():
            # Flat skill — yield and *also* check for nested sub-skills
            # below (they coexist with the parent's own SKILL.md).
            yield skill_file, subdir.name
        # One level of nesting: {parent}/{sub}/SKILL.md → "parent/sub"
        for nested in sorted(p for p in subdir.iterdir() if p.is_dir()):
            nested_file = nested / "SKILL.md"
            if nested_file.is_file():
                yield nested_file, f"{subdir.name}/{nested.name}"


def _loaded_skills_from_messages(state: Any) -> dict[str, str]:
    """Return skill names and content already loaded in visible conversation."""
    loaded: dict[str, str] = {}
    pending_by_tool_call_id: dict[str, str] = {}
    for message in getattr(state, "messages_for_llm", []):
        tool_calls = getattr(message, "tool_calls", None) or []
        for tool_call in tool_calls:
            fn = getattr(tool_call, "function", None)
            if fn is None:
                continue
            if getattr(fn, "name", None) != "skill":
                continue
            try:
                args = json.loads(getattr(fn, "arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                continue
            skill_name = args.get("skill_name")
            if isinstance(skill_name, str) and skill_name:
                loaded.setdefault(skill_name, "")
                tool_call_id = getattr(tool_call, "id", None)
                if isinstance(tool_call_id, str) and tool_call_id:
                    pending_by_tool_call_id[tool_call_id] = skill_name

        tool_call_id = getattr(message, "tool_call_id", None)
        if not isinstance(tool_call_id, str):
            continue
        skill_name = pending_by_tool_call_id.get(tool_call_id)
        content = getattr(message, "content", None)
        if skill_name and isinstance(content, str) and content:
            loaded[skill_name] = content
    return loaded


@tool(
    name="skill",
    description=_skill_tool_description,
    max_calls_per_batch=5,
    deduplicate_in_batch=True,
)
async def load_skill(
    skill_name: Annotated[
        str | None,
        Field(description="Exact skill name to load. Required when action='load'."),
    ] = None,
    action: Annotated[
        Literal["list", "load"],
        Field(description="List the full catalog or load one skill's instructions."),
    ] = "load",
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """List available skills or load one skill's instructions into context."""
    if action == "list":
        return format_available_skills(verbose=True)
    if not skill_name:
        return "skill_name is required when action='load'."

    if _state is not None:
        loaded_skills = _state.metadata.get("loaded_skills")
        if loaded_skills is None:
            loaded_skills = _loaded_skills_from_messages(_state)
            _state.metadata["loaded_skills"] = loaded_skills
        if loaded_skills.get(skill_name):
            logger.info("skill_reused name={}", skill_name)
            return loaded_skills[skill_name]

    roots = [r for r in _iter_skill_roots() if r.is_dir()]
    if not roots:
        return "Skills directory not found."

    # Use the cached discover_skills() lookup to find the exact file path,
    # avoiding a fresh filesystem walk on every on-demand load.
    discovered = discover_skills()
    skill_info = discovered.get(skill_name)
    if skill_info is not None:
        skill_dir = Path(skill_info["dir"])
        skill_file = skill_dir / "SKILL.md"
        if skill_file.is_file():
            text = await asyncio.to_thread(skill_file.read_text, encoding="utf-8")
            _, body = _parse_frontmatter(text)
            logger.info(
                "skill_loaded name={} file={}",
                skill_name,
                skill_info.get("file", skill_file),
            )
            rendered = _render_tokens(body, skill_dir=skill_dir)
            if _state is not None:
                loaded_skills[skill_name] = rendered
            return rendered

    # Fallback: walk all roots for stem-based matches not captured by
    # discover_skills (e.g. unreadable skills that are listed by stem
    # but have no description).
    for skills_dir in roots:
        for path, stem in _iter_skill_paths(skills_dir):
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            name = meta.get("name", stem)
            if name == skill_name or stem == skill_name:
                rel = path.relative_to(skills_dir)
                logger.info("skill_loaded name={} file={}", name, rel)
                rendered = _render_tokens(body, skill_dir=path.parent)
                if _state is not None:
                    loaded_skills[skill_name] = rendered
                return rendered

    available = sorted(discover_skills())
    matches = get_close_matches(skill_name, available, n=3, cutoff=0.5)
    suggestion = f" Did you mean: {', '.join(matches)}?" if matches else ""
    return (
        f"Skill '{skill_name}' not found.{suggestion} "
        "Call action='list' to inspect the full catalog."
    )
