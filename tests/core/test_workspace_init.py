from __future__ import annotations

from pathlib import Path

from app.cli.seed import SeedResult
from app.cli.seed import _install_from_local
from app.cli.seed import _replace_placeholder_if_needed
from app.core.workspace_init import ensure_workspace_initialized


def test_ensure_workspace_initialized_creates_roots_and_seeds(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import app.core.workspace_init as workspace_init

    config = tmp_path / "config"
    called: list[tuple[Path, str]] = []

    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data")
    )
    monkeypatch.setattr(workspace_init.settings, "EVOFLUX_CONFIG_DIR", str(config))
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_STATE_DIR", str(tmp_path / "state")
    )
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_WORKSPACE_DIR", str(tmp_path / "workspace")
    )
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_WIKI_DIR", str(tmp_path / "wiki")
    )
    monkeypatch.setattr(workspace_init.settings, "AGENTS_DIR", str(config / "agents"))
    monkeypatch.setattr(workspace_init.settings, "SKILLS_DIR", str(config / "skills"))
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_PLUGINS_DIRS", str(config / "plugins")
    )

    def install_seed(config_dir: Path, *, provider_model: str) -> SeedResult:
        called.append((config_dir, provider_model))
        (config_dir / "agents").mkdir(parents=True, exist_ok=True)
        (config_dir / "agents" / "evoflux.md").write_text(
            "---\nmodel: __PROVIDER_MODEL__\n---\n"
        )
        return SeedResult(["evoflux.md"], [], [], [], "test")

    monkeypatch.setattr("app.cli.seed.install_seed", install_seed)

    ensure_workspace_initialized()

    assert (config / "agents").is_dir()
    assert (config / "skills").is_dir()
    assert (config / "plugins").is_dir()
    assert (tmp_path / "cache").is_dir()
    assert (config / "agents" / "executor.md").is_file()
    assert (config / "agents" / "explorer.md").is_file()
    assert (config / "agents" / "coding" / "coder.md").is_file()
    assert (config / "agents" / "coding" / "explorer.md").is_file()
    assert called == [(config, "__PROVIDER_MODEL__")]


def test_ensure_workspace_initialized_skips_seed_when_agents_exist(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import app.core.workspace_init as workspace_init

    config = tmp_path / "config"
    agents = config / "agents"
    agents.mkdir(parents=True)
    (agents / "existing.md").write_text(
        "---\nname: existing\nrole: lead\nmodel: openai:gpt-5\ntemperature: 0.4\n---\n"
    )

    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data")
    )
    monkeypatch.setattr(workspace_init.settings, "EVOFLUX_CONFIG_DIR", str(config))
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_STATE_DIR", str(tmp_path / "state")
    )
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_WORKSPACE_DIR", str(tmp_path / "workspace")
    )
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_WIKI_DIR", str(tmp_path / "wiki")
    )
    monkeypatch.setattr(workspace_init.settings, "AGENTS_DIR", str(agents))
    monkeypatch.setattr(workspace_init.settings, "SKILLS_DIR", str(config / "skills"))
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_PLUGINS_DIRS", str(config / "plugins")
    )
    monkeypatch.setattr(
        "app.cli.seed.install_seed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected seed")
        ),
    )

    ensure_workspace_initialized()

    assert (config / "plugins").is_dir()
    assert "temperature:" not in (agents / "existing.md").read_text()


def test_ensure_workspace_initialized_materializes_builtins_without_seed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import app.core.workspace_init as workspace_init

    config = tmp_path / "config"
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data")
    )
    monkeypatch.setattr(workspace_init.settings, "EVOFLUX_CONFIG_DIR", str(config))
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_STATE_DIR", str(tmp_path / "state")
    )
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_WORKSPACE_DIR", str(tmp_path / "workspace")
    )
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_WIKI_DIR", str(tmp_path / "wiki")
    )
    monkeypatch.setattr(workspace_init.settings, "AGENTS_DIR", str(config / "agents"))
    monkeypatch.setattr(workspace_init.settings, "SKILLS_DIR", str(config / "skills"))
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_PLUGINS_DIRS", str(config / "plugins")
    )

    from app.cli.seed import SeedDownloadError

    monkeypatch.setattr(
        "app.cli.seed.install_seed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SeedDownloadError("offline")),
    )

    ensure_workspace_initialized()

    assert (config / "agents" / "executor.md").is_file()
    assert (config / "agents" / "explorer.md").is_file()
    assert (config / "agents" / "coding" / "coder.md").is_file()
    assert (config / "agents" / "coding" / "explorer.md").is_file()
    # Regression: a failed seed download must not leave the workspace
    # without a lead agent (the seed bundle normally supplies it).
    assert (config / "agents" / "evoflux.md").is_file()
    assert (config / "agents" / "coding" / "evoflux.md").is_file()


