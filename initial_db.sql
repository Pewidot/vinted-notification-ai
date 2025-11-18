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
    query_name TEXT
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
    FOREIGN KEY (query_id) REFERENCES queries (id)
);

-- Allowlist table
CREATE TABLE IF NOT EXISTS allowlist
(
    country TEXT
);

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

       ('version', '1.0.3'),
       ('github_url', 'https://github.com/Fuyucch1/Vinted-Notifications'),

       ('items_per_query', '20'),
       ('query_refresh_delay', '60'),

       ('proxy_list', ''),
       ('proxy_list_link', ''),
       ('check_proxies', 'False'),
       ('last_proxy_check_time', '0'),
       ('proxy_test_timeout', '5'),
       ('request_timeout', '30'),
       ('banwords', ''),
       ('user_agents', '["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"]'),
       ('default_headers', '{"Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate, br", "Connection": "keep-alive"}');
