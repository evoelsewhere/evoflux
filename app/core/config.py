import os
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic.fields import Field
from pydantic.types import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _safe_home() -> Path | None:
    """Return ``Path.home()`` or ``None`` when the home directory cannot be resolved."""
    try:
        return Path.home()
    except RuntimeError:
        return None


_HOME_DIR = _safe_home()


def _default_dirs(app_env: str) -> dict[str, Path]:
    """Return the default XDG-aligned roots for the given environment.

    Five separate roots:

    - ``data``      — EvoFlux-internal data (SQLite DB).  Denied to agent fs tools.
    - ``config``    — hand-edited configuration (agents, skills, prompts, ``.env``,
      OAuth tokens).  Allowed.
    - ``state``     — logs, telemetry, OTEL rollups.  Denied.
    - ``cache``     — regeneratable throwaway (quote of the day, OAuth tokens).
      Denied.
    - ``wiki``      — shared wiki store (``USER.md``, ``topics/``, ``notes/``).
      Allowed.
    - ``workspace`` — per-session agent workspaces (``{workspace}/<sid>``).
      The active session's workspace is the relative-path root for fs tools.
      User uploads land inside the workspace at ``{workspace}/<sid>/uploads/``
      so agent tools can reach them as ``uploads/<filename>`` without a
      staging step.

    Production (``app_env=production``) maps to OS XDG conventions::

        ~/.local/share/evoflux            ← data (DB)
        ~/.local/share/evoflux-wiki       ← wiki
        ~/.local/share/evoflux-workspace  ← workspace (incl. uploads/)
        ~/.config/evoflux                 ← config
        ~/.local/state/evoflux            ← state
        ~/.cache/evoflux                  ← cache

    Development (anything else) keeps runtime state under ``.evoflux/dev/``
    in the project root so project commands/skills can live directly under
    ``.evoflux/`` without mixing with local runtime data::

        .evoflux/dev/data/
            evoflux.db
        .evoflux/dev/wiki/
        .evoflux/dev/workspace/<sid>/uploads/
        .evoflux/dev/config/
        .evoflux/dev/state/
        .evoflux/dev/cache/
    """
    home = _HOME_DIR or Path(".")
    if app_env == "production":
        data = home / ".local" / "share" / "evoflux"
        return {
            "data": data,
            "wiki": home / ".local" / "share" / "evoflux-wiki",
            "workspace": home / ".local" / "share" / "evoflux-workspace",
            "config": home / ".config" / "evoflux",
            "state": home / ".local" / "state" / "evoflux",
            "cache": home / ".cache" / "evoflux",
        }
    root = Path(".evoflux") / "dev"
    root = root.absolute()
    data = root / "data"
    return {
        "data": data,
        "wiki": root / "wiki",
        "workspace": root / "workspace",
        "config": root / "config",
        "state": root / "state",
        "cache": root / "cache",
    }


