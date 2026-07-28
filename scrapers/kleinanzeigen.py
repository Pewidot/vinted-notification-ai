"""
Kleinanzeigen scraper.

Fetches a kleinanzeigen.de search URL and parses the result list from the HTML.
Uses the platform-specific Kleinanzeigen proxy pool (proxies.configure_proxy /
proxies.blacklist_proxy with platform="kleinanzeigen") with rotation on failures.

Parsing approach based on https://github.com/Superschnizel/Kleinanzeigen-Telegram-Bot
"""

import json
import random
import re
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

import db
import proxies
from logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://www.kleinanzeigen.de"
MAX_PROXY_RETRIES = 3

PRICE_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?)")


def _parse_price(price_text):
    """
    Parse a Kleinanzeigen price string like '1.234 €', '120 € VB' or 'Zu verschenken'.

    Returns:
        float: The price (0 if free or not parseable)
    """
    if not price_text:
        return 0.0
    match = PRICE_RE.search(price_text)
    if not match:
        return 0.0
    number = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(number)
    except ValueError:
        return 0.0


def _parse_date(date_text):
    """
    Parse a Kleinanzeigen listing date like 'Heute, 12:34', 'Gestern, 18:15'
    or '12.07.2026' into a unix timestamp.

    Returns:
        int: Unix timestamp, or 0 if the date cannot be parsed
             (e.g. promoted "TOP" ads without a date - these are old ads anyway)
    """
    if not date_text:
        return 0
    date_text = date_text.strip()
    try:
        now = datetime.now()
        if date_text.lower().startswith("heute"):
            time_part = date_text.split(",", 1)[1].strip() if "," in date_text else "00:00"
            hour, minute = map(int, time_part.split(":"))
            return int(now.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp())
        if date_text.lower().startswith("gestern"):
            time_part = date_text.split(",", 1)[1].strip() if "," in date_text else "00:00"
            hour, minute = map(int, time_part.split(":"))
            yesterday = now - timedelta(days=1)
            return int(yesterday.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp())
        # Absolute date like 12.07.2026
        return int(datetime.strptime(date_text, "%d.%m.%Y").timestamp())
    except (ValueError, IndexError):
        return 0


class KleinanzeigenItem:
    """
    A single Kleinanzeigen listing, exposing the same attributes as the
    pyVintedVN Item class so it can flow through core.clear_item_queue unchanged.
    """

    platform = "kleinanzeigen"
    currency = "EUR"

    def __init__(self, article):
        self.raw_data = {}

        href = article.get("data-href") or (article.a.get("href") if article.a else "")
        self.url = urljoin(BASE_URL, href)

        # data-adid is the stable numeric ad id
        adid = article.get("data-adid")
        if adid:
            self.id = str(adid)
        else:
            # Fallback: extract the id from the URL (…/title/2145678901-217-1234)
            last_segment = self.url.rstrip("/").split("/")[-1]
            self.id = last_segment.split("-")[0]

        title_el = article.find("h2", class_="text-module-begin") or article.find("a", class_="ellipsis")
        self.title = title_el.get_text(strip=True) if title_el else "No title"

        price_el = article.find("p", class_="aditem-main--middle--price-shipping--price")
        self.price_text = price_el.get_text(strip=True) if price_el else ""
        self.price = _parse_price(self.price_text)

        # Location goes into brand_title so the {brand} message template slot shows it
        location_el = article.find("div", class_="aditem-main--top--left")
        self.brand_title = location_el.get_text(strip=True) if location_el else "Kleinanzeigen"

        date_el = article.find("div", class_="aditem-main--top--right")
        self.raw_timestamp = _parse_date(date_el.get_text(strip=True) if date_el else "")

        self.photo = None
        img = article.find("img")
        if img:
            src = img.get("src") or img.get("data-imgsrc") or ""
            if not src and img.get("srcset"):
                src = img["srcset"].split(",")[0].strip().split(" ")[0]
            if src.startswith("//"):
                src = "https:" + src
            self.photo = src or None

    def is_new_item(self, minutes=20):
        """
        Same semantics as the Vinted item: only listings posted within the last
        `minutes` minutes count as new. Ads without a parseable date (promoted
        TOP ads) are never considered new.
        """
        if not self.raw_timestamp:
            return False
        return (time.time() - self.raw_timestamp) < minutes * 60

    def __eq__(self, other):
        return isinstance(other, KleinanzeigenItem) and self.id == other.id

    def __hash__(self):
        return hash(("kleinanzeigen", self.id))


