BEGIN TRANSACTION;

-- Allow queries to be paused: an inactive query stays in the database (with its
-- items and settings) but is skipped entirely during scraping until reactivated.
ALTER TABLE queries ADD COLUMN active INTEGER DEFAULT 1;

-- Update version
UPDATE parameters
SET value = '1.0.6.1'
WHERE key = 'version';

COMMIT;
