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

        default_written = ensure_builtin_agent_blueprints(agents_dir, mode="forge")
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
    from app.agent.loader import ensure_builtin_lead_blueprint

    healed_forge = ensure_builtin_lead_blueprint(agents_dir, mode="forge")
    healed_coding = ensure_builtin_lead_blueprint(agents_dir / "coding", mode="coding")
    if healed_forge or healed_coding:
        logger.warning(
            "workspace_lead_agent_healed forge={} coding={}",
            healed_forge,
            healed_coding,
        )
