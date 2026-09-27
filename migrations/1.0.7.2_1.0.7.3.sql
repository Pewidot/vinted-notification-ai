BEGIN TRANSACTION;

-- Claim each item/channel pair before handing it to Telegram. This protects
-- against overlapping searches, duplicate queue entries, and process retries.
CREATE TABLE IF NOT EXISTS telegram_deliveries
(
    item         TEXT,
    chat_id      TEXT,
    delivered_at NUMERIC DEFAULT (strftime('%s', 'now')),
    PRIMARY KEY (item, chat_id)
);

UPDATE parameters
SET value = '1.0.7.3'
WHERE key = 'version';

COMMIT;
