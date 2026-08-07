"""Tests for app/tools/builtin/skill.py."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.builtin_skills.catalog import BUNDLED_SKILL_MODES
from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.tools.builtin.skill import (
    _builtin_skills_dir,
    _discover_skills_cached,
    _iter_skill_paths,
    _iter_skill_roots,
    _parse_frontmatter,
    _skill_tool_description,
    _skills_dir_signature,
    discover_skills,
    load_skill,
    skills_for_mode,
)


# ---------------------------------------------------------------------------
# _parse_frontmatter
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_with_frontmatter(self):
        text = "---\nname: test\ndescription: A test skill\n---\nBody content here."
        meta, body = _parse_frontmatter(text)
        assert meta["name"] == "test"
        assert meta["description"] == "A test skill"
        assert body == "Body content here."

    def test_no_frontmatter(self):
        text = "Just plain markdown body."
        meta, body = _parse_frontmatter(text)
        assert meta == {}
        assert body == "Just plain markdown body."

    def test_empty_frontmatter(self):
        text = "---\n\n---\nBody after empty frontmatter."
        meta, body = _parse_frontmatter(text)
        assert meta == {}
        assert body == "Body after empty frontmatter."


# ---------------------------------------------------------------------------
# discover_skills
# ---------------------------------------------------------------------------


class TestDiscoverSkills:
    def test_discover_skills_from_dir(self, tmp_path):
        skill_dir = tmp_path / "example-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: example-skill\ndescription: Example skill\n---\nInstructions."
        )
        result = discover_skills(skills_dir=tmp_path)
        assert "example-skill" in result
        assert result["example-skill"]["description"] == "Example skill"
        assert result["example-skill"]["file"] == "example-skill/SKILL.md"

    def test_discover_skills_empty_dir(self, tmp_path):
        result = discover_skills(skills_dir=tmp_path)
        assert result == {}

    def test_discover_skills_missing_dir(self, tmp_path):
        result = discover_skills(skills_dir=tmp_path / "nonexistent")
        assert result == {}

    def test_discover_skills_name_from_stem(self, tmp_path):
        """If frontmatter has no name, fall back to the subdirectory name."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\ndescription: desc\n---\nBody.")
        result = discover_skills(skills_dir=tmp_path)
        assert "my-skill" in result

    def test_discover_multiple_skills(self, tmp_path):
        for name, body in [("alpha", "A instructions."), ("beta", "B instructions.")]:
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n{body}")
        result = discover_skills(skills_dir=tmp_path)
        assert len(result) == 2
        assert "alpha" in result
        assert "beta" in result

    def test_subdir_without_skill_md_is_ignored(self, tmp_path):
        """A subdirectory that has no SKILL.md must not appear in results."""
        orphan = tmp_path / "orphan"
        orphan.mkdir()
        (orphan / "notes.md").write_text("not a skill")
        result = discover_skills(skills_dir=tmp_path)
        assert result == {}

    def test_openai_interface_and_invocation_policy_are_parsed(self, tmp_path):
        skill_dir = tmp_path / "specialist"
        (skill_dir / "agents").mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: specialist\ndescription: Specialist workflow.\n---\nBody."
        )
        (skill_dir / "agents" / "openai.yaml").write_text(
            "interface:\n"
            "  display_name: Deep specialist\n"
            "  short_description: Run the exact specialist workflow\n"
            "  default_prompt: Use $specialist on this task.\n"
            "policy:\n"
            "  allow_implicit_invocation: false\n"
        )

        result = discover_skills(skills_dir=tmp_path)["specialist"]

        assert result["display_name"] == "Deep specialist"
        assert result["short_description"] == "Run the exact specialist workflow"
        assert result["default_prompt"] == "Use $specialist on this task."
        assert result["allow_implicit_invocation"] is False
        assert result["resource_count"] == 1

    def test_oversized_openai_metadata_is_not_read(self, tmp_path, monkeypatch):
        skill_dir = tmp_path / "specialist"
        (skill_dir / "agents").mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: specialist\ndescription: Specialist workflow.\n---\nBody."
        )
        metadata_path = skill_dir / "agents" / "openai.yaml"
        metadata_path.write_text("x" * (256 * 1024 + 1))
        original_read_text = Path.read_text

        def guarded_read_text(path, *args, **kwargs):
            if path == metadata_path:
                raise AssertionError("oversized agents/openai.yaml was read")
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", guarded_read_text)

        result = discover_skills(skills_dir=tmp_path)["specialist"]

        assert result["valid"] is True
        assert any(
            item["code"] == "openai-metadata-too-large"
            for item in result["diagnostics"]
        )

    def test_openai_tool_dependencies_are_bounded_and_projected(self, tmp_path):
        skill_dir = tmp_path / "specialist"
        (skill_dir / "agents").mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: specialist\ndescription: Specialist workflow.\n---\nBody."
        )
        (skill_dir / "agents" / "openai.yaml").write_text(
            "interface:\n"
            "  display_name: Specialist\n"
            "  short_description: Run a specialist workflow\n"
            "dependencies:\n"
            "  tools:\n"
            "    - type: mcp\n"
            "      value: github\n"
            "      description: GitHub MCP server\n"
            "    - type: mcp\n"
            "      description: Missing value\n"
        )

        result = discover_skills(skills_dir=tmp_path)["specialist"]

        assert result["dependencies"] == [
            {
                "type": "mcp",
                "value": "github",
                "description": "GitHub MCP server",
            }
        ]
        assert any(
            item["code"] == "invalid-openai-dependency"
            for item in result["diagnostics"]
        )

    def test_openai_interface_fields_are_individually_bounded(self, tmp_path):
        skill_dir = tmp_path / "specialist"
        (skill_dir / "agents").mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: specialist\ndescription: Specialist workflow.\n---\nBody."
        )
        (skill_dir / "agents" / "openai.yaml").write_text(
            "interface:\n"
            "  display_name: Specialist\n"
            "  short_description: Run a specialist workflow\n"
            f"  default_prompt: {'x' * 4097}\n"
        )

        result = discover_skills(skills_dir=tmp_path)["specialist"]

        assert result["default_prompt"] is None
        assert any(
            item["code"] == "openai-interface-field-too-long"
            for item in result["diagnostics"]
        )

    def test_malformed_scope_fails_open_with_visible_diagnostic(self, tmp_path):
        skill_dir = tmp_path / "specialist"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: specialist\ndescription: Specialist workflow.\n---\nBody."
        )
        (skill_dir / ".evoflux.json").write_text('{"modes": [')

        result = discover_skills(skills_dir=tmp_path)["specialist"]

        assert result["valid"] is True
        assert result["modes"] == ["work", "coding"]
        diagnostic = next(
            item
            for item in result["diagnostics"]
            if item["code"] == "invalid-skill-scope"
        )
        assert ".evoflux.json is not valid JSON" in diagnostic["message"]

    @pytest.mark.parametrize(
        "payload",
        [
            '{"modes":["coding","typo"]}',
            '{"modes":' + ("[" * 1_500) + '"work"' + ("]" * 1_500) + "}",
            "x" * (16 * 1024 + 1),
        ],
    )
    def test_invalid_scope_variants_always_fail_open_to_both_modes(
        self, tmp_path, payload
    ):
        skill_dir = tmp_path / "specialist"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: specialist\ndescription: Specialist workflow.\n---\nBody."
        )
        (skill_dir / ".evoflux.json").write_text(payload)

        result = discover_skills(skills_dir=tmp_path)["specialist"]

        assert result["valid"] is True
        assert result["modes"] == ["work", "coding"]
        assert any(
            item["code"] == "invalid-skill-scope" for item in result["diagnostics"]
        )

    def test_deeply_nested_yaml_isolated_from_valid_sibling(self, tmp_path):
        broken = tmp_path / "broken"
        broken.mkdir()
        nested_yaml = "".join(("  " * index) + "a:\n" for index in range(500))
        content = f"---\n{nested_yaml}---\nBody."
        assert len(content.encode("utf-8")) < 512 * 1024
        (broken / "SKILL.md").write_text(content)

        valid = tmp_path / "valid"
        valid.mkdir()
        (valid / "SKILL.md").write_text(
            "---\nname: valid\ndescription: Valid workflow.\n---\nBody."
        )

        result = discover_skills(skills_dir=tmp_path)

        assert result["broken"]["valid"] is False
        assert result["valid"]["valid"] is True

    def test_deeply_nested_openai_yaml_becomes_diagnostic(self, tmp_path):
        skill_dir = tmp_path / "specialist"
        (skill_dir / "agents").mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: specialist\ndescription: Specialist workflow.\n---\nBody."
        )
        nested_yaml = "".join(("  " * index) + "a:\n" for index in range(500))
        assert len(nested_yaml.encode("utf-8")) < 256 * 1024
        (skill_dir / "agents" / "openai.yaml").write_text(nested_yaml)

        result = discover_skills(skills_dir=tmp_path)["specialist"]

        assert result["valid"] is True
        assert any(
            item["code"] == "invalid-openai-metadata" for item in result["diagnostics"]
        )

    def test_wide_root_is_capped_while_consuming_scandir(self, tmp_path, monkeypatch):
        from app.agent.skills import discovery as discovery_module

        for index in range(10):
            skill_dir = tmp_path / f"skill-{index}"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: skill-{index}\ndescription: Skill {index}.\n---\nBody."
            )

        real_scandir = discovery_module.os.scandir
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
                    raise AssertionError("discovery consumed beyond its hard cap")
                return next(self._iterator)

        monkeypatch.setattr(discovery_module, "MAX_DISCOVERY_ENTRIES", 3)
        monkeypatch.setattr(discovery_module.os, "scandir", GuardedScandir)

        paths = list(_iter_skill_paths(tmp_path))

        assert consumed <= 4
        assert len(paths) <= 3
        assert [stem for _path, stem in paths] == sorted(stem for _path, stem in paths)

    def test_symlinked_discovery_root_makes_every_bundle_read_only(self, tmp_path):
        real_root = tmp_path / "real-skills"
        skill_dir = real_root / "specialist"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: specialist\ndescription: Specialist workflow.\n---\nBody."
        )
        linked_root = tmp_path / "linked-skills"
        linked_root.symlink_to(real_root, target_is_directory=True)

        result = discover_skills(skills_dir=linked_root)["specialist"]

        assert result["symlinked"] is True
        assert result["editable"] is False

    def test_malformed_skill_does_not_hide_valid_sibling(self, tmp_path):
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "SKILL.md").write_text(
            "---\nname: broken\ndescription: [unterminated\n---\nBody."
        )
        valid = tmp_path / "valid"
        valid.mkdir()
        (valid / "SKILL.md").write_text(
            "---\nname: valid\ndescription: Valid workflow.\n---\nBody."
        )

        result = discover_skills(skills_dir=tmp_path)

        assert result["broken"]["valid"] is False
        assert result["valid"]["valid"] is True

    def test_empty_skill_body_is_invalid_at_runtime(self, tmp_path):
        skill_dir = tmp_path / "empty"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: empty\ndescription: Empty workflow.\n---\n"
        )

        result = discover_skills(skills_dir=tmp_path)["empty"]

        assert result["valid"] is False
        assert any(item["code"] == "empty-body" for item in result["diagnostics"])

    def test_duplicate_name_surfaces_shadow_diagnostic(self, tmp_path, monkeypatch):
        first = tmp_path / "first"
        second = tmp_path / "second"
        for root, description in ((first, "First."), (second, "Second.")):
            skill_dir = root / "duplicate"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: duplicate\ndescription: {description}\n---\nBody."
            )
        monkeypatch.setattr(
            "app.agent.tools.builtin.skill._iter_skill_roots",
            lambda: [first, second],
        )

        result = discover_skills()["duplicate"]

        assert result["description"] == "First."
        assert result["shadowed_paths"] == [str(second / "duplicate" / "SKILL.md")]
        assert any(
            item["code"] == "shadowed-duplicate" for item in result["diagnostics"]
        )


