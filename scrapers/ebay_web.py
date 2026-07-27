"""
eBay search-URL scraper (no API key needed).

Fetches an ebay.de/ebay.com search URL (/sch/i.html?...) and parses the result
cards from the HTML. eBay blocks plain HTTP clients via TLS fingerprinting, so
this module uses curl_cffi with browser impersonation. Requests are routed
through the eBay-specific proxy pool (platform="ebay") with rotation on blocks -
important because eBay blocks datacenter IPs, so a direct connection often 403s.

The search URL should be sorted by newly listed (_sop=10); core.py enforces
this when the query is added.
"""

import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

from bs4 import BeautifulSoup

import db
import proxies
from logger import get_logger

logger = get_logger(__name__)

# Tried in order until one returns a real result page. eBay's bot detection is
# fingerprint-specific: at the time of writing chrome124 passes while chrome131
# is blocked, so a single pinned profile would be fragile.
IMPERSONATE_PROFILES = ["chrome124", "chrome120", "chrome110", "chrome131", "chrome"]

# How many different eBay proxies to try before giving up on a fetch
MAX_PROXY_ATTEMPTS = 6
# Cap the per-attempt timeout for eBay fetches: a proxy slower than this is not
# worth waiting for, and a lower cap means dead proxies fail fast during rotation.
# (Session warming downloads the homepage + a ~1.5MB search page, so allow a bit.)
EBAY_FETCH_TIMEOUT_CAP = 12

PRICE_RE = re.compile(r"(?P<currency>EUR|USD|GBP|CHF|\$|£)\s*(?P<amount>\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:\.\d+)?)")
DATE_RE = re.compile(r"^(\d{1,2})\.?\s*([A-Za-zÄäÖöÜü]{3})\.?\s+(\d{1,2}):(\d{2})$")
ITM_ID_RE = re.compile(r"/itm/(\d{9,})")

MONTHS = {
    "jan": 1, "feb": 2, "mär": 3, "mrz": 3, "mar": 3, "apr": 4, "mai": 5, "may": 5,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12,
}

CURRENCY_MAP = {"$": "USD", "£": "GBP"}


def _parse_price(price_text):
    """
    Parse an eBay price string like 'EUR 162,00', '$20.00' or
    'EUR 12,50 bis EUR 20,00' (uses the first price of a range).

    Returns:
        tuple: (price as float, currency code)
    """
    if not price_text:
        return 0.0, "EUR"
    match = PRICE_RE.search(price_text)
    if not match:
        return 0.0, "EUR"
    currency = CURRENCY_MAP.get(match.group("currency"), match.group("currency"))
    amount = match.group("amount")
    if "," in amount:
        # German format: 1.234,56
        amount = amount.replace(".", "").replace(",", ".")
    try:
        return float(amount), currency
    except ValueError:
        return 0.0, currency


def _parse_date(date_text):
    """
    Parse an eBay listing date like '27. Jul. 09:54' (German) or
    'Jul 27, 09:54'-style variants into a unix timestamp.

    Returns:
        int: Unix timestamp, or 0 if not parseable
    """
    if not date_text:
        return 0
    match = DATE_RE.match(date_text.strip())
    if not match:
        return 0
    day, month_name, hour, minute = match.groups()
    month = MONTHS.get(month_name.lower())
    if not month:
        return 0
    now = datetime.now()
    try:
        dt = now.replace(
            month=month, day=int(day), hour=int(hour), minute=int(minute),
            second=0, microsecond=0,
        )
    except ValueError:
        return 0
    # Year boundary: a December date seen in January belongs to last year
    if dt > now + timedelta(days=1):
        dt = dt.replace(year=dt.year - 1)
    return int(dt.timestamp())


