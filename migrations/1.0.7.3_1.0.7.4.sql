BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS query_worker_state
(
    query_id       INTEGER PRIMARY KEY,
    platform       TEXT NOT NULL,
    state          TEXT NOT NULL DEFAULT 'idle',
    worker_id      TEXT,
    started_at     NUMERIC,
    finished_at    NUMERIC,
    heartbeat_at   NUMERIC,
    last_error     TEXT,
    run_count      INTEGER NOT NULL DEFAULT 0,
    success_count  INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (query_id) REFERENCES queries (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS proxy_scan_state
(
    platform       TEXT PRIMARY KEY,
    state          TEXT NOT NULL DEFAULT 'idle',
    started_at     NUMERIC,
    finished_at    NUMERIC,
    heartbeat_at   NUMERIC,
    checked_count  INTEGER NOT NULL DEFAULT 0,
    total_count    INTEGER NOT NULL DEFAULT 0,
    working_count  INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT
);

CREATE TABLE IF NOT EXISTS proxy_state
(
    platform          TEXT NOT NULL,
    proxy             TEXT NOT NULL,
    working           INTEGER NOT NULL DEFAULT 0,
    query_blacklisted INTEGER NOT NULL DEFAULT 0,
    scan_blacklisted  INTEGER NOT NULL DEFAULT 0,
    last_success      NUMERIC,
    last_failure      NUMERIC,
    last_scan         NUMERIC,
    PRIMARY KEY (platform, proxy)
);

INSERT OR IGNORE INTO parameters (key, value) VALUES
    ('proxy_scan_blacklist_vinted', ''),
    ('proxy_scan_blacklist_kleinanzeigen', ''),
    ('proxy_scan_blacklist_ebay', ''),
    ('working_proxies_vinted', ''),
    ('working_proxies_kleinanzeigen', ''),
    ('working_proxies_ebay', ''),
    ('all_proxies_vinted', ''),
    ('all_proxies_kleinanzeigen', ''),
    ('all_proxies_ebay', '');

UPDATE parameters SET value = '1.0.7.4' WHERE key = 'version';

COMMIT;