# ---------------------------------------------------------------------------
# load_skill
# ---------------------------------------------------------------------------


class TestLoadSkill:
    def test_skill_tool_declares_batch_storm_guard(self):
        assert load_skill.max_calls_per_batch == 5
        assert load_skill.deduplicate_in_batch is True

    @pytest.mark.asyncio
    async def test_load_skill_by_name(self, tmp_path, monkeypatch):
        d = tmp_path / "analysis"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: analysis\ndescription: Analyze data.\n---\nAnalyse data carefully."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)
        result = await load_skill("analysis")
        assert result == "Analyse data carefully."

    @pytest.mark.asyncio
    async def test_load_skill_reuses_visible_session_skill(self, tmp_path, monkeypatch):
        d = tmp_path / "analysis"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: analysis\ndescription: Analyze data.\n---\nAnalyse data carefully."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)

        state = SimpleNamespace(metadata={}, messages_for_llm=[])
        first = await load_skill("analysis", _state=state)
        second = await load_skill("analysis", _state=state)

        assert '<skill_content name="analysis"' in first
        assert "Analyse data carefully." in first
        assert (
            second
            == "Skill 'analysis' is already loaded; reuse its visible instructions."
        )

    @pytest.mark.asyncio
    async def test_load_skill_rehydrates_visible_session_skill_body(
        self, tmp_path, monkeypatch
    ):
        d = tmp_path / "analysis"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: analysis\ndescription: Analyze data.\n---\nFresh body."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)
        state = SimpleNamespace(
            metadata={},
            messages_for_llm=[
                SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            function=SimpleNamespace(
                                name="skill",
                                arguments='{"skill_name":"analysis"}',
                            ),
                        )
                    ]
                ),
                SimpleNamespace(
                    role="tool",
                    tool_call_id="call_1",
                    content='<skill_content name="analysis">Previously loaded body.</skill_content>',
                ),
            ],
        )

        result = await load_skill("analysis", _state=state)

        assert (
            result
            == "Skill 'analysis' is already loaded; reuse its visible instructions."
        )

    @pytest.mark.asyncio
    async def test_load_skill_ignores_malformed_visible_skill_call(
        self, tmp_path, monkeypatch
    ):
        d = tmp_path / "analysis"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: analysis\ndescription: Analyze data.\n---\nFresh body."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)
        state = SimpleNamespace(
            metadata={},
            messages_for_llm=[
                SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            id="call_bad",
                            function=SimpleNamespace(
                                name="skill",
                                arguments="not-json",
                            ),
                        )
                    ]
                ),
                SimpleNamespace(
                    role="tool",
                    tool_call_id="call_bad",
                    content="Stale body must not be reused.",
                ),
            ],
        )

        result = await load_skill("analysis", _state=state)

        assert '<skill_content name="analysis"' in result
        assert "Fresh body." in result

    @pytest.mark.asyncio
    async def test_load_skill_reload_when_visible_pair_has_no_body(
        self, tmp_path, monkeypatch
    ):
        d = tmp_path / "analysis"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: analysis\ndescription: Analyze data.\n---\nFresh body."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)
        state = SimpleNamespace(
            metadata={},
            messages_for_llm=[
                SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            id="call_empty",
                            function=SimpleNamespace(
                                name="skill",
                                arguments='{"skill_name":"analysis"}',
                            ),
                        )
                    ]
                ),
                SimpleNamespace(role="tool", tool_call_id="call_empty", content=""),
            ],
        )

        result = await load_skill("analysis", _state=state)

        assert '<skill_content name="analysis"' in result
        assert "Fresh body." in result

    @pytest.mark.asyncio
    async def test_load_skill_ignores_noncanonical_activation_substring(
        self, tmp_path, monkeypatch
    ):
        skill_dir = tmp_path / "analysis"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: analysis\ndescription: Analyze data.\n---\nFresh body."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)
        state = SimpleNamespace(
            metadata={},
            messages_for_llm=[
                SimpleNamespace(
                    tool_calls=[
                        SimpleNamespace(
                            id="call_spoofed",
                            function=SimpleNamespace(
                                name="skill",
                                arguments='{"action":"load","skill_name":"analysis"}',
                            ),
                        )
                    ]
                ),
                SimpleNamespace(
                    role="tool",
                    tool_call_id="call_spoofed",
                    content="Error mentioned <skill_content but did not activate.",
                ),
            ],
        )

        result = await load_skill("analysis", _state=state)

        assert '<skill_content name="analysis"' in result
        assert "Fresh body." in result

    @pytest.mark.asyncio
    async def test_load_skill_rejects_directory_name_mismatch(
        self, tmp_path, monkeypatch
    ):
        d = tmp_path / "my-skill"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: different-name\ndescription: Different.\n---\nBody content."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)
        result = await load_skill("my-skill")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_load_skill_surfaces_matching_invalid_bundle_diagnostic(
        self, tmp_path, monkeypatch
    ):
        skill_dir = tmp_path / "broken"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: broken\n---\nBody content.")
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)

        result = await load_skill("broken")

        assert "Skill 'broken' is invalid" in result
        assert "requires a non-empty description" in result

    @pytest.mark.asyncio
    async def test_load_skill_not_found(self, tmp_path, monkeypatch):
        d = tmp_path / "existing"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: existing\ndescription: Existing.\n---\nBody."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)
        result = await load_skill("existng")
        assert "not found" in result
        assert "existing" in result
        assert "action='list'" in result
        assert len(result) < 200

    @pytest.mark.asyncio
    async def test_load_skill_dir_missing(self, tmp_path, monkeypatch):
        # Multi-root discovery means the "no roots" message is only
        # produced when *every* root is absent. Force all four to point
        # under tmp_path so the developer's real opencode-global library
        # doesn't leak in.
        gone = tmp_path / "gone"
        monkeypatch.setattr(
            "app.agent.tools.builtin.skill._iter_skill_roots", lambda: [gone]
        )
        result = await load_skill("anything")
        assert "Skills directory not found" in result

    def test_tool_description_tells_agent_not_to_reload_visible_skills(self):
        description = _skill_tool_description()
        assert "at most once per selected skill" in description
        assert "reuse instructions already visible" in description
        assert "action='list'" in description

    @pytest.mark.asyncio
    async def test_list_action_returns_full_catalog(self, tmp_path, monkeypatch):
        d = tmp_path / "analysis"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: analysis\ndescription: Full catalog description\n---\nBody."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)

        result = await load_skill(action="list")

        assert "analysis" in result
        assert "Full catalog description" in result

    @pytest.mark.asyncio
    async def test_activation_lists_and_reads_exact_resource(
        self, tmp_path, monkeypatch
    ):
        skill_dir = tmp_path / "analysis"
        references = skill_dir / "references"
        references.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: analysis\ndescription: Analyze data.\n---\n"
            "Read references/checks.md only when validating output."
        )
        (references / "checks.md").write_text("# Quality checks\n- Reconcile totals.")
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)
        state = SimpleNamespace(metadata={}, messages_for_llm=[])

        activated = await load_skill("analysis", _state=state)
        resource = await load_skill(
            "analysis",
            action="read_resource",
            resource_path="references/checks.md",
            _state=state,
        )
        traversal = await load_skill(
            "analysis",
            action="read_resource",
            resource_path="../outside.md",
            _state=state,
        )

        assert "references/checks.md" in activated
        assert "Reconcile totals" in resource
        assert "stay inside" in traversal

    def test_tool_description_omits_catalog_until_list_action(
        self, tmp_path, monkeypatch
    ):
        d = tmp_path / "analysis"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: analysis\ndescription: Expensive full description\n---\nBody."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)

        description = _skill_tool_description()

        assert "analysis" not in description
        assert "Expensive full description" not in description


