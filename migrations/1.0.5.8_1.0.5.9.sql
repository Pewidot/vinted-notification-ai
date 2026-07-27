BEGIN TRANSACTION;

-- Per-platform proxy lists. Each platform (vinted, kleinanzeigen, ebay) keeps
-- its own proxy list, fetch link, blacklist, validated count and last-check time.
-- The existing global proxy_list / proxy_list_link values are copied into every
-- platform so current behaviour is preserved after the upgrade.

INSERT OR IGNORE INTO parameters (key, value)
SELECT 'proxy_list_vinted', COALESCE((SELECT value FROM parameters WHERE key = 'proxy_list'), '');
INSERT OR IGNORE INTO parameters (key, value)
SELECT 'proxy_list_kleinanzeigen', COALESCE((SELECT value FROM parameters WHERE key = 'proxy_list'), '');
INSERT OR IGNORE INTO parameters (key, value)
SELECT 'proxy_list_ebay', COALESCE((SELECT value FROM parameters WHERE key = 'proxy_list'), '');

INSERT OR IGNORE INTO parameters (key, value)
SELECT 'proxy_list_link_vinted', COALESCE((SELECT value FROM parameters WHERE key = 'proxy_list_link'), '');
INSERT OR IGNORE INTO parameters (key, value)
SELECT 'proxy_list_link_kleinanzeigen', COALESCE((SELECT value FROM parameters WHERE key = 'proxy_list_link'), '');
INSERT OR IGNORE INTO parameters (key, value)
SELECT 'proxy_list_link_ebay', COALESCE((SELECT value FROM parameters WHERE key = 'proxy_list_link'), '');

INSERT OR IGNORE INTO parameters (key, value) VALUES
    ('proxy_blacklist_vinted', ''),
    ('proxy_blacklist_kleinanzeigen', ''),
    ('proxy_blacklist_ebay', ''),
    ('validated_proxy_count_vinted', '0'),
    ('validated_proxy_count_kleinanzeigen', '0'),
    ('validated_proxy_count_ebay', '0'),
    ('last_proxy_check_time_vinted', '0'),
    ('last_proxy_check_time_kleinanzeigen', '0'),
    ('last_proxy_check_time_ebay', '0');

-- Update version
UPDATE parameters
SET value = '1.0.5.9'
WHERE key = 'version';

COMMIT;