def _fetch(url):
    """
    Fetch a Kleinanzeigen page using the platform proxy pool with rotation.

    If proxies are configured, a direct connection is never used as a fallback -
    that would expose the server IP. Once every proxy has failed, the platform
    pauses (see proxies.POOL_EXHAUSTED_COOLDOWN) and the list is re-checked
    afterwards.

    Returns:
        str: The HTML body

    Raises:
        proxies.NoProxyAvailable: pool configured but exhausted
        requests.HTTPError: If all attempts fail
    """
    # Refuse early while the pool is in its cooldown
    proxies.require_proxy("kleinanzeigen")
    proxies_configured = proxies.has_proxies_configured("kleinanzeigen")

    timeout_str = db.get_parameter("request_timeout")
    timeout = int(timeout_str) if timeout_str else 10

    user_agents_json = db.get_parameter("user_agents")
    user_agents = json.loads(user_agents_json) if user_agents_json else []

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": random.choice(user_agents) if user_agents else "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
            "Connection": "keep-alive",
        }
    )

    last_error = None
    for attempt in range(1, MAX_PROXY_RETRIES + 1):
        proxy_configured, current_proxy = proxies.configure_proxy(session, "kleinanzeigen")
        if current_proxy is None and proxies_configured:
            # Pool ran dry mid-rotation: pause instead of going direct
            proxies.mark_pool_exhausted("kleinanzeigen")
            raise proxies.NoProxyAvailable(
                "kleinanzeigen: no usable proxy left, pausing until the next re-check"
            )
        logger.info(
            f"Fetching Kleinanzeigen page (attempt {attempt}/{MAX_PROXY_RETRIES}) | "
            f"Proxy: {current_proxy or 'None'}"
        )
        try:
            response = session.get(url, timeout=timeout)
            if response.status_code == 200:
                return response.text
            last_error = requests.HTTPError(f"HTTP {response.status_code}")
            logger.warning(
                f"Kleinanzeigen returned HTTP {response.status_code} | Proxy: {current_proxy or 'None'}"
            )
            if current_proxy:
                proxies.blacklist_proxy(current_proxy, "kleinanzeigen")
        except requests.RequestException as e:
            last_error = e
            logger.warning(
                f"{type(e).__name__} fetching Kleinanzeigen | Proxy: {current_proxy or 'None'}: {str(e)[:200]}"
            )
            if current_proxy:
                proxies.blacklist_proxy(current_proxy, "kleinanzeigen")

    if proxies_configured:
        # Every proxy we tried is now blacklisted - pause the platform
        proxies.mark_pool_exhausted("kleinanzeigen")
        raise proxies.NoProxyAvailable(
            "kleinanzeigen: all proxies blocked, pausing until the next re-check"
        )
    raise requests.HTTPError(
        f"Failed to fetch Kleinanzeigen page after {MAX_PROXY_RETRIES} attempts: {last_error}"
    )


def parse_html(html):
    """
    Parse a Kleinanzeigen search result page into KleinanzeigenItem objects.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for article in soup.find_all("article", class_="aditem"):
        try:
            item = KleinanzeigenItem(article)
            if item.id and "/s-anzeige/" in item.url:
                items.append(item)
        except Exception as e:
            logger.warning(f"Error parsing Kleinanzeigen article: {e}")
    return items


def page_url(url, page):
    """
    Build the URL for result page N.

    Kleinanzeigen puts the page into the path rather than a query parameter:
        /s-nike-air-max/k0  ->  /s-seite:2/nike-air-max/k0
    """
    if page <= 1:
        return url
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    # Path-based paging applies to the /s-<term>/... layout, not to the
    # /s-suchanfrage.html?keywords=... form, which pages via a query parameter.
    if parts and parts[0].startswith("s-") and not parts[0].endswith(".html"):
        rest = parts[0][2:]  # drop the leading "s-"
        new_parts = [f"s-seite:{page}"]
        if rest:
            new_parts.append(rest)
        new_parts.extend(parts[1:])
        new_path = "/" + "/".join(new_parts)
        return urlunparse(
            (parsed.scheme, parsed.netloc, new_path, parsed.params,
             parsed.query, parsed.fragment)
        )
    # Unknown layout (e.g. /s-suchanfrage.html?keywords=...) -> use the query param
    params = parse_qs(parsed.query)
    params["pageNum"] = [str(page)]
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params,
         urlencode(params, doseq=True), parsed.fragment)
    )


def search(url, nbr_items=20, page=1):
    """
    Retrieve listings from a Kleinanzeigen search URL.

    Args:
        url (str): The kleinanzeigen.de search URL
        nbr_items (int, optional): Maximum number of items to return
        page (int, optional): Result page to fetch (1 = newest)

    Returns:
        List[KleinanzeigenItem]: Parsed listings, newest first (page order)
    """
    html = _fetch(page_url(url, page))
    items = parse_html(html)
    logger.info(f"Parsed {len(items)} Kleinanzeigen listings (page {page})")
    return items[:nbr_items]
