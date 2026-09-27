BEGIN TRANSACTION;

-- The timestamp-free Vinted catalogue needs a persistent one-time baseline.
-- Existing queries deliberately start at 0 so their current first page is
-- recorded silently after upgrading instead of being announced as new.
ALTER TABLE queries
    ADD COLUMN vinted_id_baselined INTEGER DEFAULT 0;

-- Exact item IDs are globally deduplicated by the application. Enforce that
-- invariant in SQLite too, so retries or overlapping queries cannot enqueue
-- the same listing twice even if they race between the read and insert.
DELETE FROM items
WHERE rowid NOT IN (
    SELECT MIN(rowid)
    FROM items
    GROUP BY item
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_items_unique_item ON items(item);

UPDATE parameters
SET value = '1.0.7.2'
WHERE key = 'version';

COMMIT;
