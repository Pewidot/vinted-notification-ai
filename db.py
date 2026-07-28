import sqlite3
from traceback import print_exc

DB_PATH = "./data/vinted_notifications.db"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_or_update_sqlite_db(db_path):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Using the sql script
        with open(db_path, "r", encoding="utf-8") as sql_file:
            sql_script = sql_file.read()
            cursor.executescript(sql_script)

        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def is_item_in_db_by_id(id):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT() FROM items WHERE item=?", (id,))
        if cursor.fetchone()[0]:
            return True
        return False
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def get_last_timestamp(query_id):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT last_item FROM queries WHERE id=?", (query_id,))
        result = cursor.fetchone()
        if result:
            return result[0]
        return None
    except Exception:
        print_exc()
        return None
    finally:
        if conn:
            conn.close()


def update_last_timestamp(query_id, timestamp):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE queries SET last_item=? WHERE id=?", (timestamp, query_id)
        )
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def add_item_to_db(id, title, query_id, price, timestamp, photo_url, currency="EUR",
                   url=None, update_last_item=True):
    """
    Store a found listing.

    Args:
        update_last_item (bool): Whether to advance the query's `last_item`
            watermark. Price runs walk *older* result pages, so they must index
            what they find without moving the watermark - otherwise genuinely
            new listings between the watermark and that old item would be
            skipped and never announced.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Insert into db the id and the query_id related to the item
        cursor.execute(
            "INSERT INTO items (item, title, price, currency, timestamp, photo_url, query_id, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, title, price, currency, timestamp, photo_url, query_id, url),
        )
        # Update the last item for the query
        if update_last_item:
            cursor.execute(
                "UPDATE queries SET last_item=? WHERE id=?", (timestamp, query_id)
            )
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def get_queries():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, query, last_item, query_name, telegram_chat_id, telegram_enabled, "
            "platform, active, track_prices, price_interval, price_depth, last_price_check, "
            "refresh_delay, last_scraped "
            "FROM queries"
        )
        return cursor.fetchall()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def is_query_in_db(processed_query):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # replace spaces in searched_text by % to match any query containing the searched text

        cursor.execute(
            "SELECT COUNT() FROM queries WHERE query = ?", (processed_query,)
        )
        if cursor.fetchone()[0]:
            return True
        return False
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def add_query_to_db(query, name=None, telegram_chat_id=None, platform="vinted"):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO queries (query, last_item, query_name, telegram_chat_id, telegram_enabled, platform) VALUES (?, NULL, ?, ?, 1, ?)",
            (query, name, telegram_chat_id, platform),
        )
        conn.commit()
        return cursor.lastrowid
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def get_query_id_by_rowid(rowid):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        query = f"SELECT id FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY ROWID) rn FROM queries) t WHERE rn={rowid}"
        cursor.execute(query)
        result = cursor.fetchone()
        if result:
            return result[0]
        return None
    except Exception:
        print_exc()
        return None
    finally:
        if conn:
            conn.close()


def remove_query_from_db(query_number):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # Delete items associated with this query using query_id
        cursor.execute("DELETE FROM items WHERE query_id=?", (query_number,))
        # Delete telegram bot links for this query
        cursor.execute("DELETE FROM query_telegram_bots WHERE query_id=?", (query_number,))
        cursor.execute("DELETE FROM query_price_bots WHERE query_id=?", (query_number,))
        # Delete price tracking data for this query
        cursor.execute("DELETE FROM price_history WHERE query_id=?", (query_number,))
        cursor.execute("DELETE FROM tracked_items WHERE query_id=?", (query_number,))
        # Delete the query
        cursor.execute("DELETE FROM queries WHERE id=?", (query_number,))
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def remove_all_queries_from_db():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # Delete all items first to maintain foreign key integrity
        cursor.execute("DELETE FROM items")
        # Delete all telegram bot links
        cursor.execute("DELETE FROM query_telegram_bots")
        cursor.execute("DELETE FROM query_price_bots")
        # Delete all price tracking data
        cursor.execute("DELETE FROM price_history")
        cursor.execute("DELETE FROM tracked_items")
        # Then delete all queries
        cursor.execute("DELETE FROM queries")
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def update_query_in_db(query_id, query, name, telegram_chat_id=None):
    """
    Update an existing query in the database.

    Args:
        query_id (int): The ID of the query to update
        query (str): The new query URL
        name (str, optional): The new name for the query
        telegram_chat_id (str, optional): Query-specific Telegram chat ID
            (None/empty = use the default telegram_chat_id parameter)

    Returns:
        bool: True if the query was updated successfully, False otherwise
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE queries SET query=?, query_name=?, telegram_chat_id=? WHERE id=?",
            (query, name, telegram_chat_id, query_id),
        )
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def get_query_telegram_settings(query_id):
    """
    Get the Telegram settings for a specific query.

    Args:
        query_id (int): The ID of the query

    Returns:
        tuple: (chat_id, enabled)
            - chat_id (str or None): Query-specific chat ID, None if not set
            - enabled (bool): Whether Telegram notifications are enabled for this query
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT telegram_chat_id, telegram_enabled FROM queries WHERE id=?",
            (query_id,),
        )
        result = cursor.fetchone()
        if result:
            chat_id = result[0] if result[0] else None
            enabled = True if result[1] is None else bool(result[1])
            return chat_id, enabled
        return None, True
    except Exception:
        print_exc()
        return None, True
    finally:
        if conn:
            conn.close()


def set_query_active(query_id, active):
    """
    Activate or deactivate a query. An inactive query is kept in the database
    but skipped entirely during scraping until reactivated.

    Args:
        query_id (int): The ID of the query
        active (bool): True to activate, False to deactivate (pause)

    Returns:
        bool: True if updated successfully, False otherwise
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE queries SET active=? WHERE id=?", (1 if active else 0, query_id)
        )
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def get_query_active(query_id):
    """Return True if the query is active (default True), False if paused."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT active FROM queries WHERE id=?", (query_id,))
        row = cursor.fetchone()
        if row is None:
            return True
        return True if row[0] is None else bool(row[0])
    except Exception:
        print_exc()
        return True
    finally:
        if conn:
            conn.close()


def get_query_name(query_id):
    """
    Get a human-readable name for a query: its stored name, or the search term
    extracted from the URL (search_text for Vinted, _nkw for eBay), or the URL.

    Returns:
        str: The query display name (empty string if not found)
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT query_name, query FROM queries WHERE id=?", (query_id,))
        row = cursor.fetchone()
        if not row:
            return ""
        name, url = row
        if name:
            return name
        from urllib.parse import urlparse, parse_qs

        params = parse_qs(urlparse(url or "").query)
        return (
            params.get("search_text", [None])[0]
            or params.get("_nkw", [None])[0]
            or url
            or ""
        )
    except Exception:
        print_exc()
        return ""
    finally:
        if conn:
            conn.close()


