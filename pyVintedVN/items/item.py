import time
from datetime import datetime, timezone


class Item:
    """
    Represents a single item from Vinted.

    This class parses and stores various attributes of a Vinted item,
    such as id, title, brand, size, price, etc.

    Attributes:
        raw_data (dict): The raw data of the item as received from the API.
        id (str): The unique identifier of the item.
        title (str): The title of the item.
        brand_title (str): The brand of the item.
        size_title (str): The size of the item, or None if not available.
        currency (str): The currency code of the item's price.
        price (float): The price of the item.
        photo (str): The URL of the item's photo.
        url (str): The URL of the item on Vinted.
        created_at_ts (datetime): Listing time, or the first observation time.
        raw_timestamp (int): Listing timestamp, or first observation timestamp.
        has_real_timestamp (bool): Whether Vinted supplied a listing timestamp.
    """

    def __init__(self, data, locale=None):
        """
        Initialize an Item with data from the Vinted API.

        Args:
            data (dict): The item data from the Vinted API.
            locale (str, optional): www.vinted.<tld> host used to expand relative URLs.
        """
        self.raw_data = data
        self.id = data["id"]
        self.title = data["title"]
        item_box = data.get("item_box") or {}
        first_line = item_box.get("first_line")
        self.brand_title = data.get("brand_title") or (
            first_line if first_line and first_line != self.title else None
        )
        self.size_title = data.get("size_title")
        if not self.size_title:
            second_line = item_box.get("second_line") or ""
            self.size_title = (
                second_line.split(" · ", 1)[0] if " · " in second_line else None
            )
        self.currency = data["price"]["currency_code"]
        self.price = data["price"]["amount"]
        self.photo = (data.get("photo") or {}).get("url")
        self.url = data["url"]
        if self.url.startswith("/") and locale:
            self.url = f"https://{locale}{self.url}"
        # We keep everything before the "items"
        self.buy_url = (
            self.url.split("items")[0]
            + "transaction/buy/new?source_screen=item&transaction%5Bitem_id%5D="
            + str(data["id"])
        )
        real_timestamp = ((data.get("photo") or {}).get("high_resolution") or {}).get(
            "timestamp"
        )
        self.has_real_timestamp = real_timestamp is not None
        self.raw_timestamp = real_timestamp if real_timestamp is not None else int(time.time())
        self.created_at_ts = datetime.fromtimestamp(self.raw_timestamp, tz=timezone.utc)

    def __eq__(self, other):
        """
        Compare this item with another one.

        Two items are considered the same if they have the same ID.

        Args:
            other (Item): The other item to compare with.

        Returns:
            bool: True if the items have the same ID, False otherwise.
        """
        if not isinstance(other, Item):
            return False
        return self.id == other.id

    def __hash__(self):
        """
        Return a hash value for this item.

        The hash is based on the item's ID, which allows items to be used
        as keys in dictionaries and elements in sets.

        Returns:
            int: A hash value for the item.
        """
        return hash(("id", self.id))

    def is_new_item(self, minutes=20):
        """
        Check if this item is newly listed.

        An item is considered new if it was created within the specified
        number of minutes from the current time.

        Args:
            minutes (int, optional): The number of minutes to consider an item as new.
                Defaults to 20. The scraper passes a window sized from how long
                the query has been blind (see core.new_item_window_minutes).

        Returns:
            bool: True if the item is new, False otherwise.
        """
        # svc-catalogue no longer exposes listing time. Its results must be
        # classified by first-seen ID in the caller instead of guessed from IDs.
        if not self.has_real_timestamp:
            return True
        delta = datetime.now(timezone.utc) - self.created_at_ts
        return delta.total_seconds() < minutes * 60

    # Alias for backward compatibility
    isNewItem = is_new_item
