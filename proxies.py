import random
import requests
import time
from requests.exceptions import RequestException
import concurrent.futures
from typing import List, Optional
from logger import get_logger

# Get logger for this module
logger = get_logger(__name__)

# Cache for proxy list
_PROXY_CACHE = None
_PROXY_CACHE_INITIALIZED = False
_SINGLE_PROXY = None
_PROXY_BLACKLIST = {}  # Track failed proxies with expiration timestamps: {proxy: expiration_time}

# Cache for stats to avoid fetching proxy list on every dashboard load
_STATS_CACHE = None
_STATS_CACHE_TIME = 0
_STATS_CACHE_DURATION = 60  # Cache stats for 60 seconds

# URL to test proxies against - testing directly against Vinted for real-world validation
_TEST_URL = "https://www.vinted.de/"
# Maximum number of concurrent workers for proxy checking
# Reduced from 90 to 30 to prevent resource exhaustion and potential memory leaks
MAX_PROXY_WORKERS = 90
# Time interval in seconds after which proxies should be rechecked (6 hours)
PROXY_RECHECK_INTERVAL = 6 * 60 * 60
# Time interval to keep a proxy in blacklist (1 hour)
PROXY_BLACKLIST_DURATION = 60 * 60


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


def check_proxies_parallel(proxies_list: List[str]) -> List[str]:
    """
    Check multiple proxies in parallel using a thread pool.

    Args:
        proxies_list (List[str]): List of proxy strings to check.

    Returns:
        List[str]: List of working proxies.
    """
    working_proxies = []
    logger.info(f"Checking {len(proxies_list)} proxies in parallel...")

    # Use ThreadPoolExecutor to check proxies in parallel
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_PROXY_WORKERS
    ) as executor:
        # Submit all proxy checking tasks
        future_to_proxy = {
            executor.submit(check_proxy, proxy): proxy for proxy in proxies_list
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
                    logger.info(f"[{checked}/{len(proxies_list)}] Proxy working: {proxy}")
                else:
                    logger.warning(f"[{checked}/{len(proxies_list)}] Proxy failed: {proxy}")
            except Exception as e:
                # If an exception occurred during checking, consider the proxy not working
                logger.warning(f"[{checked}/{len(proxies_list)}] Proxy check exception for {proxy}: {e}")

    logger.info(f"Proxy validation complete: {len(working_proxies)}/{len(proxies_list)} proxies are working")
    return working_proxies


def _cleanup_expired_blacklist():
    """
    Remove expired proxies from the blacklist.

    This function should be called periodically to prevent the blacklist from growing indefinitely.
    """
    global _PROXY_BLACKLIST
    current_time = time.time()
    expired = [proxy for proxy, expiration in _PROXY_BLACKLIST.items() if current_time >= expiration]
    for proxy in expired:
        del _PROXY_BLACKLIST[proxy]
    if expired:
        logger.info(f"Removed {len(expired)} expired proxies from blacklist")


def get_random_proxy(exclude_blacklisted: bool = True) -> Optional[str]:
    """
    Get a random proxy from the configuration values.

    Uses a cache to minimize I/O operations:
    - If there are no proxies on first check, never checks again
    - If there is only one proxy, always returns that one
    - Otherwise, returns a random proxy from the cached list
    - Excludes blacklisted proxies if exclude_blacklisted is True

    Proxies are checked in parallel to avoid blocking the main thread.
    Proxies are rechecked if they were checked more than PROXY_RECHECK_INTERVAL seconds ago.

    Args:
        exclude_blacklisted (bool): Whether to exclude blacklisted proxies. Defaults to True.

    Returns:
        Optional[str]: A randomly selected proxy string or None if no working proxies are found.
    """
    global _PROXY_CACHE, _PROXY_CACHE_INITIALIZED, _SINGLE_PROXY

    # Import db here to avoid circular imports
    import db

    current_time = time.time()

    # Clean up expired blacklisted proxies to prevent memory leak
    _cleanup_expired_blacklist()

    # Get the last proxy check time from the database
    last_proxy_check_time_str = db.get_parameter("last_proxy_check_time")
    last_proxy_check_time = (
        float(last_proxy_check_time_str) if last_proxy_check_time_str else 0
    )

    # Check if we need to recheck proxies (if more than PROXY_RECHECK_INTERVAL seconds have passed)
    if (
        _PROXY_CACHE_INITIALIZED
        and last_proxy_check_time > 0
        and current_time - last_proxy_check_time > PROXY_RECHECK_INTERVAL
    ):
        # Reset cache to force recheck
        logger.info(f"Proxy cache expired (>{PROXY_RECHECK_INTERVAL}s), rechecking proxies...")
        _PROXY_CACHE_INITIALIZED = False
        _PROXY_CACHE = None
        _SINGLE_PROXY = None

    # If cache is already initialized
    if _PROXY_CACHE_INITIALIZED:
        # If we determined there are no proxies, always return None
        if _PROXY_CACHE is None:
            logger.debug("No proxies configured")
            return None

        # If we have a single proxy, always return that one (unless blacklisted)
        if _SINGLE_PROXY is not None:
            if exclude_blacklisted and _SINGLE_PROXY in _PROXY_BLACKLIST:
                logger.warning(f"Single proxy is blacklisted: {_SINGLE_PROXY}")
                return None
            return _SINGLE_PROXY

        # Otherwise, return a random proxy from the cache (excluding blacklisted)
        if _PROXY_CACHE:
            available_proxies = [p for p in _PROXY_CACHE if p not in _PROXY_BLACKLIST] if exclude_blacklisted else _PROXY_CACHE
            if available_proxies:
                selected = random.choice(available_proxies)
                logger.debug(f"Selected proxy: {selected} (from {len(available_proxies)} available)")
                return selected
            else:
                logger.warning(f"All {len(_PROXY_CACHE)} cached proxies are blacklisted")
                return None
        return None

    # Initialize cache on first call or after recheck interval
    _PROXY_CACHE_INITIALIZED = True
    logger.info("Initializing proxy cache...")

    # Update the last check time in the database
    db.set_parameter("last_proxy_check_time", str(current_time))

    # Initialize all_proxies list
    all_proxies = []

    # Check if PROXY_LIST is configured in the database
    proxy_list = db.get_parameter("proxy_list")
    if proxy_list:
        # If PROXY_LIST is a string with multiple proxies separated by semicolons
        all_proxies = [p.strip() for p in proxy_list.split(";") if p.strip()]
        logger.info(f"Loaded {len(all_proxies)} proxies from database proxy_list")

    # Check if PROXY_LIST_LINK is configured in the database
    proxy_list_link = db.get_parameter("proxy_list_link")
    if proxy_list_link:
        # Fetch proxies from the link and add them to all_proxies
        link_proxies = fetch_proxies_from_link(proxy_list_link)
        all_proxies.extend(link_proxies)

    # Check proxies in parallel if we have any and CHECK_PROXIES is True
    if all_proxies:
        check_proxies = db.get_parameter("check_proxies") == "True"
        logger.info(f"Total proxies to process: {len(all_proxies)}, check_proxies={check_proxies}")

        if check_proxies:
            working_proxies = check_proxies_parallel(all_proxies)
            if working_proxies:
                _PROXY_CACHE = working_proxies
                # Store validated proxy count in database for stats display
                db.set_parameter("validated_proxy_count", str(len(working_proxies)))
                # If there's only one working proxy, cache it separately
                if len(working_proxies) == 1:
                    _SINGLE_PROXY = working_proxies[0]
                    logger.info(f"Using single proxy: {_SINGLE_PROXY}")
                    return _SINGLE_PROXY
                selected = random.choice(working_proxies)
                logger.info(f"Selected proxy: {selected} from {len(working_proxies)} working proxies")
                return selected
            else:
                logger.error("No working proxies found after validation")
        else:
            # If CHECK_PROXIES is False, just cache all proxies without checking them
            _PROXY_CACHE = all_proxies
            logger.warning("Proxy checking is disabled, using proxies without validation")
            # If there's only one proxy, cache it separately
            if len(all_proxies) == 1:
                _SINGLE_PROXY = all_proxies[0]
                logger.info(f"Using single proxy (unchecked): {_SINGLE_PROXY}")
                return _SINGLE_PROXY
            selected = random.choice(all_proxies)
            logger.info(f"Selected proxy (unchecked): {selected} from {len(all_proxies)} proxies")
            return selected

    # No working proxies found
    logger.warning("No proxies configured or all proxies failed validation")
    _PROXY_CACHE = None
    return None


def check_proxy(proxy: str) -> bool:
    """
    Check if a proxy is working by making a request to the test URL.

    This function is thread-safe as it creates a new session for each check.
    Uses a random user agent to avoid detection.

    Args:
        proxy (str): Proxy string to check.

    Returns:
        bool: True if the proxy is working, False otherwise.
    """
    if proxy is None:
        return False

    # Convert proxy string to dictionary format
    proxy_dict = convert_proxy_string_to_dict(proxy)

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

        # Make a GET request to the test URL with the proxy (using GET instead of HEAD for better compatibility)
        response = session.get(_TEST_URL, proxies=proxy_dict, timeout=timeout)

        # Check if the request was successful
        is_working = response.status_code == 200
        if not is_working:
            logger.debug(f"Proxy {proxy} returned status code {response.status_code}")
        return is_working
    except TimeoutError as e:
        logger.debug(f"Proxy {proxy} timed out: {e}")
        return False
    except ConnectionError as e:
        logger.debug(f"Proxy {proxy} connection error: {e}")
        return False
    except RequestException as e:
        logger.debug(f"Proxy {proxy} request exception: {e}")
        return False
    except Exception as e:
        logger.debug(f"Proxy {proxy} unexpected error: {e}")
        return False
    finally:
        # Ensure the session is closed to prevent resource leaks
        if "session" in locals():
            session.close()


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


def blacklist_proxy(proxy: str, duration: int = PROXY_BLACKLIST_DURATION):
    """
    Add a proxy to the blacklist to prevent it from being used temporarily.

    Args:
        proxy (str): Proxy string to blacklist.
        duration (int): Duration in seconds to keep the proxy blacklisted. Defaults to PROXY_BLACKLIST_DURATION.
    """
    global _PROXY_BLACKLIST
    if proxy:
        expiration_time = time.time() + duration
        _PROXY_BLACKLIST[proxy] = expiration_time
        logger.warning(f"Blacklisted proxy: {proxy} (for {duration}s)")


def unblacklist_proxy(proxy: str):
    """
    Remove a proxy from the blacklist.

    Args:
        proxy (str): Proxy string to unblacklist.
    """
    global _PROXY_BLACKLIST
    if proxy in _PROXY_BLACKLIST:
        del _PROXY_BLACKLIST[proxy]
        logger.info(f"Removed proxy from blacklist: {proxy}")


def clear_blacklist():
    """
    Clear all proxies from the blacklist.
    """
    global _PROXY_BLACKLIST
    count = len(_PROXY_BLACKLIST)
    _PROXY_BLACKLIST.clear()
    if count > 0:
        logger.info(f"Cleared {count} proxies from blacklist")


def get_proxy_stats() -> dict:
    """
    Get statistics about the proxy system.

    Returns:
        dict: Dictionary containing:
            - total_proxies: Total number of proxies cached (validated if check_proxies=True)
            - blacklisted_proxies: Number of currently blacklisted proxies
            - active_proxies: Number of working proxies available
            - validation_enabled: Whether proxy validation is enabled
    """
    global _PROXY_CACHE, _PROXY_BLACKLIST, _PROXY_CACHE_INITIALIZED, _SINGLE_PROXY

    # Import db here to avoid circular imports
    import db

    # Clean up expired blacklist entries first
    _cleanup_expired_blacklist()

    # Check if proxy validation is enabled
    validation_enabled = db.get_parameter("check_proxies") == "True"

    # Determine total proxy count
    # First check in-process cache (works if this is the same process that initialized proxies)
    total = 0

    # Check if we have a single proxy cached
    if _SINGLE_PROXY is not None:
        total = 1
    # Check if cache is initialized with a list
    elif _PROXY_CACHE_INITIALIZED and _PROXY_CACHE is not None:
        total = len(_PROXY_CACHE)
    else:
        # Cache not initialized in this process (likely web UI calling from different process)
        # If validation is enabled, get validated count from database
        if validation_enabled:
            validated_count_str = db.get_parameter("validated_proxy_count")
            if validated_count_str:
                total = int(validated_count_str)
            else:
                # No validated count stored yet
                # Show fetched count as estimate until first validation runs
                proxy_list_link = db.get_parameter("proxy_list_link")
                if proxy_list_link:
                    try:
                        proxies_from_link = fetch_proxies_from_link(proxy_list_link)
                        total = len(proxies_from_link) if proxies_from_link else 0
                    except Exception as e:
                        logger.debug(f"Error fetching proxies for stats: {e}")
                        total = 0
                else:
                    total = 0
        else:
            # Validation disabled, count all proxies from database
            proxy_list_str = db.get_parameter("proxy_list")

            # Count proxies from direct list
            if proxy_list_str:
                total = len([p.strip() for p in proxy_list_str.split(";") if p.strip()])
            # If no direct list, check if there's a link configured
            else:
                proxy_list_link = db.get_parameter("proxy_list_link")
                if proxy_list_link:
                    # Just fetch and count without validation
                    try:
                        proxies_from_link = fetch_proxies_from_link(proxy_list_link)
                        total = len(proxies_from_link) if proxies_from_link else 0
                    except Exception as e:
                        logger.debug(f"Error fetching proxies for stats: {e}")
                        total = 0

    blacklisted = len(_PROXY_BLACKLIST)
    active = total - blacklisted if total > 0 else 0

    return {
        "total_proxies": total,
        "blacklisted_proxies": blacklisted,
        "active_proxies": active,
        "validation_enabled": validation_enabled,
    }


def configure_proxy(session: requests.Session, proxy: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """
    Configure the proxy settings for a requests session.

    Args:
        session (requests.Session): The session to configure.
        proxy (Optional[str], optional): Proxy to be used. If None, a random proxy will be selected.

    Returns:
        tuple[bool, Optional[str]]: (True if proxy was configured, the proxy string used)
    """
    # If no proxy is provided, get a random one
    if proxy is None:
        proxy = get_random_proxy()

    # If we still don't have a proxy, return False
    if proxy is None:
        session.proxies.clear()
        logger.debug("No proxy configured (none available)")
        return False, None

    # Store original proxy string before conversion
    proxy_str = proxy

    # Handle string proxy
    if isinstance(proxy, str):
        proxy = convert_proxy_string_to_dict(proxy)

    # Update the session with the proxy settings
    session.proxies.update(proxy)
    logger.debug(f"Configured proxy: {proxy_str}")
    return True, proxy_str
