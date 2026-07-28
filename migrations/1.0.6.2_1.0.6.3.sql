BEGIN TRANSACTION;

-- Price tracking
--
-- Separate from the `items` table on purpose: `items` drives the "new listing"
-- notifications, while price tracking repeatedly re-reads listings that are
-- already known. Mixing them would fire notifications for old items.

-- Per-query settings
ALTER TABLE queries ADD COLUMN track_prices INTEGER DEFAULT 0;
ALTER TABLE queries ADD COLUMN price_interval INTEGER DEFAULT 360;  -- minutes between price runs
ALTER TABLE queries ADD COLUMN price_depth INTEGER DEFAULT 1;       -- result pages to walk
ALTER TABLE queries ADD COLUMN last_price_check NUMERIC DEFAULT 0;

-- One row per listing being tracked (current state)
CREATE TABLE IF NOT EXISTS tracked_items
(
    item        TEXT,
    query_id    INTEGER,
    title       TEXT,
    url         TEXT,
    photo_url   TEXT,
    currency    TEXT,
    first_price NUMERIC,
    last_price  NUMERIC,
    first_seen  NUMERIC,
    last_seen   NUMERIC,
    observations INTEGER DEFAULT 1,
    -- Auctions change price with every bid, so they are handled differently:
    -- no per-change message, but a single alert shortly before they end.
    is_auction  INTEGER DEFAULT 0,
    auction_end NUMERIC DEFAULT 0,
    ending_notified INTEGER DEFAULT 0,
    PRIMARY KEY (item, query_id),
    FOREIGN KEY (query_id) REFERENCES queries (id)
);

-- One row per observed price (the actual history)
CREATE TABLE IF NOT EXISTS price_history
(
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    item      TEXT,
    query_id  INTEGER,
    price     NUMERIC,
    currency  TEXT,
    timestamp NUMERIC,
    FOREIGN KEY (query_id) REFERENCES queries (id)
);

CREATE INDEX IF NOT EXISTS idx_price_history_item ON price_history (item, query_id);
CREATE INDEX IF NOT EXISTS idx_price_history_time ON price_history (timestamp);
CREATE INDEX IF NOT EXISTS idx_tracked_items_query ON tracked_items (query_id);

-- Which bots receive PRICE messages for a query. Kept separate from
-- query_telegram_bots so price drops can go to a different chat than new-listing
-- alerts. Empty selection falls back to the query's normal notification bots.
CREATE TABLE IF NOT EXISTS query_price_bots
(
    query_id INTEGER,
    bot_id   INTEGER,
    PRIMARY KEY (query_id, bot_id),
    FOREIGN KEY (query_id) REFERENCES queries (id),
    FOREIGN KEY (bot_id) REFERENCES telegram_bots (id)
);

-- Only report a price change if it moves at least this many percent
INSERT OR IGNORE INTO parameters (key, value)
VALUES ('price_notify_threshold', '5');

-- Global default for how often a price run may happen at all (minutes)
INSERT OR IGNORE INTO parameters (key, value)
VALUES ('price_scheduler_interval', '15');

-- Update version
UPDATE parameters
SET value = '1.0.6.3'
WHERE key = 'version';

COMMIT;
