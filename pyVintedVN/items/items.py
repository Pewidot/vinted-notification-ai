from pyVintedVN.items.item import Item
from pyVintedVN.requester import requester
from urllib.parse import urlparse, parse_qsl
from curl_cffi.requests.exceptions import HTTPError
from typing import List, Dict, Optional
from pyVintedVN.settings import Urls


class Items:
    """
    A class for searching and retrieving items from Vinted.

    This class provides methods to search for items on Vinted using a search URL
    and to parse Vinted search URLs into API parameters.

    Example:
        >>> items = Items()
        >>> results = items.search("https://www.vinted.fr/catalog?search_text=shoes")
    """

    def search(
        self,
        url: str,
        nbr_items: int = 20,
        page: int = 1,
        time: Optional[int] = None,
        json: bool = False,
    ) -> List[Item]:
        """
        Retrieve items from a given search URL on Vinted.

        Args:
            url (str): The URL of the search on Vinted.
            nbr_items (int, optional): Number of items to be returned. Defaults to 20.
            page (int, optional): Page number to be returned. Defaults to 1.
            time (int, optional): Timestamp to filter items by time. Defaults to None. Looks like it doesn't work though.
            json (bool, optional): Whether to return raw JSON data instead of Item objects.
                Defaults to False.

        Returns:
            List[Item]: A list of Item objects.

        Raises:
            HTTPError: If the request to the Vinted API fails.
        """
        # Extract the www domain used to bootstrap anonymous auth.
        locale = urlparse(url).netloc

        # Parse the URL to get the API parameters
        params = self.parse_url(url, nbr_items, page, time)

        try:
            # set_locale() and get() must not be split by another thread: the
            # requester is a shared singleton, and a concurrent scrape would
            # otherwise overwrite the locale between these two calls and send
            # the request with the wrong Host header.
            with requester.lock:
                requester.set_locale(locale)
                # Build this only after selecting the locale; the requester is
                # shared and may still point at the previous query's country.
                api_url = (
                    f"https://{requester.get_api_host()}"
                    f"{Urls.VINTED_API_URL}/{Urls.VINTED_PRODUCTS_ENDPOINT}"
                )
                response = requester.get(url=api_url, params=params)
            response.raise_for_status()

            # Parse the response
            items = response.json()
            items = items["items"]

            # Return either Item objects or raw JSON data
            if not json:
                return [Item(_item, locale=locale) for _item in items]
            else:
                return items

        except HTTPError as err:
            raise err

    def parse_url(
        self, url: str, nbr_items: int = 20, page: int = 1, time: Optional[int] = None
    ) -> Dict:
        """
        Parse a Vinted search URL to get parameters for the API call.

        Args:
            url (str): The URL of the search on Vinted.
            nbr_items (int, optional): Number of items to be returned. Defaults to 20.
            page (int, optional): Page number to be returned. Defaults to 1.
            time (int, optional): Timestamp to filter items by time. Defaults to None.

        Returns:
            Dict: A dictionary of parameters for the Vinted API.
        """
        # Parse the query parameters from the URL
        queries = parse_qsl(urlparse(url).query)

        def joined(*names):
            return ",".join(value for key, value in queries if key in names)

        # svc-catalogue renamed id filters to attribute_ids[<type>]. Legacy
        # names still return HTTP 200 but are silently ignored.
        params = {
            "search_text": joined("search_text"),
            "attribute_ids[video_game_platform]": joined(
                "video_game_platform_ids[]", "video_game_platform_ids"
            ),
            "attribute_ids[catalog]": joined("catalog[]", "catalog_ids[]", "catalog_ids"),
            "attribute_ids[color]": joined("color_ids[]", "color_ids"),
            "attribute_ids[brand]": joined("brand_ids[]", "brand_id[]", "brand_ids"),
            "attribute_ids[size]": joined("size_ids[]", "size_ids"),
            "attribute_ids[material]": joined("material_ids[]", "material_ids"),
            "attribute_ids[status]": joined("status_ids[]", "status_ids"),
            # country/city keep their legacy names: attribute_ids variants are
            # accepted by the service but currently match no results.
            "country_ids": joined("country_ids[]", "country_ids"),
            "city_ids": joined("city_ids[]", "city_ids"),
            "is_for_swap": ",".join(
                map(str, [1 for tpl in queries if tpl[0] == "disposal[]"])
            ),
            "currency": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "currency"])
            ),
            "price_to": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "price_to"])
            ),
            "price_from": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "price_from"])
            ),
            "page": page,
            "per_page": nbr_items,
            "order": ",".join(
                map(str, [tpl[1] for tpl in queries if tpl[0] == "order"])
            ),
            "time": time,
        }

        # Unlike the old endpoint, svc-catalogue rejects blank values with 400.
        return {key: value for key, value in params.items() if value not in ("", None)}

    # Aliases for backward compatibility
    parseUrl = parse_url
