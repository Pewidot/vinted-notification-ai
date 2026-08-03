"""
Short-lived, in-memory debug log per query.

Answers "why did this listing not show up?": what URL was requested, what came
back, and for every item which decision was taken (announced, already known,
too old, filtered by allowlist/banwords).

Design notes:

* Nothing is written to disk or to the database. Entries live in shared memory
  and are dropped after RETENTION_SECONDS.
* Scraper, item extractor and web UI run in separate processes, so plain module
  globals would not be visible across them. The state therefore lives in
  multiprocessing.Manager objects created once in the main process and handed
  to each child via init().
* Logging is off unless explicitly enabled for a query, and it switches itself
  off again after 10 minutes - so the normal run carries no overhead.
"""

import math
import time

RETENTION_SECONDS = 10 * 60      # entries older than this are dropped
DEFAULT_DURATION = 10 * 60       # how long recording stays on after enabling
MAX_ENTRIES = 4000               # hard cap so a busy query cannot eat memory

# Set by init(); without it every call is a no-op (e.g. when a module is used
# standalone or in tests).
_enabled_until = None   # {query_id: epoch}
_entries = None         # [ {ts, query_id, event, message, ...}, ... ]


def init(shared):
    """Attach this process to the shared state created in the main process."""
    global _enabled_until, _entries
    if not shared:
        return
    _enabled_until = shared.get("until")
    _entries = shared.get("entries")


def create_shared(manager):
    """Create the shared containers (call once, in the main process)."""
    return {"until": manager.dict(), "entries": manager.list()}


def enable(query_id, seconds=DEFAULT_DURATION):
    """Start recording for a query. Returns the epoch it switches off again."""
    if _enabled_until is None:
        return 0
    until = time.time() + seconds
    _enabled_until[int(query_id)] = until
    log(query_id, "debug", f"Debug logging enabled for {seconds // 60} minutes")
    return until


def disable(query_id):
    """Stop recording for a query immediately."""
    if _enabled_until is None:
        return
    _enabled_until.pop(int(query_id), None)


def remaining(query_id):
    """Seconds of recording left for a query, rounded up (0 = off)."""
    if _enabled_until is None:
        return 0
    until = _enabled_until.get(int(query_id), 0)
    return max(0, math.ceil(until - time.time()))


def is_enabled(query_id):
    """True while the recording window is still open."""
    if _enabled_until is None:
        return False
    return _enabled_until.get(int(query_id), 0) > time.time()


def log(query_id, event, message, **fields):
    """
    Record one line for a query - no-op unless recording is on.

    Args:
        event (str): short category, e.g. "request", "result", "skip", "notify"
        message (str): human readable line
        **fields: extra values shown as details (item id, price, ...)
    """
    if _entries is None or not is_enabled(query_id):
        return
    entry = {
        "ts": time.time(),
        "query_id": int(query_id),
        "event": event,
        "message": str(message),
        "details": {k: ("" if v is None else str(v)) for k, v in fields.items()},
    }
    try:
        _entries.append(entry)
        # Cheap cap: only trim when clearly over, so the common path stays fast
        if len(_entries) > MAX_ENTRIES:
            del _entries[: len(_entries) - MAX_ENTRIES]
    except Exception:
        # Debug logging must never break scraping
        pass


def entries(query_id=None, search=None, limit=1000):
    """
    Read back the log, newest first.

    Args:
        query_id (int, optional): only this query
        search (str, optional): case-insensitive substring over message,
            event and all detail values
        limit (int): maximum number of entries returned
    """
    if _entries is None:
        return []
    cutoff = time.time() - RETENTION_SECONDS
    try:
        snapshot = list(_entries)
    except Exception:
        return []

    needle = (search or "").strip().lower()
    out = []
    for e in snapshot:
        if e.get("ts", 0) < cutoff:
            continue
        if query_id is not None and e.get("query_id") != int(query_id):
            continue
        if needle:
            haystack = " ".join(
                [e.get("message", ""), e.get("event", "")]
                + [f"{k} {v}" for k, v in (e.get("details") or {}).items()]
            ).lower()
            if needle not in haystack:
                continue
        out.append(e)
    out.reverse()
    return out[:limit]


def prune():
    """Drop entries older than the retention window (called by readers)."""
    if _entries is None:
        return
    cutoff = time.time() - RETENTION_SECONDS
    try:
        keep = [e for e in list(_entries) if e.get("ts", 0) >= cutoff]
        if len(keep) != len(_entries):
            _entries[:] = keep
    except Exception:
        pass


def active_queries():
    """{query_id: seconds_left} for every query currently recording."""
    if _enabled_until is None:
        return {}
    now = time.time()
    try:
        return {
            int(q): math.ceil(u - now)
            for q, u in dict(_enabled_until).items()
            if u > now
        }
    except Exception:
        return {}