# ---------------------------------------------------------------------------
# Path-token substitution
#
# The skill tool replaces a small whitelist of ``{TOKEN}`` placeholders in
# both catalog output and the body returned by ``load_skill``. This is what
# lets a skill say ``cat {EVOFLUX_CONFIG_DIR}/mcp.json`` and have the
# agent receive a concrete absolute path it can hand to its file/shell
# tools without further interpretation.
#
# We invalidate the lru-cached discovery between tests because the cache
# key is the directory path, and ``_render_tokens`` reads ``settings``
# fresh on each call — but the cache hit would short-circuit that.
# ---------------------------------------------------------------------------


class TestTokenSubstitution:
    @pytest.fixture(autouse=True)
    def _clear_skill_cache(self):
        from app.agent.tools.builtin.skill import _discover_skills_cached

        _discover_skills_cached.cache_clear()
        yield
        _discover_skills_cached.cache_clear()

    def test_description_tokens_replaced_in_discovery(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.EVOFLUX_CONFIG_DIR", "/x/cfg")
        d = tmp_path / "demo"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: demo\ndescription: edits {EVOFLUX_CONFIG_DIR}/mcp.json\n---\nBody."
        )

        result = discover_skills(skills_dir=tmp_path)

        # The literal placeholder must NOT survive into what the LLM sees.
        assert result["demo"]["description"] == "edits /x/cfg/mcp.json"
        # The new ``dir`` field exposes the skill's absolute directory
        # so callers don't need a second filesystem walk.
        assert result["demo"]["dir"] == str(d)

    def test_unknown_braces_in_description_preserved(self, tmp_path):
        """Anything not in the recognised whitelist (e.g. format-string
        placeholders in a description) must round-trip unchanged."""
        d = tmp_path / "demo"
        d.mkdir()
        # Quoted YAML scalar so the colon inside braces doesn't trip
        # the parser. ``{NOT_A_TOKEN}`` is what we actually want to test.
        (d / "SKILL.md").write_text(
            '---\nname: demo\ndescription: "see {NOT_A_TOKEN} for details"\n---\nBody.'
        )

        result = discover_skills(skills_dir=tmp_path)
        assert result["demo"]["description"] == "see {NOT_A_TOKEN} for details"

    @pytest.mark.asyncio
    async def test_body_tokens_replaced_on_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.core.config.settings.EVOFLUX_CONFIG_DIR", "/x/cfg")
        monkeypatch.setattr("app.core.config.settings.AGENTS_DIR", "/x/cfg/agents")
        monkeypatch.setattr("app.core.config.settings.SKILLS_DIR", "/x/cfg/skills")
        d = tmp_path / "mcp-installer"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: mcp-installer\ndescription: Install MCP servers.\n---\n"
            "Edit {EVOFLUX_CONFIG_DIR}/mcp.json. "
            "Agents live under {AGENTS_DIR}. "
            "Other skills under {SKILLS_DIR}. "
            "Run {SKILL_DIR}/scripts/mcp.py."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)

        body = await load_skill("mcp-installer")

        assert "{EVOFLUX_CONFIG_DIR}" not in body
        assert "{AGENTS_DIR}" not in body
        assert "{SKILLS_DIR}" not in body
        assert "{SKILL_DIR}" not in body
        assert "/x/cfg/mcp.json" in body
        assert "/x/cfg/agents" in body
        assert "/x/cfg/skills" in body
        # SKILL_DIR resolves to this skill's absolute directory.
        assert str(d.resolve()) in body

    @pytest.mark.asyncio
    async def test_body_unknown_braces_preserved(self, tmp_path, monkeypatch):
        """JSON examples and other ``{...}`` content inside the body must
        survive substitution untouched — only the four whitelisted token
        names are replaced."""
        d = tmp_path / "demo"
        d.mkdir()
        body_text = (
            'Use this payload: {"servers": {"name": "x"}}\n'
            "And refer to {NOT_A_TOKEN} for context."
        )
        (d / "SKILL.md").write_text(
            f"---\nname: demo\ndescription: Demo workflow.\n---\n{body_text}"
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)

        body = await load_skill("demo")
        assert body == body_text


