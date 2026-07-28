BEGIN TRANSACTION;

-- Per-query refresh interval.
-- NULL/0 means "use the global query_refresh_delay", so existing queries keep
-- behaving exactly as before.
ALTER TABLE queries ADD COLUMN refresh_delay INTEGER;
-- When this query was last scraped, so each one can run on its own schedule
ALTER TABLE queries ADD COLUMN last_scraped NUMERIC DEFAULT 0;

-- Update version
UPDATE parameters
SET value = '1.0.6.4'
WHERE key = 'version';

COMMIT;
