"""
Flask API for the Virtual Card Creator. Runs at http://localhost:5000.

In local dev, this is the backend only -- the React app runs separately
via `npm run dev` (http://localhost:5173+) and talks to this API across
origins (see frontend/.env.development and CORS below).

In production, this ALSO serves the built React app (frontend/dist/) as
static files -- run `npm run build` first, then this one process serves
both the UI and the API on the same origin. See the "Deploying to a VPS"
section in the README.

Usage:
    python app.py
"""

import functools
import io
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory
from openpyxl import Workbook
from playwright.sync_api import sync_playwright

from automate import CONFIG_PATH, DEBUG_PORT, run_batch
from db import (
    create_batch,
    finish_batch,
    get_all_batches,
    get_all_cards,
    is_configured as mongo_is_configured,
    is_connected as mongo_is_connected,
)
from icici_login import (
    fill_and_submit_login,
    is_logged_in,
    logout,
    submit_otp,
    wait_for_post_login_state,
)

app = Flask(__name__)

BASE_DIR = Path(__file__).parent
AUTH_PATH = BASE_DIR / "auth.json"
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
CHROME_PID_PATH = BASE_DIR / "chrome.pid"
browser_process: subprocess.Popen | None = None
browser_launch_lock = threading.Lock()

valid_tokens_lock = threading.Lock()
valid_tokens: set[str] = set()


def load_auth() -> dict:
    if AUTH_PATH.exists():
        with open(AUTH_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"username": "admin", "password": "admin123"}


def require_auth(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        with valid_tokens_lock:
            if token not in valid_tokens:
                return jsonify({"error": "Not authenticated"}), 401
        return view(*args, **kwargs)

    return wrapped

FIELDS = [
    ("description", "Description"),
    ("min_transaction_amount", "Minimum Transaction Amount"),
    ("max_transaction_amount", "Maximum Transaction Amount"),
    ("start_date", "Start Date (DD/MM/YYYY)"),
    ("end_date", "End Date (DD/MM/YYYY)"),
    ("cumulative_limit", "Cumulative Limit"),
    ("max_transactions", "Maximum Number of Transactions"),
    ("first_name", "First Name"),
    ("last_name", "Last Name"),
    ("user_email", "User Email"),
    ("user_country_code", "User Country Code (e.g. India +91)"),
    ("user_mobile_number", "User Mobile Number"),
]

state_lock = threading.Lock()
state = {
    "running": False,
    "log": [],
    "results": [],
    "cancel_requested": False,
    "batch_id": None,
    "requested_count": 0,
}


def load_saved_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_form_defaults() -> dict:
    saved = load_saved_config()
    today = datetime.now().strftime("%d/%m/%Y")
    defaults = {"start_date": today, "end_date": saved.get("end_date", "21/07/2028")}
    values = {key: saved.get(key, defaults.get(key, "")) for key, _ in FIELDS}
    return values


def check_browser_status() -> dict:
    """Reports whether launch_browser.py's Chrome is reachable, and if so
    whether it looks logged in (on the smartdata domain, not the login
    page)."""
    try:
        urllib.request.urlopen(f"http://localhost:{DEBUG_PORT}/json/version", timeout=1.5)
    except Exception:
        return {"reachable": False, "logged_in": False, "url": ""}

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}", timeout=3000)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else None
            url = page.url if page else ""
            logged_in = (
                "smartdata.mastercard.co.in" in url
                and "login" not in url
                and "one-time-passcode" not in url
            )
            return {"reachable": True, "logged_in": logged_in, "url": url}
    except Exception:
        return {"reachable": True, "logged_in": False, "url": ""}


def get_connected_page():
    """Attaches to the running browser (launch_browser.py) and returns
    (playwright, page). Caller must NOT close the playwright/browser --
    it's shared/long-lived."""
    p = sync_playwright().start()
    browser = p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}", timeout=3000)
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()
    return p, page


def close_browser_session() -> None:
    """Called after every batch (success or failure) so no live bank
    session is ever left running unattended. Best-effort graceful logout
    first, then a hard kill of the actual Chrome process (see chrome.pid,
    written by launch_browser.py) regardless of whether logout worked --
    that's the real guarantee here, logout is just the polite version of
    it. Resets browser_process so ensure_browser_launched() spawns a
    fresh browser next time it's needed."""
    status = check_browser_status()
    if status["reachable"] and status["logged_in"]:
        try:
            p, page = get_connected_page()
            try:
                logout(page)
            finally:
                p.stop()
        except Exception as e:
            append_log(f"Could not log out cleanly: {e}")

    if CHROME_PID_PATH.exists():
        try:
            os.kill(int(CHROME_PID_PATH.read_text().strip()), signal.SIGTERM)
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        CHROME_PID_PATH.unlink(missing_ok=True)

    global browser_process
    with browser_launch_lock:
        if browser_process is not None:
            # Reap it -- Chrome exiting (above) makes launch_browser.py's
            # own proc.wait() return and the wrapper process exit shortly
            # after, but nothing has waited on *this* Popen handle yet.
            # Skipping that leaves a zombie process entry behind.
            try:
                browser_process.wait(timeout=5)
            except Exception:
                pass
        browser_process = None


