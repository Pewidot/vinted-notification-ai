import db
import requests
from pyVintedVN import Vinted, requester
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from logger import get_logger

# Get logger for this module
logger = get_logger(__name__)


def normalize_query_for_platform(query, platform):
    """
    Validate and normalize a query for the given platform.

    - vinted: normalize the search URL (order flag, remove volatile params)
    - kleinanzeigen: must be a kleinanzeigen.de URL, kept as-is (pagination stripped)
    - ebay: an ebay search URL (normalized to sort by newly listed, _sop=10).
      A plain search term is converted into an ebay.de search URL.
      Either way the stored query is a URL that gets scraped.

    Args:
        query (str): The query URL or search term
        platform (str): 'vinted', 'kleinanzeigen' or 'ebay'

    Returns:
        tuple: (processed_query, error_message)
            - processed_query (str or None): The normalized query, None on error
            - error_message (str or None): Error description if invalid
    """
    platform = (platform or "vinted").lower()

    if platform == "kleinanzeigen":
        parsed_url = urlparse(query)
        if "kleinanzeigen." not in parsed_url.netloc:
            return None, "Invalid Kleinanzeigen URL (expected a kleinanzeigen.de search URL)."
        return query, None

    if platform == "ebay":
        query = (query or "").strip()
        if not query:
            return None, "No eBay search term or URL provided."
        if not query.startswith("http"):
            # Plain search term -> build an ebay.de search URL from it
            query = f"https://www.ebay.de/sch/i.html?{urlencode({'_nkw': query})}"
        # Force newest-first sorting and strip pagination so the pipeline
        # sees new items first.
        parsed_url = urlparse(query)
        if "ebay." not in parsed_url.netloc:
            return None, "Invalid eBay URL (expected an ebay search URL, e.g. https://www.ebay.de/sch/...)."
        query_params = parse_qs(parsed_url.query)
        query_params["_sop"] = ["10"]
        query_params.pop("_pgn", None)
        new_query = urlencode(query_params, doseq=True)
        processed = urlunparse(
            (parsed_url.scheme, parsed_url.netloc, parsed_url.path,
             parsed_url.params, new_query, parsed_url.fragment)
        )
        return processed, None

    if platform != "vinted":
        return None, f"Unknown platform: {platform}"

    return None, None  # vinted is normalized by the caller (process_query/process_update_query)


def _apply_price_settings(query_id, track_prices, price_interval, price_depth, price_bot_ids,
                          refresh_delay=None):
    """Persist the per-query options shared by add and update."""
    if track_prices is not None:
        db.set_query_price_tracking(
            query_id, track_prices, interval=price_interval, depth=price_depth
        )
    if price_bot_ids is not None:
        db.set_query_price_bots(query_id, price_bot_ids)
    if refresh_delay is not None:
        db.set_query_refresh_delay(query_id, refresh_delay)