# ---------------------------------------------------------------------------
# Multi-root discovery (project/global × EvoFlux/opencode)
#
# Skills are discovered from four roots in this precedence order:
#   1. {cwd}/.evoflux/skills/
#   2. {cwd}/.opencode/skills/
#   3. _SKILLS_DIR  (EvoFlux global, typically {CONFIG_DIR}/skills)
#   4. ~/.config/opencode/skills/
#
# We isolate every root under tmp_path by patching ``_iter_skill_roots``
# so the developer's real ``~/.config/opencode/skills/`` doesn't leak in.
# ---------------------------------------------------------------------------


class TestMultiRootDiscovery:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from app.agent.tools.builtin.skill import _discover_skills_cached

        _discover_skills_cached.cache_clear()
        yield
        _discover_skills_cached.cache_clear()

    @pytest.fixture
    def sandbox_workspace(self, tmp_path):
        workspace = tmp_path / "workspace"
        token = set_sandbox(SandboxConfig(workspace=str(workspace), session_id="s1"))
        try:
            yield workspace
        finally:
            _sandbox_ctx.reset(token)

    @pytest.fixture
    def roots(self, tmp_path, monkeypatch):
        """Patch ``_iter_skill_roots`` to a fresh four-root layout under tmp_path."""
        project_oad = tmp_path / "proj" / ".evoflux" / "skills"
        project_oc = tmp_path / "proj" / ".opencode" / "skills"
        global_oad = tmp_path / "config" / "skills"
        global_oc = tmp_path / "home" / ".config" / "opencode" / "skills"
        ordered = [project_oad, project_oc, global_oad, global_oc]
        monkeypatch.setattr(
            "app.agent.tools.builtin.skill._iter_skill_roots", lambda: ordered
        )
        return ordered

    def _write_skill(self, root, name, description, body):
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n{body}"
        )

    def test_opencode_global_skill_discovered(self, roots):
        _project_oad, _project_oc, _global_oad, global_oc = roots
        self._write_skill(global_oc, "research", "From opencode", "Body.")

        result = discover_skills()

        assert "research" in result
        assert result["research"]["description"] == "From opencode"

    def test_precedence_EVOFLUX_wins_over_opencode_on_collision(self, roots):
        project_oad, _project_oc, _global_oad, global_oc = roots
        self._write_skill(global_oc, "research", "opencode", "opencode body")
        self._write_skill(project_oad, "research", "EvoFlux", "EvoFlux body")

        result = discover_skills()

        assert result["research"]["description"] == "EvoFlux"
        assert result["research"]["file"] == "research/SKILL.md"
        # The winning ``dir`` must point at the EvoFlux-project copy.
        assert str(project_oad / "research") == result["research"]["dir"]

    def test_local_opencode_skill_wins_over_global_EvoFlux(self, roots):
        _project_oad, project_oc, global_oad, _global_oc = roots
        self._write_skill(global_oad, "research", "global EvoFlux", "global body")
        self._write_skill(project_oc, "research", "local opencode", "local body")

        result = discover_skills()

        assert result["research"]["description"] == "local opencode"
        assert str(project_oc / "research") == result["research"]["dir"]

    def test_skills_from_all_roots_merged(self, roots):
        project_oad, project_oc, global_oad, global_oc = roots
        self._write_skill(project_oad, "alpha", "a", "ab")
        self._write_skill(project_oc, "beta", "b", "bb")
        self._write_skill(global_oad, "gamma", "g", "gb")
        self._write_skill(global_oc, "delta", "d", "db")

        result = discover_skills()

        assert set(result.keys()) == {"alpha", "beta", "gamma", "delta"}

    @pytest.mark.asyncio
    async def test_mode_filter_selects_lower_precedence_usable_collision(self, roots):
        project_oad, _project_oc, global_oad, _global_oc = roots
        self._write_skill(project_oad, "shared", "Coding copy", "Coding body")
        (project_oad / "shared" / ".evoflux.json").write_text('{"modes":["coding"]}\n')
        self._write_skill(global_oad, "shared", "Work copy", "Work body")
        (global_oad / "shared" / ".evoflux.json").write_text('{"modes":["work"]}\n')
        _discover_skills_cached.cache_clear()

        result = await load_skill("shared", _mode="work")

        assert result == "Work body"

    def test_project_skills_use_active_sandbox_workspace(self, sandbox_workspace):
        project_oad = sandbox_workspace / ".evoflux" / "skills"
        self._write_skill(project_oad, "oad/commit", "Commit workflow", "Body.")

        result = discover_skills()

        assert "oad/commit" in result
        assert result["oad/commit"]["description"] == "Commit workflow"
        assert str(project_oad / "oad" / "commit") == result["oad/commit"]["dir"]

    def test_standard_roots_include_agents_claude_and_cross_repo(self, tmp_path):
        primary = tmp_path / "primary"
        sibling = tmp_path / "sibling"
        primary.mkdir()
        sibling.mkdir()
        token = set_sandbox(
            SandboxConfig(
                workspace=str(primary),
                session_id="cross-repo",
                extra_workspace_paths=[str(sibling)],
            )
        )
        try:
            roots = _iter_skill_roots()
        finally:
            _sandbox_ctx.reset(token)

        assert primary / ".agents" / "skills" in roots
        assert primary / ".claude" / "skills" in roots
        assert sibling / ".agents" / "skills" in roots
        assert sibling / ".claude" / "skills" in roots

    def test_sandbox_project_skill_shadows_process_cwd_skill(
        self, tmp_path, monkeypatch, sandbox_workspace
    ):
        process_cwd = tmp_path / "process-cwd"
        self._write_skill(
            process_cwd / ".evoflux" / "skills",
            "oad/commit",
            "Wrong cwd skill",
            "Wrong body.",
        )
        self._write_skill(
            sandbox_workspace / ".evoflux" / "skills",
            "oad/commit",
            "Workspace skill",
            "Workspace body.",
        )
        monkeypatch.chdir(process_cwd)

        result = discover_skills()

        assert result["oad/commit"]["description"] == "Workspace skill"
        assert result["oad/commit"]["dir"] == str(
            sandbox_workspace / ".evoflux" / "skills" / "oad" / "commit"
        )

    def test_sandbox_project_skills_precede_global_EvoFlux(
        self, tmp_path, monkeypatch, sandbox_workspace
    ):
        global_oad = tmp_path / "config" / "skills"
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", global_oad)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
        self._write_skill(global_oad, "oad/commit", "Global skill", "Global body.")
        self._write_skill(
            sandbox_workspace / ".evoflux" / "skills",
            "oad/commit",
            "Workspace skill",
            "Workspace body.",
        )

        result = discover_skills()

        assert result["oad/commit"]["description"] == "Workspace skill"

    @pytest.mark.asyncio
    async def test_load_skill_reads_sandbox_project_body(self, sandbox_workspace):
        self._write_skill(
            sandbox_workspace / ".evoflux" / "skills",
            "oad/commit",
            "Commit workflow",
            "Workspace commit body.",
        )

        body = await load_skill("oad/commit")

        assert body == "Workspace commit body."

    @pytest.mark.asyncio
    async def test_load_skill_finds_opencode_skill(self, roots):
        _project_oad, _project_oc, _global_oad, global_oc = roots
        self._write_skill(global_oc, "research", "x", "Opencode body.")

        body = await load_skill("research")

        assert body == "Opencode body."

    @pytest.mark.asyncio
    async def test_load_skill_precedence_EVOFLUX_wins(self, roots):
        project_oad, _project_oc, _global_oad, global_oc = roots
        self._write_skill(global_oc, "research", "x", "Opencode body.")
        self._write_skill(project_oad, "research", "x", "EvoFlux body.")

        body = await load_skill("research")

        assert body == "EvoFlux body."

    def test_cache_invalidates_when_opencode_root_changes(self, roots):
        _project_oad, _project_oc, _global_oad, global_oc = roots
        self._write_skill(global_oc, "alpha", "a", "ab")
        first = discover_skills()
        assert set(first.keys()) == {"alpha"}

        # Adding a skill to the opencode-global root must invalidate the
        # cache. We use ``write_text`` after a fresh mkdir to guarantee a
        # different signature; the directory mtime alone might tie at the
        # nanosecond on some filesystems.
        self._write_skill(global_oc, "beta", "b", "bb")
        second = discover_skills()

        assert set(second.keys()) == {"alpha", "beta"}


