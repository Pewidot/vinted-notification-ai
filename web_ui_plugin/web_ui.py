from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import db
import core
import proxies
import os
import re
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from logger import get_logger

# Get logger for this module
logger = get_logger(__name__)

# Create Flask app
app = Flask(
    __name__,
    template_folder=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "templates"
    ),
    static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"),
)

# Secret key for session management
app.secret_key = os.urandom(24)

# Set by web_ui_process(): lets manually triggered price runs notify like the
# scheduled ones. Stays None when the UI is started standalone.
_price_queue = None


@app.context_processor
def inject_version_info():
    # No update check: the version is shown for reference only, and the old
    # "update available" banner (plus its request to GitHub on every page load)
    # is gone.
    return {
        "github_url": db.get_parameter("github_url"),
        "current_version": db.get_parameter("version"),
    }


@app.context_processor
def inject_current_year():
    return {"current_year": datetime.now().year}


@app.route("/")
def index():
    # Get parameters
    params = db.get_all_parameters()

    # Get queries
    queries = db.get_queries()
    formatted_queries = []
    for i, query in enumerate(queries):
        parsed_query = urlparse(query[1])
        query_params = parse_qs(parsed_query.query)
        query_name = (
            query[3]
            if query[3] is not None
            else (
                query_params.get("search_text", [None])[0]
                or query_params.get("_nkw", [None])[0]
            )
        )

        # Get the last timestamp for this query
        try:
            last_timestamp = db.get_last_timestamp(query[0])
            last_found_item = datetime.fromtimestamp(last_timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except Exception as e:
            logger.debug(f"Error getting last timestamp for query {query[0]}: {e}")
            last_found_item = "Never"

        formatted_queries.append(
            {
                "id": i + 1,
                "query_id": query[0],
                "query": query[1],
                "display": query_name if query_name else query[1],
                "last_found_item": last_found_item,
            }
        )

    # Get recent items
    items = db.get_items(limit=10)
    formatted_items = []
    for item in items:
        formatted_items.append(
            {
                "title": item[1],
                "price": item[2],
                "currency": item[3],
                "timestamp": datetime.fromtimestamp(item[4]).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "query": item[5],
                "photo_url": item[6],
                "url": (
                    item[8]
                    if len(item) > 8 and item[8]
                    else f"{urlparse(item[5]).scheme}://{urlparse(item[5]).netloc}/items/{item[0]}"
                ),
            }
        )

    # Get process status from the database
    telegram_running = db.get_parameter("telegram_process_running") == "True"
    rss_running = db.get_parameter("rss_process_running") == "True"

    # Get statistics for the dashboard
    stats = {
        "total_items": db.get_total_items_count(),
        "total_queries": db.get_total_queries_count(),
        "items_per_day": db.get_items_per_day(),
    }

    # Get the last found item
    last_item = db.get_last_found_item()
    if last_item:
        stats["last_item"] = {
            "title": last_item[1],
            "price": last_item[2],
            "currency": last_item[3],
            "timestamp": datetime.fromtimestamp(last_item[4]).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "query": last_item[5],
            "photo_url": last_item[6],
            "url": (
                last_item[7]
                if len(last_item) > 7 and last_item[7]
                else f"{urlparse(last_item[5]).scheme}://{urlparse(last_item[5]).netloc}/items/{last_item[0]}"
            ),
        }
    else:
        stats["last_item"] = None

    # Get proxy statistics (aggregated + per platform)
    proxy_stats = proxies.get_all_proxy_stats()

    return render_template(
        "index.html",
        params=params,
        queries=formatted_queries,
        items=formatted_items,
        telegram_running=telegram_running,
        rss_running=rss_running,
        stats=stats,
        proxy_stats=proxy_stats,
    )


@app.route("/queries")
def queries():
    # Get queries
    all_queries = db.get_queries()
    formatted_queries = []
    for i, query in enumerate(all_queries):
        parsed_query = urlparse(query[1])
        query_params = parse_qs(parsed_query.query)
        query_name = (
            query[3]
            if query[3] is not None
            else (
                query_params.get("search_text", [None])[0]
                or query_params.get("_nkw", [None])[0]
            )
        )

        # Get the last timestamp for this query
        try:
            last_timestamp = db.get_last_timestamp(query[0])
            last_found_item = datetime.fromtimestamp(last_timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except Exception as e:
            logger.debug(f"Error getting last timestamp for query {query[0]}: {e}")
            last_found_item = "Never"

        linked_bots = db.get_query_bots(query[0])
        price_bots = db.get_query_price_bots(query[0])
        formatted_queries.append(
            {
                "id": i + 1,
                "query_id": query[0],
                "query": query[1],
                "display": query_name if query_name else query[1],
                "last_found_item": last_found_item,
                "telegram_enabled": True if query[5] is None else bool(query[5]),
                "platform": (query[6] if len(query) > 6 and query[6] else "vinted"),
                "active": (True if len(query) <= 7 or query[7] is None else bool(query[7])),
                "bot_ids": [b[0] for b in linked_bots],
                "bot_names": [b[1] for b in linked_bots],
                "track_prices": bool(query[8]) if len(query) > 8 and query[8] else False,
                "price_interval": (query[9] if len(query) > 9 and query[9] else 360),
                "price_depth": (query[10] if len(query) > 10 and query[10] else 1),
                "price_bot_ids": [b[0] for b in price_bots],
            }
        )

    all_bots = db.get_telegram_bots()
    bots = [
        {"id": b[0], "name": b[1], "enabled": bool(b[4]), "is_command_bot": bool(b[5])}
        for b in all_bots
    ]
    return render_template("queries.html", queries=formatted_queries, bots=bots)


@app.route("/add_query", methods=["POST"])
def add_query():
    query = request.form.get("query")
    query_name = request.form.get("query_name", "").strip()
    platform = request.form.get("platform", "vinted").strip().lower()
    if platform not in ("vinted", "kleinanzeigen", "ebay"):
        platform = "vinted"
    bot_ids = [int(b) for b in request.form.getlist("bot_ids") if b.isdigit()]
    price_bot_ids = [int(b) for b in request.form.getlist("price_bot_ids") if b.isdigit()]
    track_prices = "track_prices" in request.form
    price_interval = request.form.get("price_interval", 360, type=int) or 360
    price_depth = request.form.get("price_depth", 1, type=int) or 1
    if query:
        message, is_new_query = core.process_query(
            query,
            name=query_name if query_name != "" else None,
            platform=platform,
            bot_ids=bot_ids,
            track_prices=track_prices,
            price_interval=price_interval,
            price_depth=price_depth,
            price_bot_ids=price_bot_ids,
        )
        if is_new_query:
            flash(f"Query added: {query}", "success")
        else:
            flash(message, "warning")
    else:
        flash("No query provided", "error")

    return redirect(url_for("queries"))


@app.route("/remove_query/<int:query_id>", methods=["POST"])
def remove_query(query_id):
    message, success = core.process_remove_query(str(query_id))
    if success:
        flash("Query removed", "success")
    else:
        flash(message, "error")

    return redirect(url_for("queries"))


@app.route("/remove_query/all", methods=["POST"])
def remove_all_queries():
    message, success = core.process_remove_query("all")
    if success:
        flash("All queries removed", "success")
    else:
        flash(message, "error")

    return redirect(url_for("queries"))


@app.route("/update_query/<int:query_id>", methods=["POST"])
def update_query(query_id):
    query = request.form.get("query")
    query_name = request.form.get("query_name", "").strip()
    bot_ids = [int(b) for b in request.form.getlist("bot_ids") if b.isdigit()]
    price_bot_ids = [int(b) for b in request.form.getlist("price_bot_ids") if b.isdigit()]
    track_prices = "track_prices" in request.form
    price_interval = request.form.get("price_interval", 360, type=int) or 360
    price_depth = request.form.get("price_depth", 1, type=int) or 1

    if query:
        message, success = core.process_update_query(
            query_id,
            query,
            name=query_name if query_name != "" else None,
            bot_ids=bot_ids,
            track_prices=track_prices,
            price_interval=price_interval,
            price_depth=price_depth,
            price_bot_ids=price_bot_ids,
        )
        if success:
            flash("Query updated", "success")
        else:
            flash(message, "error")
    else:
        flash("No query provided", "error")

    return redirect(url_for("queries"))


@app.route("/update_prices/<int:query_id>", methods=["POST"])
def update_prices_now(query_id):
    """Run a price check for one query right away, ignoring its interval."""
    import threading

    if not db.get_query_active(query_id):
        flash("Query is paused - resume it first", "warning")
        return redirect(url_for("queries"))

    # Scraping can take a while (deep runs walk several pages), so do it in the
    # background and let the user keep using the UI.
    threading.Thread(
        target=core.collect_prices_for_query,
        args=(query_id, _price_queue),
        name=f"manual-price-{query_id}",
        daemon=True,
    ).start()

    flash("Price update started - reload the price history in a moment", "success")
    return redirect(request.referrer or url_for("queries"))


@app.route("/toggle_query_active/<int:query_id>", methods=["POST"])
def toggle_query_active(query_id):
    active = db.get_query_active(query_id)
    if db.set_query_active(query_id, not active):
        flash("Query paused (no longer scraped)" if active else "Query resumed", "success")
    else:
        flash("Failed to update query", "error")
    return redirect(url_for("queries"))


@app.route("/toggle_query_telegram/<int:query_id>", methods=["POST"])
def toggle_query_telegram(query_id):
    _, enabled = db.get_query_telegram_settings(query_id)
    if db.set_query_telegram_enabled(query_id, not enabled):
        if enabled:
            flash("Telegram notifications disabled for this query", "success")
        else:
            flash("Telegram notifications enabled for this query", "success")
    else:
        flash("Failed to update query", "error")

    return redirect(url_for("queries"))


@app.route("/items")
def items():
    query_id = request.args.get("query", "")  # Default to empty string instead of None
    limit = int(request.args.get("limit", 50))

    # Get items
    query_string = None
    if query_id:
        # Get the actual query string for the given ID
        queries = db.get_queries()
        for q in queries:
            if str(q[0]) == query_id:
                query_string = q[1]
                break

    items_data = db.get_items(limit=limit, query=query_string)
    formatted_items = []

    for item in items_data:
        formatted_items.append(
            {
                "title": item[1],
                "price": item[2],
                "currency": item[3],
                "timestamp": datetime.fromtimestamp(item[4]).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                # Ugly Ugly Ugly very Ugly eeew but I have to do a proper migration of existing db later else it'll break
                # Eeew bad me >:c
                "query": (
                    item[7] if item[7] else parse_qs(urlparse(item[5]).query).get("search_text", [None])[0]
                    if parse_qs(urlparse(item[5]).query).get("search_text", [None])[0]
                    else item[5]
                ),
                "url": (
                    item[8]
                    if len(item) > 8 and item[8]
                    else f"{urlparse(item[5]).scheme}://{urlparse(item[5]).netloc}/items/{item[0]}"
                ),
                "photo_url": item[6],
            }
        )

    # Get queries for filter dropdown
    queries = db.get_queries()
    formatted_queries = []
    selected_query_display = None
    for i, q in enumerate(queries):
        parsed_query = urlparse(q[1])
        query_params = parse_qs(parsed_query.query)
        query_name = (
            q[3] if q[3] is not None else (
                query_params.get("search_text", [None])[0]
                or query_params.get("_nkw", [None])[0]
            )
        )
        display_name = query_name if query_name else q[0]
        # Store display name for selected query
        if query_id == str(q[0]):
            selected_query_display = display_name
        formatted_queries.append(
            {"id": i + 1, "query_id": q[0], "query": q[1], "display": display_name}
        )

    return render_template(
        "items.html",
        items=formatted_items,
        queries=formatted_queries,
        selected_query=query_id,
        selected_query_display=selected_query_display,
        limit=limit,
    )


@app.route("/config")
def config():
    params = db.get_all_parameters()
    return render_template("config.html", params=params)


@app.route("/update_config", methods=["POST"])
def update_config():
    # Update Telegram parameters (bots are managed on the Telegram Bots page)
    telegram_enabled = "telegram_enabled" in request.form
    db.set_parameter("telegram_enabled", str(telegram_enabled))

    # Update RSS parameters
    rss_enabled = "rss_enabled" in request.form
    db.set_parameter("rss_enabled", str(rss_enabled))
    db.set_parameter("rss_port", request.form.get("rss_port", "8080"))
    db.set_parameter("rss_max_items", request.form.get("rss_max_items", "100"))

    # Update System parameters
    db.set_parameter("items_per_query", request.form.get("items_per_query", "20"))
    db.set_parameter(
        "query_refresh_delay", request.form.get("query_refresh_delay", "60")
    )
    db.set_parameter("banwords", request.form.get("banwords", ""))

    # Update Proxy parameters
    check_proxies = "check_proxies" in request.form
    db.set_parameter("check_proxies", str(check_proxies))
    db.set_parameter("proxy_test_timeout", request.form.get("proxy_test_timeout", "5"))
    db.set_parameter(
        "proxy_blacklist_duration", request.form.get("proxy_blacklist_duration", "60")
    )
    db.set_parameter("request_timeout", request.form.get("request_timeout", "10"))
    db.set_parameter("query_timeout", request.form.get("query_timeout", "15"))

    # Per-platform proxy lists (vinted, kleinanzeigen, ebay)
    for platform in proxies.PLATFORMS:
        db.set_parameter(
            f"proxy_list_{platform}", request.form.get(f"proxy_list_{platform}", "")
        )
        db.set_parameter(
            f"proxy_list_link_{platform}",
            request.form.get(f"proxy_list_link_{platform}", ""),
        )
        # Reset this platform's proxy cache so the change takes effect on next use
        db.set_parameter(f"last_proxy_check_time_{platform}", "1")

    # Update Advanced parameters
    db.set_parameter("message_template", request.form.get("message_template", ""))
    db.set_parameter("user_agents", request.form.get("user_agents", "[]"))
    db.set_parameter("default_headers", request.form.get("default_headers", "{}"))

    logger.info("Configuration updated, per-platform proxy caches reset")

    flash("Configuration updated", "success")
    return redirect(url_for("config"))


@app.route("/reset_proxies", methods=["POST"])
def reset_proxies():
    # Wipe all proxy data (pools, blacklists, counts) for every platform and
    # signal every process to reload. Then re-validate all platforms in parallel
    # in the background so the request returns immediately.
    proxies.reset_all_proxy_data()
    import threading

    threading.Thread(
        target=proxies.validate_all_platforms,
        kwargs={"parallel": True},
        name="proxy-reset-revalidate",
        daemon=True,
    ).start()
    flash(
        "All proxy data reset. Re-validating Vinted, Kleinanzeigen and eBay proxies in parallel...",
        "success",
    )
    return redirect(url_for("config"))


@app.route("/prices")
def prices():
    query_id = request.args.get("query", type=int)
    changed_only = request.args.get("changed") == "1"
    limit = request.args.get("limit", 100, type=int)

    rows = db.get_tracked_items(query_id=query_id, limit=limit, changed_only=changed_only)
    items = []
    for r in rows:
        (item, qid, title, url, photo_url, currency, first_price,
         last_price, first_seen, last_seen, observations, query_name, platform) = r
        try:
            change_pct = ((last_price - first_price) / first_price * 100) if first_price else 0
        except (TypeError, ZeroDivisionError):
            change_pct = 0
        history = db.get_price_history(item, qid)
        items.append({
            "item": item,
            "query_id": qid,
            "title": title or "(no title)",
            "url": url,
            "photo_url": photo_url,
            "currency": currency or "EUR",
            "first_price": first_price,
            "last_price": last_price,
            "change_pct": change_pct,
            "observations": observations,
            "query_name": query_name or f"Query {qid}",
            "platform": platform or "vinted",
            "last_seen": datetime.fromtimestamp(last_seen).strftime("%Y-%m-%d %H:%M")
            if last_seen else "-",
            "spark": [float(h[0]) for h in history],
        })

    # Queries that have tracking switched on, for the filter dropdown
    tracked_queries = []
    for q in db.get_queries():
        if len(q) > 8 and q[8]:
            parsed = parse_qs(urlparse(q[1]).query)
            name = q[3] or parsed.get("search_text", [None])[0] or parsed.get("_nkw", [None])[0] or q[1]
            tracked_queries.append({"id": q[0], "name": name, "platform": q[6] or "vinted"})

    return render_template(
        "prices.html",
        items=items,
        stats=db.get_price_stats(),
        tracked_queries=tracked_queries,
        selected_query=query_id,
        changed_only=changed_only,
    )


@app.route("/price_history/<item>")
def price_history(item):
    """Full price history of one listing (used by the detail view)."""
    query_id = request.args.get("query", type=int)
    history = db.get_price_history(item, query_id)
    return jsonify({
        "item": item,
        "points": [
            {"price": float(p), "currency": c,
             "timestamp": t, "date": datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")}
            for p, c, t in history
        ],
    })


@app.route("/telegram_bots")
def telegram_bots():
    bots = db.get_telegram_bots()
    formatted_bots = [
        {
            "id": b[0],
            "name": b[1] or "",
            "token": b[2] or "",
            "chat_id": b[3] or "",
            "enabled": bool(b[4]),
            "is_command_bot": bool(b[5]),
        }
        for b in bots
    ]
    return render_template("telegram_bots.html", bots=formatted_bots)


@app.route("/add_telegram_bot", methods=["POST"])
def add_telegram_bot():
    name = request.form.get("name", "").strip()
    token = request.form.get("token", "").strip()
    chat_id = request.form.get("chat_id", "").strip()
    enabled = "enabled" in request.form
    is_command_bot = "is_command_bot" in request.form

    if not name or not token or not chat_id:
        flash("Name, token and chat ID are required", "error")
        return redirect(url_for("telegram_bots"))

    if db.add_telegram_bot(name, token, chat_id, enabled, is_command_bot) is not None:
        flash(f"Bot '{name}' added", "success")
    else:
        flash("Failed to add bot", "error")
    return redirect(url_for("telegram_bots"))


@app.route("/update_telegram_bot/<int:bot_id>", methods=["POST"])
def update_telegram_bot(bot_id):
    name = request.form.get("name", "").strip()
    token = request.form.get("token", "").strip()
    chat_id = request.form.get("chat_id", "").strip()
    enabled = "enabled" in request.form
    is_command_bot = True if "is_command_bot" in request.form else None

    if not name or not token or not chat_id:
        flash("Name, token and chat ID are required", "error")
        return redirect(url_for("telegram_bots"))

    if db.update_telegram_bot(bot_id, name, token, chat_id, enabled, is_command_bot):
        flash(f"Bot '{name}' updated", "success")
    else:
        flash("Failed to update bot", "error")
    return redirect(url_for("telegram_bots"))


@app.route("/delete_telegram_bot/<int:bot_id>", methods=["POST"])
def delete_telegram_bot(bot_id):
    if db.delete_telegram_bot(bot_id):
        flash("Bot deleted", "success")
    else:
        flash("Failed to delete bot", "error")
    return redirect(url_for("telegram_bots"))


@app.route("/set_command_bot/<int:bot_id>", methods=["POST"])
def set_command_bot(bot_id):
    if db.set_command_bot(bot_id):
        flash("Command bot updated", "success")
    else:
        flash("Failed to set command bot", "error")
    return redirect(url_for("telegram_bots"))


@app.route("/control/<process_name>/<action>", methods=["POST"])
def control_process(process_name, action):
    if process_name not in ["telegram", "rss"]:
        return jsonify({"status": "error", "message": "Invalid process name"})

    if action == "start":
        if process_name == "telegram":
            # Check current status
            if db.get_parameter("telegram_process_running") == "True":
                return jsonify(
                    {"status": "warning", "message": "Telegram bot already running"}
                )

            # Check that at least one enabled bot has a token and chat id
            if not db.has_active_telegram_bot():
                return jsonify(
                    {
                        "status": "error",
                        "message": "Please add at least one Telegram bot (with token and chat ID) on the Telegram Bots page before starting the Telegram process",
                    }
                )

            # Update process status in the database
            # The manager process will detect this and start the process
            db.set_parameter("telegram_process_running", "True")
            logger.info("Telegram bot process start requested")
            return jsonify(
                {"status": "success", "message": "Telegram bot start requested"}
            )

        elif process_name == "rss":
            # Check current status
            if db.get_parameter("rss_process_running") == "True":
                return jsonify(
                    {"status": "warning", "message": "RSS feed already running"}
                )

            # Update process status in the database
            # The manager process will detect this and start the process
            db.set_parameter("rss_process_running", "True")
            logger.info("RSS feed process start requested")
            return jsonify({"status": "success", "message": "RSS feed start requested"})

    elif action == "stop":
        if process_name == "telegram":
            # Check current status
            if db.get_parameter("telegram_process_running") != "True":
                return jsonify(
                    {"status": "warning", "message": "Telegram bot not running"}
                )

            # Update process status in the database
            # The manager process will detect this and stop the process
            db.set_parameter("telegram_process_running", "False")
            logger.info("Telegram bot process stop requested")
            return jsonify(
                {"status": "success", "message": "Telegram bot stop requested"}
            )

        elif process_name == "rss":
            # Check current status
            if db.get_parameter("rss_process_running") != "True":
                return jsonify({"status": "warning", "message": "RSS feed not running"})

            # Update process status in the database
            # The manager process will detect this and stop the process
            db.set_parameter("rss_process_running", "False")
            logger.info("RSS feed process stop requested")
            return jsonify({"status": "success", "message": "RSS feed stop requested"})

    return jsonify({"status": "error", "message": "Invalid action"})


@app.route("/control/status", methods=["GET"])
def process_status():
    # Get process status from the database
    telegram_running = db.get_parameter("telegram_process_running") == "True"
    rss_running = db.get_parameter("rss_process_running") == "True"

    return jsonify({"telegram": telegram_running, "rss": rss_running})


@app.route("/allowlist")
def allowlist():
    countries = db.get_allowlist()
    if countries == 0:
        countries = []

    return render_template("allowlist.html", countries=countries)


@app.route("/add_country", methods=["POST"])
def add_country():
    country = request.form.get("country", "").strip()
    if country:
        message, country_list = core.process_add_country(country)
        flash(message, "success" if "added" in message else "warning")
    else:
        flash("No country provided", "error")

    return redirect(url_for("allowlist"))


@app.route("/remove_country/<country>", methods=["POST"])
def remove_country(country):
    message, country_list = core.process_remove_country(country)
    flash(message, "success")

    return redirect(url_for("allowlist"))


@app.route("/clear_allowlist", methods=["POST"])
def clear_allowlist():
    db.clear_allowlist()
    flash("Allowlist cleared", "success")

    return redirect(url_for("allowlist"))


@app.route("/logs")
def logs():
    return render_template("logs.html")


@app.route("/api/logs")
def api_logs():
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 100))
    level_filter = request.args.get("level", "all")

    log_file_path = os.path.join("logs", "vinted.log")

    if not os.path.exists(log_file_path):
        return jsonify({"logs": [], "total": 0})

    # Parse log file
    log_entries = []
    total_matching_entries = 0

    try:
        with open(log_file_path, "r", encoding="utf-8") as file:
            # Read all lines from the file
            all_lines = file.readlines()

            # Process lines in reverse order (newest first)
            all_lines.reverse()

            # Regular expression to parse log lines
            # Format: 2023-09-15 12:34:56,789 - module_name - LEVEL - Message
            log_pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - ([^-]+) - ([A-Z]+) - (.+)"

            current_entry = 0

            for line in all_lines:
                match = re.match(log_pattern, line.strip())
                if match:
                    timestamp, module, level, message = match.groups()

                    # Apply level filter if specified
                    if level_filter != "all" and level != level_filter:
                        continue

                    total_matching_entries += 1

                    # Skip entries before offset
                    if total_matching_entries <= offset:
                        continue

                    # Add entry if within limit
                    if current_entry < limit:
                        log_entries.append(
                            {
                                "timestamp": timestamp,
                                "module": module.strip(),
                                "level": level,
                                "message": message,
                            }
                        )
                        current_entry += 1

                    # Stop if we've reached the limit
                    if current_entry >= limit:
                        break
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
        return jsonify({"logs": [], "total": 0, "error": str(e)})

    return jsonify({"logs": log_entries, "total": total_matching_entries})


def web_ui_process(price_queue=None):
    """
    Args:
        price_queue (Queue, optional): shared queue so a manually triggered
            price update can still send Telegram notifications, just like the
            scheduled runs do.
    """
    global _price_queue
    _price_queue = price_queue
    logger.info("Web UI process started")
    try:
        app.run(host="0.0.0.0", port=8000, debug=False)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Web UI process stopped")
    except Exception as e:
        logger.error(f"Error in web UI process: {e}", exc_info=True)
