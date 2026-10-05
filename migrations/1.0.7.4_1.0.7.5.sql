BEGIN TRANSACTION;

ALTER TABLE proxy_state
    ADD COLUMN working_blacklisted_until NUMERIC NOT NULL DEFAULT 0;

-- Previously working proxies were stored in the permanent query blacklist.
-- Preserve the original failure time: an hour-old failure is already eligible
-- for another attempt. Scan failures still require a successful manual scan.
UPDATE proxy_state
SET working=0,
    query_blacklisted=0,
    working_blacklisted_until=COALESCE(last_failure, CAST(strftime('%s', 'now') AS INTEGER)) + 3600
WHERE query_blacklisted=1 AND scan_blacklisted=0 AND last_success IS NOT NULL;

UPDATE parameters SET value='1.0.7.5' WHERE key='version';

COMMIT;
