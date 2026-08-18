"""
Creates one or more virtual cards on Mastercard Smart Data and saves each
card's details to MongoDB (backend/db.py).

REQUIRES launch_browser.py to already be running (log in there first --
this script attaches to that same browser/session instead of starting a
new one, so you don't need to log in again for every test run).

Usage:
    python automate.py [count]
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from db import save_card
from icici_login import is_logged_in

MAX_FILL_RETRIES = 2
MAX_CARD_ATTEMPTS = 3
NAV_CLICK_TIMEOUT = 20000
HEADER_IFRAME_SELECTOR = "iframe[src*='smart-data-header-ui']"
# Direct GWT form URL -- NOT the SPA root (that drops the session).
CREATE_FORM_URL = (
    "https://smartdata.mastercard.co.in/sdpc/purchaserequest/"
    "createPurchaseRequestRender.do"
)

CONFIG_PATH = Path(__file__).parent / "config.json"
DEBUG_PORT = 9222
START_URL = "https://smartdata.mastercard.co.in/"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


# Ids confirmed by inspecting the live DOM (diagnose_fields.py / diagnose_inputs.py).
FIELD_IDS = {
    "description": "#description",
    "min_transaction_amount": "#minimum-transaction-amount",
    "max_transaction_amount": "#maximum-transaction-amount",
    "start_date": "#start-date",
    "end_date": "#end-date",
    "cumulative_limit": "#cumulativeColumnIdVCW",
    "max_transactions": "#maximumNumberOfTransactionIdVCW",
    "first_name": "#userDetailsFirstNameTextBox",
    "last_name": "#userDetailsLastNameTextBox",
    "user_email": "#userDetailsEmailAddressTextBox",
    "user_mobile_number": "#userDetailsPhoneNumberTextBox",
}


def find_country_code_field_id(page) -> str:
    """The Country Code combobox's id (e.g. gwt-uid-119) is auto-generated
    by a counter that climbs across the whole session, so it changes
    between navigations. Find it fresh by proximity to the stable
    'user-mobile-country-code-label' label id."""
    field_id = page.main_frame.evaluate(
        """
        () => {
            const label = document.getElementById('user-mobile-country-code-label');
            if (!label) return null;
            const labelRect = label.getBoundingClientRect();
            const candidates = Array.from(document.querySelectorAll("input[role='combobox']"));
            let best = null, bestDist = Infinity;
            for (const el of candidates) {
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                const dist = Math.abs(r.y - labelRect.y);
                if (dist < bestDist) { bestDist = dist; best = el; }
            }
            return best ? best.id : null;
        }
        """
    )
    if not field_id:
        raise RuntimeError("Could not locate the Country Code combobox on the page")
    return field_id


def dump_page_frames(page, log=print) -> None:
    """Log every frame URL plus raw <iframe> srcs so a nav timeout is
    diagnosable without the screenshot (header missing vs still loading
    vs session sent us somewhere else)."""
    log(f"  Current URL: {page.url}")
    log(f"  Playwright frame count: {len(page.frames)}")
    for i, frame in enumerate(page.frames):
        log(f"    frame[{i}] name={frame.name!r} url={frame.url}")
    try:
        iframe_count = page.locator(HEADER_IFRAME_SELECTOR).count()
        log(f"  Header iframe matches: {iframe_count}")
        srcs = page.locator("iframe").evaluate_all(
            "els => els.map(e => e.getAttribute('src') || e.id || e.name || '')"
        )
        log(f"  <iframe> srcs: {srcs}")
    except Exception as e:
        log(f"  Could not list <iframe> elements: {e}")


def dismiss_session_dialogs(page) -> None:
    """Bank session-warning modals sit on top of the header and make
    Payment Control unclickable. Only click clearly session-related
    buttons -- a generic OK could submit the card form. count() first so
    the happy path doesn't wait 800ms per name."""
    names = (
        "Stay Logged In",
        "Continue Session",
        "Extend Session",
        "Keep me signed in",
    )
    for name in names:
        loc = page.get_by_role("button", name=name, exact=False)
        try:
            if loc.count() == 0:
                continue
            loc.first.click(timeout=800)
            return
        except Exception:
            continue
    try:
        header = page.frame_locator(HEADER_IFRAME_SELECTOR).last
        loc = header.get_by_role("button", name="Continue Session", exact=False)
        if loc.count() > 0:
            loc.first.click(timeout=800)
    except Exception:
        pass


