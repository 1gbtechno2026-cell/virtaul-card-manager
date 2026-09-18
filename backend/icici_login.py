"""
Automates the Mastercard Smart Data login form (User ID + Password), and
the OTP step that follows it.

All selectors here were confirmed by inspecting the live DOM:
  - User ID: #loginUserID, Password: #passwordControl, button: "Sign In"
  - OTP: six separate single-digit boxes, #otp-input-0 .. #otp-input-5,
    submitted with the same "Sign In" button text.
"""

import time
from pathlib import Path

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

USER_ID_SELECTOR = "#loginUserID"
PASSWORD_SELECTOR = "#passwordControl"
OTP_BOX_IDS = [f"otp-input-{i}" for i in range(6)]
DEBUG_DIR = Path(__file__).parent
LOGIN_START_URL = "https://smartdata.mastercard.co.in/"


def is_logged_in(page: Page) -> bool:
    """URL-only checks miss a common failure mode: Smart Data leaves you
    on the last .do form after the session dies, so the URL never contains
    'login'. Also treat the login form and OTP screen as logged-out."""
    url = (page.url or "").lower()
    if "smartdata.mastercard.co.in" not in url:
        return False
    if "login" in url or "one-time-passcode" in url:
        return False
    try:
        if page.locator(USER_ID_SELECTOR).count() > 0:
            return False
        if page.locator(f"#{OTP_BOX_IDS[0]}").count() > 0:
            return False
    except Exception:
        pass
    return True


def dismiss_cookie_banner(page: Page) -> None:
    """A OneTrust cookie-consent banner covers the login form on a fresh
    profile (no prior consent choice saved) and its dark-filter overlay
    intercepts every click on the fields underneath, hanging the login
    automation until Playwright's click retries time out. Try clicking
    the real button first; if it doesn't show up in time, rip the overlay
    out of the DOM so it can't block anything after."""
    for selector in ("#onetrust-accept-btn-handler", "#onetrust-reject-all-handler"):
        try:
            page.locator(selector).click(timeout=3000)
            return
        except PlaywrightTimeoutError:
            continue
    page.evaluate(
        "document.querySelectorAll('#onetrust-consent-sdk, .onetrust-pc-dark-filter')"
        ".forEach(el => el.remove())"
    )


