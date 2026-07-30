#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skill Quality Fixer
===================
Auto-fixes common quality issues in SKILL.md files.

This script adds missing sections to skills that fail quality validation:
1. "When to Use" section - extracted from description frontmatter
2. "When NOT to Use" section - generated as exclusion criteria
3. Verification step - added at the end if missing

Usage:
    python scripts/fix_skill_quality.py [--dry-run]
"""

import re
import sys
from pathlib import Path
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SKILLS_DIR = PROJECT_ROOT / "app" / "agent" / "builtin_skills"

# ---------------------------------------------------------------------------
# Quality gate patterns (same as validate_skills.py)
# ---------------------------------------------------------------------------

WHEN_TO_USE_PATTERNS = [
    r"##\s+When\s+to\s+[Uu]se",
    r"##\s+Use\s+[Cc]ases",
    r"##\s+When\s+to\s+use\s+this",
]

WHEN_NOT_PATTERNS = [
    r"##\s+When\s+[Nn][Oo][Tt]\s*to\s*[Uu]se",
    r"##\s+[Ll]imitations",
    r"##\s+When\s+not\s+to\s+use",
    r"\*\*When\s+[Nn][Oo][Tt]\s*to\s+use[:\*]",
]

VERIFY_SECTION_PATTERNS = [
    r"##\s+Verification",
    r"##\s+Verify",
    r"##\s+Quality",
    r"##\s+Check",
    r"###\s+Verification",
    r"###\s+Verify",
    r"###\s+Quality\s+Check",
]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class FixResult:
    name: str
    path: Path
    fixes_applied: list[str]
    skipped: bool = False


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not match:
        return {}, text.strip()
    try:
        import yaml

        meta = yaml.safe_load(match.group(1)) or {}
    except ImportError:
        # Fallback: simple regex parsing
        meta = {}
        for line in match.group(1).split("\n"):
            m = re.match(r"^(\w+):\s*(.+)$", line)
            if m:
                meta[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    body = match.group(2).strip()
    return meta, body


def extract_description_trigger(description: str) -> str:
    """Extract a concise 'When to Use' summary from description."""
    # Try to extract "Use when..." phrase
    m = re.search(r"Use (?:this |it )?when (.+?)(?:\.|$)", description, re.IGNORECASE)
    if m:
        phrase = m.group(1).strip()
        # Clean up and capitalize
        if not phrase[0].isupper():
            phrase = phrase[0].upper() + phrase[1:]
        return f"- Use when {phrase}"

    # Try "Triggers:" list
    m = re.search(r"Triggers?:\s*(.+?)(?:\n|$)", description, re.IGNORECASE)
    if m:
        return f"- Triggers on: {m.group(1).strip()}"

    # Fallback: use first sentence of description
    sentences = description.split(".")
    if sentences:
        first = sentences[0].strip()
        if len(first) > 20:
            return f"- {first}"

    return "- See skill description for trigger conditions"


def generate_when_not(meta: dict, body: str) -> str:
    """Generate 'When NOT to Use' section based on skill content."""
    name = meta.get("name", "this skill")

    # Common exclusion patterns
    exclusions = []

    # Check if skill has specific exclusions mentioned
    if re.search(r"not.*applicable|not.*suitable|not.*intended", body, re.IGNORECASE):
        # Extract existing exclusion mentions
        m = re.search(r"(?:not|don't|do not).*?(?:\.|$)", body, re.IGNORECASE)
        if m:
            exclusions.append(f"- {m.group(0).strip()}")

    # Add generic exclusions based on skill type
    if "test" in name.lower():
        exclusions.append("- Pure configuration changes or documentation updates")
    elif "debug" in name.lower():
        exclusions.append(
            "- When the issue is clearly understood and doesn't require investigation"
        )
    elif "review" in name.lower():
        exclusions.append("- During initial implementation (review comes after)")
    elif "deploy" in name.lower():
        exclusions.append("- For local development workflows")
    elif "research" in name.lower():
        exclusions.append("- For quick factual questions (use simpler search instead)")
    elif "security" in name.lower():
        exclusions.append("- For non-security-related code changes")
    elif "performance" in name.lower():
        exclusions.append("- When correctness is the primary concern")

    if not exclusions:
        exclusions.append("- When the task doesn't match this skill's domain")
        exclusions.append("- For simple tasks that don't require structured workflows")

    return "\n".join(exclusions)


def generate_verification(name: str, body: str) -> str:
    """Generate a verification section based on skill type."""
    # Check if skill already has verification-like content
    if re.search(r"verify|check|confirm|validate", body, re.IGNORECASE):
        # Extract existing verification mentions
        lines = []
        for line in body.split("\n"):
            if re.search(r"verify|check|confirm|validate", line, re.IGNORECASE):
                lines.append(f"- {line.strip()}")
        if lines:
            return "\n".join(lines[:3])  # Take first 3

    # Generate based on skill type
    if "test" in name.lower():
        return "- Run the tests to verify they pass\n- Check test coverage for new code"
    elif "debug" in name.lower():
        return "- Verify the fix resolves the original issue\n- Confirm no regressions were introduced"
    elif "review" in name.lower():
        return "- Review feedback has been addressed\n- All quality gates pass"
    elif "deploy" in name.lower():
        return "- Deployment completed successfully\n- Health checks pass\n- No errors in logs"
    elif "write" in name.lower() or "doc" in name.lower():
        return "- Read back the content to verify accuracy\n- Check formatting renders correctly"
    elif "research" in name.lower():
        return "- Verify claims against primary sources\n- Check citation completeness"
    else:
        return "- Read back the output to verify quality\n- Confirm all requirements are met"


# ---------------------------------------------------------------------------
# Fix logic
# ---------------------------------------------------------------------------


def fix_skill(skill_path: Path, dry_run: bool = False) -> FixResult:
    """Fix quality issues in a single skill."""
    name = skill_path.parent.name
    result = FixResult(name=name, path=skill_path, fixes_applied=[])

    try:
        text = skill_path.read_text(encoding="utf-8")
    except Exception as e:
        result.fixes_applied.append(f"ERROR: Could not read file: {e}")
        return result

    meta, body = parse_frontmatter(text)
    description = meta.get("description", "")

    # Check what needs fixing
    needs_when_to = not any(
        re.search(p, body, re.IGNORECASE) for p in WHEN_TO_USE_PATTERNS
    )
    needs_when_not = not any(
        re.search(p, body, re.IGNORECASE) for p in WHEN_NOT_PATTERNS
    )
    needs_verify = not any(
        re.search(p, body, re.IGNORECASE) for p in VERIFY_SECTION_PATTERNS
    )

    if not (needs_when_to or needs_when_not or needs_verify):
        result.skipped = True
        return result

    # Build new body
    new_body = body

    # Add verification section before "When to Use" if it exists at the end
    # Or append at the end
    if needs_verify:
        verification = generate_verification(name, body)
        verification_section = f"\n\n## Verification\n\n{verification}"

        # Try to insert before existing sections at the end
        # Find the last ## section
        last_section_match = list(
            re.finditer(r"^##\s+", new_body, re.MULTILINE | re.IGNORECASE)
        )
        if last_section_match:
            insert_pos = last_section_match[-1].start()
            new_body = (
                new_body[:insert_pos]
                + verification_section
                + "\n\n"
                + new_body[insert_pos:]
            )
        else:
            new_body += verification_section
        result.fixes_applied.append("Added 'Verification' section")

    if needs_when_not and description:
        when_not = generate_when_not(meta, new_body)
        when_not_section = f"\n\n## When NOT to Use\n\n{when_not}"

        # Insert after "When to Use" section if it exists
        when_to_match = re.search(
            r"(##\s+When\s+to\s+[Uu]se.*?)(?=\n##\s+|\Z)",
            new_body,
            re.DOTALL | re.IGNORECASE,
        )
        if when_to_match:
            insert_pos = when_to_match.end()
            new_body = new_body[:insert_pos] + when_not_section + new_body[insert_pos:]
        else:
            new_body += when_not_section
        result.fixes_applied.append("Added 'When NOT to Use' section")

    if needs_when_to and description:
        when_to = extract_description_trigger(description)
        when_to_section = f"\n\n## When to Use\n\n{when_to}"
        new_body = when_to_section + new_body
        result.fixes_applied.append("Added 'When to Use' section")

    # Write back
    if not dry_run:
        skill_path.write_text(text.replace(body, new_body), encoding="utf-8")

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("DRY RUN MODE - No files will be modified\n")

    skill_dirs = sorted(d for d in SKILLS_DIR.iterdir() if d.is_dir())

    fixed = 0
    skipped = 0
    errors = 0

    for skill_dir in skill_dirs:
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        result = fix_skill(skill_file, dry_run=dry_run)

        if result.skipped:
            skipped += 1
            print(f"  ⏭ {result.name}: Already compliant")
        elif result.fixes_applied and "ERROR" in result.fixes_applied[0]:
            errors += 1
            print(f"  ❌ {result.name}: {result.fixes_applied[0]}")
        elif result.fixes_applied:
            fixed += 1
            print(f"  ✅ {result.name}: {', '.join(result.fixes_applied)}")
        else:
            skipped += 1

    print(f"\n{'=' * 60}")
    print(f"Summary: {fixed} fixed, {skipped} skipped, {errors} errors")
    print(f"{'=' * 60}")

    if dry_run:
        print("\nRun without --dry-run to apply fixes.")


if __name__ == "__main__":
    main()
