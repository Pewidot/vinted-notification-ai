-- init_schema.sql
-- Initial Scheme

PRAGMA foreign_keys = ON;

/* ============================
   Tables
   ============================ */

-- Queries table
CREATE TABLE IF NOT EXISTS queries
(
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    query     TEXT,
    last_item NUMERIC,
    query_name TEXT,
    telegram_chat_id TEXT,
    telegram_enabled INTEGER DEFAULT 1,
    platform TEXT DEFAULT 'vinted',
    active INTEGER DEFAULT 1,
    track_prices INTEGER DEFAULT 0,
    price_interval INTEGER DEFAULT 360,
    price_depth INTEGER DEFAULT 1,
    last_price_check NUMERIC DEFAULT 0,
    refresh_delay INTEGER,
    last_scraped NUMERIC DEFAULT 0
);

-- Items table
CREATE TABLE IF NOT EXISTS items
(
    item      NUMERIC,
    title     TEXT,
    price     NUMERIC,
    currency  TEXT,
    timestamp NUMERIC,
    photo_url TEXT,
    query_id  INTEGER,
    url       TEXT,
    FOREIGN KEY (query_id) REFERENCES queries (id)
);

-- Allowlist table
CREATE TABLE IF NOT EXISTS allowlist
(
    country TEXT
);

-- Telegram bots table (multiple bots, each with its own token and chat)
CREATE TABLE IF NOT EXISTS telegram_bots
(
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT,
    token          TEXT,
    chat_id        TEXT,
    enabled        INTEGER DEFAULT 1,
    is_command_bot INTEGER DEFAULT 0
);

-- Query <-> Telegram bots mapping (which bots notify a given query)
CREATE TABLE IF NOT EXISTS query_telegram_bots
(
    query_id INTEGER,
    bot_id   INTEGER,
    PRIMARY KEY (query_id, bot_id),
    FOREIGN KEY (query_id) REFERENCES queries (id),
    FOREIGN KEY (bot_id) REFERENCES telegram_bots (id)
);

-- Which bots receive PRICE messages (may differ from new-listing alerts)
CREATE TABLE IF NOT EXISTS query_price_bots
(
    query_id INTEGER,
    bot_id   INTEGER,
    PRIMARY KEY (query_id, bot_id),
    FOREIGN KEY (query_id) REFERENCES queries (id),
    FOREIGN KEY (bot_id) REFERENCES telegram_bots (id)
);

-- Price tracking: current state per tracked listing
CREATE TABLE IF NOT EXISTS tracked_items
(
    item         TEXT,
    query_id     INTEGER,
    title        TEXT,
    url          TEXT,
    photo_url    TEXT,
    currency     TEXT,
    first_price  NUMERIC,
    last_price   NUMERIC,
    first_seen   NUMERIC,
    last_seen    NUMERIC,
    observations INTEGER DEFAULT 1,
    -- Auctions change price with every bid: no per-change message, but a
    -- single alert shortly before they end.
    is_auction   INTEGER DEFAULT 0,
    auction_end  NUMERIC DEFAULT 0,
    ending_notified INTEGER DEFAULT 0,
    PRIMARY KEY (item, query_id),
    FOREIGN KEY (query_id) REFERENCES queries (id)
);

-- Price tracking: one row per observed price
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

-- Parameters table
CREATE TABLE IF NOT EXISTS parameters
(
    key   TEXT PRIMARY KEY,
    value TEXT
);

/* ============================
   Initial data
   ============================ */

INSERT INTO parameters (key, value)
VALUES ('telegram_enabled', 'False'),
       ('telegram_token', ''),
       ('telegram_chat_id', ''),
       ('telegram_process_running', 'False'),

       ('rss_enabled', 'False'),
       ('rss_port', '8080'),
       ('rss_max_items', '100'),
       ('rss_process_running', 'False'),

       ('price_scheduler_interval', '15'),
       ('price_notify_threshold', '5'),

       ('version', '1.0.6.4'),
       ('github_url', 'https://github.com/Fuyucch1/Vinted-Notifications'),

       ('items_per_query', '20'),
       ('query_refresh_delay', '60'),

       ('proxy_list', ''),
       ('proxy_list_link', ''),
       ('check_proxies', 'False'),
       ('last_proxy_check_time', '0'),

       ('proxy_list_vinted', ''),
       ('proxy_list_kleinanzeigen', ''),
       ('proxy_list_ebay', ''),
       ('proxy_list_link_vinted', ''),
       ('proxy_list_link_kleinanzeigen', ''),
       ('proxy_list_link_ebay', ''),
       ('proxy_blacklist_vinted', ''),
       ('proxy_blacklist_kleinanzeigen', ''),
       ('proxy_blacklist_ebay', ''),
       ('validated_proxy_count_vinted', '0'),
       ('validated_proxy_count_kleinanzeigen', '0'),
       ('validated_proxy_count_ebay', '0'),
       ('last_proxy_check_time_vinted', '0'),
       ('last_proxy_check_time_kleinanzeigen', '0'),
       ('last_proxy_check_time_ebay', '0'),
       ('proxy_test_timeout', '5'),
       ('proxy_blacklist_duration', '60'),
       ('request_timeout', '10'),
       ('query_timeout', '15'),
       ('banwords', ''),
       ('user_agents', '["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"]'),
       ('default_headers', '{"Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate, br", "Connection": "keep-alive"}');