def get_query_platform(query_id):
    """
    Get the platform of a query ('vinted', 'kleinanzeigen' or 'ebay').

    Args:
        query_id (int): The ID of the query

    Returns:
        str: The platform name, defaults to 'vinted'
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT platform FROM queries WHERE id=?", (query_id,))
        result = cursor.fetchone()
        if result and result[0]:
            return result[0]
        return "vinted"
    except Exception:
        print_exc()
        return "vinted"
    finally:
        if conn:
            conn.close()


def set_query_telegram_enabled(query_id, enabled):
    """
    Enable or disable Telegram notifications for a specific query.

    Args:
        query_id (int): The ID of the query
        enabled (bool): True to enable, False to disable

    Returns:
        bool: True if updated successfully, False otherwise
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE queries SET telegram_enabled=? WHERE id=?",
            (1 if enabled else 0, query_id),
        )
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


### PRICE TRACKING ###


def set_query_refresh_delay(query_id, seconds):
    """
    Set how often a query is scraped.

    Args:
        seconds (int or None): interval in seconds; None/0 falls back to the
            global query_refresh_delay.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        value = None
        if seconds:
            try:
                value = max(5, int(seconds))
            except (TypeError, ValueError):
                value = None
        cursor.execute("UPDATE queries SET refresh_delay=? WHERE id=?", (value, query_id))
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def mark_query_scraped(query_id, timestamp=None):
    """Remember when a query was last scraped (drives its own interval)."""
    import time as _time

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE queries SET last_scraped=? WHERE id=?",
            (timestamp if timestamp is not None else _time.time(), query_id),
        )
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def get_scraper_tick_seconds(floor=10):
    """
    How often the scraper loop should wake up.

    Must be at least as fine-grained as the fastest query, otherwise a query set
    to 30s would still only run at the global interval.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM parameters WHERE key='query_refresh_delay'")
        row = cursor.fetchone()
        delays = [int(row[0])] if row and row[0] else [60]
        cursor.execute(
            "SELECT MIN(refresh_delay) FROM queries"
            " WHERE COALESCE(active,1)=1 AND refresh_delay IS NOT NULL AND refresh_delay > 0"
        )
        row = cursor.fetchone()
        if row and row[0]:
            delays.append(int(row[0]))
        return max(floor, min(delays))
    except Exception:
        print_exc()
        return 60
    finally:
        if conn:
            conn.close()