@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        return "", 204


@app.after_request
def add_cors_headers(response):
    # Allows the React dev server (a different port, e.g. 5173) to call
    # this API during local development.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


def append_log(message: str) -> None:
    with state_lock:
        state["log"].append(message)


def is_cancel_requested() -> bool:
    with state_lock:
        return state["cancel_requested"]


def worker(cfg: dict, count: int, batch_id: str) -> None:
    status = "completed"
    error = None
    try:
        results = run_batch(cfg, count, batch_id, log=append_log, should_cancel=is_cancel_requested)
        with state_lock:
            state["results"].extend(results)
        if len(results) < count:
            status = "cancelled"
            append_log(f"Cancelled. Created {len(results)}/{count} card(s). Saved to the database.")
        else:
            append_log(f"Done. Created {len(results)}/{count} card(s). Saved to the database.")
    except Exception as e:
        status = "failed"
        error = str(e)
        append_log(f"Failed: {e}")
    finally:
        # Runs on every outcome -- success, failure, or cancellation --
        # so no live bank session is ever left open unattended. Logged
        # and completed before the "running" flag flips so the frontend's
        # final /status poll (which stops once running=False) still shows
        # these lines.
        append_log("Logging out and closing the browser...")
        try:
            close_browser_session()
            append_log("Browser closed. Log in again to create more cards.")
        except Exception as e:
            append_log(f"Warning: could not fully close the browser session: {e}")
        try:
            finish_batch(batch_id, status=status, error=error)
        except Exception as e:
            append_log(f"Warning: could not finalize batch record: {e}")
        with state_lock:
            state["running"] = False
            state["cancel_requested"] = False


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    auth = load_auth()
    if data.get("username") == auth["username"] and data.get("password") == auth["password"]:
        token = secrets.token_hex(16)
        with valid_tokens_lock:
            valid_tokens.add(token)
        return jsonify({"token": token})
    return jsonify({"error": "Invalid username or password."}), 401


@app.route("/api/config")
@require_auth
def api_config():
    return jsonify({"fields": FIELDS, "values": get_form_defaults()})


@app.route("/browser-status")
@require_auth
def browser_status():
    return jsonify(check_browser_status())


def ensure_browser_launched() -> dict:
    """Starts launch_browser.py if it's not already reachable. check-then-
    spawn must be atomic -- React StrictMode (and just plain double-clicks)
    can fire this twice almost simultaneously, and two Chrome processes
    racing to start against the same profile dir break the debug port for
    both."""
    global browser_process

    with browser_launch_lock:
        current = check_browser_status()
        if current["reachable"]:
            return {"status": "already_running", **current}

        if browser_process is None or browser_process.poll() is not None:
            browser_process = subprocess.Popen(
                [sys.executable, str(BASE_DIR / "launch_browser.py")],
                cwd=str(BASE_DIR),
            )

    return {"status": "launching"}


@app.route("/launch-browser", methods=["POST"])
@require_auth
def launch_browser_endpoint():
    return jsonify(ensure_browser_launched())


@app.route("/icici-login", methods=["POST"])
@require_auth
def icici_login_endpoint():
    data = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"error": "Username and password are required."}), 400

    status = check_browser_status()
    if not status["reachable"]:
        return jsonify({"error": "Browser is not running. Launch it first."}), 409

    p, page = get_connected_page()
    try:
        if is_logged_in(page):
            return jsonify({"status": "logged_in", "url": page.url})

        fill_and_submit_login(page, username, password)
        result = wait_for_post_login_state(page)

        if result == "logged_in":
            return jsonify({"status": "logged_in", "url": page.url})
        if result == "otp_required":
            return jsonify({"status": "otp_required"})
        if result == "invalid_login":
            return jsonify(
                {"error": "Invalid User ID or password -- the bank rejected these credentials."}
            ), 401

        debug_path = BASE_DIR / "debug_login_result.png"
        page.screenshot(path=str(debug_path), full_page=True)
        return jsonify(
            {"status": "unknown", "url": page.url, "debug": str(debug_path)}
        )
    except Exception as e:
        return jsonify({"error": f"Login automation failed: {e}"}), 500
    finally:
        p.stop()


