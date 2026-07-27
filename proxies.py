import random
import requests
import time
from requests.exceptions import RequestException
import concurrent.futures
from typing import List, Optional
from logger import get_logger

# Get logger for this module
logger = get_logger(__name__)

# Supported scraping platforms. Each keeps its own proxy list, blacklist,
# validated-count and last-check time, and is validated against its own URL.
PLATFORMS = ("vinted", "kleinanzeigen", "ebay")
DEFAULT_PLATFORM = "vinted"

# URL to test proxies against - each platform is tested against its own site
# for real-world validation (a proxy working for Vinted may be blocked by eBay).
TEST_URLS = {
    "vinted": "https://www.vinted.de/",
    "kleinanzeigen": "https://www.kleinanzeigen.de/",
    # A real search page: eBay proxies are validated against the same endpoint
    # (and via curl_cffi) that the scraper actually uses.
    "ebay": "https://www.ebay.de/sch/i.html?_nkw=test&_sop=10",
}

# Per-platform caches. Every dict is keyed by platform name.
_PROXY_CACHE = {}              # {platform: [proxies] or None}
_PROXY_CACHE_INITIALIZED = {}  # {platform: bool}
_SINGLE_PROXY = {}             # {platform: proxy str or None}
_PROXY_BLACKLIST = {}          # {platform: {proxy: expiration_time}}

# Maximum number of concurrent workers for proxy checking
MAX_PROXY_WORKERS = 90
# Time interval in seconds after which proxies should be rechecked (12 hours).
# Within this window the validated pool is reused (also across restarts, since
# it is persisted to the database) instead of being re-validated.
PROXY_RECHECK_INTERVAL = 12 * 60 * 60
# Time interval to keep a proxy in blacklist (1 hour)
PROXY_BLACKLIST_DURATION = 60 * 60


def _normalize_platform(platform: Optional[str]) -> str:
    """Return a valid platform name, falling back to the default."""
    platform = (platform or DEFAULT_PLATFORM).lower()
    return platform if platform in PLATFORMS else DEFAULT_PLATFORM


def _pkey(base: str, platform: str) -> str:
    """Build the per-platform parameter key, e.g. ('proxy_list', 'ebay') -> 'proxy_list_ebay'."""
    return f"{base}_{platform}"


def _get_blacklist(platform: str) -> dict:
    """Get (and lazily create) the in-memory blacklist for a platform."""
    return _PROXY_BLACKLIST.setdefault(platform, {})


def _get_test_url(platform: str) -> str:
    return TEST_URLS.get(platform, TEST_URLS[DEFAULT_PLATFORM])


def fetch_proxies_from_link(url: str) -> List[str]:
    """
    Fetch proxies from a URL.

    Args:
        url (str): URL to fetch proxies from.

    Returns:
        List[str]: List of proxies.
    """
    try:
        logger.info(f"Fetching proxy list from: {url}")
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            # Split by newlines and filter out empty lines
            proxies = [line.strip() for line in response.text.splitlines() if line.strip()]
            logger.info(f"Fetched {len(proxies)} proxies from {url}")
            return proxies
        else:
            logger.warning(f"Failed to fetch proxies from {url}, status code: {response.status_code}")
        return []
    except Exception as e:
        # If there's any error fetching proxies, return an empty list
        logger.error(f"Error fetching proxies from {url}: {e}")
        return []


def check_proxies_parallel(proxies_list: List[str], platform: str) -> List[str]:
    """
    Check multiple proxies in parallel using a thread pool, validating each
    against the given platform's test URL.

    Args:
        proxies_list (List[str]): List of proxy strings to check.
        platform (str): The platform whose test URL is used for validation.

    Returns:
        List[str]: List of working proxies.
    """
    working_proxies = []
    logger.info(f"[{platform}] Checking {len(proxies_list)} proxies in parallel...")

    # Use ThreadPoolExecutor to check proxies in parallel
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_PROXY_WORKERS
    ) as executor:
        # Submit all proxy checking tasks
        future_to_proxy = {
            executor.submit(check_proxy, proxy, platform): proxy for proxy in proxies_list
        }

        # Process results as they complete
        checked = 0
        for future in concurrent.futures.as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            checked += 1
            try:
                is_working = future.result()
                if is_working:
                    working_proxies.append(proxy)
                    logger.info(f"[{platform}] [{checked}/{len(proxies_list)}] Proxy working: {proxy}")
                else:
                    logger.warning(f"[{platform}] [{checked}/{len(proxies_list)}] Proxy failed: {proxy}")
            except Exception as e:
                # If an exception occurred during checking, consider the proxy not working
                logger.warning(f"[{platform}] [{checked}/{len(proxies_list)}] Proxy check exception for {proxy}: {e}")

    logger.info(f"[{platform}] Proxy validation complete: {len(working_proxies)}/{len(proxies_list)} proxies are working")
    return working_proxies


