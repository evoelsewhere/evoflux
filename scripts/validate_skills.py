#!/usr/bin/env python3
"""Validate Agent Skills bundles against the specification and best practices.

Checks every direct child of a skills directory that contains ``SKILL.md``:

* frontmatter, strictly, with ``app.agent.skills.spec`` (the runtime parser);
* bundle hygiene: no nested ``SKILL.md``, no symlinks, no control-plane files
  (``agents/``, ``evals/``, ``README.md``, ``.evoflux.json``);
* progressive disclosure: relative links resolve inside the bundle, use forward
  slashes, and every Markdown file a reference links to is also linked from
  ``SKILL.md`` (references stay one level deep); reference files over 100
  lines start with a table of contents;
* no host placeholders or calls to the removed ``skill`` tool.

See documents/architecture/agent-skills.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.skills.spec import (  # noqa: E402 - needs the project root on sys.path
    MAX_SKILL_FILE_BYTES,
    READ_LINE_PREFIX_CHARS,
    READ_WINDOW_CHARS,
    parse_skill,
    SkillFormatError,
)

DEFAULT_SKILLS_DIR = PROJECT_ROOT / "app" / "agent" / "builtin_skills"
# A reference longer than this is previewed partially by models; the best
# practices ask for a table of contents at its top.
TOC_LINE_THRESHOLD = 100
TOC_SEARCH_LINES = 30
MAX_SKILL_DIRECTORIES = 2_000
MAX_BUNDLE_ENTRIES = 20_000
FORBIDDEN_ENTRIES = {"agents", "evals", ".evoflux.json", "README.md"}
_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_PLACEHOLDER_RE = re.compile(
    r"\{(?:SKILL_DIR|SKILLS_DIR|AGENTS_DIR|EVOFLUX_CONFIG_DIR)\}|<[A-Z_]+_SKILL_DIR>"
)
_SKILL_TOOL_RE = re.compile(r"\bskill\(\s*action\s*=")
_TOC_RE = re.compile(r"^#{1,3}\s*(table of )?contents\b", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    severity: str = "error"
    path: str = "SKILL.md"


@dataclass
class SkillValidation:
    name: str
    path: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(item.severity == "error" for item in self.findings)

    def add(
        self,
        code: str,
        message: str,
        *,
        severity: str = "error",
        path: str = "SKILL.md",
    ) -> None:
        self.findings.append(Finding(code, message, severity, path))


def _bundle_files(skill_dir: Path, result: SkillValidation) -> list[Path]:
    files: list[Path] = []
    stack = [skill_dir]
    seen = 0
    while stack:
        current = stack.pop()
        for entry in sorted(current.iterdir(), key=lambda item: item.name):
            seen += 1
            if seen > MAX_BUNDLE_ENTRIES:
                result.add(
                    "bundle-too-large", f"Bundle exceeds {MAX_BUNDLE_ENTRIES} entries."
                )
                return files
            relative = entry.relative_to(skill_dir).as_posix()
            if entry.name == "__pycache__":
                continue
            if entry.is_symlink():
                result.add(
                    "symlink", "Bundles must not contain symlinks.", path=relative
                )
                continue
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file():
                files.append(entry)
    return files


def _links(text: str) -> list[str]:
    links: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            links.extend(match.group(1) for match in _LINK_RE.finditer(line))
    return links


def _local_target(source: Path, target: str, skill_dir: Path) -> Path | None:
    """Resolve a relative link target, or ``None`` for URLs and anchors.

    The specification makes paths relative to the skill root, which is also
    how the model resolves them. A link relative to the linking file is
    accepted when that is the only reading that exists.
    """

    if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) or target.startswith(
        "#"
    ):
        return None
    clean = target.split("#", 1)[0]
    if not clean:
        return None
    from_root = (skill_dir / clean).resolve()
    if from_root.exists():
        return from_root
    from_file = (source.parent / clean).resolve()
    return from_file if from_file.exists() else from_root


def _check_markdown(
    skill_dir: Path,
    path: Path,
    text: str,
    result: SkillValidation,
) -> set[Path]:
    """Validate one Markdown file's links; return linked Markdown files."""

    relative = path.relative_to(skill_dir).as_posix()
    linked: set[Path] = set()
    root = skill_dir.resolve()
    for target in _links(text):
        if "\\" in target:
            result.add(
                "backslash-path", f"Link '{target}' uses a backslash.", path=relative
            )
            continue
        resolved = _local_target(path, target, skill_dir)
        if resolved is None:
            continue
        if not resolved.is_relative_to(root):
            result.add(
                "link-escapes-bundle",
                f"Link '{target}' leaves the bundle.",
                path=relative,
            )
            continue
        if not resolved.exists():
            result.add(
                "missing-link-target", f"Link '{target}' does not exist.", path=relative
            )
            continue
        if resolved.suffix.lower() == ".md":
            linked.add(resolved)
    if _PLACEHOLDER_RE.search(text):
        result.add(
            "host-placeholder",
            "Host placeholders are not expanded; use relative paths or the paths "
            "stated in the Skills system-prompt section.",
            path=relative,
        )
    if _SKILL_TOOL_RE.search(text):
        result.add(
            "skill-tool-call",
            "The skill tool does not exist; read files with the read tool.",
            path=relative,
        )
    return linked


