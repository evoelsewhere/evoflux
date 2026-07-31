"""First-run workspace materialisation for non-interactive app starts."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from app.core.config import settings


def ensure_workspace_initialized() -> None:
    """Create expected local roots and seed editable defaults if missing."""
    for path in (
        settings.EVOFLUX_DATA_DIR,
        settings.EVOFLUX_CONFIG_DIR,
        settings.EVOFLUX_STATE_DIR,
        settings.EVOFLUX_CACHE_DIR,
        settings.EVOFLUX_WORKSPACE_DIR,
        settings.EVOFLUX_WIKI_DIR,
        settings.AGENTS_DIR,
        settings.SKILLS_DIR,
    ):
        Path(path).mkdir(parents=True, exist_ok=True)

    for plugin_dir in settings.plugin_dirs():
        plugin_dir.mkdir(parents=True, exist_ok=True)

    agents_dir = Path(settings.AGENTS_DIR)
    if not any(agents_dir.glob("*.md")):
        from app.cli.seed import PROVIDER_MODEL_TOKEN, SeedDownloadError, install_seed

        try:
            result = install_seed(
                Path(settings.EVOFLUX_CONFIG_DIR),
                provider_model=PROVIDER_MODEL_TOKEN,
            )
        except SeedDownloadError as exc:
            logger.warning("workspace_seed_install_failed error={}", exc)
            result = None

        from app.agent.loader import ensure_builtin_agent_blueprints

        default_written = ensure_builtin_agent_blueprints(agents_dir, mode="work")
        coding_written = ensure_builtin_agent_blueprints(
            agents_dir / "coding", mode="coding"
        )

        if result is None:
            logger.info(
                "workspace_builtin_agents_installed agents={} coding_agents={}",
                len(default_written),
                len(coding_written),
            )
        else:
            logger.info(
                "workspace_seed_installed agents={} skills={} configs={} source={} builtin_agents={} builtin_coding_agents={}",
                len(result.agents_written),
                len(result.skills_written),
                len(result.configs_written),
                result.source,
                len(default_written),
                len(coding_written),
            )

    # Self-heal: guarantee a lead agent exists even if a prior run's seed
    # download failed and only left member blueprints behind (the seed
    # bundle normally supplies the lead; the builtin fallback above only
    # covers members). Runs every start, not just on a fully empty dir, so
    # an already-broken workspace recovers without manual intervention.
    from app.agent.config import agent_dir_has_lead

    healed_work = None
    healed_coding = None
    work_has_lead = agent_dir_has_lead(agents_dir)
    coding_has_lead = agent_dir_has_lead(agents_dir / "coding")
    if not work_has_lead or not coding_has_lead:
        from app.agent.loader import ensure_builtin_lead_blueprint

        if not work_has_lead:
            healed_work = ensure_builtin_lead_blueprint(agents_dir, mode="work")
        if not coding_has_lead:
            healed_coding = ensure_builtin_lead_blueprint(
                agents_dir / "coding", mode="coding"
            )
    if healed_work or healed_coding:
        logger.warning(
            "workspace_lead_agent_healed work={} coding={}",
            healed_work,
            healed_coding,
        )

    from app.services.agent_fs import migrate_agent_temperature_settings

    migrated_agents = migrate_agent_temperature_settings(agents_dir)
    if migrated_agents:
        logger.info(
            "workspace_agent_temperature_settings_removed count={}",
            migrated_agents,
        )