class TestBuiltinSkills:
    @pytest.fixture(autouse=True)
    def _builtin_only(self, monkeypatch):
        _discover_skills_cached.cache_clear()
        monkeypatch.setattr(
            "app.agent.tools.builtin.skill._iter_skill_roots",
            lambda: [_builtin_skills_dir()],
        )
        yield
        _discover_skills_cached.cache_clear()

    def test_operational_builtin_skills_are_discovered(self):
        result = discover_skills()

        assert {
            "self-healing",
            "skill-installer",
            "mcp-installer",
            "plugin-installer",
            "review-pull-requests",
        }.issubset(result)
        assert (_builtin_skills_dir() / "mcp-installer" / "mcp_apply.py").is_file()

    def test_builtin_catalog_is_curated_and_mode_scoped(self):
        assert set(discover_skills()) == {
            "algorithmic-art",
            "canvas-design",
            "code-graph-navigation",
            "coding-debugging",
            "coding-implementation",
            "coding-investigation",
            "coding-migration",
            "coding-performance",
            "coding-review",
            "coding-router",
            "coding-security",
            "coding-testing",
            "docx",
            "frontend-design",
            "mcp-installer",
            "pdf",
            "plugin-installer",
            "pptx",
            "review-pull-requests",
            "self-healing",
            "skill-installer",
            "theme-factory",
            "work-decision",
            "work-data-analysis",
            "work-planning",
            "work-research",
            "work-router",
            "work-writing",
            "xlsx",
        }
        assert set(discover_skills()) == set(BUNDLED_SKILL_MODES)

    def test_mode_catalogs_expose_only_relevant_workflows(self):
        discovered = discover_skills()
        work = set(skills_for_mode(discovered, "work"))
        coding = set(skills_for_mode(discovered, "coding"))

        assert {"work-research", "work-decision", "docx", "xlsx"} <= work
        assert {
            "code-graph-navigation",
            "coding-investigation",
            "coding-implementation",
            "coding-debugging",
            "coding-review",
            "coding-migration",
            "coding-performance",
            "review-pull-requests",
            "coding-security",
            "coding-testing",
        } <= coding
        assert "code-graph-navigation" not in work
        assert "coding-investigation" not in work
        assert "work-research" not in coding

    def test_custom_skill_mode_scope_comes_from_sidecar(self, tmp_path):
        skill_dir = tmp_path / "custom"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: custom\ndescription: Custom.\n---\nBody."
        )
        (skill_dir / ".evoflux.json").write_text('{"modes":["coding"]}\n')

        discovered = discover_skills(skills_dir=tmp_path)

        assert discovered["custom"]["modes"] == ["coding"]
        assert "custom" not in skills_for_mode(discovered, "work")
        assert "custom" in skills_for_mode(discovered, "coding")

    @pytest.mark.asyncio
    async def test_load_and_list_reject_out_of_mode_builtin_skill(self):
        result = await load_skill("coding-investigation", _mode="work")
        assert "not available in work mode" in result

        work_catalog = await load_skill(action="list", _mode="work")
        assert "work-router" in work_catalog
        assert "work-research" not in work_catalog
        assert "coding-investigation" not in work_catalog

    @pytest.mark.asyncio
    async def test_router_can_delegate_to_explicit_only_specialist(self):
        state = SimpleNamespace(metadata={}, messages_for_llm=[])

        router = await load_skill("coding-router", _mode="coding", _state=state)
        specialist = await load_skill(
            "coding-investigation", _mode="coding", _state=state
        )
        catalog = await load_skill(action="list", _mode="coding", _state=state)

        assert "coding-investigation" in router
        assert '<skill_content name="coding-investigation"' in specialist
        assert "coding-investigation" not in catalog
        assert "code-graph-navigation" in catalog
        assert "switch to the `code-graph-navigation` workflow" in specialist
        assert (
            "definition, callers, callees, references, neighborhood" not in specialist
        )

    @pytest.mark.asyncio
    async def test_code_graph_skill_is_visible_and_loads_native_tool_contract(self):
        state = SimpleNamespace(metadata={}, messages_for_llm=[])

        catalog = await load_skill(action="list", _mode="coding", _state=state)
        navigation = await load_skill(
            "code-graph-navigation", _mode="coding", _state=state
        )

        assert "code-graph-navigation" in catalog
        assert '<skill_content name="code-graph-navigation"' in navigation
        assert "native `code_graph` tool" in navigation
        assert "Never translate the user's sentence" in navigation

    @pytest.mark.asyncio
    async def test_code_graph_skill_is_unavailable_in_work_mode(self):
        result = await load_skill("code-graph-navigation", _mode="work")

        assert "not available in work mode" in result

    def test_all_builtin_skills_follow_bundle_contract(self):
        """Keep bundled skills portable and compatible with progressive disclosure."""
        root = _builtin_skills_dir()
        for skill_file in sorted(root.glob("*/SKILL.md")):
            text = skill_file.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            assert set(meta) == {"name", "description"}, skill_file
            assert meta["name"] == skill_file.parent.name, skill_file
            assert isinstance(meta["description"], str) and meta["description"].strip()
            assert body.strip(), skill_file

    def test_native_code_graph_contract_has_one_skill_owner(self):
        owners = [
            skill_file.parent.name
            for skill_file in sorted(_builtin_skills_dir().glob("*/SKILL.md"))
            if "code_graph" in skill_file.read_text(encoding="utf-8")
        ]

        assert owners == ["code-graph-navigation"]

    def test_builtin_skill_resource_links_exist(self):
        root = _builtin_skills_dir()
        resource_link = re.compile(
            r"(?:\[[^\]]+\]\(([^)]+)\)|"
            r"`((?:references?|scripts?|assets?|templates?|themes?)/[^`]+)`)"
        )
        missing: list[str] = []
        for skill_file in sorted(root.glob("*/SKILL.md")):
            text = skill_file.read_text(encoding="utf-8")
            for match in resource_link.finditer(text):
                raw = (match.group(1) or match.group(2)).split("#", 1)[0]
                if raw.startswith(("http:", "https:", "#")):
                    continue
                if not (skill_file.parent / raw).exists():
                    missing.append(f"{skill_file.parent.name}: {raw}")
        assert missing == []

    def test_pptx_skill_keeps_style_questions_inside_the_same_run(self):
        """Presentation style policy must not force avoidable chat turns."""
        skill = (_builtin_skills_dir() / "pptx" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        normalized = " ".join(skill.split())

        assert "Treat the user's visual direction as confirmed" in normalized
        assert "continue without asking the user to approve" in normalized
        assert "call the `ask_user` tool" in normalized
        assert "deferred `ask_user`" not in normalized
        assert "resume outline, authoring, rendering, and composition" in normalized
        assert "Never send a plain assistant message asking" in normalized

    @pytest.mark.asyncio
    async def test_builtin_skill_dir_points_at_auxiliary_files(self):
        body = await load_skill("mcp-installer")

        skill_dir = str((_builtin_skills_dir() / "mcp-installer").resolve())
        assert skill_dir in body
        assert "mcp_apply.py" in body


# ---------------------------------------------------------------------------
# Sub-skill support (one nested level)
#
# Skills may live one level deeper than the flat layout:
#   skills/{parent}/{sub}/SKILL.md  →  name "parent/sub"
#
# The parent directory itself may or may not have its own SKILL.md — both
# configurations are valid and must coexist.
# ---------------------------------------------------------------------------


class TestSubSkills:
    """Tests for one-level nested skill support."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _discover_skills_cached.cache_clear()
        yield
        _discover_skills_cached.cache_clear()

    # ── _iter_skill_paths ────────────────────────────────────────────────

    def test_iter_yields_nested_skill(self, tmp_path):
        parent = tmp_path / "git"
        sub = parent / "commit"
        sub.mkdir(parents=True)
        (sub / "SKILL.md").write_text("---\nname: git/commit\n---\nBody.")

        results = list(_iter_skill_paths(tmp_path))

        assert len(results) == 1
        path, stem = results[0]
        assert stem == "git/commit"
        assert path == sub / "SKILL.md"

    def test_iter_yields_flat_and_nested_together(self, tmp_path):
        # Flat skill
        flat = tmp_path / "search"
        flat.mkdir()
        (flat / "SKILL.md").write_text("---\nname: search\n---\nSearch.")
        # Nested skill under the same parent
        nested = tmp_path / "git" / "commit"
        nested.mkdir(parents=True)
        (nested / "SKILL.md").write_text("---\nname: git/commit\n---\nCommit.")

        stems = {stem for _, stem in _iter_skill_paths(tmp_path)}

        assert stems == {"search", "git/commit"}

    def test_iter_parent_with_own_skill_md_and_sub_skills(self, tmp_path):
        """Parent dir can have its own SKILL.md AND nested sub-skills."""
        parent = tmp_path / "git"
        parent.mkdir()
        (parent / "SKILL.md").write_text("---\nname: git\n---\nGit overview.")
        sub = parent / "commit"
        sub.mkdir()
        (sub / "SKILL.md").write_text("---\nname: git/commit\n---\nCommit detail.")

        stems = {stem for _, stem in _iter_skill_paths(tmp_path)}

        assert stems == {"git", "git/commit"}

    def test_iter_ignores_directory_without_skill_md(self, tmp_path):
        """A sub-directory with no SKILL.md (e.g. scripts/) is never yielded."""
        parent = tmp_path / "git"
        scripts = parent / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "helper.py").write_text("# helper")

        results = list(_iter_skill_paths(tmp_path))

        assert results == []

    # ── discover_skills ──────────────────────────────────────────────────

    def test_discover_nested_skill(self, tmp_path):
        sub = tmp_path / "git" / "commit"
        sub.mkdir(parents=True)
        (sub / "SKILL.md").write_text(
            "---\nname: git/commit\ndescription: Make a git commit.\n---\nBody."
        )

        result = discover_skills(skills_dir=tmp_path)

        assert "git/commit" in result
        assert result["git/commit"]["description"] == "Make a git commit."
        assert result["git/commit"]["file"] == "git/commit/SKILL.md"

    def test_discover_flat_and_nested_coexist(self, tmp_path):
        (tmp_path / "search").mkdir()
        (tmp_path / "search" / "SKILL.md").write_text(
            "---\nname: search\ndescription: Search.\n---\nSearch body."
        )
        sub = tmp_path / "git" / "push"
        sub.mkdir(parents=True)
        (sub / "SKILL.md").write_text(
            "---\nname: git/push\ndescription: Push commits.\n---\nPush body."
        )

        result = discover_skills(skills_dir=tmp_path)

        assert set(result.keys()) == {"search", "git/push"}

    def test_discover_nested_name_from_stem_when_no_frontmatter_name(self, tmp_path):
        """Stem ``parent/sub`` is used when frontmatter has no ``name`` key."""
        sub = tmp_path / "git" / "rebase"
        sub.mkdir(parents=True)
        (sub / "SKILL.md").write_text("---\ndescription: Rebase.\n---\nBody.")

        result = discover_skills(skills_dir=tmp_path)

        assert "git/rebase" in result

    def test_discover_precedence_flat_over_nested_same_name(self, tmp_path):
        """If a flat skill and a nested SKILL.md accidentally resolve to the
        same name, the flat one (discovered first in sorted order) wins."""
        flat = tmp_path / "git"
        flat.mkdir()
        (flat / "SKILL.md").write_text(
            "---\nname: git\ndescription: flat\n---\nFlat body."
        )
        sub = flat / "sub"
        sub.mkdir()
        (sub / "SKILL.md").write_text(
            "---\nname: git/sub\ndescription: nested\n---\nNested body."
        )

        result = discover_skills(skills_dir=tmp_path)

        # Both should appear under their distinct names.
        assert "git" in result
        assert "git/sub" in result

    # ── _skills_dir_signature ────────────────────────────────────────────

    def test_signature_changes_when_nested_skill_added(self, tmp_path):
        sig_before = _skills_dir_signature(tmp_path)

        sub = tmp_path / "git" / "commit"
        sub.mkdir(parents=True)
        (sub / "SKILL.md").write_text("---\nname: git/commit\n---\nBody.")

        sig_after = _skills_dir_signature(tmp_path)

        assert sig_after != sig_before

    def test_signature_changes_when_nested_skill_edited(self, tmp_path):
        sub = tmp_path / "git" / "commit"
        sub.mkdir(parents=True)
        skill_file = sub / "SKILL.md"
        skill_file.write_text("---\nname: git/commit\n---\nOriginal.")

        sig_before = _skills_dir_signature(tmp_path)

        import time

        time.sleep(0.01)  # ensure mtime changes on fast filesystems
        skill_file.write_text("---\nname: git/commit\n---\nEdited.")

        sig_after = _skills_dir_signature(tmp_path)

        assert sig_after != sig_before

    def test_signature_changes_when_skill_scope_changes(self, tmp_path):
        skill_dir = tmp_path / "research"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: research\n---\nBody.")
        scope = skill_dir / ".evoflux.json"

        sig_before = _skills_dir_signature(tmp_path)
        scope.write_text('{"modes":["work"]}\n')
        sig_after = _skills_dir_signature(tmp_path)

        assert sig_after != sig_before

    # ── load_skill ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_load_nested_skill_by_slash_name(self, tmp_path, monkeypatch):
        sub = tmp_path / "git" / "commit"
        sub.mkdir(parents=True)
        (sub / "SKILL.md").write_text(
            "---\nname: git/commit\ndescription: Commit workflow.\n---\nCommit body."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)

        result = await load_skill("git/commit")

        assert result == "Commit body."

    @pytest.mark.asyncio
    async def test_load_nested_skill_rejects_stem_alias(self, tmp_path, monkeypatch):
        sub = tmp_path / "git" / "commit"
        sub.mkdir(parents=True)
        (sub / "SKILL.md").write_text(
            "---\nname: git-commit\ndescription: Commit workflow.\n---\nCommit body by stem."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)

        result = await load_skill("git/commit")

        assert "not found" in result

    @pytest.mark.asyncio
    async def test_flat_and_nested_skill_both_loadable(self, tmp_path, monkeypatch):
        (tmp_path / "search").mkdir()
        (tmp_path / "search" / "SKILL.md").write_text(
            "---\nname: search\ndescription: Search workflow.\n---\nSearch body."
        )
        sub = tmp_path / "git" / "push"
        sub.mkdir(parents=True)
        (sub / "SKILL.md").write_text(
            "---\nname: git/push\ndescription: Push workflow.\n---\nPush body."
        )
        monkeypatch.setattr("app.agent.tools.builtin.skill._SKILLS_DIR", tmp_path)

        assert await load_skill("search") == "Search body."
        assert await load_skill("git/push") == "Push body."
