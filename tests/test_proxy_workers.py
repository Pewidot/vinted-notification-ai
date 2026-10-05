import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jinja2 import Environment, FileSystemLoader, StrictUndefined

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
  working_blacklisted_until NUMERIC NOT NULL DEFAULT 0,
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
        self.clock_patch = patch("time.time", return_value=1000)
        self.clock = self.clock_patch.start()

    def tearDown(self):
        self.clock_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def test_third_attempt_prefers_last_real_query_success(self):
        db.seed_proxy_pool("vinted", ["p1", "p2", "p3"])
        db.mark_proxy_result("vinted", "p2", True)
        with patch("proxies.random.choice", side_effect=lambda values: values[0]):
            self.assertEqual(proxies.get_random_proxy("vinted", attempt=3), "p2")

    def test_query_failure_stays_blacklisted_until_valid_manual_scan(self):
        db.seed_proxy_pool("vinted", ["p1", "p2"])
        proxies.blacklist_proxy("p1", "vinted")
        self.clock.return_value = 10000
        self.assertNotIn("p1", db.get_proxy_candidates("vinted"))
        self.assertEqual(db.get_proxy_state_counts("vinted")[2], 1)
        self.assertEqual(db.get_proxy_lists("vinted")["working_blacklisted"], [])

        db.replace_proxy_scan_results("vinted", ["p1", "p2"], ["p1"])
        self.assertIn("p1", db.get_proxy_candidates("vinted"))
        lists = db.get_proxy_lists("vinted")
        self.assertIn("p2", lists["scan_blacklisted"])
        self.assertNotIn("p1", lists["blacklisted"])

    def test_former_success_is_blocked_for_exactly_60_minutes_per_platform(self):
        for platform in proxies.PLATFORMS:
            with self.subTest(platform=platform):
                self.clock.return_value = 1000
                proxies.mark_proxy_working("p1", platform)
                proxies.blacklist_proxy("p1", platform)
                self.assertEqual(db.get_proxy_state_counts(platform), (1, 0, 0, 0, 0, 1))
                lists = db.get_proxy_lists(platform)
                self.assertEqual(lists["working_blacklisted"], ["p1"])
                self.assertEqual(lists["blacklisted"], ["p1"])
                self.assertEqual(lists["query_blacklisted"], [])
                # A new connection reads the deadline from disk, not process memory.
                with closing(sqlite3.connect(self.path)) as conn:
                    deadline = conn.execute(
                        "SELECT working_blacklisted_until FROM proxy_state WHERE platform=?",
                        (platform,),
                    ).fetchone()[0]
                self.assertEqual(deadline, 4600)
                self.clock.return_value = 4599.999
                for attempt in (1, 2, 3):
                    self.assertIsNone(proxies.get_random_proxy(platform, attempt=attempt))
                self.clock.return_value = 4600
                self.assertEqual(db.get_proxy_candidates(platform), ["p1"])
                self.assertEqual(db.get_proxy_candidates(platform, working_only=True), [])
                self.assertEqual(db.get_proxy_lists(platform)["blacklisted"], [])
                self.assertEqual(db.get_proxy_state_counts(platform), (1, 0, 0, 0, 1, 0))
                proxies.mark_proxy_working("p1", platform)
                self.assertEqual(db.get_proxy_candidates(platform, working_only=True), ["p1"])

    def test_expiry_recovers_exhausted_pool_without_rescan(self):
        proxies.mark_proxy_working("p1", "vinted")
        proxies.blacklist_proxy("p1", "vinted")
        with patch.object(proxies, "complete_proxy_rescan") as rescan, \
                patch.object(proxies, "fetch_proxies_from_link") as fetch:
            with self.assertRaises(proxies.NoProxyAvailable):
                proxies.require_proxy("vinted")
            self.clock.return_value = 4600
            proxies.require_proxy("vinted")
            self.assertEqual(proxies.get_random_proxy("vinted", attempt=3), "p1")
            rescan.assert_not_called()
            fetch.assert_not_called()

    def test_repeat_failure_restarts_cooldown_even_after_expiry(self):
        db.mark_proxy_result("vinted", "p1", True)
        for failed_at in (1000, 2000, 10000):
            with self.subTest(failed_at=failed_at):
                self.clock.return_value = failed_at
                self.assertEqual(db.mark_proxy_result("vinted", "p1", False), "working")
                self.clock.return_value = failed_at + 3599
                self.assertEqual(db.get_proxy_candidates("vinted"), [])
                self.assertEqual(db.get_proxy_lists("vinted")["query_blacklisted"], [])
                self.clock.return_value = failed_at + 3600
                self.assertEqual(db.get_proxy_candidates("vinted"), ["p1"])

    def test_late_inflight_success_does_not_lift_active_cooldown(self):
        db.mark_proxy_result("vinted", "p1", True)
        db.mark_proxy_result("vinted", "p1", False)
        self.clock.return_value = 1001
        db.mark_proxy_result("vinted", "p1", True)
        self.assertEqual(db.get_proxy_candidates("vinted", working_only=True), [])
        self.assertEqual(db.get_proxy_lists("vinted")["working"], [])
        self.assertEqual(db.get_proxy_state_counts("vinted"), (1, 0, 0, 0, 0, 1))

    def test_valid_manual_scan_can_release_cooldown_and_preserves_history(self):
        db.mark_proxy_result("vinted", "p1", True)
        db.mark_proxy_result("vinted", "p1", False)
        db.replace_proxy_scan_results("vinted", ["p1"], ["p1"])
        self.assertEqual(db.get_proxy_candidates("vinted"), ["p1"])
        # A scan is not a real search and must not promote the proxy to Working.
        self.assertEqual(db.get_proxy_candidates("vinted", working_only=True), [])
        self.assertEqual(db.get_proxy_lists("vinted")["working_blacklisted"], [])
        self.assertEqual(db.mark_proxy_result("vinted", "p1", False), "working")
        self.assertEqual(db.get_proxy_lists("vinted")["working_blacklisted"], ["p1"])

    def test_failed_scan_still_blocks_proxy_after_cooldown_expires(self):
        db.mark_proxy_result("vinted", "p1", True)
        db.mark_proxy_result("vinted", "p1", False)
        db.replace_proxy_scan_results("vinted", ["p1"], [])
        self.clock.return_value = 4600
        self.assertEqual(db.get_proxy_candidates("vinted"), [])
        self.assertEqual(db.get_proxy_lists("vinted")["working_blacklisted"], [])
        self.assertEqual(db.get_proxy_lists("vinted")["scan_blacklisted"], ["p1"])
        db.replace_proxy_scan_results("vinted", ["p1"], ["p1"])
        self.assertEqual(db.get_proxy_candidates("vinted"), ["p1"])

    def test_rescan_cannot_forget_unchecked_blacklisted_proxies(self):
        db.mark_proxy_result("vinted", "p1", True)
        db.mark_proxy_result("vinted", "p1", False)
        db.mark_proxy_result("vinted", "p2", False)
        db.replace_proxy_scan_results("vinted", ["p3"], [])
        lists = db.get_proxy_lists("vinted")
        self.assertEqual(lists["working_blacklisted"], ["p1"])
        self.assertEqual(lists["query_blacklisted"], ["p2"])
        self.assertEqual(lists["scan_blacklisted"], ["p3"])

    def test_cooldown_is_platform_specific_and_in_dashboard_counts(self):
        for platform in proxies.PLATFORMS:
            db.seed_proxy_pool(platform, ["p1"])
        proxies.mark_proxy_working("p1", "vinted")
        proxies.blacklist_proxy("p1", "vinted")
        self.assertEqual(db.get_proxy_candidates("kleinanzeigen"), ["p1"])
        stats = proxies.get_all_proxy_stats()
        self.assertEqual(stats["working_blacklisted_proxies"], 1)
        self.assertEqual(stats["per_platform"]["vinted"]["working_blacklisted_proxies"], 1)
        self.assertEqual(stats["available_proxies"], len(proxies.PLATFORMS) - 1)
        self.clock.return_value = 4600
        stats = proxies.get_all_proxy_stats()
        self.assertEqual(stats["working_blacklisted_proxies"], 0)
        self.assertEqual(stats["available_proxies"], len(proxies.PLATFORMS))

    def test_dashboard_and_config_render_cooldown_without_starting_server(self):
        root = Path(__file__).resolve().parents[1]
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.executescript((root / "initial_db.sql").read_text())
            params = dict(conn.execute("SELECT key, value FROM parameters"))
        env = Environment(
            loader=FileSystemLoader(root / "web_ui_plugin/templates"),
            undefined=StrictUndefined, autoescape=True,
        )
        env.globals.update(
            current_version="1.0.7.5", current_year=2026, github_url="",
            request=SimpleNamespace(path="/"), url_for=lambda *args, **kwargs: "/static/test",
            get_flashed_messages=lambda **kwargs: [],
        )
        proxies.mark_proxy_working("p1", "vinted")
        proxies.blacklist_proxy("p1", "vinted")
        for now, count in ((1000, 1), (4600, 0)):
            with self.subTest(now=now):
                self.clock.return_value = now
                dashboard = env.get_template("index.html").render(
                    params=params, proxy_stats=proxies.get_all_proxy_stats(),
                    stats={"total_items": 0, "total_queries": 0,
                           "items_per_day": 0, "last_item": None},
                    items=[], queries=[], worker_states=[], proxy_scan_states=[],
                    telegram_running=False, rss_running=False,
                )
                config = env.get_template("config.html").render(
                    params=params,
                    proxy_lists={p: db.get_proxy_lists(p) for p in proxies.PLATFORMS},
                )
                self.assertIn("Used / Working Blacklist", dashboard)
                self.assertIn("Automatically unblocked after 60 minutes", dashboard)
                self.assertIn(f"Used / Working Blacklist ({count})", config)