def process_query(query, name=None, telegram_chat_id=None, platform="vinted", bot_ids=None,
                  track_prices=None, price_interval=None, price_depth=None, price_bot_ids=None,
                  refresh_delay=None):
    """
    Process a query for the given platform and add it to the database.

    For Vinted URLs:
    1. Checking if the URL is a brand URL and converting it to standard format if needed
    2. Parsing the URL and extracting query parameters
    3. Ensuring the order flag is set to "newest_first"
    4. Removing time and search_id parameters
    5. Rebuilding the query string and URL

    For Kleinanzeigen: the search URL is validated and stored as-is.
    For eBay: a plain search term (or the _nkw param of an ebay search URL) is stored.

    Args:
        query (str): The query URL (vinted/kleinanzeigen) or search term (ebay)
        name (str, optional): A name for the query. If provided, it will be used as the query name.
        telegram_chat_id (str, optional): Query-specific Telegram chat ID.
            If not provided, notifications go to the default chat ID.
        platform (str, optional): 'vinted', 'kleinanzeigen' or 'ebay'. Defaults to 'vinted'.

    Returns:
        tuple: (message, is_new_query)
            - message (str): Status message
            - is_new_query (bool): True if query was added, False if it already existed
    """
    platform = (platform or "vinted").lower()

    if platform != "vinted":
        processed_query, error = normalize_query_for_platform(query, platform)
        if error:
            return error, False
        if db.is_query_in_db(processed_query) is True:
            return "Query already exists.", False
        new_id = db.add_query_to_db(processed_query, name, telegram_chat_id, platform)
        # Link the selected telegram bots (if any)
        if new_id is not None:
            if bot_ids is not None:
                db.set_query_bots(new_id, bot_ids)
            _apply_price_settings(new_id, track_prices, price_interval, price_depth,
                                  price_bot_ids, refresh_delay)
        return "Query added.", True

    # Check if the URL is a brand URL (format: url/brand/id-name)
    parsed_url = urlparse(query)
    path_parts = parsed_url.path.strip("/").split("/")

    if len(path_parts) >= 2 and path_parts[0] == "brand":
        # Extract the brand ID from the format "id-name"
        brand_id_with_name = path_parts[1]
        brand_id = brand_id_with_name.split("-")[0]

        # Create a new URL with the standard format
        new_path = "/catalog"
        new_query_params = {"brand_ids[]": [brand_id]}
        new_query_string = urlencode(new_query_params, doseq=True)

        # Rebuild the URL
        query = urlunparse(
            (parsed_url.scheme, parsed_url.netloc, new_path, "", new_query_string, "")
        )
        logger.info(f"Converted brand URL to standard format: {query}")

        # Parse the URL and extract the query parameters
        parsed_url = urlparse(query)

    query_params = parse_qs(parsed_url.query)

    # Ensure the order flag is set to newest_first
    query_params["order"] = ["newest_first"]
    # Remove time and search_id if provided
    query_params.pop("time", None)
    query_params.pop("search_id", None)
    query_params.pop("disabled_personalization", None)
    query_params.pop("page", None)

    # Rebuild the query string and the entire URL
    new_query = urlencode(query_params, doseq=True)
    processed_query = urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment,
        )
    )

    # Some queries are made with filters only, so we need to check if the search_text is present
    if db.is_query_in_db(processed_query) is True:
        return "Query already exists.", False
    else:
        # add the query to the db
        new_id = db.add_query_to_db(processed_query, name, telegram_chat_id)
        # Link the selected telegram bots (if any)
        if new_id is not None:
            if bot_ids is not None:
                db.set_query_bots(new_id, bot_ids)
            _apply_price_settings(new_id, track_prices, price_interval, price_depth,
                                  price_bot_ids, refresh_delay)
        return "Query added.", True


def get_formatted_query_list():
    """
    Get a formatted list of all queries in the database.

    Returns:
        str: A formatted string with all queries, numbered
    """
    all_queries = db.get_queries()
    queries_keywords = []
    for query in all_queries:
        parsed_url = urlparse(query[1])
        query_params = parse_qs(parsed_url.query)

        # Get the name or extract the search term (search_text for Vinted, _nkw for eBay)
        query_name = (
            query[3]
            if query[3] is not None
            else (
                query_params.get("search_text", [None])[0]
                or query_params.get("_nkw", [None])[0]
            )
        )

        if query_name is None:
            # Use query text instead of the whole query object
            queries_keywords.append(query[1])
        else:
            queries_keywords.append(query_name)

    query_list = ("\n").join(
        [str(i + 1) + ". " + j for i, j in enumerate(queries_keywords)]
    )
    return query_list


def process_remove_query(number):
    """
    Process the removal of a query from the database.

    Args:
        number (str): The number of the query to remove or "all" to remove all queries

    Returns:
        tuple: (message, success)
            - message (str): Status message
            - success (bool): True if query was removed successfully
    """
    if number == "all":
        db.remove_all_queries_from_db()
        return "All queries removed.", True

    # Check if number is a valid digit
    if number.isdigit():
        # Remove the query from the database
        db.remove_query_from_db(number)
        return "Query removed.", True
    else:
        return "Invalid number.", False