def header_iframe_present(page) -> bool:
    try:
        return page.locator(HEADER_IFRAME_SELECTOR).count() > 0
    except Exception:
        return False


def is_on_create_form_page(page) -> bool:
    return "createPurchaseRequestRender.do" in (page.url or "")


def wait_for_header_iframe(page, timeout_ms: int = 15000) -> bool:
    """True if a header iframe attaches. Use .last so leftover iframes
    from earlier navigations don't make the locator wait for uniqueness
    (Playwright frame_locator is strict -- 2+ matches look like a timeout)."""
    try:
        page.locator(HEADER_IFRAME_SELECTOR).last.wait_for(
            state="attached", timeout=timeout_ms
        )
        return True
    except PlaywrightTimeoutError:
        return False


def click_text_anywhere(page, text: str, timeout_ms: int = 8000) -> None:
    """Click exact text in the newest header iframe, then any frame, then
    the main page. Raises PlaywrightTimeoutError if nothing matched."""
    if page.locator(HEADER_IFRAME_SELECTOR).count() > 0:
        header = page.frame_locator(HEADER_IFRAME_SELECTOR).last
        try:
            header.get_by_text(text, exact=True).click(timeout=timeout_ms)
            return
        except PlaywrightTimeoutError:
            pass

    for frame in page.frames:
        try:
            loc = frame.get_by_text(text, exact=True)
            if loc.count() == 0:
                continue
            loc.first.click(timeout=min(timeout_ms, 5000))
            return
        except Exception:
            continue

    loc = page.get_by_text(text, exact=True)
    loc.first.click(timeout=timeout_ms)


def open_create_form_via_header_menu(page) -> None:
    """The real nav bar lives inside the header iframe (the same labels
    in the main page are a zero-size legacy leftover). .last = newest
    iframe after many card navigations."""
    header = page.frame_locator(HEADER_IFRAME_SELECTOR).last
    header.get_by_text("Payment Control", exact=True).click(timeout=NAV_CLICK_TIMEOUT)
    page.wait_for_timeout(500)
    header.get_by_text("Purchase Requests", exact=True).click(timeout=NAV_CLICK_TIMEOUT)
    page.wait_for_timeout(500)
    try:
        # This click navigates the *parent* page away from the iframe
        # that initiated it, which can hang the click call itself even
        # though the navigation succeeds -- confirmed by watching the URL
        # change on a "failed" run. Safe to ignore.
        header.get_by_text("Create Single Request", exact=True).click(
            timeout=NAV_CLICK_TIMEOUT
        )
    except PlaywrightTimeoutError:
        pass


def open_create_form_via_any_frame(page) -> None:
    click_text_anywhere(page, "Payment Control", timeout_ms=NAV_CLICK_TIMEOUT)
    page.wait_for_timeout(500)
    click_text_anywhere(page, "Purchase Requests", timeout_ms=NAV_CLICK_TIMEOUT)
    page.wait_for_timeout(500)
    try:
        click_text_anywhere(page, "Create Single Request", timeout_ms=NAV_CLICK_TIMEOUT)
    except PlaywrightTimeoutError:
        pass


def wait_for_fresh_form(page, timeout_ms: int = 15000) -> None:
    """A leftover confirmation from the previous card still has
    #description. Filling that screen again would resubmit the same
    request and re-read the same card number -- wait until confirmation
    is gone."""
    page.wait_for_selector(FIELD_IDS["description"], timeout=timeout_ms)
    card_number = page.locator("#cardNumberLabel")
    try:
        if card_number.count() > 0:
            card_number.wait_for(state="hidden", timeout=min(8000, timeout_ms))
    except PlaywrightTimeoutError:
        raise PlaywrightTimeoutError(
            "Create form is showing but the previous card's confirmation "
            "is still visible -- not a fresh form"
        )


def raise_if_logged_out() -> None:
    raise RuntimeError("Session expired mid-batch -- logged out of Smart Data.")


def open_create_form_via_direct_url(page, log=print) -> None:
    """The GWT create page has no Angular header -- only a dummy
    iframe (src javascript:''). Reloading this URL (not the SPA root)
    is how we get a fresh form after a confirmation, without dropping
    the session."""
    log("  Opening a fresh create form via direct URL")
    page.goto(CREATE_FORM_URL, wait_until="domcontentloaded", timeout=30000)
    if not is_logged_in(page):
        dump_page_frames(page, log)
        raise_if_logged_out()
    wait_for_fresh_form(page, timeout_ms=20000)


