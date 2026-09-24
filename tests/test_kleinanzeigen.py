import unittest
from datetime import datetime

from scrapers.kleinanzeigen import parse_html


CURRENT_CARD = """
<article class="flex justify-between p-medium" data-adid="3521691864"
         data-href="/s-anzeige/funkeys-figuren-konvolut/3521691864-227-6629">
  <img src="https://img.example/current.jpg">
  <div><svg data-title="locationOutline"></svg><span>84524 Neuötting</span></div>
  <div><svg data-title="calendarOutline"></svg><span>Heute, 10:44</span></div>
  <h3><a href="/s-anzeige/funkeys-figuren-konvolut/3521691864-227-6629">
    U.B. Funkeys Figuren Konvolut
  </a></h3>
  <p>Eine Beschreibung des Artikels.</p>
  <p class="my-xsmall text-title3 font-strong text-secondary">125 € VB</p>
</article>
"""


LEGACY_CARD = """
<article class="aditem" data-adid="2145678901"
         data-href="/s-anzeige/legacy-listing/2145678901-227-1234">
  <h2 class="text-module-begin">Legacy title</h2>
  <p class="aditem-main--middle--price-shipping--price">1.234,50 €</p>
  <div class="aditem-main--top--left">10115 Berlin</div>
  <div class="aditem-main--top--right">18.09.2026</div>
  <img data-imgsrc="https://img.example/legacy.jpg">
</article>
"""


class KleinanzeigenParserTests(unittest.TestCase):
    def test_current_card_markup(self):
        items = parse_html(CURRENT_CARD)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.id, "3521691864")
        self.assertEqual(item.title, "U.B. Funkeys Figuren Konvolut")
        self.assertEqual(item.price, 125.0)
        self.assertEqual(item.price_text, "125 € VB")
        self.assertEqual(item.brand_title, "84524 Neuötting")
        self.assertEqual(item.photo, "https://img.example/current.jpg")
        self.assertEqual(datetime.fromtimestamp(item.raw_timestamp).hour, 10)
        self.assertEqual(datetime.fromtimestamp(item.raw_timestamp).minute, 44)

    def test_legacy_card_markup_still_works(self):
        items = parse_html(LEGACY_CARD)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.title, "Legacy title")
        self.assertEqual(item.price, 1234.5)
        self.assertEqual(item.brand_title, "10115 Berlin")
        self.assertEqual(item.photo, "https://img.example/legacy.jpg")
        self.assertEqual(
            datetime.fromtimestamp(item.raw_timestamp).date(),
            datetime(2026, 9, 18).date(),
        )


if __name__ == "__main__":
    unittest.main()