def process_update_query(query_id, query, name, telegram_chat_id=None, bot_ids=None,
                         track_prices=None, price_interval=None, price_depth=None,
                         price_bot_ids=None, refresh_delay=None):
    """
    Process the update of a query in the database.

    Args:
        query_id (int): The ID of the query to update
        query (str): The new Vinted query URL
        name (str, optional): A new name for the query. If provided, it will be used as the query name.
        telegram_chat_id (str, optional): Query-specific Telegram chat ID (legacy).
        bot_ids (list, optional): Telegram bot ids to notify for this query.
            If provided (even empty), the query's bot links are replaced.

    Returns:
        tuple: (message, success)
            - message (str): Status message
            - success (bool): True if query was updated successfully
    """
    # Non-vinted queries are not URL-normalized, only validated
    platform = db.get_query_platform(query_id)
    if platform != "vinted":
        processed_query, error = normalize_query_for_platform(query, platform)
        if error:
            return error, False
        if db.update_query_in_db(query_id, processed_query, name, telegram_chat_id):
            if bot_ids is not None:
                db.set_query_bots(query_id, bot_ids)
            _apply_price_settings(query_id, track_prices, price_interval, price_depth,
                              price_bot_ids, refresh_delay)
            return "Query updated.", True
        return "Failed to update query.", False

    # Parse the URL and extract the query parameters
    parsed_url = urlparse(query)
    query_params = parse_qs(parsed_url.query)

    # Ensure the order flag is set to newest_first
    query_params["order"] = ["newest_first"]
    # Remove time and search_id if provided
    query_params.pop("time", None)
    query_params.pop("search_id", None)
    query_params.pop("disabled_personalization", None)
    query_params.pop("page", None)

    # Rebuild the query string and the entire URL
    new_query = urlencode(query_params, doseq=True)
    processed_query = urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment,
        )
    )

    # Update the query in the database
    if db.update_query_in_db(query_id, processed_query, name, telegram_chat_id):
        if bot_ids is not None:
            db.set_query_bots(query_id, bot_ids)
        _apply_price_settings(query_id, track_prices, price_interval, price_depth,
                              price_bot_ids, refresh_delay)
        return "Query updated.", True
    else:
        return "Failed to update query.", False


def process_add_country(country):
    """
    Process the addition of a country to the allowlist.

    Args:
        country (str): The country code to add

    Returns:
        tuple: (message, country_list)
            - message (str): Status message
            - country_list (list): Current list of allowed countries
    """
    # Format the country code (remove spaces)
    country = country.replace(" ", "")
    country_list = db.get_allowlist()

    # Validate the country code (check if it's 2 characters long)
    if len(country) != 2:
        return "Invalid country code", country_list

    # Check if the country is already in the allowlist
    # If country_list is 0, it means the allowlist is empty
    if country_list != 0 and country.upper() in country_list:
        return f'Country "{country.upper()}" already in allowlist.', country_list

    # Add the country to the allowlist
    db.add_to_allowlist(country.upper())
    return "Country added.", db.get_allowlist()


def process_remove_country(country):
    """
    Process the removal of a country from the allowlist.

    Args:
        country (str): The country code to remove

    Returns:
        tuple: (message, country_list)
            - message (str): Status message
            - country_list (list): Current list of allowed countries
    """
    # Format the country code (remove spaces)
    country = country.replace(" ", "")

    # Validate the country code (check if it's 2 characters long)
    if len(country) != 2:
        return "Invalid country code", db.get_allowlist()

    # Remove the country from the allowlist
    db.remove_from_allowlist(country.upper())
    return "Country removed.", db.get_allowlist()


def get_user_country(profile_id):
    """
    Get the country code for a Vinted user.

    Makes an API request to retrieve the user's country code.
    Handles rate limiting by trying an alternative endpoint.

    Args:
        profile_id (str): The Vinted user's profile ID

    Returns:
        str: The user's country code (2-letter ISO code) or "XX" if it can't be determined
    """
    # Users are shared between all Vinted platforms, so we can use whatever locale we want
    url = f"https://www.vinted.fr/api/v2/users/{profile_id}?localize=false"
    response = requester.get(url)
    # That's a LOT of requests, so if we get a 429 we wait a bit before retrying once
    if response.status_code == 429:
        # In case of rate limit, we're switching the endpoint. This one is slower, but it doesn't RL as soon.
        # We're limiting the items per page to 1 to grab as little data as possible
        url = f"https://www.vinted.fr/api/v2/users/{profile_id}/items?page=1&per_page=1"
        response = requester.get(url)
        try:
            user_country = response.json()["items"][0]["user"]["country_iso_code"]
        except KeyError:
            logger.warning(
                "Couldn't get the country due to too many requests. Returning default value."
            )
            user_country = "XX"
    else:
        user_country = response.json()["user"]["country_iso_code"]
    return user_country


