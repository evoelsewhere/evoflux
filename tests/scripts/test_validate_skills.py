from __future__ import annotations

from pathlib import Path

from scripts import validate_skills as validator


def _skill(root: Path, name: str, body: str = "Read [forms.md](forms.md).") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Fills forms. Use for forms.\n---\n{body}\n",
        encoding="utf-8",
    )
    return directory


def _codes(result: validator.SkillValidation) -> set[str]:
    return {item.code for item in result.findings}


def test_clean_bundle_passes(tmp_path) -> None:
    directory = _skill(tmp_path, "forms")
    (directory / "forms.md").write_text("# Forms\nFill them.\n", encoding="utf-8")

    result = validator.validate_skill(directory)

    assert result.valid and result.findings == []


def test_deep_yaml_is_reported_without_crashing(tmp_path) -> None:
    directory = tmp_path / "deep"
    directory.mkdir()
    nested = "".join(("  " * index) + "a:\n" for index in range(500))
    (directory / "SKILL.md").write_text(f"---\n{nested}---\nBody.", encoding="utf-8")

    result = validator.validate_skill(directory)

    assert not result.valid


def test_frontmatter_is_validated_strictly(tmp_path) -> None:
    directory = tmp_path / "forms"
    directory.mkdir()
    (directory / "SKILL.md").write_text(
        "---\nname: other\ndescription: d\nx-custom: 1\n---\nBody\n", encoding="utf-8"
    )

    result = validator.validate_skill(directory)

    assert not result.valid
    assert {"name-directory-mismatch", "unknown-field"} <= _codes(result)


def test_control_plane_files_and_nested_skills_are_rejected(tmp_path) -> None:
    directory = _skill(tmp_path, "forms", body="Body.")
    (directory / "agents").mkdir()
    (directory / "agents" / "evoflux.yaml").write_text("interface: {}\n")
    (directory / "evals").mkdir()
    (directory / "README.md").write_text("# Readme\n")
    (directory / "references" / "inner").mkdir(parents=True)
    (directory / "references" / "inner" / "SKILL.md").write_text(
        "---\nname: inner\ndescription: d\n---\nx\n"
    )

    result = validator.validate_skill(directory)

    assert not result.valid
    assert {"control-plane-file", "nested-skill"} <= _codes(result)


def test_links_must_resolve_inside_the_bundle_and_stay_one_level_deep(tmp_path) -> None:
    directory = _skill(
        tmp_path,
        "forms",
        body="Read [a](references/a.md), [gone](missing.md), [up](../x.md), [bad](references\\a.md).",
    )
    (directory / "references").mkdir()
    (directory / "references" / "a.md").write_text(
        "See [b](references/b.md).\n", encoding="utf-8"
    )
    (directory / "references" / "b.md").write_text("Details.\n", encoding="utf-8")
    (directory / "references" / "orphan.md").write_text("Unused.\n", encoding="utf-8")

    result = validator.validate_skill(directory)

    codes = _codes(result)
    assert {
        "missing-link-target",
        "link-escapes-bundle",
        "backslash-path",
        "nested-reference",
        "unlinked-reference",
    } <= codes


def test_long_reference_needs_contents_and_placeholders_are_rejected(tmp_path) -> None:
    directory = _skill(
        tmp_path,
        "forms",
        body='Run {SKILL_DIR}/x.py or skill(action="load"). [r](r.md)',
    )
    (directory / "r.md").write_text(
        "\n".join(f"line {n}" for n in range(150)), encoding="utf-8"
    )

    result = validator.validate_skill(directory)

    assert {"missing-contents", "host-placeholder", "skill-tool-call"} <= _codes(result)

    (directory / "r.md").write_text(
        "# R\n\n## Contents\n- A\n\n" + "\n".join(f"line {n}" for n in range(150)),
        encoding="utf-8",
    )
    assert "missing-contents" not in _codes(validator.validate_skill(directory))


def test_main_exit_codes(tmp_path, capsys) -> None:
    _skill(tmp_path, "forms", body="Plain body.")

    assert validator.main([str(tmp_path)]) == 0
    assert validator.main([str(tmp_path / "missing")]) == 2
    (tmp_path / "forms" / "README.md").write_text("x")
    assert validator.main([str(tmp_path), "--json"]) == 1
    assert '"control-plane-file"' in capsys.readouterr().out
