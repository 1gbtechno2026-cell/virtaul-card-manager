"""
Launches ONE long-lived, HEADLESS Chrome instance with remote debugging
enabled, so automate.py/app.py can attach to this same running, logged-in
session as many times as needed without logging in again each time.

Headless because every interaction (bank login, OTP, card form) is driven
entirely through the web UI -- nobody needs to see or click the actual
browser window. This also means it runs fine on a real server with no
display attached.

Launches Chrome as a plain subprocess (NOT via Playwright's own
launch_persistent_context). Playwright always adds its own
--remote-debugging-pipe transport for its own control channel, and having
that alongside our --remote-debugging-port for external access turned out
to be unreliable -- the port sometimes silently failed to bind. A plain
subprocess avoids that dual-transport entirely.

Usage:
    python launch_browser.py

Run this once and leave it running. automate.py/app.py attach to it via CDP.
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

PROFILE_DIR = Path(__file__).parent / "chrome-profile"
PID_PATH = Path(__file__).parent / "chrome.pid"
DEBUG_PORT = 9222
START_URL = "https://smartdata.mastercard.co.in/"
LAUNCH_ATTEMPTS = 3

CHROME_CANDIDATES = [
    # Windows
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    # Linux
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise SystemExit(
        "Could not find a Chrome/Chromium install. Edit CHROME_CANDIDATES in "
        "launch_browser.py to add its path."
    )


def debug_port_reachable(timeout_s: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", DEBUG_PORT), timeout=timeout_s):
            return True
    except OSError:
        return False


def wait_briefly_for_port(timeout_s: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if debug_port_reachable():
            return True
        time.sleep(0.3)
    return False


def main() -> None:
    PROFILE_DIR.mkdir(exist_ok=True)
    chrome_path = find_chrome()

    args = [
        chrome_path,
        "--headless=new",
        # Chrome refuses to start as root without this (common on VPS
        # deployments that run everything as root) -- confirmed the hard
        # way in production, see crbug.com/638180.
        "--no-sandbox",
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={PROFILE_DIR}",
        "--window-size=1920,1080",
        "--no-first-run",
        "--no-default-browser-check",
        START_URL,
    ]

    proc = None
    for attempt in range(1, LAUNCH_ATTEMPTS + 1):
        proc = subprocess.Popen(args)
        print(f"Headless Chrome launched (pid={proc.pid}), remote debugging on port {DEBUG_PORT}.")
        # Written so app.py can kill this exact process later (see
        # close_browser_session() in app.py) -- killing this wrapper script
        # alone does not kill Chrome, since nothing here forwards signals to it.
        PID_PATH.write_text(str(proc.pid))

        if wait_briefly_for_port():
            break

        # Chrome can lose a race for its own profile lock if the previous
        # instance's shutdown (SIGTERM from close_browser_session()) hadn't
        # fully released chrome-profile/ yet, and exits almost immediately
        # without ever opening the debug port. Previously this left the
        # app stuck polling /browser-status forever with no way to recover
        # short of manually relaunching. Retry instead.
        if proc.poll() is not None and attempt < LAUNCH_ATTEMPTS:
            print(
                f"Chrome exited before the debug port came up "
                f"(attempt {attempt}/{LAUNCH_ATTEMPTS}) -- retrying..."
            )
            PID_PATH.unlink(missing_ok=True)
            time.sleep(2)
            continue
        break

    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        PID_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
