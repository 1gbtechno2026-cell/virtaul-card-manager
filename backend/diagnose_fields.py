"""
One-off diagnostic: for each known field label on the purchase request
form, find the <label> element and resolve its `for` attribute to the
actual input/select element (id, name, type). Prints a full mapping in
one pass so we don't have to debug field-by-field.

Usage:
    python diagnose_fields.py
"""

from playwright.sync_api import sync_playwright

DEBUG_PORT = 9222

LABELS = [
    "Description",
    "Minimum Transaction Amount",
    "Maximum Transaction Amount",
    "Start Date",
    "End Date",
    "Cumulative Limit",
    "Maximum Number of Transactions",
    "First Name",
    "Last Name",
    "User Email",
    "User Country Code",
    "User Mobile Number",
]


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        target_frame = page.main_frame
        print(f"Using frame: {target_frame.url}")

        result = target_frame.evaluate(
            """
            (labels) => {
                const out = {};
                for (const labelText of labels) {
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
                    let node, found = null;
                    while ((node = walker.nextNode())) {
                        const text = node.textContent ? node.textContent.trim() : '';
                        if (node.tagName === 'LABEL' && node.children.length === 0 && text === labelText) {
                            found = node;
                            break;
                        }
                    }
                    if (!found) {
                        out[labelText] = {error: 'label not found'};
                        continue;
                    }
                    const forAttr = found.getAttribute('for');
                    let target = null;
                    if (forAttr) {
                        target = document.getElementById(forAttr);
                    }
                    out[labelText] = {
                        labelId: found.id,
                        forAttr: forAttr,
                        targetTag: target ? target.tagName : null,
                        targetType: target ? target.type || null : null,
                        targetId: target ? target.id : null,
                        targetName: target ? target.name || null : null,
                    };
                }
                return out;
            }
            """,
            LABELS,
        )

        for label, info in result.items():
            print(f"{label!r}: {info}")


if __name__ == "__main__":
    main()