def _save_blacklist_to_db(platform: str):
    """
    Save the current blacklist for a platform to the database for cross-process access.
    Stores as JSON: {proxy: expiration_time, ...}
    """
    import db
    import json

    try:
        blacklist_json = json.dumps(_get_blacklist(platform))
        db.set_parameter(_pkey("proxy_blacklist", platform), blacklist_json)
    except Exception as e:
        logger.error(f"[{platform}] Failed to save blacklist to database: {e}")


def _load_blacklist_from_db(platform: str):
    """
    Load the blacklist for a platform from the database and merge with in-memory cache.
    Automatically removes expired entries.
    """
    import db
    import json

    try:
        blacklist_json = db.get_parameter(_pkey("proxy_blacklist", platform))
        if blacklist_json:
            db_blacklist = json.loads(blacklist_json)
            blacklist = _get_blacklist(platform)

            # Merge with current in-memory blacklist, keeping the later expiration time
            current_time = time.time()
            for proxy, expiration in db_blacklist.items():
                # Only add if not expired
                if expiration > current_time:
                    # Keep the later expiration if proxy already in memory
                    if proxy in blacklist:
                        blacklist[proxy] = max(blacklist[proxy], expiration)
                    else:
                        blacklist[proxy] = expiration
    except Exception as e:
        logger.debug(f"[{platform}] Failed to load blacklist from database: {e}")


def _cleanup_expired_blacklist(platform: str):
    """
    Remove expired proxies from a platform's blacklist.
    Updates both in-memory cache and database.
    """
    blacklist = _get_blacklist(platform)
    current_time = time.time()
    expired = [proxy for proxy, expiration in blacklist.items() if current_time >= expiration]
    for proxy in expired:
        del blacklist[proxy]
    if expired:
        logger.info(f"[{platform}] Removed {len(expired)} expired proxies from blacklist")
        # Update database after cleanup
        _save_blacklist_to_db(platform)


