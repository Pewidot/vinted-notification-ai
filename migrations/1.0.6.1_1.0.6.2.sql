BEGIN TRANSACTION;

-- How long a failing proxy stays blacklisted before it is retried, in minutes.
-- Was hardcoded to 60 minutes; configurable now because the right value depends
-- on the proxy pool (large free pools tolerate long bans, small paid pools
-- should recover quickly).
INSERT OR IGNORE INTO parameters (key, value)
VALUES ('proxy_blacklist_duration', '60');

-- Update version
UPDATE parameters
SET value = '1.0.6.2'
WHERE key = 'version';

COMMIT;
