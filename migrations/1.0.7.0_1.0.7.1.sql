BEGIN TRANSACTION;

-- Remember the last *successful* scrape of a query, separately from the last
-- attempt.
--
-- `last_scraped` is stamped before the request so a failing query waits for its
-- own interval instead of being retried on every tick. That makes it useless as
-- a measure of "how long have we been blind?": during a proxy outage it keeps
-- advancing while nothing is actually fetched.
--
-- The new-item window is derived from this column, so an outage widens the
-- window by exactly as much as it cost us.
--
-- Plain ADD COLUMN on purpose: rebuilding `queries` would trip over the foreign
-- keys that items and query_telegram_bots hold on it.

ALTER TABLE queries
    ADD COLUMN last_success NUMERIC DEFAULT 0;

-- Existing rows start from their last attempt, otherwise the first tick after
-- the update would treat every query as "blind since 1970" and widen the window
-- to the cap.
UPDATE queries
SET last_success = COALESCE(last_scraped, 0);

UPDATE parameters
SET value = '1.0.7.1'
WHERE key = 'version';

COMMIT;
