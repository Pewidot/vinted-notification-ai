BEGIN TRANSACTION;

-- Per-query Telegram settings:
-- telegram_chat_id: optional chat id for this query (NULL/empty = use default telegram_chat_id parameter)
-- telegram_enabled: 1 = send Telegram notifications for this query, 0 = disabled
ALTER TABLE queries ADD COLUMN telegram_chat_id TEXT;
ALTER TABLE queries ADD COLUMN telegram_enabled INTEGER DEFAULT 1;

-- Update version
UPDATE parameters
SET value = '1.0.5.7'
WHERE key = 'version';

COMMIT;
