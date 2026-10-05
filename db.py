import sqlite3
from traceback import print_exc

DB_PATH = "./data/vinted_notifications.db"
WORKING_PROXY_BLACKLIST_SECONDS = 60 * 60

# The items table doubles as the persistent ID-deduplication store, so filtered
# Vinted listings still need to be recorded there. Keep non-EUR Vinted rows out
# of user-facing history and dashboard statistics while leaving other platforms
# untouched.
VISIBLE_ITEM_SQL = (
    "(q.query NOT LIKE '%vinted.%' "
    "OR UPPER(COALESCE(i.currency, '')) = 'EUR')"
)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def create_or_update_sqlite_db(db_path):
    """
    Run a SQL script against the database.

    Returns True on success and False if the script failed - the caller must
    check, because a migration that silently fails would otherwise be retried
    forever without ever advancing the version.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Using the sql script
        with open(db_path, "r", encoding="utf-8") as sql_file:
            sql_script = sql_file.read()
            cursor.executescript(sql_script)

        conn.commit()
        return True
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def is_item_in_db_by_id(id):
    conn = None
    try:
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
                   url=None):
    """Store a found listing and advance the query's watermark."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Insert into db the id and the query_id related to the item
        cursor.execute(
            "INSERT OR IGNORE INTO items (item, title, price, currency, timestamp, photo_url, query_id, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, title, price, currency, timestamp, photo_url, query_id, url),
        )
        # Update the last item for the query
        cursor.execute(
            "UPDATE queries SET last_item=? WHERE id=?", (timestamp, query_id)
        )
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def is_vinted_id_baselined(query_id):
    """Whether this query has primed the timestamp-free Vinted ID catalogue."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(vinted_id_baselined, 0) FROM queries WHERE id=?",
            (query_id,),
        )
        result = cursor.fetchone()
        return bool(result and result[0])
    except Exception:
        print_exc()
        return False
    finally:
        if conn:
            conn.close()


def mark_vinted_id_baselined(query_id):
    """Persist completion of a query's silent Vinted ID baseline."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE queries SET vinted_id_baselined=1 WHERE id=?", (query_id,)
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, query, last_item, query_name, telegram_chat_id, telegram_enabled, "
            "platform, active, refresh_delay, last_scraped, last_success "
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
        cursor = conn.cursor()
        # Delete items associated with this query using query_id
        cursor.execute("DELETE FROM items WHERE query_id=?", (query_number,))
        # Delete telegram bot links for this query
        cursor.execute("DELETE FROM query_telegram_bots WHERE query_id=?", (query_number,))
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
        conn = get_db_connection()
        cursor = conn.cursor()
        # Delete all items first to maintain foreign key integrity
        cursor.execute("DELETE FROM items")
        # Delete all telegram bot links
        cursor.execute("DELETE FROM query_telegram_bots")
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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


### QUERY SCHEDULING ###


def set_query_refresh_delay(query_id, seconds):
    """
    Set how often a query is scraped.

    Args:
        seconds (int or None): interval in seconds; None/0 falls back to the
            global query_refresh_delay.
    """
    conn = None
    try:
        conn = get_db_connection()
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
        conn = get_db_connection()
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


def mark_query_success(query_id, timestamp=None):
    """
    Remember when a query last returned results.

    Kept apart from last_scraped, which is stamped before the request and keeps
    advancing while a query only produces errors. The new-item window is sized
    from this column, so an outage widens it by as much as it cost us.
    """
    import time as _time

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE queries SET last_success=? WHERE id=?",
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