def ensure_on_login_form(page: Page) -> None:
    """Wrong OTP often kicks Smart Data off the OTP screen back to a
    blank shell or the User ID form. Get us onto the real login fields
    before typing credentials. Do not use this while still on OTP --
    that would request a new OTP unnecessarily."""
    try:
        if page.locator(USER_ID_SELECTOR).count() > 0:
            return
    except Exception:
        pass
    page.goto(LOGIN_START_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector(USER_ID_SELECTOR, timeout=15000)


def fill_and_submit_login(page: Page, username: str, password: str) -> None:
    # This is an Angular form -- .fill() sets the value directly without
    # firing the real keystroke events Angular needs to mark the form
    # valid/touched, leaving the Sign In button stuck disabled (same root
    # cause as the country-code combobox earlier). Type it out for real.
    ensure_on_login_form(page)
    page.wait_for_selector(USER_ID_SELECTOR, timeout=10000)
    dismiss_cookie_banner(page)
    user_field = page.locator(USER_ID_SELECTOR)
    user_field.click()
    user_field.fill("")
    user_field.press_sequentially(username, delay=30)

    password_field = page.locator(PASSWORD_SELECTOR)
    password_field.click()
    password_field.fill("")
    password_field.press_sequentially(password, delay=30)

    # Move focus off the password field so Angular registers it as
    # "touched" before we check/click the button.
    page.keyboard.press("Tab")
    page.wait_for_timeout(200)

    page.get_by_role("button", name="Sign In", exact=True).click()


def find_invalid_login_banner(page: Page) -> bool:
    """True if Smart Data's "Invalid Login" rejection banner is showing
    (wrong User ID/password) -- distinct from 'unknown' so the frontend
    can tell you the bank rejected your credentials instead of a generic
    "could not confirm login" message."""
    try:
        return page.get_by_text("Invalid Login", exact=False).count() > 0
    except Exception:
        return False


def wait_for_post_login_state(page: Page, timeout_ms: int = 15000) -> str:
    """After clicking Sign In, the button visibly goes into a disabled
    "processing" state before the real navigation happens -- checking
    once, right away, can catch it mid-transition and wrongly conclude
    nothing happened. Poll instead of trusting a single fixed wait.
    Returns 'logged_in', 'otp_required', 'invalid_login', or 'unknown'."""
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        if is_logged_in(page):
            return "logged_in"
        if find_otp_field(page):
            return "otp_required"
        if find_invalid_login_banner(page):
            return "invalid_login"
        page.wait_for_timeout(400)
    return "unknown"


def find_otp_field(page: Page) -> bool:
    """True if the six-box OTP screen is currently showing. Retries once
    since a query right after navigation can hit a destroyed context."""
    for attempt in range(3):
        try:
            return page.locator(f"#{OTP_BOX_IDS[0]}").count() > 0
        except Exception:
            if attempt == 2:
                raise
            page.wait_for_timeout(500)


def logout(page: Page) -> bool:
    """Best-effort graceful logout -- clicks a logout control if one can
    be found, so the session is invalidated server-side (not just walked
    away from). The real button hasn't been confirmed against the live
    DOM yet (unlike every other selector here, which was found via
    diagnose.py against a live logged-in session first) -- this tries the
    most likely spots and gives up quietly rather than raising, since the
    caller always hard-closes the browser afterward regardless of whether
    this succeeds. Returns True if it looks like logout worked.

    TODO: run diagnose.py against a live logged-in session (search for
    "Logout" / "Sign Out" / the profile menu) and tighten these selectors
    once confirmed.
    """
    if not is_logged_in(page):
        return True

    header = page.frame_locator("iframe[src*='smart-data-header-ui']").last
    candidates = [
        lambda: header.get_by_text("Logout", exact=False).click(timeout=3000),
        lambda: header.get_by_text("Sign Out", exact=False).click(timeout=3000),
        lambda: page.get_by_text("Logout", exact=False).click(timeout=3000),
        lambda: page.get_by_text("Sign Out", exact=False).click(timeout=3000),
    ]
    for attempt in candidates:
        try:
            attempt()
            page.wait_for_timeout(500)
            if not is_logged_in(page):
                return True
        except Exception:
            continue

    return not is_logged_in(page)


def classify_post_otp_state(page: Page) -> str:
    """Where Smart Data landed after submitting an OTP.
    logged_in / otp_still_showing / login_required / unknown."""
    if is_logged_in(page):
        return "logged_in"
    if find_otp_field(page):
        return "otp_still_showing"
    try:
        if page.locator(USER_ID_SELECTOR).count() > 0:
            return "login_required"
    except Exception:
        pass
    url = (page.url or "").lower()
    if "login" in url and "one-time-passcode" not in url:
        return "login_required"
    return "unknown"


def submit_otp(page: Page, otp: str) -> dict:
    digits = otp.strip()
    if len(digits) != 6 or not digits.isdigit():
        return {"status": "error", "message": "OTP must be exactly 6 digits."}

    if not find_otp_field(page):
        # OTP screen already gone (previous wrong code kicked us back).
        # Caller should re-run User ID + password instead of failing.
        if classify_post_otp_state(page) == "login_required":
            return {
                "status": "login_required",
                "message": "OTP screen is gone. Sign in again to get a new OTP.",
            }
        debug_path = DEBUG_DIR / "debug_otp_not_found.png"
        page.screenshot(path=str(debug_path), full_page=True)
        return {
            "status": "login_required",
            "message": "OTP boxes not found -- will sign in again for a new OTP.",
            "debug": str(debug_path),
        }

    for box_id in OTP_BOX_IDS:
        page.fill(f"#{box_id}", "")
    for box_id, digit in zip(OTP_BOX_IDS, digits):
        page.fill(f"#{box_id}", digit)

    page.get_by_role("button", name="Sign In", exact=True).click()

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = classify_post_otp_state(page)
        if state == "logged_in":
            return {"status": "logged_in", "url": page.url}
        if state == "login_required":
            return {
                "status": "login_required",
                "message": "That OTP was rejected and the login screen is showing again.",
            }
        page.wait_for_timeout(400)

    state = classify_post_otp_state(page)
    if state == "logged_in":
        return {"status": "logged_in", "url": page.url}
    if state == "otp_still_showing":
        return {
            "status": "otp_invalid",
            "message": "That OTP was not accepted. Enter a new 6-digit code.",
        }
    if state == "login_required":
        return {
            "status": "login_required",
            "message": "That OTP was rejected and the login screen is showing again.",
        }

    debug_path = DEBUG_DIR / "debug_otp_result.png"
    page.screenshot(path=str(debug_path), full_page=True)
    return {
        "status": "login_required",
        "message": "Main screen did not appear after OTP. Will sign in again.",
        "url": page.url,
        "debug": str(debug_path),
    }