@app.route("/icici-otp", methods=["POST"])
@require_auth
def icici_otp_endpoint():
    data = request.get_json(force=True)
    otp = (data.get("otp") or "").strip()
    if not otp:
        return jsonify({"error": "OTP is required."}), 400

    status = check_browser_status()
    if not status["reachable"]:
        return jsonify({"error": "Browser is not running."}), 409

    p, page = get_connected_page()
    try:
        result = submit_otp(page, otp)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"OTP submission failed: {e}"}), 500
    finally:
        p.stop()


@app.route("/create", methods=["POST"])
@require_auth
def create():
    with state_lock:
        if state["running"]:
            return jsonify({"error": "Already running, please wait."}), 409

    if not mongo_is_connected():
        return jsonify(
            {
                "error": "Database is not connected -- card creation is disabled until "
                "MongoDB is reachable (check MONGODB_URI in backend/.env)."
            }
        ), 503

    data = request.get_json(force=True)
    cfg = {key: (data.get(key) or "").strip() for key, _ in FIELDS}
    missing = [label for key, label in FIELDS if not cfg[key]]
    if missing:
        return jsonify({"error": "Missing fields: " + ", ".join(missing)}), 400

    try:
        count = int(data.get("count", 0))
        if count < 1:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Number of cards must be a positive integer."}), 400

    # Persist for next time (excludes start_date -- that should always
    # default to "today" on next launch, not whatever was last used).
    to_save = {k: v for k, v in cfg.items() if k != "start_date"}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(to_save, f, indent=2)

    cfg["created_by"] = cfg["description"]

    batch_id = create_batch(
        description=cfg["description"], created_by=cfg["created_by"], requested_count=count
    )

    with state_lock:
        state["running"] = True
        state["log"] = []
        state["results"] = []
        state["batch_id"] = batch_id
        state["requested_count"] = count

    threading.Thread(target=worker, args=(cfg, count, batch_id), daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/cancel", methods=["POST"])
@require_auth
def cancel():
    with state_lock:
        if not state["running"]:
            return jsonify({"status": "not_running"})
        state["cancel_requested"] = True
    return jsonify({"status": "cancelling"})


def _card_filters_from_request():
    return {
        "date_from": request.args.get("date_from") or None,
        "date_to": request.args.get("date_to") or None,
        "search": request.args.get("search") or None,
        "batch_id": request.args.get("batch_id") or None,
    }


@app.route("/api/cards")
@require_auth
def api_cards():
    if not mongo_is_configured():
        return jsonify({"error": "MongoDB is not configured (set MONGODB_URI in backend/.env)."}), 409
    return jsonify({"cards": get_all_cards(**_card_filters_from_request())})


@app.route("/api/batches")
@require_auth
def api_batches():
    if not mongo_is_configured():
        return jsonify({"error": "MongoDB is not configured (set MONGODB_URI in backend/.env)."}), 409
    return jsonify({"batches": get_all_batches()})


@app.route("/api/cards/download")
@require_auth
def api_cards_download():
    if not mongo_is_configured():
        return jsonify({"error": "MongoDB is not configured (set MONGODB_URI in backend/.env)."}), 409

    cards = get_all_cards(**_card_filters_from_request())

    wb = Workbook()
    ws = wb.active
    ws.title = "Virtual Cards"
    headers = [
        "Created At", "Created By", "Card Alias", "Virtual Card Number",
        "Card Amount", "Expiry Date", "CVC", "Billing Name", "Description",
    ]
    ws.append(headers)
    for card in cards:
        ws.append(
            [
                card.get("created_at", ""),
                card.get("created_by", ""),
                card.get("card_alias", ""),
                card.get("card_number", ""),
                card.get("card_amount", ""),
                card.get("expiry", ""),
                card.get("cvc", ""),
                card.get("billing_name", ""),
                card.get("description", ""),
            ]
        )

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"cards_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/status")
@require_auth
def status():
    with state_lock:
        return jsonify(
            {
                "running": state["running"],
                "log": state["log"],
                "results": state["results"],
                "batch_id": state["batch_id"],
                "requested_count": state["requested_count"],
            }
        )


# Serves the built React app (production only -- run `npm run build` in
# frontend/ first). Placed last so it never shadows the API routes above:
# Werkzeug always prefers a matching static route over a <path:...>
# catch-all, regardless of registration order.
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if not FRONTEND_DIST.exists():
        return jsonify(
            {
                "error": "Frontend not built. Run 'npm run build' in frontend/, "
                "or use 'npm run dev' separately for local development."
            }
        ), 404

    target = FRONTEND_DIST / path
    if path and target.is_file():
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, "index.html")


# Runs once whether started via `python app.py` or imported by a WSGI
# server (gunicorn) -- either way, the browser should already be starting
# up by the time the first request arrives.
ensure_browser_launched()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
