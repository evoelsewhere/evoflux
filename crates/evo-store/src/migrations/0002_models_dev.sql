-- 0002: the models.dev database cache.
--
-- models.dev (https://models.dev/api.json) is evo's model database: model
-- lists, limits, pricing and reasoning controls. The engine stores the last
-- downloaded document here and refreshes it in the background; the snapshot
-- bundled in evo-runtime only seeds a machine that has never been online.

CREATE TABLE models_dev_cache (
    singleton   INTEGER PRIMARY KEY NOT NULL CHECK (singleton = 1),
    body        TEXT NOT NULL,
    etag        TEXT,
    fetched_at  INTEGER NOT NULL,
    -- Last time the document was checked, changed or not (ETag revalidation).
    checked_at  INTEGER NOT NULL,
    model_count INTEGER NOT NULL DEFAULT 0
) STRICT;