def get_random_proxy(platform: str = DEFAULT_PLATFORM, exclude_blacklisted: bool = True) -> Optional[str]:
    """
    Get a random proxy for a platform from its configured proxy list.

    Uses a per-platform cache to minimize I/O operations:
    - If there are no proxies on first check, never checks again
    - If there is only one proxy, always returns that one
    - Otherwise, returns a random proxy from the cached list
    - Excludes blacklisted proxies if exclude_blacklisted is True

    Proxies are checked in parallel against the platform's test URL and are
    rechecked if they were last checked more than PROXY_RECHECK_INTERVAL seconds ago.

    Args:
        platform (str): The platform to get a proxy for.
        exclude_blacklisted (bool): Whether to exclude blacklisted proxies. Defaults to True.

    Returns:
        Optional[str]: A randomly selected proxy string or None if none are available.
    """
    platform = _normalize_platform(platform)

    # Import db here to avoid circular imports
    import db

    current_time = time.time()

    # Clean up expired blacklisted proxies to prevent memory leak
    _cleanup_expired_blacklist(platform)
    blacklist = _get_blacklist(platform)

    # Get the last proxy check time for this platform from the database
    last_proxy_check_time_str = db.get_parameter(_pkey("last_proxy_check_time", platform))
    last_proxy_check_time = (
        float(last_proxy_check_time_str) if last_proxy_check_time_str else 0
    )

    # Check if we need to recheck proxies (if more than PROXY_RECHECK_INTERVAL seconds have passed)
    if (
        _PROXY_CACHE_INITIALIZED.get(platform)
        and last_proxy_check_time > 0
        and current_time - last_proxy_check_time > PROXY_RECHECK_INTERVAL
    ):
        # Reset cache to force recheck
        logger.info(f"[{platform}] Proxy cache expired (>{PROXY_RECHECK_INTERVAL}s), rechecking proxies...")
        _PROXY_CACHE_INITIALIZED[platform] = False
        _PROXY_CACHE[platform] = None
        _SINGLE_PROXY[platform] = None

    # If cache is already initialized
    if _PROXY_CACHE_INITIALIZED.get(platform):
        # If we determined there are no proxies, always return None
        if _PROXY_CACHE.get(platform) is None:
            logger.debug(f"[{platform}] No proxies configured")
            return None

        # If we have a single proxy, always return that one (unless blacklisted)
        if _SINGLE_PROXY.get(platform) is not None:
            single = _SINGLE_PROXY[platform]
            if exclude_blacklisted and single in blacklist:
                logger.warning(f"[{platform}] Single proxy is blacklisted: {single}")
                return None
            return single

        # Otherwise, return a random proxy from the cache (excluding blacklisted)
        cache = _PROXY_CACHE.get(platform)
        if cache:
            available_proxies = [p for p in cache if p not in blacklist] if exclude_blacklisted else cache
            if available_proxies:
                selected = random.choice(available_proxies)
                logger.debug(f"[{platform}] Selected proxy: {selected} (from {len(available_proxies)} available)")
                return selected
            else:
                logger.warning(f"[{platform}] All {len(cache)} cached proxies are blacklisted")
                return None
        return None

    # Initialize cache on first call or after recheck interval
    _PROXY_CACHE_INITIALIZED[platform] = True
    logger.info(f"[{platform}] Initializing proxy cache...")

    # Reuse a recently-validated pool across restarts: if the last check for this
    # platform was less than PROXY_RECHECK_INTERVAL (12h) ago and we have a
    # persisted validated list, load it instead of re-fetching/re-validating.
    if last_proxy_check_time > 0 and (current_time - last_proxy_check_time) < PROXY_RECHECK_INTERVAL:
        persisted = db.get_parameter(_pkey("validated_proxies", platform))
        cached = [p.strip() for p in persisted.split(";") if p.strip()] if persisted else []
        if cached:
            age_hours = (current_time - last_proxy_check_time) / 3600
            logger.info(
                f"[{platform}] Reusing {len(cached)} validated proxies from "
                f"{age_hours:.1f}h ago (last check < {PROXY_RECHECK_INTERVAL // 3600}h, no re-validation)"
            )
            _PROXY_CACHE[platform] = cached
            if len(cached) == 1:
                _SINGLE_PROXY[platform] = cached[0]
            available = [p for p in cached if p not in blacklist] if exclude_blacklisted else cached
            return random.choice(available) if available else None

    # Update the last check time in the database (a full (re)validation follows)
    db.set_parameter(_pkey("last_proxy_check_time", platform), str(current_time))

    # Initialize all_proxies list
    all_proxies = []

    # Check if the platform proxy list is configured in the database
    proxy_list = db.get_parameter(_pkey("proxy_list", platform))
    if proxy_list:
        # Multiple proxies separated by semicolons
        all_proxies = [p.strip() for p in proxy_list.split(";") if p.strip()]
        logger.info(f"[{platform}] Loaded {len(all_proxies)} proxies from database proxy_list")

    # Check if the platform proxy list link is configured in the database
    proxy_list_link = db.get_parameter(_pkey("proxy_list_link", platform))
    if proxy_list_link:
        # Fetch proxies from the link and add them to all_proxies
        link_proxies = fetch_proxies_from_link(proxy_list_link)
        all_proxies.extend(link_proxies)

    # Check proxies in parallel if we have any and CHECK_PROXIES is True
    if all_proxies:
        check_proxies = db.get_parameter("check_proxies") == "True"
        logger.info(f"[{platform}] Total proxies to process: {len(all_proxies)}, check_proxies={check_proxies}")

        if check_proxies:
            working_proxies = check_proxies_parallel(all_proxies, platform)
            if working_proxies:
                _PROXY_CACHE[platform] = working_proxies
                # Store validated proxy count + list in database (list is reused
                # across restarts within the recheck window)
                db.set_parameter(_pkey("validated_proxy_count", platform), str(len(working_proxies)))
                db.set_parameter(_pkey("validated_proxies", platform), ";".join(working_proxies))
                logger.info(f"[{platform}] Stored validated_proxy_count={len(working_proxies)} in database")
                # If there's only one working proxy, cache it separately
                if len(working_proxies) == 1:
                    _SINGLE_PROXY[platform] = working_proxies[0]
                    logger.info(f"[{platform}] Using single proxy: {_SINGLE_PROXY[platform]}")
                    return _SINGLE_PROXY[platform]
                selected = random.choice(working_proxies)
                logger.info(f"[{platform}] Selected proxy: {selected} from {len(working_proxies)} working proxies")
                return selected
            else:
                logger.error(f"[{platform}] No working proxies found after validation")
                # Store 0 count / empty list so we don't reuse a stale pool
                db.set_parameter(_pkey("validated_proxy_count", platform), "0")
                db.set_parameter(_pkey("validated_proxies", platform), "")
        else:
            # If CHECK_PROXIES is False, just cache all proxies without checking them
            _PROXY_CACHE[platform] = all_proxies
            db.set_parameter(_pkey("validated_proxy_count", platform), str(len(all_proxies)))
            db.set_parameter(_pkey("validated_proxies", platform), ";".join(all_proxies))
            logger.warning(f"[{platform}] Proxy checking is disabled, using proxies without validation")
            # If there's only one proxy, cache it separately
            if len(all_proxies) == 1:
                _SINGLE_PROXY[platform] = all_proxies[0]
                logger.info(f"[{platform}] Using single proxy (unchecked): {_SINGLE_PROXY[platform]}")
                return _SINGLE_PROXY[platform]
            selected = random.choice(all_proxies)
            logger.info(f"[{platform}] Selected proxy (unchecked): {selected} from {len(all_proxies)} proxies")
            return selected

    # No working proxies found
    logger.warning(f"[{platform}] No proxies configured or all proxies failed validation")
    _PROXY_CACHE[platform] = None
    return None


