-- 0001: provider settings, discovered models and discovery health.
--
-- Secrets never live in this database: API keys and OAuth tokens stay in the
-- owner-only auth.json (see docs/design/app-database.md for the keychain plan).
-- Timestamps are Unix seconds.

CREATE TABLE provider_settings (
    provider_id  TEXT PRIMARY KEY NOT NULL,
    -- The user connected this provider. Required for keyless local providers
    -- (Ollama) so an absent daemon is not counted as connected.
    enabled      INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    -- Endpoint override; wins over <PROVIDER>_BASE_URL and the catalog.
    base_url     TEXT,
    -- Reserved for per-provider options that are not secrets (organisation,
    -- project, region, extra headers). JSON object.
    options_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(options_json)),
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
) STRICT;

-- Models a provider serves. `discovered` rows mirror its /models endpoint and
-- are replaced on every refresh; `custom` rows are added by the user and
-- survive refreshes.
CREATE TABLE provider_models (
    provider_id   TEXT NOT NULL REFERENCES provider_settings (provider_id) ON DELETE CASCADE,
    model_id      TEXT NOT NULL,
    display_name  TEXT,
    source        TEXT NOT NULL CHECK (source IN ('discovered', 'custom')),
    -- Hidden from model pickers without forgetting it.
    hidden        INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
    -- Reserved for user overrides of catalog metadata (context window, cost).
    metadata_json TEXT CHECK (metadata_json IS NULL OR json_valid(metadata_json)),
    position      INTEGER NOT NULL DEFAULT 0,
    seen_at       INTEGER NOT NULL,
    PRIMARY KEY (provider_id, model_id)
) STRICT;

-- The last discovery attempt per provider, for the settings page.
CREATE TABLE provider_discovery (
    provider_id     TEXT PRIMARY KEY NOT NULL REFERENCES provider_settings (provider_id) ON DELETE CASCADE,
    status          TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    error           TEXT,
    model_count     INTEGER NOT NULL DEFAULT 0,
    last_attempt_at INTEGER NOT NULL,
    last_success_at INTEGER
) STRICT;
