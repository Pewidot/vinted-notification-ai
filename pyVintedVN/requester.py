import json
import proxies
import sys
import os
import db
import random
# Vinted now serves its API behind a Cloudflare bot challenge that fingerprints
# the TLS/JA3 handshake. The plain `requests` library gets challenged (HTTP 200
# with an HTML "Please wait" page instead of JSON), so we use curl_cffi which can
# impersonate a real browser's TLS fingerprint and pass the challenge.
from curl_cffi import requests
from curl_cffi.requests.exceptions import (
    HTTPError,
    ProxyError,
    ConnectTimeout,
    ReadTimeout,
    ConnectionError as ReqConnectionError,
)

# Browser profile used by curl_cffi to impersonate the TLS fingerprint.
# "chrome" tracks the latest supported Chrome version in the installed curl_cffi.
IMPERSONATE_BROWSER = "chrome"

# Add the parent directory to sys.path to import logger
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

# Get logger for this module
logger = get_logger(__name__)


class Requester:
    """
    A class for handling HTTP requests to Vinted.

    This class manages session headers, cookies, and provides methods for making
    HTTP requests with retry logic for handling authentication issues.
    """

    def __init__(self, debug=False):
        """
        Initialize the Requester with default headers and session.

        Sets up the request headers with a randomly selected User-Agent,
        initializes the session, and configures default settings.

        Args:
            debug (bool, optional): Whether to print debug messages. Defaults to False.
        """

        # Add the parent directory to sys.path to import db
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import db

        # Get user agents and default headers from the database
        user_agents_json = db.get_parameter("user_agents")
        default_headers_json = db.get_parameter("default_headers")

        # Parse JSON strings
        user_agents = json.loads(user_agents_json) if user_agents_json else []
        default_headers = (
            json.loads(default_headers_json) if default_headers_json else {}
        )

        self.HEADER = {
            # Grabs a user agent from the database
            "User-Agent": random.choice(user_agents) if user_agents else "Mozilla/5.0",
            **(default_headers or {}),
            "Host": "www.vinted.fr",
        }
        self.VINTED_AUTH_URL = "https://www.vinted.fr/"
        self.MAX_RETRIES = 3

        # Get request timeout from database (default 30 seconds)
        timeout_str = db.get_parameter("request_timeout")
        self.REQUEST_TIMEOUT = int(timeout_str) if timeout_str else 30

        self.session = requests.Session(impersonate=IMPERSONATE_BROWSER)
        self.session.headers.update(self.HEADER)
        self.debug = debug

        if self.debug:
            logger.debug(f"Using User-Agent: {self.HEADER['User-Agent']}")

    def set_locale(self, locale):
        """
        Set the locale of the requester.

        Updates the authentication URL and headers to use the specified locale.

        Args:
            locale (str): The locale domain to use (e.g., 'www.vinted.fr', 'www.vinted.de')
        """
        self.VINTED_AUTH_URL = f"https://{locale}/"
        # Get user agents and default headers from the database
        user_agents_json = db.get_parameter("user_agents")
        default_headers_json = db.get_parameter("default_headers")

        # Parse JSON strings
        user_agents = json.loads(user_agents_json) if user_agents_json else []
        default_headers = (
            json.loads(default_headers_json) if default_headers_json else {}
        )

        self.HEADER = {
            "User-Agent": random.choice(user_agents) if user_agents else "Mozilla/5.0",
            **(default_headers or {}),
            "Host": f"{locale}",
        }
        self.session.headers.update(self.HEADER)
        if self.debug:
            logger.debug(
                f"Locale set to {locale} with User-Agent: {self.HEADER['User-Agent']}"
            )

    def get(self, url, params=None):
        """
        Make a GET request with retry logic and proxy rotation.

        If a 401 status code is received, it will attempt to refresh cookies
        and retry the request up to MAX_RETRIES times.
        If proxy errors occur, it will try with a different proxy.

        Args:
            url (str): The URL to request
            params (dict, optional): Query parameters for the request

        Returns:
            requests.Response: The response object if successful

        Raises:
            HTTPError: If the request fails after all retries
        """

        # Set a random proxy for this request
        proxy_configured, current_proxy = proxies.configure_proxy(self.session)
        if proxy_configured:
            logger.info(f"Making request to {url} using proxy: {current_proxy}")
        else:
            logger.info(f"Making request to {url} without proxy")

        tried = 0
        new_session = False
        proxy_retries = 0
        max_proxy_retries = 3  # Try up to 3 different proxies

        while tried < self.MAX_RETRIES:
            tried += 1
            try:
                response = self.session.get(url, params=params, timeout=self.REQUEST_TIMEOUT)
                if response.status_code in (401, 404) and tried < self.MAX_RETRIES:
                    logger.warning(
                        f"Cookies invalid (HTTP {response.status_code}), "
                        f"retrying {tried}/{self.MAX_RETRIES} | Proxy: {current_proxy or 'None'}"
                    )
                    self.set_cookies()
                elif response.status_code == 200:
                    logger.info(
                        f"Request successful (HTTP 200) | Proxy: {current_proxy or 'None'}"
                    )
                    return response
                elif tried == self.MAX_RETRIES:
                    # If we've reached max retries, return the last response
                    # even if it's not a 200 status code

                    # New try : if we still get a 401 or 403, we reset the session
                    if response.status_code in (401, 403) and not new_session:
                        # Log the error details for 401 and 403 errors, including headers and body snippet
                        logger.error(
                            f"Received HTTP {response.status_code} error for URL: {url}\n"
                            f"   Proxy used: {current_proxy or 'None'}\n"
                            f"   Response headers: {dict(response.headers)}\n"
                            f"   Response body (first 500 chars): {response.text[:500]}"
                        )

                        new_session = True
                        # Close old session before creating new one to prevent memory leak
                        old_session = self.session
                        self.session = requests.Session(impersonate=IMPERSONATE_BROWSER)
                        self.session.headers.update(self.HEADER)
                        try:
                            old_session.close()
                        except Exception:
                            pass  # Ignore errors when closing old session

                        # Try with a different proxy
                        if current_proxy and proxy_retries < max_proxy_retries:
                            logger.warning(f"Blacklisting failed proxy and trying another: {current_proxy}")
                            proxies.blacklist_proxy(current_proxy)
                            proxy_configured, current_proxy = proxies.configure_proxy(self.session)
                            proxy_retries += 1
                            if proxy_configured:
                                logger.info(f"Retrying with new proxy: {current_proxy}")
                            else:
                                logger.warning("No more proxies available, continuing without proxy")
                        else:
                            proxy_configured, current_proxy = proxies.configure_proxy(self.session)

                        tried = 0
                        continue

                    logger.error(
                        f"Request failed with HTTP {response.status_code} | "
                        f"Proxy: {current_proxy or 'None'}"
                    )
                    return response

            except (ProxyError, ConnectTimeout, ReadTimeout, ReqConnectionError) as e:
                error_type = type(e).__name__
                logger.error(
                    f"{error_type} with proxy {current_proxy or 'None'}: {str(e)[:200]}"
                )

                # Try with a different proxy if available
                if current_proxy and proxy_retries < max_proxy_retries:
                    proxies.blacklist_proxy(current_proxy)
                    proxy_retries += 1
                    logger.warning(f"Attempting retry {proxy_retries}/{max_proxy_retries} with different proxy...")

                    # Get a new proxy
                    proxy_configured, current_proxy = proxies.configure_proxy(self.session)
                    if proxy_configured:
                        logger.info(f"Retrying with new proxy: {current_proxy}")
                        tried -= 1  # Don't count proxy errors against regular retry limit
                        continue
                    else:
                        logger.warning("No more proxies available, continuing without proxy")
                        current_proxy = None
                        tried -= 1
                        continue
                else:
                    # No more proxies to try, fail
                    logger.error(f"All proxy retry attempts exhausted")
                    raise HTTPError(
                        f"Connection failed after {proxy_retries} proxy retries: {error_type} - {str(e)[:200]}"
                    )

            except Exception as e:
                error_type = type(e).__name__
                logger.error(
                    f"Unexpected error during request: {error_type} - {str(e)[:200]} | "
                    f"Proxy: {current_proxy or 'None'}"
                )
                # For unexpected errors, don't retry with different proxy, just re-raise
                raise

        # This should only happen if the loop exits without returning
        raise HTTPError(
            f"Failed to get a valid response after {self.MAX_RETRIES} attempts | "
            f"Last proxy: {current_proxy or 'None'}"
        )

    def post(self, url, params=None):
        """
        Make a POST request with proxy support and error handling.

        Args:
            url (str): The URL to request
            params (dict, optional): Parameters for the request

        Returns:
            requests.Response: The response object if successful

        Raises:
            HTTPError: If the request fails
        """
        # Set a random proxy for this request
        proxy_configured, current_proxy = proxies.configure_proxy(self.session)
        if proxy_configured:
            logger.info(f"Making POST request to {url} using proxy: {current_proxy}")
        else:
            logger.info(f"Making POST request to {url} without proxy")

        try:
            response = self.session.post(url, params, timeout=self.REQUEST_TIMEOUT)
            response.raise_for_status()
            logger.info(f"POST request successful (HTTP {response.status_code}) | Proxy: {current_proxy or 'None'}")
            return response
        except (ProxyError, ConnectTimeout, ReadTimeout, ReqConnectionError) as e:
            error_type = type(e).__name__
            logger.error(
                f"{error_type} during POST request with proxy {current_proxy or 'None'}: {str(e)[:200]}"
            )
            if current_proxy:
                proxies.blacklist_proxy(current_proxy)
            raise
        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                f"POST request failed: {error_type} - {str(e)[:200]} | Proxy: {current_proxy or 'None'}"
            )
            raise

    def set_cookies(self):
        """
        Reset and fetch new cookies for authentication.

        Clears the current session cookies and makes a HEAD request to
        the Vinted authentication URL to get new cookies.
        """
        self.session.cookies.clear()
        try:
            self.session.head(self.VINTED_AUTH_URL, timeout=self.REQUEST_TIMEOUT)
            if self.debug:
                logger.debug("Cookies set!")
        except Exception:
            if self.debug:
                logger.error(
                    "There was an error fetching cookies for vinted", exc_info=True
                )

    def update_cookies(self, cookies: dict):
        """
        Update the session cookies with the provided dictionary.

        Args:
            cookies (dict): Dictionary of cookies to update
        """
        self.session.cookies.update(cookies)
        if self.debug:
            logger.debug(f"Cookies manually updated ({len(cookies)} cookies received)")

    def close(self):
        """
        Close the session and clean up resources.

        Should be called when the Requester is no longer needed to prevent resource leaks.
        """
        try:
            self.session.close()
            if self.debug:
                logger.debug("Requester session closed")
        except Exception as e:
            logger.error(f"Error closing requester session: {e}")

    # Alias for backward compatibility
    setLocale = set_locale
    setCookies = set_cookies


# Singleton instance of the Requester class
requester = Requester()
