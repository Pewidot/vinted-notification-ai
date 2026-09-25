import time
import unittest
from queue import Queue
from unittest.mock import ANY, MagicMock, patch

import core
from pyVintedVN.items.item import Item
from pyVintedVN.items.items import Items
from pyVintedVN.requester import Requester


class VintedCatalogueTests(unittest.TestCase):
    @staticmethod
    def make_item(item_id=12345678901):
        return Item(
            {
                "id": item_id,
                "title": "Nike trainers",
                "item_box": {
                    "first_line": "Nike",
                    "second_line": "42 · Very good",
                },
                "price": {"amount": "25.00", "currency_code": "EUR"},
                "photo": {
                    "url": "https://images.example/item.jpg",
                    "high_resolution": {"id": "1", "orientation": "portrait"},
                },
                "url": f"/items/{item_id}-nike-trainers",
            },
            locale="www.vinted.de",
        )

    def test_new_filter_names_and_empty_values(self):
        params = Items().parse_url(
            "https://www.vinted.de/catalog?brand_ids%5B%5D=53"
            "&catalog%5B%5D=79&price_to=&order=newest_first",
            nbr_items=20,
        )

        self.assertEqual(params["attribute_ids[brand]"], "53")
        self.assertEqual(params["attribute_ids[catalog]"], "79")
        self.assertNotIn("brand_ids", params)
        self.assertNotIn("price_to", params)
        self.assertNotIn("time", params)

    def test_new_item_shape_and_relative_url(self):
        before = int(time.time())
        item = self.make_item()

        self.assertEqual(item.brand_title, "Nike")
        self.assertEqual(item.size_title, "42")
        self.assertEqual(
            item.url, "https://www.vinted.de/items/12345678901-nike-trainers"
        )
        self.assertIn("https://www.vinted.de/transaction/buy/new", item.buy_url)
        self.assertFalse(item.has_real_timestamp)
        self.assertGreaterEqual(item.raw_timestamp, before)
        self.assertTrue(item.is_new_item())

    def test_title_is_not_mistaken_for_brand(self):
        item = Item(
            {
                "id": 123,
                "title": "Unbranded coat",
                "item_box": {"first_line": "Unbranded coat", "second_line": "Good"},
                "price": {"amount": "5.00", "currency_code": "EUR"},
                "photo": None,
                "url": "/items/123-unbranded-coat",
            },
            locale="www.vinted.fr",
        )
        self.assertIsNone(item.brand_title)
        self.assertIsNone(item.size_title)

    def test_api_host_and_auth_headers(self):
        requester = Requester()
        requester.set_locale("www.vinted.nl")
        requester.session.cookies.set("access_token_web", "token")
        requester.session.cookies.set("anon_id", "anonymous")

        self.assertEqual(requester.get_api_host(), "api.vinted.nl")
        self.assertEqual(requester._auth_headers()["Authorization"], "Bearer token")
        self.assertEqual(requester._auth_headers()["x-anon-id"], "anonymous")
        self.assertNotIn("Host", requester.session.headers)

    def test_switching_market_clears_anonymous_auth_cookies(self):
        requester = Requester()
        requester.set_locale("www.vinted.com")
        requester.session.cookies.set("access_token_web", "us-token")
        requester.session.cookies.set("anon_id", "us-anonymous")

        requester.set_locale("www.vinted.de")

        self.assertIsNone(requester.session.cookies.get("access_token_web"))
        self.assertIsNone(requester.session.cookies.get("anon_id"))
        self.assertEqual(requester.VINTED_AUTH_URL, "https://www.vinted.de/")

    @patch("core.db.get_parameter", return_value="de")
    @patch("core.requester")
    def test_cross_market_item_must_be_buyable_from_germany(
        self, requester_mock, _get_parameter
    ):
        item = self.make_item()
        item.url = "https://www.vinted.co.uk/items/12345678901-nike-trainers"
        requester_mock.session.cookies.get.return_value = "german-token"
        response = MagicMock()
        response.status_code = 200
        response.text = (
            r'{\"can_buy\":false,\"instant_buy\":false,'
            r'\"item_id\":\"12345678901\"}'
        )
        requester_mock.get.return_value = response

        self.assertFalse(core.can_buy_from_delivery_market(item))
        requester_mock.set_locale.assert_called_once_with("www.vinted.de")
        requester_mock.get.assert_called_once_with(
            "https://www.vinted.de/items/12345678901-nike-trainers"
        )

    @patch("core.db.get_parameter", return_value="de")
    @patch("core.requester")
    def test_delivery_check_ignores_other_items_in_page(
        self, requester_mock, _get_parameter
    ):
        item = self.make_item()
        item.url = "https://www.vinted.fr/items/12345678901-nike-trainers"
        requester_mock.session.cookies.get.return_value = "german-token"
        response = MagicMock()
        response.status_code = 200
        response.text = (
            r'{\"can_buy\":true,\"item_id\":\"999\"}'
            r'{\"can_buy\":false,\"item_id\":\"12345678901\"}'
        )
        requester_mock.get.return_value = response

        self.assertFalse(core.can_buy_from_delivery_market(item))

    @patch("core.debug_log.log")
    @patch("core.db.update_last_timestamp")
    @patch("core.db.add_item_to_db")
    @patch("core.db.is_item_in_db_by_id", return_value=False)
    @patch("core.db.get_last_timestamp", return_value=None)
    @patch("core.db.get_parameter", return_value="")
    def test_first_timestamp_less_run_is_recorded_silently(
        self,
        _get_parameter,
        _get_last_timestamp,
        _is_known,
        add_item,
        update_watermark,
        _debug_log,
    ):
        incoming = Queue()
        notifications = Queue()
        incoming.put(([self.make_item()], 42))

        core.clear_item_queue(incoming, notifications)

        self.assertTrue(notifications.empty())
        add_item.assert_called_once()
        update_watermark.assert_called_once()

    @patch("core.debug_log.log")
    @patch("core.db.mark_query_success")
    @patch("core.db.update_last_timestamp")
    @patch("core.db.get_last_timestamp", return_value=None)
    @patch("core.db.mark_query_scraped")
    @patch("core.Vinted")
    def test_empty_first_page_still_establishes_baseline(
        self,
        vinted_class,
        _mark_scraped,
        _get_last_timestamp,
        update_watermark,
        _mark_success,
        _debug_log,
    ):
        vinted = MagicMock()
        vinted.items.search.return_value = []
        vinted_class.return_value = vinted
        query = (42, "https://www.vinted.de/catalog?search_text=rare", 0,
                 "rare", None, 1, "vinted", 1, 60, 0, 0)
        results = Queue()

        core._scrape_platform_queries("vinted", [query], 20, results)

        update_watermark.assert_called_once_with(42, ANY)
        self.assertEqual(results.get_nowait(), ([], 42))


if __name__ == "__main__":
    unittest.main()
