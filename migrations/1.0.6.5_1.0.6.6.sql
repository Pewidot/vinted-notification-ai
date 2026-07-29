BEGIN TRANSACTION;

-- Price-change notifications can be switched off per platform.
--
-- eBay renders the same listing with the tax and rounding of whichever region
-- the fetching proxy sat in, so its "price changes" are mostly display
-- artefacts. Tracking keeps running (the history stays complete) - only the
-- Telegram messages are muted.
INSERT OR IGNORE INTO parameters (key, value) VALUES
    ('price_notify_vinted', 'True'),
    ('price_notify_kleinanzeigen', 'True'),
    ('price_notify_ebay', 'False');

-- Update version
UPDATE parameters
SET value = '1.0.6.6'
WHERE key = 'version';

COMMIT;
