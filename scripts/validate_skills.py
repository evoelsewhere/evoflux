#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skill Quality Validator
=======================
Audits all built-in skills in app/agent/builtin_skills/ against quality standards.

Quality gates:
  1. Body has >= 500 characters (after YAML frontmatter)
  2. Has a "When to Use" section (or equivalent)
  3. Has a "When NOT to Use" section (or equivalent)
  4. Has a verification step (section header or keyword in body)

Usage:
    python scripts/validate_skills.py
"""

import os
import re
import sys
from pathlib import Path
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SKILLS_DIR = PROJECT_ROOT / "app" / "agent" / "builtin_skills"

# ---------------------------------------------------------------------------
# Quality gate definitions
# ---------------------------------------------------------------------------

# Patterns for "When to Use" — checked against ## headers
WHEN_TO_USE_PATTERNS = [
    r"##\s+When\s+to\s+[Uu]se",
    r"##\s+Use\s+[Cc]ases",
    r"##\s+When\s+to\s+use\s+this",
]

# Patterns for "When NOT to Use" — checked against ## headers AND inline text
# (many skills embed it as **When NOT to use:** inside the When to Use section)
WHEN_NOT_PATTERNS = [
    r"##\s+When\s+[Nn][Oo][Tt]\s*to\s*[Uu]se",
    r"##\s+[Ll]imitations",
    r"##\s+When\s+not\s+to\s+use",
    # Inline bold pattern often used inside When to Use sections
    r"\*\*When\s+[Nn][Oo][Tt]\s*to\s+use[:\*]",
]

# Patterns for verification — checked against ## headers and keyword presence
VERIFY_SECTION_PATTERNS = [
    r"##\s+Verification",
    r"##\s+Verify",
    r"##\s+Quality",
    r"##\s+Check",
    r"###\s+Verification",
    r"###\s+Verify",
    r"###\s+Quality\s+Check",
]

MIN_BODY_LENGTH = 500

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class SkillResult:
    name: str
    path: Path
    body_length: int = 0
    has_when_to_use: bool = False
    has_when_not: bool = False
    has_verification: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_skill(skill_path: Path) -> SkillResult:
    """Parse a SKILL.md file and run all quality checks."""
    name = skill_path.parent.name
    result = SkillResult(name=name, path=skill_path)

    try:
        raw = skill_path.read_text(encoding="utf-8")
    except Exception as e:
        result.errors.append(f"Could not read file: {e}")
        return result

    # --- Split frontmatter from body ---
    body = raw
    if raw.startswith("---"):
        # Find closing ---
        second = raw.find("---", 3)
        if second != -1:
            body = raw[second + 3 :].strip()

    result.body_length = len(body)

    # --- Gate 1: Minimum body length ---
    if result.body_length < MIN_BODY_LENGTH:
        result.errors.append(
            f"Body too short: {result.body_length} chars (min {MIN_BODY_LENGTH})"
        )

    # --- Gate 2: "When to Use" section ---
    for pat in WHEN_TO_USE_PATTERNS:
        if re.search(pat, body, re.IGNORECASE):
            result.has_when_to_use = True
            break

    if not result.has_when_to_use:
        result.errors.append("Missing 'When to Use' section")

    # --- Gate 3: "When NOT to Use" ---
    for pat in WHEN_NOT_PATTERNS:
        if re.search(pat, body, re.IGNORECASE):
            result.has_when_not = True
            break

    if not result.has_when_not:
        result.errors.append("Missing 'When NOT to Use' section (or equivalent)")

    # --- Gate 4: Verification step ---
    # First check for explicit section headers
    for pat in VERIFY_SECTION_PATTERNS:
        if re.search(pat, body, re.IGNORECASE):
            result.has_verification = True
            break

    # Fallback: check for "verify" keyword in body
    if not result.has_verification:
        if re.search(r"verify", body, re.IGNORECASE):
            result.has_verification = True

    if not result.has_verification:
        result.errors.append("No verification section or 'verify' keyword found")

    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

SEPARATOR = "=" * 72
THIN_SEP = "-" * 72


def print_report(results: list[SkillResult]) -> None:
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]

    print(SEPARATOR)
    print("  SKILL QUALITY VALIDATION REPORT")
    print(SEPARATOR)
    print(f"  Total skills: {len(results)}")
    print(f"  Passed:       {len(passed)}")
    print(f"  Failed:       {len(failed)}")
    print(SEPARATOR)
    print()

    # --- PASS list ---
    print(f"  ✅ PASS ({len(passed)})")
    print(THIN_SEP)
    for r in sorted(passed, key=lambda x: x.name):
        print(f"    ✓ {r.name}")
    print()

    # --- FAIL list ---
    if failed:
        print(f"  ❌ FAIL ({len(failed)})")
        print(THIN_SEP)
        for r in sorted(failed, key=lambda x: x.name):
            print(f"    ✗ {r.name}")
            for err in r.errors:
                print(f"        - {err}")
            print()
    else:
        print("  🎉 All skills passed!")
        print()

    # --- Summary table ---
    print(SEPARATOR)
    print("  SUMMARY")
    print(SEPARATOR)
    print(f"  {'Skill':<40} {'Chars':>6} {'Use':>4} {'NOT':>4} {'Vfy':>4} {'Status':>8}")
    print(THIN_SEP)
    for r in sorted(results, key=lambda x: x.name):
        status = "PASS" if r.passed else "FAIL"
        print(
            f"  {r.name:<40} {r.body_length:>6} "
            f"{'✓' if r.has_when_to_use else '✗':>4} "
            f"{'✓' if r.has_when_not else '✗':>4} "
            f"{'✓' if r.has_verification else '✗':>4} "
            f"{status:>8}"
        )
    print(SEPARATOR)

    # Exit code
    if failed:
        print(f"\n  ⚠️  {len(failed)} skill(s) need attention.")
        sys.exit(1)
    else:
        print(f"\n  ✨ All {len(results)} skills meet quality standards.")
        sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def discover_skills(skills_dir: Path) -> list[Path]:
    """Find all SKILL.md files in the skills directory."""
    skill_files = []
    if not skills_dir.is_dir():
        print(f"ERROR: Skills directory not found: {skills_dir}", file=sys.stderr)
        sys.exit(1)

    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if skill_md.is_file():
            skill_files.append(skill_md)

    return skill_files


def main():
    skill_files = discover_skills(SKILLS_DIR)

    if not skill_files:
        print("ERROR: No SKILL.md files found.", file=sys.stderr)
        sys.exit(1)

    results = []
    for path in skill_files:
        results.append(parse_skill(path))

    print_report(results)


if __name__ == "__main__":
    main()
