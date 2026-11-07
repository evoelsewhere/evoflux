-- 0009: how long each response took (docs/features/usage-and-cost/sdd.md).
--
-- From the request going out to the last token, in ms. Feeds the Usage
-- page's speed figures (output tokens per second per model). NULL for rows
-- recorded before this column existed or when the provider gave no start time.
ALTER TABLE usage_events ADD COLUMN duration_ms INTEGER;