class EbayWebItem:
    """
    A single scraped eBay listing, exposing the same attributes as the
    pyVintedVN Item class so it can flow through core.clear_item_queue unchanged.
    """

    platform = "ebay"

    def __init__(self, card, base_netloc):
        self.raw_data = {}

        link = card.find("a", href=True)
        href = link["href"] if link else ""
        itm_match = ITM_ID_RE.search(href)
        listing_id = card.get("data-listingid", "")
        if itm_match:
            self.id = itm_match.group(1)
        elif listing_id.isdigit() and len(listing_id) >= 9:
            self.id = listing_id
        else:
            self.id = None
        # Canonical URL without tracking parameters
        self.url = f"https://{base_netloc}/itm/{self.id}" if self.id else href

        # The real title sits in a child span; "Neues Angebot" badge and the
        # screen-reader "opens in new tab" span must not leak into it
        title_el = card.select_one(".s-card__title")
        self.title = "No title"
        if title_el:
            main_span = title_el.select_one("span.su-styled-text")
            if main_span:
                self.title = main_span.get_text(strip=True)
            else:
                for junk in title_el.select(".clipped, .s-card__new-listing"):
                    junk.decompose()
                self.title = title_el.get_text(strip=True) or "No title"

        price_el = card.select_one(".s-card__price")
        self.price, self.currency = _parse_price(price_el.get_text(strip=True) if price_el else "")

        # Condition ("Gebraucht | Privat") fills the {brand} template slot
        subtitle_el = card.select_one(".s-card__subtitle")
        subtitle = subtitle_el.get_text(" ", strip=True) if subtitle_el else ""
        self.brand_title = re.sub(r"\s*\|\s*", " | ", subtitle) or "eBay"

        self.photo = None
        img = card.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or ""
            if src.startswith("http") and "ebaystatic" not in src:
                self.photo = src

        # Listing date is one of the attribute rows (only present with _sop=10);
        # sponsored/ad cards have none and therefore never count as new
        self.raw_timestamp = 0
        for row in card.select(".s-card__attribute-row"):
            ts = _parse_date(row.get_text(strip=True))
            if ts:
                self.raw_timestamp = ts
                break

    def is_new_item(self, minutes=20):
        if not self.raw_timestamp:
            return False
        return (time.time() - self.raw_timestamp) < minutes * 60

    def __eq__(self, other):
        return isinstance(other, EbayWebItem) and self.id == other.id

    def __hash__(self):
        return hash(("ebay", self.id))


def _fetch_once(url, proxy_dict, timeout):
    """
    Fetch the eBay search page over one proxy (or direct connection) using
    SESSION WARMING: first load the eBay homepage to obtain consent/session
    cookies, then request the search URL within the same cookie session.

    A cold search request (no cookies) is reliably answered with HTTP 403,
    whereas a warmed session usually gets through - even on an IP that 403s
    cold requests. (Technique adapted from a Scrapy-based eBay scraper that
    warms cookies via a homepage request before searching.)

    Rotating fingerprints only helps when eBay answered and blocked the search;
    on a homepage block (IP-level) or a connection failure we abort this proxy
    immediately instead of burning time on every remaining profile.

    Returns:
        str or None: The HTML body if a profile succeeded, else None
    """
    from curl_cffi import requests as curl_requests

    parsed = urlparse(url)
    homepage = f"{parsed.scheme}://{parsed.netloc}/"

    for profile in IMPERSONATE_PROFILES:
        try:
            session = curl_requests.Session(impersonate=profile)
            session.headers.update(
                {
                    "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
                    "Upgrade-Insecure-Requests": "1",
                }
            )
            req_kwargs = {"timeout": timeout}
            if proxy_dict:
                req_kwargs["proxies"] = proxy_dict

            # 1) Warm the session: the homepage sets consent/session cookies
            home = session.get(homepage, **req_kwargs)
            if home.status_code != 200:
                # A block here is IP-level - no fingerprint will help. Abort proxy.
                logger.warning(
                    f"[ebay] homepage warm-up blocked (HTTP {home.status_code}) via this proxy, skipping it"
                )
                return None

            # 2) The actual search, carrying the warmed cookies
            response = session.get(url, **req_kwargs)
            # Block pages are ~2KB error stubs; real result pages are >100KB
            if response.status_code == 200 and len(response.text) > 50000:
                logger.info(f"[ebay] page fetched with profile {profile} (session-warmed)")
                return response.text
            logger.warning(
                f"[ebay] search blocked profile {profile} (HTTP {response.status_code}, {len(response.text)} bytes)"
            )
            # Got an HTTP response on the search: a different fingerprint might
            # get through, so keep trying the remaining profiles on this proxy.
        except Exception as e:
            # Connection-level failure (timeout, refused, ...): the proxy is
            # dead/unreachable. Abort - other profiles would only time out too.
            logger.warning(
                f"[ebay] proxy/connection failed on profile {profile}, "
                f"skipping remaining profiles: {str(e)[:150]}"
            )
            return None
    return None