def check_proxy(proxy: str, platform: str = DEFAULT_PLATFORM) -> bool:
    """
    Check if a proxy is working by making a request to the platform's test URL.

    This function is thread-safe as it creates a new session for each check.
    Uses a random user agent to avoid detection.

    Args:
        proxy (str): Proxy string to check.
        platform (str): The platform whose test URL is used.

    Returns:
        bool: True if the proxy is working, False otherwise.
    """
    if proxy is None:
        return False

    platform = _normalize_platform(platform)

    # Convert proxy string to dictionary format
    proxy_dict = convert_proxy_string_to_dict(proxy)

    # eBay blocks plain HTTP clients via TLS fingerprinting, so a proxy that
    # "works" with requests may still be useless for the curl_cffi scraper.
    # Validate eBay proxies the same way we scrape: curl_cffi against a real
    # search page, requiring a full result page (not a block stub).
    if platform == "ebay":
        return _check_proxy_ebay(proxy_dict)

    try:
        # Create a new session for testing (ensures thread safety)
        session = requests.Session()

        # Import db here to avoid circular imports
        import db
        import json

        # Get user agents and default headers from the database
        user_agents_json = db.get_parameter("user_agents")
        default_headers_json = db.get_parameter("default_headers")
        timeout_str = db.get_parameter("proxy_test_timeout")

        # Parse JSON strings and timeout
        user_agents = json.loads(user_agents_json) if user_agents_json else []
        default_headers = (
            json.loads(default_headers_json) if default_headers_json else {}
        )
        timeout = int(timeout_str) if timeout_str else 5

        # Set random user agent and default headers
        headers = {
            "User-Agent": random.choice(user_agents) if user_agents else "Mozilla/5.0",
            **default_headers,
        }
        session.headers.update(headers)

        # Make a GET request to the platform's test URL with the proxy
        response = session.get(_get_test_url(platform), proxies=proxy_dict, timeout=timeout)

        # Check if the request was successful
        is_working = response.status_code == 200
        if not is_working:
            logger.debug(f"[{platform}] Proxy {proxy} returned status code {response.status_code}")
        return is_working
    except TimeoutError as e:
        logger.debug(f"[{platform}] Proxy {proxy} timed out: {e}")
        return False
    except ConnectionError as e:
        logger.debug(f"[{platform}] Proxy {proxy} connection error: {e}")
        return False
    except RequestException as e:
        logger.debug(f"[{platform}] Proxy {proxy} request exception: {e}")
        return False
    except Exception as e:
        logger.debug(f"[{platform}] Proxy {proxy} unexpected error: {e}")
        return False
    finally:
        # Ensure the session is closed to prevent resource leaks
        if "session" in locals():
            session.close()


