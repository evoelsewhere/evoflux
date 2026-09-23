"""The Agent Skills ``SKILL.md`` format: parsing and validation.

Implements the frontmatter rules of the Agent Skills specification
(https://agentskills.io/specification) and Anthropic's Skill constraints
(reserved words, no XML tags). Runtime discovery is lenient — cosmetic
violations are warnings and the Skill still loads — while authoring paths
(Settings, Conductor sync, the bundle validator) use ``strict=True`` so a new
Skill cannot be created in a non-portable shape.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import yaml


MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 1_024
MAX_COMPATIBILITY_CHARS = 500
MAX_SKILL_FILE_BYTES = 512 * 1024
RECOMMENDED_BODY_LINES = 500
# The ``read`` tool returns at most this many characters and prefixes every
# line with a 5-digit number plus "| ". A SKILL.md that does not fit arrives
# truncated, so the model would act on partial instructions.
READ_WINDOW_CHARS = 20_000
READ_LINE_PREFIX_CHARS = 7
RESERVED_NAME_WORDS = ("anthropic", "claude")

_BOM = chr(0xFEFF)
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_XML_TAG_RE = re.compile(r"<\s*/?\s*[A-Za-z][\w.:-]*(?:\s[^<>]*)?/?\s*>")
_FRONTMATTER_RE = re.compile(
    r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)(.*)$", re.DOTALL
)

SPEC_FIELDS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)
EVOFLUX_FIELDS = frozenset({"disable-model-invocation", "user-invocable"})
KNOWN_FIELDS = SPEC_FIELDS | EVOFLUX_FIELDS

Severity = Literal["warning", "error"]
# Warnings that stay warnings even in strict mode: they describe authoring
# quality, not portability.
_ADVISORY_CODES = frozenset({"body-too-long", "exceeds-read-window"})


@dataclass(frozen=True)
class SkillDiagnostic:
    code: str
    message: str
    severity: Severity = "warning"

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "severity": self.severity}


@dataclass(frozen=True)
class SkillDefinition:
    """The parsed content of one ``SKILL.md``."""

    name: str
    description: str
    body: str
    license: str | None
    compatibility: str | None
    metadata: dict[str, str]
    allowed_tools: str | None
    disable_model_invocation: bool
    user_invocable: bool
    diagnostics: tuple[SkillDiagnostic, ...]

    @property
    def valid(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)


class SkillFormatError(ValueError):
    """``SKILL.md`` has no parseable frontmatter mapping."""


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split ``SKILL.md`` text into its YAML mapping and Markdown body."""

    match = _FRONTMATTER_RE.match(text.removeprefix(_BOM))
    if match is None:
        raise SkillFormatError(
            "SKILL.md must start with YAML frontmatter between '---' lines."
        )
    try:
        loaded = yaml.safe_load(match.group(1))
    except (yaml.YAMLError, RecursionError) as exc:
        raise SkillFormatError(f"Frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SkillFormatError("Frontmatter must be a YAML mapping.")
    return loaded, match.group(2).strip()


def name_problems(
    name: str, *, directory_name: str | None = None
) -> list[SkillDiagnostic]:
    """Return every specification problem with *name*."""

    problems: list[SkillDiagnostic] = []
    if not NAME_RE.fullmatch(name):
        problems.append(
            SkillDiagnostic(
                "invalid-name",
                "name may contain only lowercase letters, digits and single hyphens, "
                "and must not start or end with a hyphen.",
                "error",
            )
        )
    if len(name) > MAX_NAME_CHARS:
        problems.append(
            SkillDiagnostic(
                "name-too-long", f"name exceeds {MAX_NAME_CHARS} characters."
            )
        )
    lowered = name.casefold()
    for word in RESERVED_NAME_WORDS:
        if word in lowered:
            problems.append(
                SkillDiagnostic("reserved-name", f"name must not contain '{word}'.")
            )
    if directory_name is not None and name != directory_name:
        problems.append(
            SkillDiagnostic(
                "name-directory-mismatch",
                f"name '{name}' does not match its directory '{directory_name}'.",
            )
        )
    return problems


def _optional_string(
    meta: dict[str, Any], key: str, diagnostics: list[SkillDiagnostic]
) -> str | None:
    value = meta.get(key)
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    diagnostics.append(
        SkillDiagnostic(
            f"invalid-{key}", f"{key} must be a non-empty string; it is ignored."
        )
    )
    return None


def _optional_bool(
    meta: dict[str, Any], key: str, default: bool, diagnostics: list[SkillDiagnostic]
) -> bool:
    value = meta.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    diagnostics.append(
        SkillDiagnostic(
            f"invalid-{key}", f"{key} must be true or false; it is ignored."
        )
    )
    return default


def parse_skill(
    text: str,
    *,
    directory_name: str | None = None,
    strict: bool = False,
) -> SkillDefinition:
    """Parse and validate one ``SKILL.md``.

    Raises :class:`SkillFormatError` only when no frontmatter mapping exists.
    Every other problem becomes a diagnostic; ``valid`` is false when any
    diagnostic is an error.
    """

    meta, body = split_frontmatter(text)
    diagnostics: list[SkillDiagnostic] = []

    raw_name = meta.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name:
        diagnostics.append(
            SkillDiagnostic(
                "missing-name", "Frontmatter requires a non-empty name.", "error"
            )
        )
    else:
        diagnostics.extend(name_problems(name, directory_name=directory_name))

    raw_description = meta.get("description")
    description = raw_description.strip() if isinstance(raw_description, str) else ""
    if not description:
        diagnostics.append(
            SkillDiagnostic(
                "missing-description",
                "Frontmatter requires a non-empty description.",
                "error",
            )
        )
    elif len(description) > MAX_DESCRIPTION_CHARS:
        diagnostics.append(
            SkillDiagnostic(
                "description-too-long",
                f"description exceeds {MAX_DESCRIPTION_CHARS} characters.",
            )
        )
    for field, value in (("name", name), ("description", description)):
        if value and _XML_TAG_RE.search(value):
            diagnostics.append(
                SkillDiagnostic("xml-tag", f"{field} must not contain XML tags.")
            )

    license_value = _optional_string(meta, "license", diagnostics)
    compatibility = _optional_string(meta, "compatibility", diagnostics)
    if compatibility is not None and len(compatibility) > MAX_COMPATIBILITY_CHARS:
        diagnostics.append(
            SkillDiagnostic(
                "compatibility-too-long",
                f"compatibility exceeds {MAX_COMPATIBILITY_CHARS} characters.",
            )
        )
    allowed_tools = _optional_string(meta, "allowed-tools", diagnostics)

    metadata: dict[str, str] = {}
    raw_metadata = meta.get("metadata")
    if raw_metadata is not None:
        if isinstance(raw_metadata, dict) and all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw_metadata.items()
        ):
            metadata = dict(raw_metadata)
        else:
            diagnostics.append(
                SkillDiagnostic(
                    "invalid-metadata",
                    "metadata must map string keys to string values; it is ignored.",
                )
            )

    disable_model_invocation = _optional_bool(
        meta, "disable-model-invocation", False, diagnostics
    )
    user_invocable = _optional_bool(meta, "user-invocable", True, diagnostics)

    for key in sorted(str(item) for item in meta if item not in KNOWN_FIELDS):
        diagnostics.append(
            SkillDiagnostic(
                "unknown-field",
                f"Frontmatter field '{key}' is not supported and is ignored.",
            )
        )

    if not body:
        diagnostics.append(
            SkillDiagnostic(
                "empty-body", "SKILL.md instructions must not be empty.", "error"
            )
        )
    line_count = len(body.splitlines())
    if line_count > RECOMMENDED_BODY_LINES:
        diagnostics.append(
            SkillDiagnostic(
                "body-too-long",
                f"SKILL.md body has {line_count} lines; keep it under "
                f"{RECOMMENDED_BODY_LINES} and move detail into reference files.",
            )
        )
    lines = text.splitlines()
    read_size = sum(len(line) + READ_LINE_PREFIX_CHARS for line in lines)
    if read_size > READ_WINDOW_CHARS:
        diagnostics.append(
            SkillDiagnostic(
                "exceeds-read-window",
                f"SKILL.md needs about {read_size} characters in a read result; "
                f"one read returns {READ_WINDOW_CHARS}. Move detail into reference files.",
            )
        )

    if strict:
        diagnostics = [
            item
            if item.severity == "error" or item.code in _ADVISORY_CODES
            else SkillDiagnostic(item.code, item.message, "error")
            for item in diagnostics
        ]

    return SkillDefinition(
        name=name,
        description=description,
        body=body,
        license=license_value,
        compatibility=compatibility,
        metadata=metadata,
        allowed_tools=allowed_tools,
        disable_model_invocation=disable_model_invocation,
        user_invocable=user_invocable,
        diagnostics=tuple(diagnostics),
    )