def set_query_price_tracking(query_id, enabled, interval=None, depth=None):
    """
    Configure price tracking for a query.

    Args:
        query_id (int): The query id
        enabled (bool): Whether to track prices at all
        interval (int, optional): Minutes between price runs
        depth (int, optional): How many result pages to walk per run
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        fields = ["track_prices=?"]
        values = [1 if enabled else 0]
        if interval is not None:
            fields.append("price_interval=?")
            values.append(max(1, int(interval)))
        if depth is not None:
            fields.append("price_depth=?")
            values.append(max(1, int(depth)))
        values.append(query_id)
        cursor.execute(f"UPDATE queries SET {', '.join(fields)} WHERE id=?", values)
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def get_queries_due_for_price_check(now=None):
    """
    Queries whose price run is due: tracking on, query active, and the
    configured interval has elapsed since the last run.

    Returns:
        list of tuples: (id, query, platform, price_depth, price_interval)
    """
    import time as _time

    now = now if now is not None else _time.time()
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, query, platform, price_depth, price_interval "
            "FROM queries "
            "WHERE track_prices=1 AND COALESCE(active,1)=1 "
            "AND (COALESCE(last_price_check,0) + price_interval*60) <= ?",
            (now,),
        )
        return cursor.fetchall()
    except Exception:
        print_exc()
        return []
    finally:
        if conn:
            conn.close()


def update_last_price_check(query_id, timestamp=None):
    """Mark a query's price run as done."""
    import time as _time

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE queries SET last_price_check=? WHERE id=?",
            (timestamp if timestamp is not None else _time.time(), query_id),
        )
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


# eBay shows some (mostly commercial / cross-border) listings alternately with
# and without VAT, so the same unchanged listing appears to jump by exactly the
# VAT rate - e.g. 39.58 <-> 47.10, which is exactly x1.19. Matching the common
# EU rates with a tight tolerance keeps genuine price moves detectable.
VAT_MULTIPLIERS = (1.05, 1.07, 1.09, 1.10, 1.17, 1.19, 1.20, 1.21, 1.22,
                   1.23, 1.24, 1.25, 1.27)
VAT_TOLERANCE = 0.002  # 0.2% - tight enough not to swallow real price changes


def looks_like_vat_switch(old_price, new_price):
    """
    True if the two prices differ by exactly a common VAT rate.

    Used to tell "the same listing was shown net instead of gross" apart from a
    real price change, which otherwise produces a notification on every run.
    """
    try:
        old_v, new_v = float(old_price), float(new_price)
    except (TypeError, ValueError):
        return False
    if old_v <= 0 or new_v <= 0:
        return False
    ratio = max(old_v, new_v) / min(old_v, new_v)
    return any(abs(ratio - m) <= VAT_TOLERANCE for m in VAT_MULTIPLIERS)


