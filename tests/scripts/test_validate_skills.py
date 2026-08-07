from __future__ import annotations

from scripts import validate_skills as validator


def test_validator_reports_deep_yaml_without_crashing(tmp_path) -> None:
    skill_dir = tmp_path / "deep-yaml"
    skill_dir.mkdir()
    nested_yaml = "".join(("  " * index) + "a:\n" for index in range(500))
    content = f"---\n{nested_yaml}---\nBody."
    assert len(content.encode("utf-8")) < validator.MAX_SKILL_BYTES
    (skill_dir / "SKILL.md").write_text(content)

    result = validator.validate_skill(skill_dir)

    assert result.valid is False
    assert any(item.code == "invalid-frontmatter" for item in result.findings)


def test_validator_reports_deep_agent_yaml_without_crashing(tmp_path) -> None:
    skill_dir = tmp_path / "deep-agent"
    (skill_dir / "agents").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: deep-agent\ndescription: Validate metadata.\n---\nBody."
    )
    nested_yaml = "".join(("  " * index) + "a:\n" for index in range(500))
    assert len(nested_yaml.encode("utf-8")) < validator.MAX_AGENT_METADATA_BYTES
    (skill_dir / "agents" / "evoflux.yaml").write_text(nested_yaml)

    result = validator.validate_skill(skill_dir)

    assert result.valid is False
    assert any(item.code == "invalid-agent-metadata" for item in result.findings)


def test_validator_reports_deep_eval_json_without_crashing(
    tmp_path, monkeypatch
) -> None:
    skill_dir = tmp_path / "deep-eval"
    (skill_dir / "evals").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: deep-eval\ndescription: Validate eval data.\n---\nBody."
    )
    (skill_dir / "evals" / "trigger-cases.json").write_text("{}")

    def raise_recursion(_text):
        raise RecursionError("nesting is too deep")

    monkeypatch.setattr(validator.json, "loads", raise_recursion)

    result = validator.validate_skill(skill_dir)

    assert result.valid is False
    assert any(item.code == "invalid-trigger-evals" for item in result.findings)


def test_validator_caps_scandir_before_materializing_wide_bundle(
    tmp_path, monkeypatch
) -> None:
    skill_dir = tmp_path / "wide"
    skill_dir.mkdir()
    for index in range(10):
        (skill_dir / f"{index:02}.md").write_text(str(index))

    real_scandir = validator.os.scandir
    consumed = 0

    class GuardedScandir:
        def __init__(self, path):
            self._iterator = real_scandir(path)

        def __enter__(self):
            self._iterator.__enter__()
            return self

        def __exit__(self, *args):
            return self._iterator.__exit__(*args)

        def __iter__(self):
            return self

        def __next__(self):
            nonlocal consumed
            consumed += 1
            if consumed > 4:
                raise AssertionError("validator consumed beyond its hard cap")
            return next(self._iterator)

    monkeypatch.setattr(validator, "MAX_BUNDLE_ENTRIES", 3)
    monkeypatch.setattr(validator.os, "scandir", GuardedScandir)
    result = validator.SkillResult(name="wide", path=str(skill_dir / "SKILL.md"))

    validator._validate_resources(skill_dir, result)

    assert consumed <= 4
    assert any(item.code == "bundle-entry-limit" for item in result.findings)
