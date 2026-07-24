"""
Recording session.

Opens a dedicated automation profile (separate from your everyday Chrome
profile). Chrome refuses to attach remote-debugging/automation to its
*default* profile location as a security measure, so this deliberately
uses a project-local folder instead -- that's the only kind of profile
Playwright can actually control.

Since this is a fresh profile, you'll need to log in manually here (once
per login-session expiry -- the profile is persistent, so cookies survive
between runs until the bank logs you out).

We are NOT relying on the AutoFormer+ extension anymore (it's been
removed/disabled by Chrome, unrelated to this script, likely the
Manifest V2 phase-out). Repeated field values will instead be filled
directly by the automation script itself.

Usage:
    python explore.py

What happens:
  1. Chrome opens with a blank page.
  2. Script pauses and opens the Playwright Inspector.
  3. You manually: log in, navigate to the purchase request / virtual
     card creation form, fill it in by hand once, submit.
  4. The Inspector's "Record" panel shows Python code for every action
     you take in real time -- this is what we'll turn into the real
     automation script's field values and selectors.
  5. Click "Resume" in the Inspector (or close it) when you're done to
     end the script.
"""

from pathlib import Path
from playwright.sync_api import sync_playwright, Error as PlaywrightError

PROFILE_DIR = Path(__file__).parent / "chrome-profile"


def main() -> None:
    PROFILE_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            args=[
                "--start-maximized",
            ],
            ignore_default_args=["--enable-automation", "--no-sandbox"],
            no_viewport=True,
        )

        page = context.pages[0] if context.pages else context.new_page()
        page.goto("about:blank")

        print("Browser is open. Log in and navigate manually.")
        print("The Playwright Inspector window records your actions as code.")
        page.pause()

        try:
            context.close()
        except PlaywrightError:
            pass  # window was already closed manually


if __name__ == "__main__":
    main()
