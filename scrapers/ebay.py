"""
eBay search via the official eBay Developer Browse API.

Uses the client-credentials OAuth flow with the App ID (Client ID) and
Cert ID (Client Secret) configured in the parameters table. Requests go
directly to api.ebay.com - NO proxy is used for eBay on purpose, since the
official API is keyed to the developer account.
"""

import base64
import time
from datetime import datetime, timezone

import requests

import db
from logger import get_logger

logger = get_logger(__name__)

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

# Explicitly bypass any proxy (including environment proxies)
NO_PROXY = {"http": None, "https": None}

# Module-level token cache (one per process)
_token_cache = {"token": None, "expires_at": 0}


def _get_timeout():
    timeout_str = db.get_parameter("request_timeout")
    return int(timeout_str) if timeout_str else 10


def _get_access_token(force_refresh=False):
    """
    Get (and cache) an application OAuth token via the client-credentials flow.

    Raises:
        ValueError: If the eBay credentials are not configured
        requests.HTTPError: If the token request fails
    """
    if (
        not force_refresh
        and _token_cache["token"]
        and time.time() < _token_cache["expires_at"] - 60
    ):
        return _token_cache["token"]

    app_id = db.get_parameter("ebay_app_id")
    cert_id = db.get_parameter("ebay_cert_id")
    if not app_id or not cert_id:
        raise ValueError(
            "eBay API credentials not configured (set ebay_app_id and ebay_cert_id in the configuration panel)"
        )

    credentials = base64.b64encode(f"{app_id}:{cert_id}".encode()).decode()
    response = requests.post(
        OAUTH_URL,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        },
        timeout=_get_timeout(),
        proxies=NO_PROXY,
    )
    response.raise_for_status()
    data = response.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + int(data.get("expires_in", 7200))
    logger.info("Fetched new eBay OAuth token")
    return _token_cache["token"]


class EbayItem:
    """
    A single eBay listing, exposing the same attributes as the pyVintedVN Item
    class so it can flow through core.clear_item_queue unchanged.
    """

    platform = "ebay"

    def __init__(self, summary):
        self.raw_data = summary
        self.id = str(summary.get("legacyItemId") or summary.get("itemId"))
        self.title = summary.get("title", "No title")

        price = summary.get("price") or summary.get("currentBidPrice") or {}
        try:
            self.price = float(price.get("value", 0))
        except (TypeError, ValueError):
            self.price = 0.0
        self.currency = price.get("currency", "EUR")

        # Condition ("Neu", "Gebraucht", ...) fills the {brand} template slot
        self.brand_title = summary.get("condition") or "eBay"

        self.url = summary.get("itemWebUrl", "")

        self.photo = None
        image = summary.get("image") or {}
        if image.get("imageUrl"):
            self.photo = image["imageUrl"]
        else:
            thumbnails = summary.get("thumbnailImages") or []
            if thumbnails and thumbnails[0].get("imageUrl"):
                self.photo = thumbnails[0]["imageUrl"]

        self.raw_timestamp = self._parse_creation_date(summary.get("itemCreationDate"))
        self._has_creation_date = self.raw_timestamp > 0
        if not self._has_creation_date:
            # No creation date in the response: treat as "now" and rely on the
            # item-id dedup in the pipeline to avoid resending
            self.raw_timestamp = int(time.time())

    @staticmethod
    def _parse_creation_date(value):
        if not value:
            return 0
        try:
            # e.g. 2026-07-27T12:34:56.000Z
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return int(dt.timestamp())
        except ValueError:
            return 0

    def is_new_item(self, minutes=20):
        if not self._has_creation_date:
            return True
        return (time.time() - self.raw_timestamp) < minutes * 60

    def __eq__(self, other):
        return isinstance(other, EbayItem) and self.id == other.id

    def __hash__(self):
        return hash(("ebay", self.id))


def search(keyword, nbr_items=20):
    """
    Search eBay for newly listed items matching a keyword.

    Args:
        keyword (str): The search term (stored as the query text)
        nbr_items (int, optional): Maximum number of items to return

    Returns:
        List[EbayItem]: Listings sorted by listing date (newest first)
    """
    marketplace = db.get_parameter("ebay_marketplace") or "EBAY_DE"
    params = {
        "q": keyword,
        "sort": "newlyListed",
        "limit": min(max(int(nbr_items), 1), 200),
    }

    token = _get_access_token()
    for attempt in range(2):
        response = requests.get(
            BROWSE_SEARCH_URL,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": marketplace,
                "Accept": "application/json",
            },
            timeout=_get_timeout(),
            proxies=NO_PROXY,
        )
        if response.status_code == 401 and attempt == 0:
            # Token expired or revoked: refresh once and retry
            logger.warning("eBay token rejected (401), refreshing token")
            token = _get_access_token(force_refresh=True)
            continue
        break

    response.raise_for_status()
    summaries = response.json().get("itemSummaries", [])
    items = [EbayItem(s) for s in summaries]
    logger.info(f"eBay API returned {len(items)} listings for '{keyword}'")
    return items
