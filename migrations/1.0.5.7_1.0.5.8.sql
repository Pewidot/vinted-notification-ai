BEGIN TRANSACTION;

-- Multi-platform support:
-- platform: which site this query targets ('vinted', 'kleinanzeigen' or 'ebay')
ALTER TABLE queries ADD COLUMN platform TEXT DEFAULT 'vinted';

-- Store the full item URL (Kleinanzeigen/eBay URLs cannot be reconstructed from the query URL)
ALTER TABLE items ADD COLUMN url TEXT;

-- eBay official developer API credentials (no proxy is used for eBay)
INSERT OR IGNORE INTO parameters (key, value)
VALUES ('ebay_app_id', ''),
       ('ebay_cert_id', ''),
       ('ebay_marketplace', 'EBAY_DE');

-- Update version
UPDATE parameters
SET value = '1.0.5.8'
WHERE key = 'version';

COMMIT;