def set_query_worker_state(query_id, platform, state, worker_id=None, error=None):
    """Persist the latest state of one independent query worker."""
    import time as _time

    now = _time.time()
    conn = None
    try:
        conn = get_db_connection()
        if state == "running":
            conn.execute(
                """INSERT INTO query_worker_state
                   (query_id, platform, state, worker_id, started_at, heartbeat_at,
                    last_error, run_count, success_count)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, 1, 0)
                   ON CONFLICT(query_id) DO UPDATE SET
                     platform=excluded.platform, state=excluded.state,
                     worker_id=excluded.worker_id, started_at=excluded.started_at,
                     heartbeat_at=excluded.heartbeat_at, last_error=NULL,
                     run_count=query_worker_state.run_count + 1""",
                (query_id, platform, state, worker_id, now, now),
            )
        else:
            success_increment = 1 if state == "healthy" else 0
            conn.execute(
                """INSERT INTO query_worker_state
                   (query_id, platform, state, worker_id, finished_at, heartbeat_at,
                    last_error, run_count, success_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                   ON CONFLICT(query_id) DO UPDATE SET
                     platform=excluded.platform, state=excluded.state,
                     worker_id=excluded.worker_id, finished_at=excluded.finished_at,
                     heartbeat_at=excluded.heartbeat_at, last_error=excluded.last_error,
                     success_count=query_worker_state.success_count + ?""",
                (query_id, platform, state, worker_id, now, now,
                 (str(error)[:500] if error else None), success_increment,
                 success_increment),
            )
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def get_query_worker_states():
    conn = None
    try:
        conn = get_db_connection()
        return conn.execute(
            """SELECT w.query_id, COALESCE(q.query_name, q.query), w.platform,
                      w.state, w.worker_id, w.started_at, w.finished_at,
                      w.heartbeat_at, w.last_error, w.run_count, w.success_count
               FROM query_worker_state w
               LEFT JOIN queries q ON q.id=w.query_id
               ORDER BY w.platform, w.query_id"""
        ).fetchall()
    except Exception:
        print_exc()
        return []
    finally:
        if conn:
            conn.close()


def set_proxy_scan_state(platform, state, checked=0, total=0, working=0, error=None):
    import time as _time

    now = _time.time()
    conn = None
    try:
        conn = get_db_connection()
        started = now if state == "running" and checked == 0 else None
        finished = now if state in ("healthy", "error") else None
        conn.execute(
            """INSERT INTO proxy_scan_state
               (platform, state, started_at, finished_at, heartbeat_at,
                checked_count, total_count, working_count, last_error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(platform) DO UPDATE SET
                 state=excluded.state,
                 started_at=COALESCE(excluded.started_at, proxy_scan_state.started_at),
                 finished_at=excluded.finished_at,
                 heartbeat_at=excluded.heartbeat_at,
                 checked_count=excluded.checked_count,
                 total_count=excluded.total_count,
                 working_count=excluded.working_count,
                 last_error=excluded.last_error""",
            (platform, state, started, finished, now, checked, total, working,
             str(error)[:500] if error else None),
        )
        conn.commit()
    except Exception:
        print_exc()
    finally:
        if conn:
            conn.close()


def get_proxy_scan_states():
    conn = None
    try:
        conn = get_db_connection()
        return conn.execute(
            """SELECT platform, state, started_at, finished_at, heartbeat_at,
                      checked_count, total_count, working_count, last_error
               FROM proxy_scan_state ORDER BY platform"""
        ).fetchall()
    except Exception:
        print_exc()
        return []
    finally:
        if conn:
            conn.close()