def _scrape_platform_queries(platform, queries, items_per_query, queue, price_queue=None):
    """
    Scrape all queries of a single platform sequentially and put results on the
    queue. Runs in its own thread so the three platforms scrape in parallel.

    Sequential within a platform on purpose: the Vinted requester is a shared
    singleton and each platform draws from its own proxy pool, so we don't want
    concurrent requests within the same platform.

    Args:
        platform (str): 'vinted', 'kleinanzeigen' or 'ebay'
        queries (list): Query rows for this platform
        items_per_query (int): Number of items to request per query
        queue (Queue): Queue to put (data, query_id) results on
        price_queue (Queue, optional): queue for price-change notifications
    """
    # Create a Vinted instance only for the vinted worker (uses singleton requester)
    vinted = Vinted() if platform == "vinted" else None
    threshold = get_price_threshold()

    for query in queries:
        # Stamp before scraping: a query that keeps failing must not be retried
        # on every single tick, it waits for its own interval like the others.
        db.mark_query_scraped(query[0])
        try:
            logger.info(f"[{platform.upper()}] Scraping query {query[0]}: {query[1]}")

            # Search for items on the query's platform
            if platform == "kleinanzeigen":
                from scrapers import kleinanzeigen

                all_items = kleinanzeigen.search(query[1], nbr_items=items_per_query)
            elif platform == "ebay":
                from scrapers import ebay_web

                all_items = ebay_web.search(query[1], nbr_items=items_per_query)
            else:
                all_items = vinted.items.search(query[1], nbr_items=items_per_query)

            # Filter to only include new items
            data = [item for item in all_items if item.is_new_item()]

            logger.info(
                f"[{platform.upper()}] Found {len(data)} new item(s) "
                f"(of {len(all_items)} scraped) for query {query[0]}"
            )
            queue.put((data, query[0]))

            # This page was fetched anyway - if the query tracks prices, feed
            # everything on it into the history instead of re-requesting it
            # later. Costs no extra request.
            if len(query) > 8 and query[8] and all_items:
                # The items in `data` are on their way to the notification
                # pipeline, which indexes them itself - indexing them here first
                # would make that pipeline skip them as "already seen".
                s, n, c, i = record_items_prices(
                    query[0], all_items, price_queue, threshold,
                    skip_index_ids={str(it.id) for it in data},
                )
                if c or i:
                    logger.info(
                        f"[{platform.upper()}] Price tracking (from regular scrape) "
                        f"query {query[0]}: {c} change(s), {i} newly indexed"
                    )

        except Exception as e:
            logger.error(f"[{platform.upper()}] Error processing query {query[0]}: {e}")
            # Put empty result on error
            queue.put(([], query[0]))