def validate_skill(skill_dir: Path) -> SkillValidation:
    result = SkillValidation(name=skill_dir.name, path=str(skill_dir))
    skill_file = skill_dir / "SKILL.md"
    try:
        payload = skill_file.read_bytes()
        if len(payload) > MAX_SKILL_FILE_BYTES:
            result.add(
                "file-too-large", f"SKILL.md exceeds {MAX_SKILL_FILE_BYTES} bytes."
            )
            return result
        text = payload.decode("utf-8")
        definition = parse_skill(text, directory_name=skill_dir.name, strict=True)
    except (OSError, UnicodeError) as exc:
        result.add("unreadable-skill", str(exc))
        return result
    except SkillFormatError as exc:
        result.add("invalid-frontmatter", str(exc))
        return result
    if definition.name:
        result.name = definition.name
    for item in definition.diagnostics:
        result.add(item.code, item.message, severity=item.severity)

    for name in sorted(FORBIDDEN_ENTRIES):
        if (skill_dir / name).exists():
            result.add(
                "control-plane-file",
                f"'{name}' does not belong in a Skill bundle.",
                path=name,
            )

    files = _bundle_files(skill_dir, result)
    root = skill_dir.resolve()
    markdown = {
        path.resolve(): path
        for path in files
        if path.suffix.lower() == ".md" and path.resolve() != skill_file.resolve()
    }
    for path in files:
        if path.name == "SKILL.md" and path.resolve() != skill_file.resolve():
            result.add(
                "nested-skill",
                "Nested SKILL.md files are not skills; merge them into references.",
                path=path.relative_to(skill_dir).as_posix(),
            )

    direct = _check_markdown(skill_dir, skill_file, text, result)
    for resolved, path in sorted(markdown.items()):
        relative = path.relative_to(skill_dir).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            result.add("unreadable-resource", str(exc), path=relative)
            continue
        linked = _check_markdown(skill_dir, path, content, result)
        in_assets = PurePosixPath(relative).parts[0] == "assets"
        if resolved in direct:
            for target in sorted(linked - direct - {skill_file.resolve()}):
                result.add(
                    "nested-reference",
                    f"{relative} links to {target.relative_to(root).as_posix()}, which "
                    "SKILL.md does not link; keep references one level deep.",
                    path=relative,
                )
        elif not in_assets:
            result.add(
                "unlinked-reference",
                "Reference file is not linked from SKILL.md.",
                severity="warning",
                path=relative,
            )
        lines = content.splitlines()
        if (
            not in_assets
            and len(lines) > TOC_LINE_THRESHOLD
            and not any(_TOC_RE.match(line) for line in lines[:TOC_SEARCH_LINES])
        ):
            result.add(
                "missing-contents",
                f"Reference file has {len(lines)} lines; start it with a '## Contents' list.",
                path=relative,
            )
        window = sum(len(line) + READ_LINE_PREFIX_CHARS for line in lines)
        if window > READ_WINDOW_CHARS:
            result.add(
                "exceeds-read-window",
                f"Reference needs about {window} characters in one read result "
                f"({READ_WINDOW_CHARS} fit); split it by topic.",
                severity="warning",
                path=relative,
            )
    return result


def skill_directories(root: Path) -> list[Path]:
    directories = [
        entry
        for entry in sorted(root.iterdir(), key=lambda item: item.name)
        if entry.is_dir()
        and not entry.name.startswith(".")
        and not entry.is_symlink()
        and (entry / "SKILL.md").is_file()
    ]
    return directories[:MAX_SKILL_DIRECTORIES]


def validate_root(root: Path) -> list[SkillValidation]:
    return [validate_skill(directory) for directory in skill_directories(root)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "skills_dir",
        nargs="?",
        type=Path,
        default=DEFAULT_SKILLS_DIR,
        help="Directory whose direct children are Skills (default: bundled Skills).",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable results."
    )
    parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Treat warnings as failures (used for bundled Skills).",
    )
    args = parser.parse_args(argv)
    if not args.skills_dir.is_dir():
        print(f"Skills directory not found: {args.skills_dir}", file=sys.stderr)
        return 2
    results = validate_root(args.skills_dir)
    if args.json:
        print(
            json.dumps(
                [{**asdict(result), "valid": result.valid} for result in results],
                indent=2,
            )
        )
    else:
        for result in results:
            status = "ok" if result.valid else "invalid"
            print(f"{result.name}: {status}")
            for item in result.findings:
                print(f"  {item.severity} {item.code} {item.path}: {item.message}")
    failed = any(
        not result.valid or (args.strict_warnings and result.findings)
        for result in results
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