def _check_proxy_ebay(proxy_dict: dict) -> bool:
    """
    Validate a proxy for eBay exactly the way the scraper fetches: curl_cffi
    with session warming (load the homepage for cookies, then the search page).
    Returns True only if a full result page comes back (200 and clearly larger
    than a block stub). Validating with the same warmed-session method avoids
    wrongly rejecting good proxies that only 403 on a cold request.
    """
    import db
    from urllib.parse import urlparse

    timeout_str = db.get_parameter("proxy_test_timeout")
    timeout = int(timeout_str) if timeout_str else 5

    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        logger.warning("curl_cffi not installed, cannot validate eBay proxies")
        return False

    search_url = _get_test_url("ebay")
    homepage = f"https://{urlparse(search_url).netloc}/"

    try:
        session = curl_requests.Session(impersonate="chrome124")
        session.headers.update(
            {"Accept-Language": "de-DE,de;q=0.9,en;q=0.6", "Upgrade-Insecure-Requests": "1"}
        )
        home = session.get(homepage, proxies=proxy_dict, timeout=timeout)
        if home.status_code != 200:
            return False
        response = session.get(search_url, proxies=proxy_dict, timeout=timeout)
        return response.status_code == 200 and len(response.text) > 50000
    except Exception as e:
        logger.debug(f"[ebay] proxy validation failed: {str(e)[:120]}")
        return False


def convert_proxy_string_to_dict(proxy: Optional[str]) -> dict:
    """
    Convert a proxy string to a dictionary format compatible with requests library.

    Handles HTTP, HTTPS, SOCKS4, SOCKS4A, and SOCKS5 proxies.
    For SOCKS proxies, applies the same proxy to both http and https.

    Args:
        proxy (Optional[str]): Proxy string to convert (e.g., "http://proxy:8080", "socks5://proxy:1080").

    Returns:
        dict: Proxy configuration dictionary for requests library.
    """
    if proxy is None:
        return {}

    if "://" in proxy:
        # Protocol is specified (e.g., "http://127.0.0.1:8080", "socks5://127.0.0.1:1080")
        protocol, address = proxy.split("://", 1)
        protocol_lower = protocol.lower()

        if protocol_lower == "http":
            # HTTP proxy: apply to both http and https
            return {"http": proxy, "https": proxy}
        elif protocol_lower == "https":
            # HTTPS proxy: typically only for https
            return {"https": proxy}
        elif protocol_lower in ("socks5", "socks5h", "socks4", "socks4a"):
            # SOCKS proxy: apply to both http and https
            # Note: requests library requires python-socks or pysocks installed
            return {"http": proxy, "https": proxy}
        else:
            # Unknown protocol, try applying to both
            logger.warning(f"Unknown proxy protocol '{protocol}', applying to both http and https")
            return {"http": proxy, "https": proxy}
    else:
        # Protocol is not specified, default to http
        return {"http": f"http://{proxy}", "https": f"http://{proxy}"}


def blacklist_proxy(proxy: str, platform: str = DEFAULT_PLATFORM, duration: int = PROXY_BLACKLIST_DURATION):
    """
    Add a proxy to a platform's blacklist to prevent it from being used temporarily.
    Stores in both in-memory cache and database for cross-process access.

    Args:
        proxy (str): Proxy string to blacklist.
        platform (str): The platform the proxy failed on.
        duration (int): Duration in seconds to keep the proxy blacklisted.
    """
    if proxy:
        platform = _normalize_platform(platform)
        expiration_time = time.time() + duration
        _get_blacklist(platform)[proxy] = expiration_time
        logger.warning(f"[{platform}] Blacklisted proxy: {proxy} (for {duration}s)")

        # Store in database for cross-process access
        _save_blacklist_to_db(platform)


def unblacklist_proxy(proxy: str, platform: str = DEFAULT_PLATFORM):
    """
    Remove a proxy from a platform's blacklist.

    Args:
        proxy (str): Proxy string to unblacklist.
        platform (str): The platform to remove the proxy from.
    """
    platform = _normalize_platform(platform)
    blacklist = _get_blacklist(platform)
    if proxy in blacklist:
        del blacklist[proxy]
        _save_blacklist_to_db(platform)
        logger.info(f"[{platform}] Removed proxy from blacklist: {proxy}")


def clear_blacklist(platform: Optional[str] = None):
    """
    Clear all proxies from the blacklist of one platform, or all platforms.

    Args:
        platform (Optional[str]): The platform to clear, or None to clear every platform.
    """
    targets = [_normalize_platform(platform)] if platform else list(PLATFORMS)
    for plat in targets:
        blacklist = _get_blacklist(plat)
        count = len(blacklist)
        blacklist.clear()
        if count > 0:
            _save_blacklist_to_db(plat)
            logger.info(f"[{plat}] Cleared {count} proxies from blacklist")


