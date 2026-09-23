"""SKILL.md parsing and validation against the Agent Skills specification."""

from __future__ import annotations

import pytest

from app.agent.skills.spec import (
    SkillFormatError,
    name_problems,
    parse_skill,
    validate_skill_text,
)


def _skill(frontmatter: str, body: str = "Do the thing.") -> str:
    return f"---\n{frontmatter}\n---\n{body}\n"


def _codes(definition) -> set[str]:
    return {item.code for item in definition.diagnostics}


def test_minimal_skill_is_valid_with_defaults():
    definition = parse_skill(
        _skill("name: pdf-processing\ndescription: Extracts PDF text. Use for PDFs."),
        directory_name="pdf-processing",
    )

    assert definition.valid
    assert definition.diagnostics == ()
    assert definition.name == "pdf-processing"
    assert definition.body == "Do the thing."
    assert definition.disable_model_invocation is False
    assert definition.user_invocable is True
    assert definition.metadata == {}


def test_optional_spec_and_evoflux_fields_are_parsed():
    definition = parse_skill(
        _skill(
            "name: pdf\n"
            "description: Fills PDF forms.\n"
            "license: Apache-2.0\n"
            "compatibility: Requires Python 3.12 and uv\n"
            "allowed-tools: Bash(python:*) Read\n"
            "metadata:\n  author: example\n  version: '1.0'\n"
            "disable-model-invocation: true\n"
            "user-invocable: false"
        ),
        directory_name="pdf",
    )

    assert definition.valid and not definition.diagnostics
    assert definition.license == "Apache-2.0"
    assert definition.compatibility == "Requires Python 3.12 and uv"
    assert definition.allowed_tools == "Bash(python:*) Read"
    assert definition.metadata == {"author": "example", "version": "1.0"}
    assert definition.disable_model_invocation is True
    assert definition.user_invocable is False


@pytest.mark.parametrize(
    "text",
    [
        "no frontmatter at all",
        "---\n- a\n- b\n---\nbody",
        "---\nname: [unclosed\n---\nbody",
    ],
)
def test_missing_or_malformed_frontmatter_raises(text):
    with pytest.raises(SkillFormatError):
        parse_skill(text)


def test_missing_description_and_empty_body_are_errors():
    definition = parse_skill("---\nname: x\n---\n")

    assert not definition.valid
    assert {"missing-description", "empty-body"} <= _codes(definition)


@pytest.mark.parametrize(
    "name", ["PDF", "-pdf", "pdf-", "pdf--tools", "pdf_tools", "a/b"]
)
def test_invalid_name_characters_are_errors(name):
    problems = name_problems(name)

    assert any(
        item.code == "invalid-name" and item.severity == "error" for item in problems
    )


def test_portability_problems_warn_at_runtime_and_block_when_strict():
    text = _skill(
        f"name: claude-{'x' * 64}\ndescription: {'d' * 1100}\nargument-hint: '[file]'"
    )

    lenient = parse_skill(text, directory_name="other")
    assert lenient.valid
    assert {
        "name-too-long",
        "reserved-name",
        "name-directory-mismatch",
        "description-too-long",
        "unknown-field",
    } <= _codes(lenient)
    assert all(item.severity == "warning" for item in lenient.diagnostics)

    strict = parse_skill(text, directory_name="other", strict=True)
    assert not strict.valid


def test_xml_tags_are_reported():
    definition = parse_skill(
        _skill("name: x\ndescription: Handles <instructions> blocks."),
        directory_name="x",
    )

    assert "xml-tag" in _codes(definition)


def test_wrong_types_for_optional_fields_are_ignored_with_warnings():
    definition = parse_skill(
        _skill(
            "name: x\ndescription: d\nmetadata: {a: 1}\n"
            "disable-model-invocation: 'yes'\nlicense: ''"
        ),
        directory_name="x",
    )

    assert definition.valid
    assert definition.metadata == {}
    assert definition.disable_model_invocation is False
    assert {
        "invalid-metadata",
        "invalid-disable-model-invocation",
        "invalid-license",
    } <= _codes(definition)


def test_long_body_and_read_window_are_advisory_even_when_strict():
    body = "\n".join(
        f"Line {index} with some instructional text." for index in range(600)
    )

    definition = parse_skill(
        _skill("name: x\ndescription: d", body), directory_name="x", strict=True
    )

    assert definition.valid
    assert {"body-too-long", "exceeds-read-window"} <= _codes(definition)


def test_validate_skill_text_returns_blocking_errors_only():
    definition, errors = validate_skill_text(
        _skill("name: Bad_Name\ndescription: d"), directory_name="bad-name"
    )

    assert definition is not None
    assert {item.code for item in errors} >= {"invalid-name", "name-directory-mismatch"}
    assert all(item.severity == "error" for item in errors)

    _definition, errors = validate_skill_text("plain text", directory_name="x")
    assert [item.code for item in errors] == ["invalid-frontmatter"]


def test_crlf_and_bom_are_accepted():
    text = chr(0xFEFF) + "---\r\nname: x\r\ndescription: d\r\n---\r\nBody\r\n"

    definition = parse_skill(text, directory_name="x")

    assert definition.valid
    assert definition.body == "Body"