def record_price(item, query_id, price, currency="EUR", title=None, url=None,
                 photo_url=None, timestamp=None, is_auction=False, auction_end=0):
    """
    Record one price observation for a listing.

    A history row is only written when the price actually changed (or on first
    sight) - re-reading an unchanged listing every few hours would otherwise
    bloat the table without adding information. `last_seen` is always refreshed.

    Returns:
        tuple: (status, old_price, new_price)
            status is one of:
              "new"             first time this listing is seen
              "changed"         real price move - worth announcing
              "flapping"        value bounced back to a recent one (recorded,
                                but not announced)
              "currency_switch" price arrived in a different currency, so the
                                numbers are not comparable (ignored)
              "vat_switch"      same listing shown net instead of gross (or vice
                                versa) - differs by exactly a VAT rate (ignored)
              "unchanged"       same price as before
    """
    import time as _time

    ts = timestamp if timestamp is not None else _time.time()
    item = str(item)
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_price, observations, currency FROM tracked_items"
            " WHERE item=? AND query_id=?",
            (item, query_id),
        )
        row = cursor.fetchone()

        if row is None:
            cursor.execute(
                "INSERT INTO tracked_items (item, query_id, title, url, photo_url, currency,"
                " first_price, last_price, first_seen, last_seen, observations,"
                " is_auction, auction_end)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (item, query_id, title, url, photo_url, currency, price, price, ts, ts,
                 1 if is_auction else 0, auction_end or 0),
            )
            cursor.execute(
                "INSERT INTO price_history (item, query_id, price, currency, timestamp)"
                " VALUES (?, ?, ?, ?, ?)",
                (item, query_id, price, currency, ts),
            )
            conn.commit()
            return "new", None, price

        old_price, _obs, old_currency = row[0], row[1], row[2]

        # Cross-border listings are shown converted into the viewer's currency,
        # and eBay serves the same listing sometimes in the seller's currency
        # and sometimes converted. Comparing those numbers is meaningless, so
        # the observation is ignored entirely: no history row (it would mix
        # currencies in one series) and no change to last_price. Only the
        # "seen" bookkeeping is updated below.
        # Same reasoning for the net/gross flip: eBay shows some listings with
        # VAT and some without, so an unchanged listing appears to jump by
        # exactly the VAT rate (e.g. 39.58 <-> 47.10 = x1.19).
        ignore_reason = None
        if old_currency and currency and old_currency != currency:
            ignore_reason = "currency_switch"
        elif looks_like_vat_switch(old_price, price):
            ignore_reason = "vat_switch"

        if ignore_reason:
            cursor.execute(
                "UPDATE tracked_items SET last_seen=?, observations=observations+1,"
                " title=COALESCE(?, title), url=COALESCE(?, url),"
                " photo_url=COALESCE(?, photo_url)"
                " WHERE item=? AND query_id=?",
                (ts, title, url, photo_url, item, query_id),
            )
            conn.commit()
            return ignore_reason, old_price, price

        changed = old_price is None or abs(float(old_price) - float(price)) > 0.001

        status = "unchanged"
        if changed:
            cursor.execute(
                "INSERT INTO price_history (item, query_id, price, currency, timestamp)"
                " VALUES (?, ?, ?, ?, ?)",
                (item, query_id, price, currency, ts),
            )
            status = "changed"

            # Two cases that look like a price change but are not, and would
            # otherwise produce a message on every single run:
            #
            #  1) the currency switched (some listings are served in the
            #     seller's currency one time and converted the next), so the
            #     two numbers are not comparable at all
            #  2) the value is bouncing back to one it already had moments ago
            #     (seen on worldwide listings that alternate between a net and
            #     a gross price)
            #
            # The observation is still recorded - only the notification is
            # suppressed by reporting a distinct status.
            if old_currency and currency and old_currency != currency:
                status = "currency_switch"
            else:
                cursor.execute(
                    "SELECT price FROM price_history WHERE item=? AND query_id=?"
                    " ORDER BY timestamp DESC, id DESC LIMIT 4",
                    (item, query_id),
                )
                recent = [r[0] for r in cursor.fetchall()]
                # recent[0] is the row just inserted; anything further back that
                # matches means the price is oscillating rather than moving.
                if any(abs(float(p) - float(price)) < 0.001 for p in recent[2:]):
                    status = "flapping"
        cursor.execute(
            "UPDATE tracked_items SET last_price=?, last_seen=?, observations=observations+1,"
            " title=COALESCE(?, title), url=COALESCE(?, url), photo_url=COALESCE(?, photo_url),"
            " is_auction=?, auction_end=CASE WHEN ?>0 THEN ? ELSE auction_end END"
            " WHERE item=? AND query_id=?",
            (price, ts, title, url, photo_url, 1 if is_auction else 0,
             auction_end or 0, auction_end or 0, item, query_id),
        )
        conn.commit()
        return status, old_price, price
    except Exception:
        print_exc()
        return "unchanged", None, price
    finally:
        if conn:
            conn.close()


