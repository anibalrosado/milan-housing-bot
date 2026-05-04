"""
Dumps raw Spotahome API payloads to inspect their structure.
Run: python tests/debug_spotahome_payload.py
"""

import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING)

from playwright.sync_api import sync_playwright, Response

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_SEARCH_URL = "https://www.spotahome.com/for-rent/milan--italy"
_CONSENT_TEXTS = ["accept all", "accept cookies", "i accept", "accetta", "agree"]


def main():
    payloads = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )

        def capture(response: Response):
            if response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                data = response.json()
                payloads.append({"url": response.url, "data": data})
            except Exception:
                pass

        context.on("response", capture)
        page = context.new_page()
        page.goto(_SEARCH_URL, wait_until="load", timeout=45_000)
        time.sleep(4)

        # Dismiss consent
        import re
        for text in _CONSENT_TEXTS:
            try:
                btn = page.get_by_role("button", name=re.compile(text, re.IGNORECASE))
                if btn.count() > 0:
                    btn.first.click(timeout=3_000)
                    print(f"Dismissed consent: '{text}'")
                    break
            except Exception:
                pass
        # Scroll to trigger lazy loading
        for _ in range(6):
            page.evaluate("window.scrollBy(0, 600)")
            time.sleep(0.8)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(3)

        # Screenshot after full load
        page.screenshot(path="spotahome_debug_after_scroll.png")
        print("Screenshot saved → spotahome_debug_after_scroll.png")

        browser.close()

    print(f"\nTotal JSON responses captured: {len(payloads)}\n")
    print("=" * 70)

    for i, p in enumerate(payloads):
        print(f"\n[{i+1}] URL: {p['url']}")
        data = p["data"]

        # Print top-level keys
        if isinstance(data, dict):
            print(f"     Top-level keys: {list(data.keys())}")
            # Show first item from any list-valued key
            for k, v in data.items():
                if isinstance(v, list) and len(v) > 0:
                    print(f"\n     '{k}' is a list of {len(v)} item(s). First item keys:")
                    first = v[0]
                    if isinstance(first, dict):
                        print(f"       {list(first.keys())}")
                        # Print first item truncated
                        print(f"\n     First item sample:")
                        sample = json.dumps(first, indent=4, ensure_ascii=False)
                        print("\n".join("       " + l for l in sample.splitlines()[:40]))
                    break
                elif isinstance(v, dict):
                    print(f"\n     '{k}' is a dict with keys: {list(v.keys())}")
        elif isinstance(data, list):
            print(f"     Root is a list of {len(data)} item(s)")
            if data and isinstance(data[0], dict):
                print(f"     First item keys: {list(data[0].keys())}")
                sample = json.dumps(data[0], indent=4, ensure_ascii=False)
                print("\n".join("       " + l for l in sample.splitlines()[:40]))

    # Also save full dump for deeper inspection
    out_path = os.path.join(os.getcwd(), "spotahome_payload_dump.json")
    with open(out_path, "w") as f:
        json.dump(payloads, f, indent=2, ensure_ascii=False)
    print(f"\n\nFull dump saved → {out_path}")


if __name__ == "__main__":
    main()
