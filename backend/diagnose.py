"""
One-off diagnostic: attaches to the already-running browser (from
launch_browser.py) and reports exactly where a given text label actually
lives -- which frame, what tag, what CSS visibility, and what
input/select sits nearby -- so we stop guessing blindly at selectors.

Usage:
    python diagnose.py "Description"
"""

import sys

from playwright.sync_api import sync_playwright

DEBUG_PORT = 9222
DEFAULT_LABEL = "Description"


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LABEL

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        print(f"Main page URL: {page.url}")
        print(f"Number of frames: {len(page.frames)}")
        for i, frame in enumerate(page.frames):
            print(f"  frame[{i}]: name={frame.name!r} url={frame.url}")

        for i, frame in enumerate(page.frames):
            try:
                matches = frame.evaluate(
                    """
                    (label) => {
                        const results = [];
                        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
                        let node;
                        while ((node = walker.nextNode())) {
                            const text = node.textContent ? node.textContent.trim() : '';
                            if (node.children.length === 0 && text === label) {
                                const rect = node.getBoundingClientRect();
                                const style = window.getComputedStyle(node);

                                // look for a nearby input/select: next sibling(s), then parent's next sibling
                                let nearbyInput = null;
                                let sib = node.nextElementSibling;
                                while (sib && !nearbyInput) {
                                    nearbyInput = sib.matches('input,select,textarea') ? sib : sib.querySelector('input,select,textarea');
                                    sib = sib.nextElementSibling;
                                }
                                if (!nearbyInput) {
                                    let parentSib = node.parentElement ? node.parentElement.nextElementSibling : null;
                                    while (parentSib && !nearbyInput) {
                                        nearbyInput = parentSib.matches('input,select,textarea') ? parentSib : parentSib.querySelector('input,select,textarea');
                                        parentSib = parentSib.nextElementSibling;
                                    }
                                }

                                results.push({
                                    tag: node.tagName,
                                    className: node.className,
                                    id: node.id,
                                    parentTag: node.parentElement ? node.parentElement.tagName : null,
                                    parentClass: node.parentElement ? node.parentElement.className : null,
                                    rect: {w: rect.width, h: rect.height, x: rect.x, y: rect.y},
                                    display: style.display,
                                    visibility: style.visibility,
                                    opacity: style.opacity,
                                    nearbyInput: nearbyInput ? {
                                        tag: nearbyInput.tagName,
                                        type: nearbyInput.type || null,
                                        name: nearbyInput.name || null,
                                        id: nearbyInput.id || null,
                                    } : null,
                                });
                            }
                        }
                        return results;
                    }
                    """,
                    label,
                )
                if matches:
                    print(f"Matches in frame[{i}] ({frame.url}):")
                    for m in matches:
                        print(f"    {m}")
            except Exception as e:
                print(f"  (could not evaluate in frame[{i}]: {e})")


if __name__ == "__main__":
    main()
