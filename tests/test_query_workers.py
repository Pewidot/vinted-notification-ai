import threading
import time
import unittest
from queue import Queue
from unittest.mock import patch

import core


class QueryWorkerIsolationTests(unittest.TestCase):
    def tearDown(self):
        with core._QUERY_WORKERS_LOCK:
            core._QUERY_WORKERS.clear()

    def test_stuck_query_does_not_block_another_query(self):
        release_first = threading.Event()
        second_started = threading.Event()
        queries = [
            (1, "https://www.vinted.de/catalog?search_text=one", 0, "one",
             None, 1, "vinted", 1, 60, 0, 0),
            (2, "https://www.vinted.de/catalog?search_text=two", 0, "two",
             None, 1, "vinted", 1, 60, 0, 0),
        ]

        def fake_worker(_platform, query, _items_per_query, _queue):
            if query[0] == 1:
                release_first.wait(2)
            else:
                second_started.set()

        with patch("core.db.get_queries", return_value=queries), \
             patch("core.db.get_parameter", side_effect=lambda key: "20" if key == "items_per_query" else "60"), \
             patch("core._scrape_query_worker", side_effect=fake_worker):
            started = time.monotonic()
            core.process_items(Queue())
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.5)
        self.assertTrue(second_started.wait(0.5))
        release_first.set()


if __name__ == "__main__":
    unittest.main()