def reset_stale_worker_states():
    """Mark workers left running by a previous process as interrupted."""
    import time as _time

    conn = None
    try:
        conn = get_db_connection()
        now = _time.time()
        conn.execute(
            """UPDATE query_worker_state
               SET state='error', finished_at=?, heartbeat_at=?,
                   last_error='Application restarted while this worker was running'
               WHERE state='running'""",
            (now, now),
        )
        conn.execute(
            """UPDATE proxy_scan_state
               SET state='error', finished_at=?, heartbeat_at=?,
                   last_error='Application restarted while this scan was running'
               WHERE state='running'""",
            (now, now),
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


def seed_proxy_pool(platform, proxy_values):
    """Add configured proxies without changing any learned state."""
    values = sorted({str(p).strip() for p in proxy_values if str(p).strip()})
    if not values:
        return
    conn = None
    try:
        conn = get_db_connection()
        conn.executemany(
            "INSERT OR IGNORE INTO proxy_state (platform, proxy) VALUES (?, ?)",
            [(platform, proxy) for proxy in values],
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


def replace_proxy_scan_results(platform, all_proxies, working_scan_proxies):
    """Atomically publish one complete manual scan for a platform."""
    import time as _time

    all_set = {str(p).strip() for p in all_proxies if str(p).strip()}
    valid = {str(p).strip() for p in working_scan_proxies if str(p).strip()}
    now = _time.time()
    conn = None
    try:
        conn = get_db_connection()
        conn.execute("BEGIN IMMEDIATE")
        previous = {
            row[0]: row[1:] for row in conn.execute(
                """SELECT proxy, working, query_blacklisted, scan_blacklisted,
                          working_blacklisted_until, last_success, last_failure,
                          last_scan FROM proxy_state WHERE platform=?""",
                (platform,),
            ).fetchall()
        }
        # A missing source entry is not evidence that a blocked proxy recovered.
        # Retain its history until it is actually tested again.
        retained = all_set | {
            proxy for proxy, state in previous.items()
            if state[1] or state[2] or state[3] > now
        }
        results = []
        for proxy in sorted(retained):
            working, query_blocked, scan_blocked, until, success, failure, last_scan = (
                previous.get(proxy, (0, 0, 0, 0, None, None, None))
            )
            if proxy in all_set:
                last_scan = now
                if proxy in valid:
                    query_blocked, scan_blocked, until = 0, 0, 0
                else:
                    working, scan_blocked = 0, 1
            results.append((platform, proxy, working, query_blocked, scan_blocked,
                            until, success, failure, last_scan))
        conn.execute("DELETE FROM proxy_state WHERE platform=?", (platform,))
        conn.executemany(
            """INSERT INTO proxy_state
               (platform, proxy, working, query_blacklisted, scan_blacklisted,
                working_blacklisted_until, last_success, last_failure, last_scan)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            results,
        )
        conn.commit()
    finally:
        if conn:
            conn.close()


def mark_proxy_result(platform, proxy, success):
    """Record a query result; failed former successes get a 60-minute cooldown.

    Return the blacklist category on failure. Retaining last_success means a
    formerly working proxy can cool down again if its retry also fails.
    """
    import time as _time

    if not proxy:
        return
    now = _time.time()
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            "INSERT OR IGNORE INTO proxy_state (platform, proxy) VALUES (?, ?)",
            (platform, proxy),
        )
        if success:
            # An already-in-flight success must not lift a cooldown or a scan
            # blacklist created by another worker. Eligibility is checked when
            # selecting proxies and when calculating visible counts/lists.
            conn.execute(
                """UPDATE proxy_state SET working=1, last_success=?
                   WHERE platform=? AND proxy=?""",
                (now, platform, proxy),
            )
        else:
            working, last_success, query_blocked, scan_blocked = conn.execute(
                """SELECT working, last_success, query_blacklisted, scan_blacklisted
                   FROM proxy_state WHERE platform=? AND proxy=?""",
                (platform, proxy),
            ).fetchone()
            temporary = (working or last_success is not None) and not (
                query_blocked or scan_blocked
            )
            conn.execute(
                """UPDATE proxy_state
                   SET working=0, query_blacklisted=?, last_failure=?,
                       working_blacklisted_until=?
                   WHERE platform=? AND proxy=?""",
                (0 if temporary else 1, now,
                 now + WORKING_PROXY_BLACKLIST_SECONDS if temporary else 0,
                 platform, proxy),
            )
        conn.commit()
        if not success:
            return "working" if temporary else "query"
    finally:
        if conn:
            conn.close()


def get_proxy_candidates(platform, working_only=False):
    import time as _time

    conn = None
    try:
        conn = get_db_connection()
        sql = (
            "SELECT proxy FROM proxy_state WHERE platform=? "
            "AND query_blacklisted=0 AND scan_blacklisted=0 "
            "AND working_blacklisted_until<=?"
        )
        if working_only:
            sql += " AND working=1"
        return [row[0] for row in conn.execute(sql, (platform, _time.time())).fetchall()]
    finally:
        if conn:
            conn.close()


def get_proxy_state_counts(platform):
    """Counts: total, working, query-blocked, scan-blocked, available, cooling down."""
    import time as _time

    now = _time.time()
    conn = None
    try:
        conn = get_db_connection()
        row = conn.execute(
            """SELECT COUNT(*),
                      COALESCE(SUM(CASE WHEN working=1 AND query_blacklisted=0
                                        AND scan_blacklisted=0
                                        AND working_blacklisted_until<=?
                                        THEN 1 ELSE 0 END), 0),
                      COALESCE(SUM(query_blacklisted), 0),
                      COALESCE(SUM(scan_blacklisted), 0),
                      COALESCE(SUM(CASE WHEN query_blacklisted=0
                                        AND scan_blacklisted=0
                                        AND working_blacklisted_until<=?
                                        THEN 1 ELSE 0 END), 0),
                      COALESCE(SUM(CASE WHEN working_blacklisted_until>?
                                        THEN 1 ELSE 0 END), 0)
               FROM proxy_state WHERE platform=?""",
            (now, now, now, platform),
        ).fetchone()
        return tuple(int(value or 0) for value in row)
    finally:
        if conn:
            conn.close()


def get_proxy_lists(platform):
    import time as _time

    conn = None
    try:
        conn = get_db_connection()
        rows = conn.execute(
            """SELECT proxy, working, query_blacklisted, scan_blacklisted,
                      working_blacklisted_until
               FROM proxy_state WHERE platform=? ORDER BY proxy""",
            (platform,),
        ).fetchall()
        now = _time.time()
        return {
            "all": [row[0] for row in rows],
            "working": [row[0] for row in rows
                        if row[1] and not row[2] and not row[3] and row[4] <= now],
            "query_blacklisted": [row[0] for row in rows if row[2]],
            "scan_blacklisted": [row[0] for row in rows if row[3]],
            "working_blacklisted": [row[0] for row in rows if row[4] > now],
            "blacklisted": [row[0] for row in rows if row[2] or row[3] or row[4] > now],
        }
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT is_command_bot FROM telegram_bots WHERE id=?", (bot_id,))
        row = cursor.fetchone()
        was_command = bool(row[0]) if row else False

        cursor.execute("DELETE FROM query_telegram_bots WHERE bot_id=?", (bot_id,))
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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


def claim_telegram_delivery(item_id, chat_id):
    """
    Atomically claim one item for one Telegram destination.

    Returns True only to the first caller. The claim is intentionally made
    before the network request: if Telegram times out after accepting a post,
    retrying would otherwise create the exact duplicate this guard prevents.
    """
    if item_id is None or chat_id is None:
        return True
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO telegram_deliveries (item, chat_id) VALUES (?, ?)",
            (str(item_id), str(chat_id)),
        )
        claimed = cursor.rowcount == 1
        conn.commit()
        return claimed
    except Exception:
        print_exc()
        # Fail closed: a database problem must not turn into a Telegram flood.
        return False
    finally:
        if conn:
            conn.close()


def add_to_allowlist(country):
    conn = None
    try:
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
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
        conn = get_db_connection()
        cursor = conn.cursor()
        if query:
            # Get the query_id for the given query
            cursor.execute("SELECT id FROM queries WHERE query=?", (query,))
            result = cursor.fetchone()
            if result:
                query_id = result[0]
                # Get items with the matching query_id
                cursor.execute(
                    "SELECT i.item, i.title, i.price, i.currency, i.timestamp, q.query, i.photo_url, q.query_name, i.url "
                    "FROM items i JOIN queries q ON i.query_id = q.id "
                    f"WHERE i.query_id=? AND {VISIBLE_ITEM_SQL} "
                    "ORDER BY i.timestamp DESC LIMIT ?",
                    (query_id, limit),
                )
            else:
                return []
        else:
            # Join with queries table to get the query text
            cursor.execute(
                "SELECT i.item, i.title, i.price, i.currency, i.timestamp, q.query, i.photo_url, q.query_name, i.url "
                "FROM items i JOIN queries q ON i.query_id = q.id "
                f"WHERE {VISIBLE_ITEM_SQL} ORDER BY i.timestamp DESC LIMIT ?",
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM items i JOIN queries q ON i.query_id = q.id "
            f"WHERE {VISIBLE_ITEM_SQL}"
        )
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
        conn = get_db_connection()
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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT i.item, i.title, i.price, i.currency, i.timestamp, q.query, i.photo_url, i.url "
            "FROM items i JOIN queries q ON i.query_id = q.id "
            f"WHERE {VISIBLE_ITEM_SQL} ORDER BY i.timestamp DESC LIMIT 1"
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
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get total items
        cursor.execute(
            "SELECT COUNT(*) FROM items i JOIN queries q ON i.query_id = q.id "
            f"WHERE {VISIBLE_ITEM_SQL}"
        )
        total_items = cursor.fetchone()[0]

        if total_items == 0:
            return 0

        # Get earliest and latest timestamps
        cursor.execute(
            "SELECT MIN(i.timestamp), MAX(i.timestamp) "
            "FROM items i JOIN queries q ON i.query_id = q.id "
            f"WHERE {VISIBLE_ITEM_SQL}"
        )
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
