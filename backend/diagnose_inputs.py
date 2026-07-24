"""
One-off diagnostic: lists every input/select/textarea on the current page
(main frame) with its id/name/type/nearby label text, so we can map the
remaining unresolved fields (Description, First Name, Last Name, User
Email, User Country Code, User Mobile Number) by hand.

Usage:
    python diagnose_inputs.py
"""

from playwright.sync_api import sync_playwright

DEBUG_PORT = 9222


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        print(f"URL: {page.url}")

        result = page.main_frame.evaluate(
            """
            () => {
                const els = Array.from(document.querySelectorAll('input, select, textarea'));
                return els.map(el => {
                    const rect = el.getBoundingClientRect();
                    return {
                        tag: el.tagName,
                        type: el.type || null,
                        id: el.id || null,
                        name: el.name || null,
                        visible: rect.width > 0 && rect.height > 0,
                        y: Math.round(rect.y),
                    };
                });
            }
            """
        )

        for el in sorted(result, key=lambda e: e["y"]):
            print(el)


if __name__ == "__main__":
    main()