def open_create_form(page, log=print) -> None:
    """Get a fresh Create Single Request form. Once we are on the GWT
    create/confirmation page the header nav is gone, so skip Payment
    Control entirely and reload the form URL. Header-menu is only used
    from the SPA shell (first card). Do NOT goto() the SPA root -- that
    drops the session."""
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(300)
    dismiss_session_dialogs(page)

    if not is_logged_in(page):
        dump_page_frames(page, log)
        raise_if_logged_out()

    # After card 1 we live on createPurchaseRequestRender.do. That page
    # never contains smart-data-header-ui -- only a dummy javascript:''
    # iframe -- so Payment Control always times out. Reload the form URL
    # instead (safe even if a leftover confirmation is still showing).
    if is_on_create_form_page(page) and not header_iframe_present(page):
        open_create_form_via_direct_url(page, log)
        return

    iframe_found = wait_for_header_iframe(page, timeout_ms=8000)
    if iframe_found:
        try:
            open_create_form_via_header_menu(page)
            wait_for_fresh_form(page)
            return
        except PlaywrightTimeoutError:
            log("  Header menu path timed out -- dumping frames, trying fallbacks")
            dump_page_frames(page, log)
    else:
        log("  Header iframe not attached -- dumping frames and trying fallbacks")
        dump_page_frames(page, log)

    if not is_logged_in(page):
        raise_if_logged_out()

    if header_iframe_present(page):
        try:
            log("  Trying Payment Control / Purchase Requests in any frame")
            open_create_form_via_any_frame(page)
            wait_for_fresh_form(page)
            return
        except PlaywrightTimeoutError:
            log("  In-page menu fallback timed out")

    if not is_logged_in(page):
        raise_if_logged_out()

    open_create_form_via_direct_url(page, log)


def navigate_and_fill_form(page, cfg: dict, log=print) -> None:
    """Everything up to (not including) the Submit click. Nothing here
    has touched Mastercard's servers in a way that creates a card, so
    it's safe for create_one_card() to retry this on a timeout."""
    open_create_form(page, log=log)

    page.fill(FIELD_IDS["description"], cfg["description"])
    page.fill(FIELD_IDS["min_transaction_amount"], cfg["min_transaction_amount"])
    page.fill(FIELD_IDS["max_transaction_amount"], cfg["max_transaction_amount"])
    page.fill(FIELD_IDS["start_date"], cfg["start_date"])
    page.fill(FIELD_IDS["end_date"], cfg["end_date"])
    page.fill(FIELD_IDS["cumulative_limit"], cfg["cumulative_limit"])
    page.fill(FIELD_IDS["max_transactions"], cfg["max_transactions"])
    page.fill(FIELD_IDS["first_name"], cfg["first_name"])
    page.fill(FIELD_IDS["last_name"], cfg["last_name"])
    page.fill(FIELD_IDS["user_email"], cfg["user_email"])

    # Country Code is a GWT/YUI autocomplete combobox. Just filling text
    # sets the visible value but never fires the widget's internal
    # "selection" event, so form validation still treats it as empty
    # ("User Country Code is required"). We have to actually type (so the
    # live filter fires) and click the matching suggestion from the list.
    # Its id (e.g. gwt-uid-119) is auto-generated by a counter that keeps
    # climbing across the whole session -- NOT stable between navigations
    # -- so it must be rediscovered fresh each time via proximity to the
    # stable "user-mobile-country-code-label" label id.
    country_code_id = find_country_code_field_id(page)
    country_code_field = page.locator(f"#{country_code_id}")
    country_code_field.click()
    country_code_field.fill("")
    country_code_field.press_sequentially(cfg["user_country_code"], delay=80)
    country_code_option = page.locator(f"li[data-text='{cfg['user_country_code']}']")
    country_code_option.wait_for(state="visible", timeout=8000)
    country_code_option.click(timeout=5000)

    page.fill(FIELD_IDS["user_mobile_number"], cfg["user_mobile_number"])