def validate_skill_text(
    text: str, *, directory_name: str
) -> tuple[SkillDefinition | None, list[SkillDiagnostic]]:
    """Strictly validate authored ``SKILL.md`` text.

    Returns the parsed definition (``None`` if frontmatter is unparseable) and
    the blocking error diagnostics.
    """

    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        return None, [
            SkillDiagnostic(
                "invalid-encoding", f"SKILL.md is not valid UTF-8: {exc}", "error"
            )
        ]
    if len(encoded) > MAX_SKILL_FILE_BYTES:
        return None, [
            SkillDiagnostic(
                "file-too-large",
                f"SKILL.md exceeds {MAX_SKILL_FILE_BYTES} bytes.",
                "error",
            )
        ]
    try:
        definition = parse_skill(text, directory_name=directory_name, strict=True)
    except SkillFormatError as exc:
        return None, [SkillDiagnostic("invalid-frontmatter", str(exc), "error")]
    errors = [item for item in definition.diagnostics if item.severity == "error"]
    return definition, errors


__all__ = [
    "EVOFLUX_FIELDS",
    "KNOWN_FIELDS",
    "MAX_COMPATIBILITY_CHARS",
    "MAX_DESCRIPTION_CHARS",
    "MAX_NAME_CHARS",
    "MAX_SKILL_FILE_BYTES",
    "NAME_RE",
    "READ_WINDOW_CHARS",
    "RECOMMENDED_BODY_LINES",
    "RESERVED_NAME_WORDS",
    "SPEC_FIELDS",
    "SkillDefinition",
    "SkillDiagnostic",
    "SkillFormatError",
    "name_problems",
    "parse_skill",
    "split_frontmatter",
    "validate_skill_text",
]
