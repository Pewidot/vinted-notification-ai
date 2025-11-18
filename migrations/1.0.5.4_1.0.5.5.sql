BEGIN TRANSACTION;

-- Add missing user_agents parameter with common browser user agents
INSERT OR IGNORE INTO parameters (key, value)
VALUES ('user_agents', '["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"]');

-- Add missing default_headers parameter with common HTTP headers
INSERT OR IGNORE INTO parameters (key, value)
VALUES ('default_headers', '{"Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate, br", "Connection": "keep-alive"}');

-- Add configurable proxy test timeout (default 5 seconds instead of 2)
INSERT OR IGNORE INTO parameters (key, value)
VALUES ('proxy_test_timeout', '5');

-- Add configurable request timeout (default 30 seconds to prevent hanging requests)
INSERT OR IGNORE INTO parameters (key, value)
VALUES ('request_timeout', '30');

-- Update version
UPDATE parameters
SET value = '1.0.5.5'
WHERE key = 'version';

COMMIT;