def process_items(queue, price_queue=None):
    """
    Scrape all active queries and put their results on the queue.

    Queries are grouped by platform (vinted / kleinanzeigen / ebay) and each
    platform is scraped in its own thread, so a slow platform (e.g. eBay with
    session warming and proxy rotation) does not hold up the others. Within a
    platform, queries run sequentially.

    Args:
        queue (Queue): The queue to put the (items, query_id) results on.

    Returns:
        None
    """
    import threading
    from collections import defaultdict

    all_queries = db.get_queries()

    # Get the number of items per query from the database
    items_per_query = int(db.get_parameter("items_per_query"))

    # Each query may define its own refresh interval; the global setting is the
    # default. The scheduler ticks faster than the shortest interval, so this
    # decides which queries are actually due right now.
    import time as _time

    now = _time.time()
    try:
        default_delay = int(db.get_parameter("query_refresh_delay") or 60)
    except (TypeError, ValueError):
        default_delay = 60

    # Group active, due queries by platform
    queries_by_platform = defaultdict(list)
    for query in all_queries:
        platform = (query[6] if len(query) > 6 and query[6] else "vinted").lower()
        # Skip paused (inactive) queries entirely
        active = query[7] if len(query) > 7 and query[7] is not None else 1
        if not active:
            logger.debug(f"[{platform.upper()}] Skipping paused query {query[0]}")
            continue

        delay = query[12] if len(query) > 12 and query[12] else default_delay
        last_scraped = query[13] if len(query) > 13 and query[13] else 0
        if last_scraped and (now - float(last_scraped)) < int(delay):
            continue  # not due yet

        queries_by_platform[platform].append(query)

    if not queries_by_platform:
        return

    # One thread per platform -> the three scrapers run in parallel
    threads = [
        threading.Thread(
            target=_scrape_platform_queries,
            args=(platform, queries, items_per_query, queue, price_queue),
            name=f"scraper-{platform}",
            daemon=True,
        )
        for platform, queries in queries_by_platform.items()
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def scrape_page(platform, query, page, nbr_items):
    """
    Fetch one result page for a query on its platform.

    Returns:
        list: platform item objects (empty on error)
    """
    if platform == "kleinanzeigen":
        from scrapers import kleinanzeigen

        return kleinanzeigen.search(query, nbr_items=nbr_items, page=page)
    if platform == "ebay":
        from scrapers import ebay_web

        return ebay_web.search(query, nbr_items=nbr_items, page=page)
    return Vinted().items.search(query, nbr_items=nbr_items, page=page)


def get_price_threshold():
    """Minimum percentage move before a price change is worth announcing."""
    try:
        return float(db.get_parameter("price_notify_threshold") or 5)
    except (TypeError, ValueError):
        return 5.0


def record_items_prices(query_id, items, price_queue=None, threshold=None,
                        skip_index_ids=None):
    """
    Record prices for a batch of already-scraped listings.

    Shared by the deep price runs and the normal scrape: whatever the regular
    scraper fetched is free data, so it is fed into the price history too
    instead of being re-requested later.

    Listings that are not in the database yet are indexed with their real
    publish time and WITHOUT advancing the query watermark, so this never fires
    a "new listing" notification and never hides genuinely new listings.

    Args:
        skip_index_ids (set, optional): ids that must NOT be indexed here
            because the notification pipeline is about to handle them. Without
            this, indexing a brand-new listing would make clear_item_queue treat
            it as already known and silently drop its notification.

    Returns:
        tuple: (seen, new, changed, indexed)
    """
    if threshold is None:
        threshold = get_price_threshold()
    skip_index_ids = skip_index_ids or set()
    seen = new = changed = indexed = 0

    for item in items:
        price = getattr(item, "price", None)
        if price is None:
            continue

        if str(item.id) not in skip_index_ids and not db.is_item_in_db_by_id(item.id):
            db.add_item_to_db(
                id=item.id,
                title=getattr(item, "title", None),
                query_id=query_id,
                price=float(price),
                timestamp=getattr(item, "raw_timestamp", 0) or 0,
                photo_url=getattr(item, "photo", None),
                currency=getattr(item, "currency", "EUR"),
                url=getattr(item, "url", None),
                update_last_item=False,
            )
            indexed += 1

        is_auction = bool(getattr(item, "is_auction", False))
        status, old_price, new_price = db.record_price(
            item=item.id,
            query_id=query_id,
            price=float(price),
            currency=getattr(item, "currency", "EUR"),
            title=getattr(item, "title", None),
            url=getattr(item, "url", None),
            photo_url=getattr(item, "photo", None),
            is_auction=is_auction,
            auction_end=getattr(item, "auction_end", 0),
        )
        seen += 1
        if status == "new":
            new += 1
        elif status in ("flapping", "currency_switch", "vat_switch"):
            # Recorded in the history, but not a real move - stay silent.
            # Seen on worldwide eBay listings that alternate between two values.
            logger.debug(
                f"[PRICES] {status} for item {item.id} "
                f"({old_price} -> {new_price}) - no notification"
            )
        elif status == "changed":
            changed += 1
            # Auction prices move with every bid - the history is still
            # recorded, but announcing each bid would be noise. Auctions get a
            # single alert shortly before they end instead.
            if is_auction:
                continue
            if price_queue is not None and old_price:
                pct = (float(new_price) - float(old_price)) / float(old_price) * 100
                if abs(pct) >= threshold:
                    price_queue.put({
                        "type": "price_change",
                        "query_id": query_id,
                        "title": getattr(item, "title", "") or "",
                        "url": getattr(item, "url", "") or "",
                        "photo": getattr(item, "photo", None),
                        "old_price": float(old_price),
                        "new_price": float(new_price),
                        "currency": getattr(item, "currency", "EUR"),
                        "pct": pct,
                    })
    return seen, new, changed, indexed


def run_price_check(query_id, query, platform, depth, price_queue=None,
                    items_per_query=None, threshold=None):
    """
    Walk `depth` result pages for one query and record every price found.

    Page 1 only ever shows the newest listings; the older ones - and their price
    changes - live further back, which is why depth matters here.
    """
    import time as _time

    platform = (platform or "vinted").lower()
    depth = max(1, int(depth or 1))
    if items_per_query is None:
        items_per_query = int(db.get_parameter("items_per_query") or 20)
    if threshold is None:
        threshold = get_price_threshold()

    seen = new = changed = indexed = 0
    try:
        for page in range(1, depth + 1):
            try:
                items = scrape_page(platform, query, page, items_per_query)
            except Exception as e:
                logger.warning(
                    f"[PRICES] {platform} query {query_id} page {page} failed: {str(e)[:120]}"
                )
                break
            if not items:
                break  # no more results - stop paging

            s, n, c, i = record_items_prices(query_id, items, price_queue, threshold)
            seen += s
            new += n
            changed += c
            indexed += i

            # Be gentle between pages - deep runs otherwise look like a burst
            if page < depth:
                _time.sleep(2)
    finally:
        # Always advance the timer, even after an error, so one broken query
        # cannot monopolise every following run.
        db.update_last_price_check(query_id)

    logger.info(
        f"[PRICES] query {query_id} ({platform}): {seen} listings checked, "
        f"{new} newly tracked, {indexed} indexed into items, {changed} price change(s)"
    )
    return {"seen": seen, "new": new, "changed": changed, "indexed": indexed}


def collect_prices(price_queue=None):
    """
    Scheduler entry point: run a price check for every query that is due.

    Args:
        price_queue (Queue, optional): queue for price-change notifications
    """
    due = db.get_queries_due_for_price_check()
    if due:
        items_per_query = int(db.get_parameter("items_per_query") or 20)
        threshold = get_price_threshold()
        logger.info(f"[PRICES] {len(due)} query/queries due for a price check")
        for query_id, query, platform, depth, interval in due:
            run_price_check(query_id, query, platform, depth, price_queue,
                            items_per_query, threshold)

    # After the runs: announce auctions about to close (once each)
    notify_ending_auctions(price_queue)


def collect_prices_for_query(query_id, price_queue=None):
    """
    Run a price check for a single query right now, ignoring its interval.
    Used by the "update prices now" button in the web UI.
    """
    for q in db.get_queries():
        if q[0] == query_id:
            result = run_price_check(
                query_id, q[1], q[6] if len(q) > 6 else "vinted",
                q[10] if len(q) > 10 else 1, price_queue,
            )
            notify_ending_auctions(price_queue)
            return result
    return None


def notify_ending_auctions(price_queue=None, within_minutes=10):
    """
    Send a one-time alert for auctions ending within the next `within_minutes`.

    Auctions are deliberately excluded from per-change price messages (every bid
    would trigger one); this is the single moment where an alert is useful.
    """
    if price_queue is None:
        return
    ending = db.get_auctions_ending_soon(within_seconds=within_minutes * 60)
    for item, query_id, title, url, photo_url, last_price, currency, auction_end in ending:
        price_queue.put({
            "type": "auction_ending",
            "query_id": query_id,
            "title": title or "",
            "url": url or "",
            "photo": photo_url,
            "price": float(last_price or 0),
            "currency": currency or "EUR",
            "ends_at": auction_end,
        })
        db.mark_auction_notified(item, query_id)
    if ending:
        logger.info(f"[PRICES] {len(ending)} auction(s) ending soon announced")


def clear_item_queue(items_queue, new_items_queue):
    """
    Process items from the items_queue.
    This function is scheduled to run frequently.
    """
    if not items_queue.empty():
        data, query_id = items_queue.get()
        banwords_str = db.get_parameter("banwords")
        for item in reversed(data):

            # If already in db, pass
            last_query_timestamp = db.get_last_timestamp(query_id)
            if (
                last_query_timestamp is not None
                and last_query_timestamp >= item.raw_timestamp
            ):
                pass
            # In case of multiple queries, we need to check if the item is already in the db
            elif db.is_item_in_db_by_id(item.id) is True:
                # We update the timestamp
                db.update_last_timestamp(query_id, item.raw_timestamp)
                pass
            # If there's an allowlist and
            # If the user's country is not in the allowlist, we just update the timestamp
            # (country lookup only exists for Vinted items)
            elif getattr(item, "platform", "vinted") == "vinted" and db.get_allowlist() != 0 and (
                get_user_country(item.raw_data["user"]["id"])
            ) not in (db.get_allowlist() + ["XX"]):
                db.update_last_timestamp(query_id, item.raw_timestamp)
                pass
            # Check if the item title contains any banwords
            elif banwords_str and contains_banwords(item.title, banwords_str):
                # If it contains banwords, just update the timestamp and skip
                db.update_last_timestamp(query_id, item.raw_timestamp)
                pass
            else:
                # We create the message
                message_template = db.get_parameter("message_template")

                # Handle case where template is empty or None
                if not message_template:
                    logger.warning(f"Message template is empty, using default for item {item.id}")
                    message_template = "🔎 {query}\n<b>{title}</b>\n💰 {price}\n🏷️ {brand}"

                # Human-readable name of the query that found this item
                query_name = db.get_query_name(query_id)

                try:
                    content = message_template.format(
                        title=item.title or "No title",
                        price=str(item.price) + " " + item.currency if item.price else "No price",
                        brand=item.brand_title or "No brand",
                        image=None if item.photo is None else item.photo,
                        query=query_name or "",
                    )
                except Exception as e:
                    logger.error(f"Error formatting message template: {e}, using fallback")
                    content = f"<b>{item.title}</b>\n💰 {item.price} {item.currency}\n🏷️ {item.brand_title}"

                # If the template doesn't reference the query name, prepend it so
                # the message always shows which query matched.
                if query_name and "{query}" not in message_template:
                    content = f"🔎 {query_name}\n{content}"

                # Ensure content is not empty
                if not content or not content.strip():
                    logger.warning(f"Generated content is empty for item {item.id}, using minimal fallback")
                    content = f"New item: {item.title or 'Unknown'}"

                # Button label matches the item's platform
                button_text = {
                    "vinted": "Open Vinted",
                    "kleinanzeigen": "Open Kleinanzeigen",
                    "ebay": "Open eBay",
                }.get(getattr(item, "platform", "vinted"), "Open listing")

                # add the item to the queue (query_id lets the telegram bot pick the right chat,
                # item.photo lets it attach the image as a real photo)
                new_items_queue.put((content, item.url, button_text, None, None, query_id, item.photo))
                # new_items_queue.put((content, item.url, button_text, item.buy_url, "Open buy page", query_id, item.photo))
                # Add the item to the db
                db.add_item_to_db(
                    id=item.id,
                    timestamp=item.raw_timestamp,
                    price=item.price,
                    title=item.title,
                    photo_url=item.photo,
                    query_id=query_id,
                    currency=item.currency,
                    url=item.url,
                )


def contains_banwords(title, banwords_str):
    """
    Check if a title contains any banwords.

    Args:
        title (str): The title to check
        banwords_str (str): List of banwords separated by 3 pipe character
    Returns:
        bool: True if the title contains any banwords, False otherwise
    """

    # Split the banwords string into a list using pipe as delimiter
    banwords = [
        word.strip().lower() for word in banwords_str.split("|||") if word.strip()
    ]

    # If the list is empty, return False
    if not banwords:
        return False

    # Check if any banword is in the title (case-insensitive)
    title_lower = title.lower()
    for word in banwords:
        if word in title_lower:
            return True

    return False


