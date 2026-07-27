BEGIN TRANSACTION;

-- Multiple Telegram bots: each bot has its own token and chat. A query can be
-- linked to one or more bots (many-to-many); one bot is the "command bot" that
-- polls for commands (/add_query etc.) and is the fallback for queries with no
-- explicit bot selection.

CREATE TABLE IF NOT EXISTS telegram_bots
(
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT,
    token          TEXT,
    chat_id        TEXT,
    enabled        INTEGER DEFAULT 1,
    is_command_bot INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS query_telegram_bots
(
    query_id INTEGER,
    bot_id   INTEGER,
    PRIMARY KEY (query_id, bot_id),
    FOREIGN KEY (query_id) REFERENCES queries (id),
    FOREIGN KEY (bot_id) REFERENCES telegram_bots (id)
);

-- Migrate the existing single bot into telegram_bots as the command bot
-- (only if a token was configured).
INSERT INTO telegram_bots (name, token, chat_id, enabled, is_command_bot)
SELECT 'Default',
       (SELECT value FROM parameters WHERE key = 'telegram_token'),
       (SELECT value FROM parameters WHERE key = 'telegram_chat_id'),
       1, 1
WHERE (SELECT value FROM parameters WHERE key = 'telegram_token') IS NOT NULL
  AND (SELECT value FROM parameters WHERE key = 'telegram_token') <> '';

-- Preserve per-query chat overrides: create one extra bot per distinct custom
-- chat_id (sharing the default token) and link the affected queries to it.
INSERT INTO telegram_bots (name, token, chat_id, enabled, is_command_bot)
SELECT DISTINCT 'Chat ' || q.telegram_chat_id,
       (SELECT value FROM parameters WHERE key = 'telegram_token'),
       q.telegram_chat_id, 1, 0
FROM queries q
WHERE q.telegram_chat_id IS NOT NULL
  AND q.telegram_chat_id <> ''
  AND (SELECT value FROM parameters WHERE key = 'telegram_token') <> '';

INSERT OR IGNORE INTO query_telegram_bots (query_id, bot_id)
SELECT q.id, b.id
FROM queries q
JOIN telegram_bots b ON b.chat_id = q.telegram_chat_id AND b.is_command_bot = 0
WHERE q.telegram_chat_id IS NOT NULL
  AND q.telegram_chat_id <> '';

-- Update version
UPDATE parameters
SET value = '1.0.6.0'
WHERE key = 'version';

COMMIT;
