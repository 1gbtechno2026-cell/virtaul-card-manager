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


def is_logged_in(page: Page) -> bool:
    url = page.url
    return "smartdata.mastercard.co.in" in url and "login" not in url


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


def fill_and_submit_login(page: Page, username: str, password: str) -> None:
    # This is an Angular form -- .fill() sets the value directly without
    # firing the real keystroke events Angular needs to mark the form
    # valid/touched, leaving the Sign In button stuck disabled (same root
    # cause as the country-code combobox earlier). Type it out for real.
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


def wait_for_post_login_state(page: Page, timeout_ms: int = 15000) -> str:
    """After clicking Sign In, the button visibly goes into a disabled
    "processing" state before the real navigation happens -- checking
    once, right away, can catch it mid-transition and wrongly conclude
    nothing happened. Poll instead of trusting a single fixed wait.
    Returns 'logged_in', 'otp_required', or 'unknown'."""
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        if is_logged_in(page):
            return "logged_in"
        if find_otp_field(page):
            return "otp_required"
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


def submit_otp(page: Page, otp: str) -> dict:
    digits = otp.strip()
    if len(digits) != 6 or not digits.isdigit():
        return {"status": "error", "message": "OTP must be exactly 6 digits."}

    if not find_otp_field(page):
        debug_path = DEBUG_DIR / "debug_otp_not_found.png"
        page.screenshot(path=str(debug_path), full_page=True)
        return {
            "status": "error",
            "message": "OTP boxes not found on the page.",
            "debug": str(debug_path),
        }

    for box_id, digit in zip(OTP_BOX_IDS, digits):
        page.fill(f"#{box_id}", digit)

    page.get_by_role("button", name="Sign In", exact=True).click()

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if is_logged_in(page):
            return {"status": "logged_in", "url": page.url}
        page.wait_for_timeout(400)

    debug_path = DEBUG_DIR / "debug_otp_result.png"
    page.screenshot(path=str(debug_path), full_page=True)
    return {"status": "still_pending", "url": page.url, "debug": str(debug_path)}