def get_auctions_ending_soon(within_seconds=600, now=None):
    """
    Auctions that end within the given window and have not been announced yet.

    Only rows that are still in the future are returned, so a run that was down
    for a while does not spam alerts for auctions that already closed.

    Returns:
        list of tuples: (item, query_id, title, url, photo_url, last_price,
                         currency, auction_end)
    """
    import time as _time

    now = now if now is not None else _time.time()
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT item, query_id, title, url, photo_url, last_price, currency, auction_end"
            " FROM tracked_items"
            " WHERE is_auction=1 AND COALESCE(ending_notified,0)=0"
            " AND auction_end > ? AND auction_end <= ?",
            (now, now + within_seconds),
        )
        return cursor.fetchall()
    except Exception:
        print_exc()
        return []
    finally:
        if conn:
            conn.close()


def mark_auction_notified(item, query_id):
    """Remember that the ending alert for this auction was sent (one-time)."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tracked_items SET ending_notified=1 WHERE item=? AND query_id=?",
            (str(item), query_id),
        )
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def get_price_history(item, query_id=None, limit=500):
    """All recorded prices for a listing, oldest first."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if query_id is None:
            cursor.execute(
                "SELECT price, currency, timestamp FROM price_history WHERE item=?"
                " ORDER BY timestamp LIMIT ?",
                (str(item), limit),
            )
        else:
            cursor.execute(
                "SELECT price, currency, timestamp FROM price_history"
                " WHERE item=? AND query_id=? ORDER BY timestamp LIMIT ?",
                (str(item), query_id, limit),
            )
        return cursor.fetchall()
    except Exception:
        print_exc()
        return []
    finally:
        if conn:
            conn.close()