def test_ensure_workspace_initialized_heals_preexisting_leadless_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Regression: a workspace left without a lead by a past failed seed
    download (only member blueprints on disk) must self-heal on the *next*
    startup too, not just when the agents dir starts out empty."""
    import app.core.workspace_init as workspace_init

    config = tmp_path / "config"
    agents = config / "agents"
    agents.mkdir(parents=True)
    # Simulate the broken state: builtin member blueprints materialized by
    # an earlier run whose seed download failed, but no lead agent.
    (agents / "executor.md").write_text(
        "---\nname: executor\nrole: member\nmodel: __PROVIDER_MODEL__\n---\n"
    )

    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data")
    )
    monkeypatch.setattr(workspace_init.settings, "EVOFLUX_CONFIG_DIR", str(config))
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_STATE_DIR", str(tmp_path / "state")
    )
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache")
    )
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_WORKSPACE_DIR", str(tmp_path / "workspace")
    )
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_WIKI_DIR", str(tmp_path / "wiki")
    )
    monkeypatch.setattr(workspace_init.settings, "AGENTS_DIR", str(agents))
    monkeypatch.setattr(workspace_init.settings, "SKILLS_DIR", str(config / "skills"))
    monkeypatch.setattr(
        workspace_init.settings, "EVOFLUX_PLUGINS_DIRS", str(config / "plugins")
    )
    monkeypatch.setattr(
        "app.cli.seed.install_seed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unexpected seed: agents dir already has files")
        ),
    )

    ensure_workspace_initialized()

    assert (agents / "evoflux.md").is_file()


def test_replace_placeholder_updates_only_seed_model(tmp_path: Path) -> None:
    agent = tmp_path / "agent.md"
    agent.write_text(
        "---\nname: evoflux\nmodel: __PROVIDER_MODEL__\n---\n\nCustom prompt\n",
        encoding="utf-8",
    )

    changed = _replace_placeholder_if_needed(agent, "codex:gpt-5.5")

    assert changed is True
    assert agent.read_text(encoding="utf-8") == (
        "---\nname: evoflux\nmodel: codex:gpt-5.5\n---\n\nCustom prompt\n"
    )


def test_install_seed_writes_runtime_settings_model(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "agents").mkdir()
    (seed / "skills").mkdir()

    result = _install_from_local(
        seed,
        tmp_path / "config",
        provider_model="codex:gpt-5.5",
    )

    assert result.configs_written == [
        "settings.yaml",
    ]
    settings = (tmp_path / "config" / "settings.yaml").read_text(encoding="utf-8")
    assert "dream:" in settings
    assert "model: codex:gpt-5.5" in settings


def test_install_seed_leaves_runtime_settings_model_empty_for_placeholder(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "agents").mkdir()
    (seed / "skills").mkdir()

    result = _install_from_local(
        seed,
        tmp_path / "config",
        provider_model="__PROVIDER_MODEL__",
    )

    assert "settings.yaml" in result.configs_written
    settings = (tmp_path / "config" / "settings.yaml").read_text(encoding="utf-8")
    assert "__PROVIDER_MODEL__" not in settings
    assert "model:" not in settings


def test_install_seed_prunes_untouched_removed_first_party_agents(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "agents").mkdir()
    (seed / "skills").mkdir()
    config = tmp_path / "config"
    legacy = config / "agents" / "consultant.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "---\nname: consultant\nrole: member\nmodel: codex:gpt-5\n---\n\n"
        'You are "consultant".\n\nOld shipped body.\n',
        encoding="utf-8",
    )

    result = _install_from_local(seed, config, provider_model="codex:gpt-5")

    assert result.agents_removed == ["consultant.md"]
    assert not legacy.exists()


def test_install_seed_keeps_custom_file_with_removed_first_party_name(
    tmp_path: Path,
) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "agents").mkdir()
    (seed / "skills").mkdir()
    config = tmp_path / "config"
    custom = config / "agents" / "coding" / "qa.md"
    custom.parent.mkdir(parents=True)
    custom.write_text(
        "---\nname: qa\nrole: member\nmodel: codex:gpt-5\n---\n\n"
        "Project-specific release checklist owner.\n",
        encoding="utf-8",
    )

    result = _install_from_local(seed, config, provider_model="codex:gpt-5")

    assert result.agents_removed == []
    assert custom.exists()


def test_install_seed_prunes_untouched_coding_executor(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "agents").mkdir()
    (seed / "skills").mkdir()
    config = tmp_path / "config"
    legacy = config / "agents" / "coding" / "executor.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "---\nname: executor\nrole: member\nmodel: codex:gpt-5\n---\n\n"
        'You are "executor".\n\nOld shipped body.\n',
        encoding="utf-8",
    )

    result = _install_from_local(seed, config, provider_model="codex:gpt-5")

    assert result.agents_removed == ["coding/executor.md"]
    assert not legacy.exists()


# ── _local_seed_dir: repo checkout vs wheel-bundled app/_seed ────────────────


def _fake_checkout(tmp_path: Path) -> Path:
    """A fake ``app/cli/seed.py`` location with no seed/ next to it."""
    fake_module = tmp_path / "pkg" / "app" / "cli" / "seed.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("")
    return fake_module


def test_local_seed_dir_prefers_repo_checkout(monkeypatch, tmp_path: Path) -> None:
    import app as app_pkg
    import app.cli.seed as seed_mod

    # Fake source checkout: <repo>/app/cli/seed.py + <repo>/seed/agents/.
    repo = tmp_path / "repo"
    fake_module = repo / "app" / "cli" / "seed.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text("")
    (repo / "seed" / "agents").mkdir(parents=True)
    (repo / "seed" / "agents" / "x.md").write_text("x")

    # A wheel-bundled copy also exists — the repo checkout must win.
    site_app = tmp_path / "site-packages" / "app"
    (site_app / "_seed" / "agents").mkdir(parents=True)
    (site_app / "_seed" / "agents" / "x.md").write_text("x")

    monkeypatch.setattr(seed_mod, "__file__", str(fake_module))
    monkeypatch.setattr(app_pkg, "__file__", str(site_app / "__init__.py"))

    assert seed_mod._local_seed_dir() == (repo / "seed").resolve()


def test_local_seed_dir_falls_back_to_wheel_bundled_copy(
    monkeypatch, tmp_path: Path
) -> None:
    import app as app_pkg
    import app.cli.seed as seed_mod

    site_app = tmp_path / "site-packages" / "app"
    (site_app / "_seed" / "agents").mkdir(parents=True)
    (site_app / "_seed" / "agents" / "x.md").write_text("x")

    monkeypatch.setattr(seed_mod, "__file__", str(_fake_checkout(tmp_path)))
    monkeypatch.setattr(app_pkg, "__file__", str(site_app / "__init__.py"))

    assert seed_mod._local_seed_dir() == (site_app / "_seed").resolve()


def test_local_seed_dir_none_without_checkout_or_bundle(
    monkeypatch, tmp_path: Path
) -> None:
    import app as app_pkg
    import app.cli.seed as seed_mod

    site_app = tmp_path / "site-packages" / "app"
    site_app.mkdir(parents=True)  # no _seed/ inside

    monkeypatch.setattr(seed_mod, "__file__", str(_fake_checkout(tmp_path)))
    monkeypatch.setattr(app_pkg, "__file__", str(site_app / "__init__.py"))

    assert seed_mod._local_seed_dir() is None