def get_proxy_stats(platform: str = DEFAULT_PLATFORM) -> dict:
    """
    Get statistics about the proxy system for a single platform.

    Returns:
        dict: Dictionary containing:
            - platform: The platform name
            - total_proxies: Total number of proxies cached (validated if check_proxies=True)
            - blacklisted_proxies: Number of currently blacklisted proxies
            - active_proxies: Number of working proxies available
            - validation_enabled: Whether proxy validation is enabled
    """
    platform = _normalize_platform(platform)

    # Import db here to avoid circular imports
    import db

    # Load blacklist from database (for cross-process access)
    _load_blacklist_from_db(platform)

    # Clean up expired blacklist entries first
    _cleanup_expired_blacklist(platform)

    # Check if proxy validation is enabled (global toggle)
    validation_enabled = db.get_parameter("check_proxies") == "True"

    # Determine total proxy count
    total = 0
    if _SINGLE_PROXY.get(platform) is not None:
        total = 1
    elif _PROXY_CACHE_INITIALIZED.get(platform) and _PROXY_CACHE.get(platform) is not None:
        total = len(_PROXY_CACHE[platform])
    else:
        # Cache not initialized in this process (e.g. web UI in a different process)
        if validation_enabled:
            validated_count_str = db.get_parameter(_pkey("validated_proxy_count", platform))
            total = int(validated_count_str) if validated_count_str else 0
        else:
            # Validation disabled, count proxies from the direct database list
            proxy_list_str = db.get_parameter(_pkey("proxy_list", platform))
            if proxy_list_str:
                total = len([p.strip() for p in proxy_list_str.split(";") if p.strip()])
            else:
                total = 0

    blacklisted = len(_get_blacklist(platform))
    active = total - blacklisted if total > 0 else 0

    return {
        "platform": platform,
        "total_proxies": total,
        "blacklisted_proxies": blacklisted,
        "active_proxies": active,
        "validation_enabled": validation_enabled,
    }


def get_all_proxy_stats() -> dict:
    """
    Get proxy statistics for every platform plus an aggregated total.

    Returns:
        dict: {
            "per_platform": {platform: stats, ...},
            "total_proxies": int, "blacklisted_proxies": int,
            "active_proxies": int, "validation_enabled": bool,
        }
    """
    per_platform = {plat: get_proxy_stats(plat) for plat in PLATFORMS}
    total = sum(s["total_proxies"] for s in per_platform.values())
    blacklisted = sum(s["blacklisted_proxies"] for s in per_platform.values())
    active = sum(s["active_proxies"] for s in per_platform.values())
    validation_enabled = any(s["validation_enabled"] for s in per_platform.values())
    return {
        "per_platform": per_platform,
        "total_proxies": total,
        "blacklisted_proxies": blacklisted,
        "active_proxies": active,
        "validation_enabled": validation_enabled,
    }


def configure_proxy(session: requests.Session, platform: str = DEFAULT_PLATFORM, proxy: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """
    Configure the proxy settings for a requests session using a platform's proxy pool.

    Args:
        session (requests.Session): The session to configure.
        platform (str): The platform whose proxy pool to draw from.
        proxy (Optional[str], optional): Proxy to be used. If None, a random proxy
            from the platform's pool is selected.

    Returns:
        tuple[bool, Optional[str]]: (True if proxy was configured, the proxy string used)
    """
    platform = _normalize_platform(platform)

    # If no proxy is provided, get a random one for this platform
    if proxy is None:
        proxy = get_random_proxy(platform)

    # If we still don't have a proxy, return False
    if proxy is None:
        session.proxies.clear()
        logger.debug(f"[{platform}] No proxy configured (none available)")
        return False, None

    # Store original proxy string before conversion
    proxy_str = proxy

    # Handle string proxy
    if isinstance(proxy, str):
        proxy = convert_proxy_string_to_dict(proxy)

    # Update the session with the proxy settings
    session.proxies.update(proxy)
    logger.debug(f"[{platform}] Configured proxy: {proxy_str}")
    return True, proxy_str


def get_proxy_dict(platform: str = DEFAULT_PLATFORM, proxy: Optional[str] = None) -> tuple[Optional[dict], Optional[str]]:
    """
    Get a proxy as a requests-style dict for clients that don't use a Session
    (e.g. curl_cffi for eBay).

    Args:
        platform (str): The platform whose proxy pool to draw from.
        proxy (Optional[str]): A specific proxy to use, or None to pick one.

    Returns:
        tuple[Optional[dict], Optional[str]]: (proxy dict or None, the proxy string used or None)
    """
    platform = _normalize_platform(platform)
    if proxy is None:
        proxy = get_random_proxy(platform)
    if proxy is None:
        return None, None
    return convert_proxy_string_to_dict(proxy), proxy