def _fetch(url):
    """
    Fetch an eBay page with curl_cffi browser impersonation, routed through the
    eBay proxy pool. Rotates through several proxies (blacklisting failures)
    before falling back to a direct connection.

    Returns:
        str: The HTML body

    Raises:
        RuntimeError: If curl_cffi is missing or all attempts are blocked
    """
    try:
        import curl_cffi  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "curl_cffi is required for eBay URL scraping (pip install curl_cffi)"
        ) from e

    timeout_str = db.get_parameter("request_timeout")
    timeout = int(timeout_str) if timeout_str else 10
    # Fail fast on slow/dead proxies during rotation
    timeout = min(timeout, EBAY_FETCH_TIMEOUT_CAP)

    # Try up to MAX_PROXY_ATTEMPTS different eBay proxies
    tried_direct = False
    for attempt in range(1, MAX_PROXY_ATTEMPTS + 1):
        proxy_dict, current_proxy = proxies.get_proxy_dict("ebay")
        if current_proxy:
            logger.info(f"[ebay] fetching via proxy {current_proxy} (attempt {attempt}/{MAX_PROXY_ATTEMPTS})")
        else:
            logger.info(f"[ebay] no proxy available, fetching directly (attempt {attempt}/{MAX_PROXY_ATTEMPTS})")
            tried_direct = True

        html = _fetch_once(url, proxy_dict, timeout)
        if html is not None:
            return html

        if current_proxy:
            proxies.blacklist_proxy(current_proxy, "ebay")
        else:
            # No proxy available and direct failed: no point retrying direct
            break

    # Last resort: try a direct connection if we haven't yet
    if not tried_direct:
        logger.info("[ebay] all proxies blocked, trying a direct connection")
        html = _fetch_once(url, None, timeout)
        if html is not None:
            return html

    raise RuntimeError("eBay blocked all impersonation profiles (proxies and direct)")


def parse_html(html, base_netloc="www.ebay.de"):
    """
    Parse an eBay search result page into EbayWebItem objects.
    Skips the "Shop on eBay" placeholder card and cards without a valid item id.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("li.s-card")
    if not cards:
        # Old markup fallback
        cards = soup.select("li.s-item")
    items = []
    for card in cards:
        try:
            item = EbayWebItem(card, base_netloc)
            if item.id and item.title != "Shop on eBay":
                items.append(item)
        except Exception as e:
            logger.warning(f"Error parsing eBay card: {e}")
    return items


def search(url, nbr_items=20):
    """
    Retrieve listings from an eBay search URL (scraper, no API).

    Args:
        url (str): The ebay search URL (/sch/i.html?...), sorted by newly listed.
            A plain search term is also accepted and converted to an ebay.de URL.
        nbr_items (int, optional): Maximum number of items to return

    Returns:
        List[EbayWebItem]: Parsed listings in page order (newest first)
    """
    if not url.startswith("http"):
        from urllib.parse import urlencode

        url = f"https://www.ebay.de/sch/i.html?{urlencode({'_nkw': url, '_sop': '10'})}"
    html = _fetch(url)
    netloc = urlparse(url).netloc or "www.ebay.de"
    items = parse_html(html, base_netloc=netloc)
    logger.info(f"Parsed {len(items)} eBay listings from search page")
    return items[:nbr_items]
