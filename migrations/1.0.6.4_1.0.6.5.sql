BEGIN TRANSACTION;

-- Track prices PER CURRENCY.
--
-- eBay shows cross-border listings sometimes in the seller's currency and
-- sometimes converted into the viewer's, and the exchange rate keeps moving.
-- Mixing those numbers in one series produces constant phantom swings, so each
-- currency now gets its own independent history: GBP stays GBP, USD stays USD.
--
-- SQLite cannot alter a primary key, so the table is rebuilt.

CREATE TABLE tracked_items_new
(
    item         TEXT,
    query_id     INTEGER,
    currency     TEXT,
    title        TEXT,
    url          TEXT,
    photo_url    TEXT,
    first_price  NUMERIC,
    last_price   NUMERIC,
    first_seen   NUMERIC,
    last_seen    NUMERIC,
    observations INTEGER DEFAULT 1,
    is_auction   INTEGER DEFAULT 0,
    auction_end  NUMERIC DEFAULT 0,
    ending_notified INTEGER DEFAULT 0,
    PRIMARY KEY (item, query_id, currency),
    FOREIGN KEY (query_id) REFERENCES queries (id)
);

INSERT OR IGNORE INTO tracked_items_new
    (item, query_id, currency, title, url, photo_url, first_price, last_price,
     first_seen, last_seen, observations, is_auction, auction_end, ending_notified)
SELECT item, query_id, COALESCE(NULLIF(currency, ''), 'EUR'), title, url, photo_url,
       first_price, last_price, first_seen, last_seen, observations,
       COALESCE(is_auction, 0), COALESCE(auction_end, 0), COALESCE(ending_notified, 0)
FROM tracked_items;

DROP TABLE tracked_items;
ALTER TABLE tracked_items_new RENAME TO tracked_items;

CREATE INDEX IF NOT EXISTS idx_tracked_items_query ON tracked_items (query_id);

-- Existing history rows without a currency belong to the default one
UPDATE price_history SET currency = 'EUR' WHERE currency IS NULL OR currency = '';

CREATE INDEX IF NOT EXISTS idx_price_history_item_cur
    ON price_history (item, query_id, currency);

-- Update version
UPDATE parameters
SET value = '1.0.6.5'
WHERE key = 'version';

COMMIT;