class Settings(BaseSettings):
    ZAI_API_KEY: SecretStr | None = None
    GOOGLE_API_KEY: SecretStr | None = None
    ANTHROPIC_API_KEY: SecretStr | None = None
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    OPENAI_API_KEY: SecretStr | None = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    # QwenCloud / Alibaba Model Studio international OpenAI-compatible API.
    # Subscription keys use plan-specific hosts, so the full Base URL remains
    # configurable and must match the key shown by QwenCloud.
    DASHSCOPE_API_KEY: SecretStr | None = None
    DASHSCOPE_BASE_URL: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    OPENROUTER_API_KEY: SecretStr | None = None
    NVIDIA_API_KEY: SecretStr | None = None
    XAI_API_KEY: SecretStr | None = None
    DEEPSEEK_API_KEY: SecretStr | None = None
    XIAOMI_API_KEY: SecretStr | None = None
    XIAOMI_BASE_URL: str = ""
    MOONSHOT_API_KEY: SecretStr | None = None
    MOONSHOT_BASE_URL: str = "https://api.kimi.com/coding/v1"
    # K3 is entitlement-dependent: 256K for Moderato, up to 1M for
    # Allegretto and above. Stay conservative unless explicitly unlocked.
    KIMI_CODE_K3_CONTEXT_WINDOW: int = 262144

    # FCI — FPT's OpenAI-compatible inference gateway.
    FCI_API_KEY: SecretStr | None = None
    FCI_BASE_URL: str = "https://mkp-api.fptcloud.com/v1"

    # Microsoft Foundry (Azure AI Foundry) — resource API key plus the
    # resource name (or a full endpoint URL) the base URL is derived from.
    FOUNDRY_API_KEY: SecretStr | None = None
    FOUNDRY_RESOURCE_NAME: str = ""
    NINJA_API_KEY: SecretStr | None = None

    # AWS Bedrock — region and optional named profile.
    # AWS_BEDROCK_REGION: override the region for Bedrock API calls.
    #   Falls back to AWS_DEFAULT_REGION env var, then "us-east-1".
    # AWS_BEDROCK_PROFILE: named profile from ~/.aws/credentials.
    #   None (default) uses the standard boto3 credential chain
    #   (env vars AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, instance profile, etc.).
    AWS_BEDROCK_REGION: str | None = None
    AWS_BEDROCK_PROFILE: str | None = None

    # 9Router (https://github.com/decolua/9router) — local proxy that exposes
    # an OpenAI-compatible /v1/chat/completions endpoint. Generate the API key
    # from the 9Router dashboard (default: http://localhost:20128).
    ROUTER9_API_KEY: SecretStr = Field(
        default=SecretStr("sk_9router"), description="Required for 9Router provider"
    )
    ROUTER9_BASE_URL: str = "http://localhost:20128/v1"

    # CLIProxyAPI (https://github.com/router-for-me/CLIProxyAPI) — local proxy
    # that exposes OpenAI/Gemini/Claude-compatible endpoints. We talk to it
    # via its OpenAI-compatible surface.
    CLIPROXY_API_KEY: SecretStr = Field(
        default=SecretStr("sk_cliproxy"), description="Required for cliproxy provider"
    )
    CLIPROXY_BASE_URL: str = "http://localhost:8317/v1"

    # Ollama (local daemon) — OpenAI-compatible endpoint at
    # http://localhost:11434/v1 by default. The daemon ignores auth.
    # Cloud models are reached through the same daemon by suffixing the
    # model name with "-cloud" after running "ollama signin".
    OLLAMA_API_KEY: SecretStr | None = None
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"

    # Vertex AI API key (Google Cloud key, NOT an AI Studio key)
    # Obtain from: https://console.cloud.google.com/expressmode
    VERTEXAI_API_KEY: SecretStr | None = None
    # Optional: set both to use normal mode (project-scoped URL + full model catalog)
    # Leave unset to use express mode (no project required)
    GOOGLE_CLOUD_PROJECT: str | None = None
    GOOGLE_CLOUD_LOCATION: str = "global"

    # Environment — controls data directory, log level defaults, etc.
    # Values: "production" | "development"
    APP_ENV: str = "production"

    # SSL verification for outbound HTTP calls.
    # Set to "false" on corporate networks with SSL-inspecting proxies.
    SSL_VERIFY: bool = True

    # API Server
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 4082
    API_RELOAD: bool = False
    CORS_ORIGINS: list[str] = ["*"]

    # ── XDG-aligned roots ────────────────────────────────────────────────
    # Empty string means "derive from APP_ENV" (see validator).
    # Override with an absolute path if needed.
    #
    # data:      irreplaceable internal data (SQLite DB)
    # config:    hand-edited config (agents, skills, prompts, .env)
    # state:     logs, telemetry, OTEL rollups
    # cache:     regeneratable throwaway
    # workspace: per-session agent workspaces — ``{workspace}/<sid>``;
    #            user uploads land at ``{workspace}/<sid>/uploads/``
    EVOFLUX_DATA_DIR: str = ""
    EVOFLUX_CONFIG_DIR: str = ""
    EVOFLUX_STATE_DIR: str = ""
    EVOFLUX_CACHE_DIR: str = ""
    EVOFLUX_WORKSPACE_DIR: str = ""

    # Refresh model metadata from https://models.dev at runtime. Disable in tests
    # or hermetic deployments; bundled model_registry.json remains the fallback.
    EVOFLUX_MODEL_REGISTRY_REFRESH: bool = True

    # How often the background task re-fetches models.dev. The merged registry
    # is memoized per process, so without this a long-running server never sees
    # a model released after its own boot. Clamped to at least one hour.
    EVOFLUX_MODEL_REGISTRY_REFRESH_INTERVAL_HOURS: int = 24

    # Repository index rebuilds are CPU/GIL heavy. Production isolates them
    # in one worker process so API, SSE, and aiosqlite threads remain
    # responsive. ``thread`` is retained for deterministic fault-injection
    # tests and constrained embedders.
    EVOFLUX_CODE_INDEX_EXECUTION: Literal["process", "thread"] = "process"

    # Agents directory — contains per-agent .md files.
    # Empty string means "derive from EVOFLUX_CONFIG_DIR" → ``{CONFIG_DIR}/agents``.
    # Override with an absolute or working-directory-relative path.
    AGENTS_DIR: str = ""

    # Skills directory — contains {skill-name}/SKILL.md subdirectories.
    # Empty string means "derive from EVOFLUX_CONFIG_DIR" → ``{CONFIG_DIR}/skills``.
    SKILLS_DIR: str = ""

    # User-defined plugin directories — absolute paths separated by the OS
    # path separator (``:`` on POSIX, ``;`` on Windows — same convention as
    # ``PATH`` / ``PYTHONPATH``).  Splitting on a hardcoded ``:`` would corrupt
    # Windows paths like ``C:\Users\..\plugins`` into ``["C", "\\Users\\..."]``.
    # Empty string means "derive from CONFIG_DIR" (→ ``{CONFIG_DIR}/plugins``).
    # CONFIG_DIR itself is per-environment (project-local in dev, ``~/.config/evoflux``
    # in production) so a single dir is enough — no separate "global" dir needed.
    # Each ``.py`` file in this dir is loaded at agent-build time and may
    # subscribe to hook events (see app/agent/plugins/).  Files prefixed with
    # ``_`` are skipped so authors can stash helper modules alongside plugins.
    EVOFLUX_PLUGINS_DIRS: str = ""

    # Logging — defaults to INFO in production, DEBUG in development
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR

    # Web fetch safety — when true, web_fetch allows targets that resolve
    # to private/reserved IPs (RFC 1918, loopback, link-local).  Off by
    # default to prevent DNS-rebinding attacks that trick the agent into
    # reading from internal services.
    WEB_FETCH_ALLOW_PRIVATE_NETWORK: bool = False

    DATABASE_URL: SecretStr = SecretStr("")

    # Wiki directory — shared wiki store (USER.md, topics/, notes/).
    # Empty string means "derive from APP_ENV" (→ ``.evoflux/dev/wiki`` in dev,
    # ``~/.local/share/evoflux-wiki`` in production).
    EVOFLUX_WIKI_DIR: str = ""

    model_config = SettingsConfigDict(
        # Load order: project .env first, then ~/.config/evoflux/.env on top.
        # Values in later files take priority, so the user's home config
        # always wins over the project default — and either can be absent.
        env_file=[
            ".env",
            *([str(_HOME_DIR / ".config" / "evoflux" / ".env")] if _HOME_DIR else []),
        ],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _resolve_env_defaults(self) -> "Settings":
        # ── Resolve the 4 XDG roots from APP_ENV when not explicitly set ──
        defaults = _default_dirs(self.APP_ENV)

        if not self.EVOFLUX_DATA_DIR:
            self.EVOFLUX_DATA_DIR = str(defaults["data"])
        if not self.EVOFLUX_CONFIG_DIR:
            self.EVOFLUX_CONFIG_DIR = str(defaults["config"])
        if not self.EVOFLUX_STATE_DIR:
            self.EVOFLUX_STATE_DIR = str(defaults["state"])
        if not self.EVOFLUX_CACHE_DIR:
            self.EVOFLUX_CACHE_DIR = str(defaults["cache"])
        if not self.EVOFLUX_WORKSPACE_DIR:
            self.EVOFLUX_WORKSPACE_DIR = str(defaults["workspace"])

        data = Path(self.EVOFLUX_DATA_DIR)
        config = Path(self.EVOFLUX_CONFIG_DIR)

        # DATABASE_URL: default to SQLite inside DATA_DIR if not explicitly set
        if not self.DATABASE_URL.get_secret_value():
            self.DATABASE_URL = SecretStr(f"sqlite+aiosqlite:///{data / 'evoflux.db'}")

        # Agents directory — defaults to ``{CONFIG_DIR}/agents``.
        if not self.AGENTS_DIR:
            self.AGENTS_DIR = str(config / "agents")

        # Skills directory — defaults to ``{CONFIG_DIR}/skills``.
        if not self.SKILLS_DIR:
            self.SKILLS_DIR = str(config / "skills")

        # Plugins directory — defaults to ``{CONFIG_DIR}/plugins``.  Set the
        # env var to an :data:`os.pathsep`-separated list to load from extra
        # paths (rare).
        if not self.EVOFLUX_PLUGINS_DIRS:
            self.EVOFLUX_PLUGINS_DIRS = str(config / "plugins")

        # Wiki directory.
        if not self.EVOFLUX_WIKI_DIR:
            self.EVOFLUX_WIKI_DIR = str(defaults["wiki"])

        return self

    def plugin_dirs(self) -> list[Path]:
        """Return the configured plugin directories as ``Path`` objects.

        Entries are split on :data:`os.pathsep` (``:`` on POSIX, ``;`` on
        Windows — same convention as ``PATH`` / ``PYTHONPATH``).  Splitting
        on a hardcoded ``:`` would corrupt Windows paths whose drive letter
        is followed by ``:`` (e.g. ``C:\\Users\\…\\plugins``) and cause the
        first entry to become the bare string ``"C"``, which breaks
        directory creation at startup.

        Empty entries are dropped; non-existent directories are kept (the
        loader skips them).  Order is preserved — earlier directories
        win on duplicate filenames.
        """
        return [
            Path(p) for p in self.EVOFLUX_PLUGINS_DIRS.split(os.pathsep) if p.strip()
        ]


settings = Settings()  # pyright: ignore[reportCallIssue]