class ProxyCooldownMigrationTests(unittest.TestCase):
    def test_upgrade_converts_only_previous_query_successes_to_cooldowns(self):
        root = Path(__file__).resolve().parents[1]
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.execute("CREATE TABLE parameters (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO parameters VALUES ('version', '1.0.7.3')")
            conn.executescript((root / "migrations/1.0.7.3_1.0.7.4.sql").read_text())
            conn.executemany(
                """INSERT INTO proxy_state
                   (platform, proxy, query_blacklisted, scan_blacklisted,
                    last_success, last_failure) VALUES ('vinted', ?, 1, ?, ?, ?)""",
                [("former-success", 0, 900, 1000), ("never-worked", 0, None, 1000),
                 ("scan-blocked", 1, 900, 1000)],
            )
            conn.commit()
            conn.executescript((root / "migrations/1.0.7.4_1.0.7.5.sql").read_text())
            rows = dict((row[0], row[1:]) for row in conn.execute(
                "SELECT proxy, query_blacklisted, scan_blacklisted, "
                "working_blacklisted_until, last_success, last_failure FROM proxy_state"
            ))
            self.assertEqual(rows["former-success"], (0, 0, 4600, 900, 1000))
            self.assertEqual(rows["never-worked"], (1, 0, 0, None, 1000))
            self.assertEqual(rows["scan-blocked"], (1, 1, 0, 900, 1000))
            self.assertEqual(conn.execute(
                "SELECT value FROM parameters WHERE key='version'"
            ).fetchone()[0], "1.0.7.5")

    def test_new_install_includes_cooldown_column_and_version(self):
        root = Path(__file__).resolve().parents[1]
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.executescript((root / "initial_db.sql").read_text())
            conn.execute("INSERT INTO proxy_state (platform, proxy) VALUES ('vinted', 'p1')")
            self.assertEqual(conn.execute(
                "SELECT working_blacklisted_until FROM proxy_state"
            ).fetchone()[0], 0)
            self.assertEqual(conn.execute(
                "SELECT value FROM parameters WHERE key='version'"
            ).fetchone()[0], "1.0.7.5")


if __name__ == "__main__":
    unittest.main()
