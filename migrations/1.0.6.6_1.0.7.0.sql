BEGIN TRANSACTION;

-- Remove price tracking completely.
--
-- Price runs walked older result pages and therefore had to tell "old listing,
-- just discovered" apart from "genuinely new". That classification sat directly
-- in the notification path and cost new listings, which is the opposite of what
-- this tool is for. Dropping the feature removes the classification entirely:
-- the scraper only ever looks at page 1 and everything unseen there is new.

DROP TABLE IF EXISTS price_history;
DROP TABLE IF EXISTS tracked_items;
DROP TABLE IF EXISTS query_price_bots;

DELETE FROM parameters WHERE key IN (
    'price_scheduler_interval',
    'price_notify_threshold',
    'price_notify_vinted',
    'price_notify_kleinanzeigen',
    'price_notify_ebay'
);

-- Rebuild `queries` without the price columns. The remaining columns keep the
-- order the code relies on.
CREATE TABLE queries_new
(
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    query            TEXT,
    last_item        NUMERIC,
    query_name       TEXT,
    telegram_chat_id TEXT,
    telegram_enabled INTEGER DEFAULT 1,
    platform         TEXT DEFAULT 'vinted',
    active           INTEGER DEFAULT 1,
    refresh_delay    INTEGER,
    last_scraped     NUMERIC DEFAULT 0
);

INSERT INTO queries_new
    (id, query, last_item, query_name, telegram_chat_id, telegram_enabled,
     platform, active, refresh_delay, last_scraped)
SELECT id, query, last_item, query_name, telegram_chat_id,
       COALESCE(telegram_enabled, 1), COALESCE(platform, 'vinted'),
       COALESCE(active, 1), refresh_delay, COALESCE(last_scraped, 0)
FROM queries;

DROP TABLE queries;
ALTER TABLE queries_new RENAME TO queries;

-- Update version
UPDATE parameters
SET value = '1.0.7.0'
WHERE key = 'version';

COMMIT;
