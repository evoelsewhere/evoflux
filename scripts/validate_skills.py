#!/usr/bin/env python3
"""Validate EvoFlux and portable Agent Skills bundles.

The validator checks the Agent Skills contract, EvoFlux/Codex interface metadata,
relative resource links, and activation-evaluation fixtures. It deliberately
does not require arbitrary headings or minimum prose length: a concise skill is
valid when its workflow is precise, while generic filler does not improve it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SKILLS_DIR = PROJECT_ROOT / "app" / "agent" / "builtin_skills"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)$", re.DOTALL)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
MAX_DESCRIPTION_CHARS = 1_024
MAX_SKILL_BYTES = 512 * 1024
MAX_AGENT_METADATA_BYTES = 256 * 1024
MAX_RESOURCE_BYTES = 2 * 1024 * 1024
MAX_BUNDLE_BYTES = 20 * 1024 * 1024
MAX_BUNDLE_ENTRIES = 20_000
MAX_SKILL_DIRECTORIES = 2_000
RECOMMENDED_BODY_LINES = 500
AGENT_INTERFACE_FIELD_LIMITS = {
    "display_name": 128,
    "short_description": 1_024,
    "default_prompt": 4_096,
    "icon_small": 1_024,
    "icon_large": 1_024,
    "brand_color": 64,
}
EVOFLUX_AGENT_METADATA = "evoflux.yaml"
PORTABLE_AGENT_METADATA = "openai.yaml"


@dataclass
class Finding:
    severity: str
    code: str
    message: str


@dataclass
class SkillResult:
    name: str
    path: str
    findings: list[Finding] = field(default_factory=list)
    resource_count: int = 0
    eval_count: int = 0

    @property
    def valid(self) -> bool:
        return not any(item.severity == "error" for item in self.findings)

    def add(self, severity: str, code: str, message: str) -> None:
        self.findings.append(Finding(severity, code, message))


def _read_bounded_utf8(path: Path, *, limit: int, label: str) -> str:
    """Read bounded UTF-8 without a stat/read race."""

    with path.open("rb") as handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"{label} exceeds {limit} bytes.")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8 text: {exc}") from exc


def _bounded_directory_entries(
    directory: Path, *, limit: int
) -> tuple[list[tuple[Path, bool, bool]], bool]:
    """Consume no more than *limit* scandir entries before sorting them."""

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


def _parse_skill(skill_file: Path, result: SkillResult) -> tuple[dict[str, Any], str]:
    try:
        text = _read_bounded_utf8(skill_file, limit=MAX_SKILL_BYTES, label="SKILL.md")
    except (OSError, ValueError) as exc:
        result.add("error", "unreadable-skill", str(exc))
        return {}, ""
    match = FRONTMATTER_RE.match(text)
    if not match:
        result.add("error", "missing-frontmatter", "SKILL.md needs YAML frontmatter.")
        return {}, text
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except (yaml.YAMLError, RecursionError) as exc:
        result.add("error", "invalid-frontmatter", str(exc))
        return {}, match.group(2).strip()
    if not isinstance(metadata, dict):
        result.add("error", "invalid-frontmatter", "Frontmatter must be a mapping.")
        metadata = {}
    return metadata, match.group(2).strip()


def _validate_frontmatter(
    skill_dir: Path, metadata: dict[str, Any], body: str, result: SkillResult
) -> None:
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not name:
        result.add("error", "missing-name", "name is required.")
    else:
        if not NAME_RE.fullmatch(name) or len(name) > 64:
            result.add(
                "error",
                "invalid-name",
                "name must be 1–64 lowercase letters/digits/hyphens.",
            )
        if name != skill_dir.name:
            result.add(
                "error",
                "name-directory-mismatch",
                f"name '{name}' does not match directory '{skill_dir.name}'.",
            )
    if not isinstance(description, str) or not description.strip():
        result.add("error", "missing-description", "description is required.")
    elif len(description) > MAX_DESCRIPTION_CHARS:
        result.add(
            "error",
            "description-too-long",
            f"description exceeds {MAX_DESCRIPTION_CHARS} characters.",
        )
    if not body:
        result.add("error", "empty-body", "SKILL.md instructions cannot be empty.")
    elif len(body.splitlines()) > RECOMMENDED_BODY_LINES:
        result.add(
            "warning",
            "long-body",
            f"Body exceeds {RECOMMENDED_BODY_LINES} lines; move conditional detail to references.",
        )


def _validate_agent_metadata(skill_dir: Path, result: SkillResult) -> None:
    agents_dir = skill_dir / "agents"
    native_path = agents_dir / EVOFLUX_AGENT_METADATA
    portable_path = agents_dir / PORTABLE_AGENT_METADATA
    path = native_path if native_path.exists() else portable_path
    if not path.exists():
        result.add(
            "warning",
            "missing-agent-metadata",
            "No agents/evoflux.yaml or agents/openai.yaml; runtime defaults will be used.",
        )
        return
    label = path.relative_to(skill_dir).as_posix()
    try:
        text = _read_bounded_utf8(
            path,
            limit=MAX_AGENT_METADATA_BYTES,
            label=label,
        )
        raw = yaml.safe_load(text) or {}
    except (OSError, ValueError, yaml.YAMLError, RecursionError) as exc:
        result.add("error", "invalid-agent-metadata", str(exc))
        return
    if not isinstance(raw, dict):
        result.add("error", "invalid-agent-metadata", "Root must be a mapping.")
        return
    interface = raw.get("interface")
    if not isinstance(interface, dict):
        result.add("error", "missing-agent-interface", "interface mapping is required.")
    else:
        for key in ("display_name", "short_description"):
            if not isinstance(interface.get(key), str) or not interface[key].strip():
                result.add(
                    "error",
                    "missing-agent-interface-field",
                    f"interface.{key} is required and must be non-empty.",
                )
        for key, limit in AGENT_INTERFACE_FIELD_LIMITS.items():
            value = interface.get(key)
            if value is None:
                continue
            if not isinstance(value, str):
                result.add(
                    "error",
                    "invalid-agent-interface-field",
                    f"interface.{key} must be a string.",
                )
            elif len(value) > limit:
                result.add(
                    "error",
                    "agent-interface-field-too-long",
                    f"interface.{key} exceeds {limit} characters.",
                )
    policy = raw.get("policy") or {}
    if not isinstance(policy, dict):
        result.add("error", "invalid-agent-policy", "policy must be a mapping.")
    elif "allow_implicit_invocation" in policy and not isinstance(
        policy["allow_implicit_invocation"], bool
    ):
        result.add(
            "error",
            "invalid-agent-policy",
            "policy.allow_implicit_invocation must be boolean.",
        )
    dependencies = raw.get("dependencies") or {}
    if not isinstance(dependencies, dict):
        result.add(
            "error", "invalid-agent-dependencies", "dependencies must be a mapping."
        )
        return
    tools = dependencies.get("tools") or []
    if not isinstance(tools, list):
        result.add(
            "error",
            "invalid-agent-dependencies",
            "dependencies.tools must be a list.",
        )
        return
    for index, tool in enumerate(tools):
        if not isinstance(tool, dict):
            result.add(
                "error",
                "invalid-agent-dependency",
                f"dependencies.tools[{index}] must be a mapping.",
            )
            continue
        dependency_type = tool.get("type")
        value = tool.get("value")
        if (
            not isinstance(dependency_type, str)
            or not dependency_type.strip()
            or len(dependency_type.strip()) > 64
            or not isinstance(value, str)
            or not value.strip()
            or len(value.strip()) > MAX_DESCRIPTION_CHARS
        ):
            result.add(
                "error",
                "invalid-agent-dependency",
                f"dependencies.tools[{index}] requires bounded type and value strings.",
            )


def _validate_resources(skill_dir: Path, result: SkillResult) -> None:
    """Validate bundle resources with the same hard limits as Settings CRUD."""

    total_bytes = 0
    entries_seen = 0
    root = skill_dir.resolve()
    stack = [skill_dir]
    while stack:
        base_path = stack.pop()
        entries, truncated = _bounded_directory_entries(
            base_path, limit=MAX_BUNDLE_ENTRIES - entries_seen
        )
        entries_seen += len(entries)
        directories: list[Path] = []
        files: list[Path] = []
        for path, is_directory, is_symlink in entries:
            relative = path.relative_to(skill_dir).as_posix()
            if is_symlink:
                result.add("error", "symlinked-resource", relative)
                continue
            if is_directory:
                directories.append(path)
            else:
                files.append(path)
        if truncated:
            result.add(
                "error",
                "bundle-entry-limit",
                f"Bundle exceeds {MAX_BUNDLE_ENTRIES} filesystem entries.",
            )
            return
        stack.extend(reversed(directories))
        for path in files:
            relative = path.relative_to(skill_dir).as_posix()
            if relative in {"SKILL.md", ".evoflux.json"}:
                continue
            try:
                path.resolve().relative_to(root)
                size = path.stat().st_size
            except (OSError, ValueError) as exc:
                result.add("error", "unreadable-resource", f"{relative}: {exc}")
                continue
            result.resource_count += 1
            total_bytes += size
            if size > MAX_RESOURCE_BYTES:
                result.add(
                    "error",
                    "resource-too-large",
                    f"{relative} exceeds {MAX_RESOURCE_BYTES} bytes.",
                )
            if total_bytes > MAX_BUNDLE_BYTES:
                result.add(
                    "error",
                    "bundle-too-large",
                    f"Bundle resources exceed {MAX_BUNDLE_BYTES} bytes.",
                )
                return


def _validate_links(skill_dir: Path, body: str, result: SkillResult) -> None:
    root = skill_dir.resolve()
    for raw_target in MARKDOWN_LINK_RE.findall(body):
        target = raw_target.strip().strip("<>").split("#", 1)[0]
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        relative = PurePosixPath(target)
        if relative.is_absolute() or ".." in relative.parts or "\\" in target:
            result.add("error", "unsafe-resource-link", raw_target)
            continue
        path = skill_dir.joinpath(*relative.parts)
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            result.add("error", "unsafe-resource-link", raw_target)
            continue
        if not path.exists():
            result.add("error", "missing-resource-link", target)


def _validate_evals(
    skill_dir: Path, result: SkillResult, *, require_evals: bool
) -> None:
    path = skill_dir / "evals" / "trigger-cases.json"
    if not path.exists():
        result.add(
            "error" if require_evals else "warning",
            "missing-trigger-evals",
            "No evals/trigger-cases.json activation cases.",
        )
        return
    try:
        text = _read_bounded_utf8(
            path, limit=MAX_RESOURCE_BYTES, label="evals/trigger-cases.json"
        )
        raw = json.loads(text)
    except (OSError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        result.add("error", "invalid-trigger-evals", str(exc))
        return
    cases = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(cases, list) or not cases:
        result.add("error", "invalid-trigger-evals", "Expected a non-empty case list.")
        return
    positive = 0
    negative = 0
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            result.add(
                "error", "invalid-trigger-case", f"Case {index} is not an object."
            )
            continue
        query = case.get("query", case.get("prompt"))
        trigger = case.get("should_trigger")
        if (
            not isinstance(query, str)
            or not query.strip()
            or not isinstance(trigger, bool)
        ):
            result.add(
                "error",
                "invalid-trigger-case",
                f"Case {index} requires a query/prompt and boolean should_trigger.",
            )
            continue
        positive += int(trigger)
        negative += int(not trigger)
    result.eval_count = len(cases)
    if positive == 0 or negative == 0:
        result.add(
            "error",
            "unbalanced-trigger-evals",
            "Activation evals need both positive and near-miss negative cases.",
        )


def validate_skill(skill_dir: Path, *, require_evals: bool = False) -> SkillResult:
    result = SkillResult(name=skill_dir.name, path=str(skill_dir / "SKILL.md"))
    metadata, body = _parse_skill(skill_dir / "SKILL.md", result)
    _validate_frontmatter(skill_dir, metadata, body, result)
    _validate_agent_metadata(skill_dir, result)
    _validate_links(skill_dir, body, result)
    _validate_evals(skill_dir, result, require_evals=require_evals)
    _validate_resources(skill_dir, result)
    return result


def discover_skill_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        raise FileNotFoundError(f"Skills directory not found: {root}")
    entries, truncated = _bounded_directory_entries(root, limit=MAX_SKILL_DIRECTORIES)
    if truncated:
        raise ValueError(
            f"Skills root exceeds {MAX_SKILL_DIRECTORIES} immediate entries: {root}"
        )
    return [
        path
        for path, is_directory, is_symlink in entries
        if is_directory and not is_symlink and (path / "SKILL.md").is_file()
    ]


def _print_human(results: list[SkillResult]) -> None:
    valid = sum(result.valid for result in results)
    print(
        f"Validated {len(results)} skill bundles: {valid} valid, {len(results) - valid} invalid"
    )
    for result in results:
        status = "PASS" if result.valid else "FAIL"
        print(
            f"{status:4} {result.name} "
            f"({result.resource_count} resources, {result.eval_count} evals)"
        )
        for finding in result.findings:
            print(f"  {finding.severity.upper():7} {finding.code}: {finding.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "skills_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_SKILLS_DIR,
        help="Root containing skill bundle directories.",
    )
    parser.add_argument(
        "--require-evals",
        action="store_true",
        help="Treat a missing trigger-case file as an error.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON diagnostics.")
    args = parser.parse_args(argv)
    try:
        results = [
            validate_skill(path, require_evals=args.require_evals)
            for path in discover_skill_dirs(args.skills_dir)
        ]
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(
            json.dumps(
                [
                    {
                        **asdict(result),
                        "valid": result.valid,
                    }
                    for result in results
                ],
                indent=2,
            )
        )
    else:
        _print_human(results)
    return 0 if all(result.valid for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