def submit_and_read_result(page, cfg: dict) -> dict:
    """The Submit click and reading back the confirmation. Never retried
    by create_one_card(): if this times out, we genuinely cannot tell
    whether the card was created on Mastercard's side or not, and
    blindly retrying risks creating a real duplicate card."""
    page.locator("#submitBtn").click()
    try:
        page.wait_for_selector("#cardNumberLabel", timeout=20000)
    except PlaywrightTimeoutError as e:
        raise RuntimeError(
            "Submitted the form but couldn't confirm the card was created "
            "(no confirmation appeared in time). This card was NOT retried "
            "-- check Smart Data / your card history manually before "
            "creating more, in case it was actually created."
        ) from e

    card_number_raw = page.input_value("#cardNumberLabel")
    card_number = card_number_raw.split(" (")[0].replace(" ", "")

    return {
        "card_alias": page.input_value("#card-alias"),
        "card_number": card_number,
        "card_amount": cfg["max_transaction_amount"],
        "expiry": page.input_value("#expireDateLabel"),
        "cvc": page.input_value("#cvcLabel"),
        "billing_name": page.input_value("#billingNameLabel"),
        "description": page.input_value(FIELD_IDS["description"]),
        "created_by": cfg.get("created_by", ""),
    }


def create_one_card(page, cfg: dict, log=print) -> dict:
    """Fills and submits one purchase request. The form-filling phase is
    retried on a timeout as long as the session still looks logged in --
    a slow page reload shouldn't abort the whole batch. The submit phase
    is never retried (see submit_and_read_result)."""
    for attempt in range(1, MAX_FILL_RETRIES + 2):
        try:
            navigate_and_fill_form(page, cfg, log=log)
            break
        except PlaywrightTimeoutError:
            dump_page_frames(page, log)
            if not is_logged_in(page):
                raise_if_logged_out()
            if attempt > MAX_FILL_RETRIES:
                raise
            log(f"  Form step timed out (attempt {attempt}/{MAX_FILL_RETRIES + 1}) -- retrying...")
            page.wait_for_timeout(3000)

    return submit_and_read_result(page, cfg)


def run_batch(cfg: dict, count: int, batch_id: str | None = None, log=print, should_cancel=None) -> list:
    """Attaches to the browser launched by launch_browser.py and creates
    `count` cards using field values from `cfg`. Calls log(message) for
    each progress update. If should_cancel() returns True, stops before
    starting the next card (already-created cards are kept). Returns the
    list of created card detail dicts. Reusable by both the CLI (main())
    and gui.py. batch_id (if given) is stamped onto every saved card so
    they can be queried/downloaded as one group later."""
    cfg = dict(cfg)
    cfg.setdefault("start_date", datetime.now().strftime("%d/%m/%Y"))
    cfg.setdefault("end_date", datetime.now().strftime("%d/%m/%Y"))

    results = []

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
        except Exception as e:
            raise RuntimeError(
                "Could not attach to the browser. Is launch_browser.py running? "
                f"(tried http://localhost:{DEBUG_PORT})"
            ) from e

        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        if "smartdata.mastercard.co.in" not in page.url:
            raise RuntimeError(
                "Not on the Smart Data site yet. Log in manually in the "
                "launch_browser.py window first, then try again."
            )

        try:
            for i in range(count):
                if should_cancel and should_cancel():
                    log(f"Cancelled -- created {i}/{count} card(s) before stopping.")
                    break
                log(f"Creating card {i + 1}/{count}...")
                details = None
                last_error = None
                for card_attempt in range(1, MAX_CARD_ATTEMPTS + 1):
                    try:
                        details = create_one_card(page, cfg, log=log)
                        last_error = None
                        break
                    except RuntimeError:
                        dump_page_frames(page, log)
                        raise
                    except Exception as e:
                        last_error = e
                        dump_page_frames(page, log)
                        if not is_logged_in(page):
                            raise_if_logged_out()
                        if card_attempt >= MAX_CARD_ATTEMPTS:
                            raise
                        log(
                            f"  Card {i + 1} failed ({e}) -- retrying "
                            f"({card_attempt}/{MAX_CARD_ATTEMPTS}) without closing the browser"
                        )
                        page.wait_for_timeout(5000)
                if last_error or details is None:
                    raise last_error or RuntimeError("Card creation failed with no details")
                save_card(details, batch_id=batch_id)
                results.append(details)
                log(f"  -> {details['card_number']} saved to database")
        except Exception:
            debug_path = Path(__file__).parent / "debug_error.png"
            page.screenshot(path=str(debug_path), full_page=True)
            log(f"Error occurred -- saved screenshot to {debug_path}")
            log(f"Current URL: {page.url}")
            dump_page_frames(page, log)
            raise

        # Don't close context/browser -- it's shared/long-lived, owned by launch_browser.py

    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "count", type=int, nargs="?", default=1, help="how many virtual cards to create"
    )
    args = parser.parse_args()

    cfg = load_config()
    try:
        run_batch(cfg, args.count)
    except RuntimeError as e:
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    main()
