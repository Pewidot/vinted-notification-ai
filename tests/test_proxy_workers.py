import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import db
import proxies


SCHEMA = """
CREATE TABLE parameters (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE proxy_state (
  platform TEXT NOT NULL,
  proxy TEXT NOT NULL,
  working INTEGER NOT NULL DEFAULT 0,
  query_blacklisted INTEGER NOT NULL DEFAULT 0,
  scan_blacklisted INTEGER NOT NULL DEFAULT 0,
  last_success NUMERIC,
  last_failure NUMERIC,
  last_scan NUMERIC,
  PRIMARY KEY (platform, proxy)
);
CREATE TABLE proxy_scan_state (
  platform TEXT PRIMARY KEY, state TEXT, started_at NUMERIC,
  finished_at NUMERIC, heartbeat_at NUMERIC, checked_count INTEGER DEFAULT 0,
  total_count INTEGER DEFAULT 0, working_count INTEGER DEFAULT 0,
  last_error TEXT
);
"""


class DurableProxyStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = f"{self.temp.name}/proxy.db"
        conn = sqlite3.connect(self.path)
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO parameters VALUES (?, ?)",
            [
                ("proxy_list_vinted", "p1;p2;p3"),
                ("proxy_list_link_vinted", ""),
                ("validated_proxies_vinted", ""),
                ("check_proxies", "True"),
            ],
        )
        conn.commit()
        conn.close()
        self.db_patch = patch.object(db, "DB_PATH", self.path)
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_third_attempt_prefers_last_real_query_success(self):
        db.seed_proxy_pool("vinted", ["p1", "p2", "p3"])
        db.mark_proxy_result("vinted", "p2", True)
        with patch("proxies.random.choice", side_effect=lambda values: values[0]):
            self.assertEqual(proxies.get_random_proxy("vinted", attempt=3), "p2")

    def test_query_failure_stays_blacklisted_until_valid_manual_scan(self):
        db.seed_proxy_pool("vinted", ["p1", "p2"])
        db.mark_proxy_result("vinted", "p1", True)
        proxies.blacklist_proxy("p1", "vinted")
        self.assertNotIn("p1", db.get_proxy_candidates("vinted"))
        self.assertEqual(db.get_proxy_state_counts("vinted")[2], 1)

        db.replace_proxy_scan_results("vinted", ["p1", "p2"], ["p1"])
        self.assertIn("p1", db.get_proxy_candidates("vinted"))
        lists = db.get_proxy_lists("vinted")
        self.assertIn("p2", lists["scan_blacklisted"])
        self.assertNotIn("p1", lists["blacklisted"])


if __name__ == "__main__":
    unittest.main()