def get_tracked_items(query_id=None, limit=200, changed_only=False):
    """
    Listings under price tracking, most recently seen first.

    Returns tuples:
        (item, query_id, title, url, photo_url, currency, first_price,
         last_price, first_seen, last_seen, observations, query_name, platform)
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        sql = (
            "SELECT t.item, t.query_id, t.title, t.url, t.photo_url, t.currency,"
            " t.first_price, t.last_price, t.first_seen, t.last_seen, t.observations,"
            " q.query_name, q.platform"
            " FROM tracked_items t LEFT JOIN queries q ON q.id = t.query_id"
        )
        conds, params = [], []
        if query_id is not None:
            conds.append("t.query_id=?")
            params.append(query_id)
        if changed_only:
            conds.append("t.first_price <> t.last_price")
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY t.last_seen DESC LIMIT ?"
        params.append(limit)
        cursor.execute(sql, params)
        return cursor.fetchall()
    except Exception:
        print_exc()
        return []
    finally:
        if conn:
            conn.close()


def get_price_stats():
    """Summary numbers for the price dashboard."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        stats = {}
        cursor.execute("SELECT COUNT(*) FROM tracked_items")
        stats["tracked_items"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM price_history")
        stats["observations"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tracked_items WHERE first_price <> last_price")
        stats["changed"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tracked_items WHERE last_price < first_price")
        stats["dropped"] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM queries WHERE track_prices=1")
        stats["tracked_queries"] = cursor.fetchone()[0]
        return stats
    except Exception:
        print_exc()
        return {"tracked_items": 0, "observations": 0, "changed": 0,
                "dropped": 0, "tracked_queries": 0}
    finally:
        if conn:
            conn.close()


def get_query_price_bots(query_id):
    """Bots explicitly selected for PRICE messages of a query."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT b.id, b.name, b.token, b.chat_id, b.enabled"
            " FROM telegram_bots b JOIN query_price_bots qb ON b.id = qb.bot_id"
            " WHERE qb.query_id=? ORDER BY b.id",
            (query_id,),
        )
        return cursor.fetchall()
    except Exception:
        print_exc()
        return []
    finally:
        if conn:
            conn.close()


def set_query_price_bots(query_id, bot_ids):
    """Replace the bots that receive price messages for a query."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM query_price_bots WHERE query_id=?", (query_id,))
        for bot_id in bot_ids or []:
            cursor.execute(
                "INSERT OR IGNORE INTO query_price_bots (query_id, bot_id) VALUES (?, ?)",
                (query_id, bot_id),
            )
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def get_query_price_targets(query_id):
    """
    Where price messages for this query should go.

    Falls back to the query's normal notification bots when no dedicated price
    bot is selected, so enabling tracking works without extra configuration.

    Returns:
        list of tuples: (id, name, token, chat_id)
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT b.id, b.name, b.token, b.chat_id"
            " FROM telegram_bots b JOIN query_price_bots qb ON b.id = qb.bot_id"
            " WHERE qb.query_id=? AND b.enabled=1"
            " AND b.token IS NOT NULL AND b.token <> ''"
            " AND b.chat_id IS NOT NULL AND b.chat_id <> '' ORDER BY b.id",
            (query_id,),
        )
        targets = cursor.fetchall()
        if targets:
            return targets
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()
    # No dedicated price bots -> use the query's regular notification targets
    _, targets = get_query_telegram_targets(query_id)
    return targets


### TELEGRAM BOTS ###


def get_telegram_bots(enabled_only=False):
    """
    Get all configured Telegram bots.

    Args:
        enabled_only (bool): If True, only return enabled bots.

    Returns:
        list of tuples: (id, name, token, chat_id, enabled, is_command_bot)
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        query = "SELECT id, name, token, chat_id, enabled, is_command_bot FROM telegram_bots"
        if enabled_only:
            query += " WHERE enabled=1"
        query += " ORDER BY is_command_bot DESC, id"
        cursor.execute(query)
        return cursor.fetchall()
    except Exception:
        print_exc()
        return []
    finally:
        if conn:
            conn.close()


def get_telegram_bot(bot_id):
    """Get a single Telegram bot by id, or None."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, token, chat_id, enabled, is_command_bot FROM telegram_bots WHERE id=?",
            (bot_id,),
        )
        return cursor.fetchone()
    except Exception:
        print_exc()
        return None
    finally:
        if conn:
            conn.close()


def add_telegram_bot(name, token, chat_id, enabled=True, is_command_bot=False):
    """
    Add a new Telegram bot. If it is the first bot, it automatically becomes the
    command bot. If is_command_bot is True, any previous command bot is demoted.

    Returns:
        int or None: The new bot's id, or None on error.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # First bot is always the command bot
        cursor.execute("SELECT COUNT(*) FROM telegram_bots")
        if cursor.fetchone()[0] == 0:
            is_command_bot = True
        if is_command_bot:
            cursor.execute("UPDATE telegram_bots SET is_command_bot=0")
        cursor.execute(
            "INSERT INTO telegram_bots (name, token, chat_id, enabled, is_command_bot) VALUES (?, ?, ?, ?, ?)",
            (name, token, chat_id, 1 if enabled else 0, 1 if is_command_bot else 0),
        )
        conn.commit()
        return cursor.lastrowid
    except Exception:
        print_exc()
        return None
    finally:
        if conn:
            conn.close()


def update_telegram_bot(bot_id, name, token, chat_id, enabled, is_command_bot=None):
    """
    Update an existing Telegram bot. If is_command_bot is True, other bots are
    demoted. Returns True on success.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if is_command_bot:
            cursor.execute("UPDATE telegram_bots SET is_command_bot=0")
        if is_command_bot is None:
            cursor.execute(
                "UPDATE telegram_bots SET name=?, token=?, chat_id=?, enabled=? WHERE id=?",
                (name, token, chat_id, 1 if enabled else 0, bot_id),
            )
        else:
            cursor.execute(
                "UPDATE telegram_bots SET name=?, token=?, chat_id=?, enabled=?, is_command_bot=? WHERE id=?",
                (name, token, chat_id, 1 if enabled else 0, 1 if is_command_bot else 0, bot_id),
            )
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def delete_telegram_bot(bot_id):
    """
    Delete a Telegram bot and its query links. If the deleted bot was the command
    bot, another enabled bot (if any) is promoted to command bot.

    Returns:
        bool: True on success.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT is_command_bot FROM telegram_bots WHERE id=?", (bot_id,))
        row = cursor.fetchone()
        was_command = bool(row[0]) if row else False

        cursor.execute("DELETE FROM query_telegram_bots WHERE bot_id=?", (bot_id,))
        cursor.execute("DELETE FROM query_price_bots WHERE bot_id=?", (bot_id,))
        cursor.execute("DELETE FROM telegram_bots WHERE id=?", (bot_id,))

        # Promote another bot to command bot if we removed the command bot
        if was_command:
            cursor.execute(
                "SELECT id FROM telegram_bots ORDER BY enabled DESC, id LIMIT 1"
            )
            promote = cursor.fetchone()
            if promote:
                cursor.execute(
                    "UPDATE telegram_bots SET is_command_bot=1 WHERE id=?", (promote[0],)
                )
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def set_command_bot(bot_id):
    """Make the given bot the command bot (demoting any previous one)."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE telegram_bots SET is_command_bot=0")
        cursor.execute("UPDATE telegram_bots SET is_command_bot=1 WHERE id=?", (bot_id,))
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def get_command_bot():
    """
    Get the command bot (the one that polls for commands). Falls back to the
    first enabled bot with a token if none is flagged.

    Returns:
        tuple or None: (id, name, token, chat_id, enabled, is_command_bot)
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, token, chat_id, enabled, is_command_bot FROM telegram_bots "
            "WHERE is_command_bot=1 AND token IS NOT NULL AND token <> '' LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            return row
        # Fallback: first enabled bot with a token
        cursor.execute(
            "SELECT id, name, token, chat_id, enabled, is_command_bot FROM telegram_bots "
            "WHERE enabled=1 AND token IS NOT NULL AND token <> '' ORDER BY id LIMIT 1"
        )
        return cursor.fetchone()
    except Exception:
        print_exc()
        return None
    finally:
        if conn:
            conn.close()


def has_active_telegram_bot():
    """Return True if at least one enabled bot has both a token and a chat id."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM telegram_bots "
            "WHERE enabled=1 AND token IS NOT NULL AND token <> '' "
            "AND chat_id IS NOT NULL AND chat_id <> ''"
        )
        return cursor.fetchone()[0] > 0
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def get_query_bots(query_id):
    """
    Get the bots linked to a query.

    Returns:
        list of tuples: (id, name, token, chat_id, enabled) for linked bots.
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT b.id, b.name, b.token, b.chat_id, b.enabled "
            "FROM telegram_bots b JOIN query_telegram_bots qb ON b.id = qb.bot_id "
            "WHERE qb.query_id=? ORDER BY b.id",
            (query_id,),
        )
        return cursor.fetchall()
    except Exception:
        print_exc()
        return []
    finally:
        if conn:
            conn.close()


def set_query_bots(query_id, bot_ids):
    """
    Replace the set of bots linked to a query.

    Args:
        query_id (int): The query id.
        bot_ids (iterable): Bot ids to link (may be empty).
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM query_telegram_bots WHERE query_id=?", (query_id,))
        for bot_id in bot_ids or []:
            cursor.execute(
                "INSERT OR IGNORE INTO query_telegram_bots (query_id, bot_id) VALUES (?, ?)",
                (query_id, bot_id),
            )
        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def get_query_telegram_targets(query_id):
    """
    Resolve where notifications for a query should be sent.

    Rules:
    - If the query has telegram disabled -> (False, [])
    - Otherwise the targets are the query's linked enabled bots (with token+chat).
    - If the query has no linked bots, fall back to the command bot.
    - A None query_id (legacy queue items) falls back to the command bot.

    Returns:
        tuple: (enabled, [ (id, name, token, chat_id), ... ])
    """
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        enabled = True
        if query_id is not None:
            cursor.execute("SELECT telegram_enabled FROM queries WHERE id=?", (query_id,))
            row = cursor.fetchone()
            if row is not None:
                enabled = True if row[0] is None else bool(row[0])
        if not enabled:
            return False, []

        targets = []
        if query_id is not None:
            cursor.execute(
                "SELECT b.id, b.name, b.token, b.chat_id "
                "FROM telegram_bots b JOIN query_telegram_bots qb ON b.id = qb.bot_id "
                "WHERE qb.query_id=? AND b.enabled=1 "
                "AND b.token IS NOT NULL AND b.token <> '' "
                "AND b.chat_id IS NOT NULL AND b.chat_id <> '' ORDER BY b.id",
                (query_id,),
            )
            targets = cursor.fetchall()

        if not targets:
            # Fall back to the command bot
            cursor.execute(
                "SELECT id, name, token, chat_id FROM telegram_bots "
                "WHERE is_command_bot=1 AND enabled=1 AND token IS NOT NULL AND token <> '' "
                "AND chat_id IS NOT NULL AND chat_id <> '' LIMIT 1"
            )
            cmd = cursor.fetchone()
            if cmd:
                targets = [cmd]

        return True, targets
    except Exception:
        print_exc()
        return True, []
    finally:
        if conn:
            conn.close()


def add_to_allowlist(country):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO allowlist VALUES (?)", (country,))
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def remove_from_allowlist(country):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM allowlist WHERE country=?", (country,))
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def get_allowlist():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM allowlist")
        # Get list of countries
        countries = [country[0] for country in cursor.fetchall()]
        # Return 0 if there are no countries in the allowlist
        if not countries:
            return 0
        return countries
    finally:
        if conn:
            conn.close()


def clear_allowlist():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM allowlist")
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def get_parameter(key):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM parameters WHERE key=?", (key,))
        result = cursor.fetchone()
        return result[0] if result else None
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def set_parameter(key, value):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # Use INSERT OR REPLACE to create parameter if it doesn't exist
        cursor.execute("INSERT OR REPLACE INTO parameters (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def get_all_parameters():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM parameters")
        return {row[0]: row[1] for row in cursor.fetchall()}
    except Exception:
        print_exc()
        return {}
    finally:
        if conn:
            conn.close()


def get_items(limit=50, query=None):
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if query:
            # Get the query_id for the given query
            cursor.execute("SELECT id FROM queries WHERE query=?", (query,))
            result = cursor.fetchone()
            if result:
                query_id = result[0]
                # Get items with the matching query_id
                cursor.execute(
                    "SELECT i.item, i.title, i.price, i.currency, i.timestamp, q.query, i.photo_url, q.query_name, i.url FROM items i JOIN queries q ON i.query_id = q.id WHERE i.query_id=? ORDER BY i.timestamp DESC LIMIT ?",
                    (query_id, limit),
                )
            else:
                return []
        else:
            # Join with queries table to get the query text
            cursor.execute(
                "SELECT i.item, i.title, i.price, i.currency, i.timestamp, q.query, i.photo_url, q.query_name, i.url FROM items i JOIN queries q ON i.query_id = q.id ORDER BY i.timestamp DESC LIMIT ?",
                (limit,),
            )
        return cursor.fetchall()
    except Exception:
        print_exc()
        return []
    finally:
        if conn:
            conn.close()


def get_total_items_count():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM items")
        return cursor.fetchone()[0]
    except Exception:
        print_exc()
        return 0
    finally:
        if conn:
            conn.close()


def get_total_queries_count():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM queries")
        return cursor.fetchone()[0]
    except Exception:
        print_exc()
        return 0
    finally:
        if conn:
            conn.close()


def get_last_found_item():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT i.item, i.title, i.price, i.currency, i.timestamp, q.query, i.photo_url, i.url FROM items i JOIN queries q ON i.query_id = q.id ORDER BY i.timestamp DESC LIMIT 1"
        )
        return cursor.fetchone()
    except Exception:
        print_exc()
        return None
    finally:
        if conn:
            conn.close()


def get_items_per_day():
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Get total items
        cursor.execute("SELECT COUNT(*) FROM items")
        total_items = cursor.fetchone()[0]

        if total_items == 0:
            return 0

        # Get earliest and latest timestamps
        cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM items")
        min_timestamp, max_timestamp = cursor.fetchone()

        # Calculate number of days (add 1 to include both start and end days)
        import datetime

        min_date = datetime.datetime.fromtimestamp(min_timestamp).date()
        max_date = datetime.datetime.fromtimestamp(max_timestamp).date()
        days_diff = (max_date - min_date).days + 1

        # Ensure at least 1 day to avoid division by zero
        days_diff = max(1, days_diff)

        # Calculate items per day
        return round(total_items / days_diff, 1)
    except Exception:
        print_exc()
        return 0
    finally:
        if conn:
            conn.close()
