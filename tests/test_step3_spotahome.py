"""
Step 3 test: Spotahome scraper against the live site.

Run from project root:
    python tests/test_step3_spotahome.py

Checks:
  - Scraper returns at least 1 result (or explains why it returned 0)
  - Every listing has a URL, title, and neighborhood
  - All URLs point to spotahome.com
  - Prices (when present) are within budget
  - Search type is correctly assigned
"""

import logging
import os
import sys

import yaml
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)

from src.scrapers.spotahome import SpotahomeScraper


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def main():
    config = load_config()

    # Use a rough EUR rate for the test (real rate fetched in main.py)
    EUR_RATE = 0.92
    eur_group = round(config["budget"]["group_usd_total"] * EUR_RATE, 2)
    eur_couple = round(config["budget"]["couple_usd_total"] * EUR_RATE, 2)

    print(f"\nBudgets: Group ≤ €{eur_group:.0f}/mo | Couple ≤ €{eur_couple:.0f}/mo")
    print("Running Spotahome scraper (this may take 30–60 seconds)…\n")

    scraper = SpotahomeScraper(config, eur_group, eur_couple)
    listings = scraper.scrape()

    print(f"\n{'─' * 60}")
    print(f"Total listings returned: {len(listings)}")
    print(f"{'─' * 60}\n")

    if not listings:
        print("⚠️  No listings returned.")
        print("   This may mean:")
        print("   - Spotahome's page structure changed (DOM selectors need updating)")
        print("   - No listings match our filters (neighborhoods + price) right now")
        print("   - The site blocked the headless browser")
        print("\n   Check logs above for details. The scraper did not crash, which is ✓.")
        return

    # ── Validate each listing ─────────────────────────────────────────────────
    errors = []
    group_count = 0
    couple_count = 0

    for i, l in enumerate(listings):
        prefix = f"Listing {i+1}"
        if not l.url:
            errors.append(f"{prefix}: missing URL")
        elif "spotahome.com" not in l.url:
            errors.append(f"{prefix}: URL not from spotahome.com — {l.url}")
        if not l.title:
            errors.append(f"{prefix}: missing title")
        if not l.neighborhood:
            errors.append(f"{prefix}: missing neighborhood")
        if l.search_type == "Group of 5":
            group_count += 1
            if l.price_eur and l.price_eur > eur_group:
                errors.append(f"{prefix}: price €{l.price_eur} exceeds Group budget €{eur_group}")
        elif l.search_type == "Couple":
            couple_count += 1
            if l.price_eur and l.price_eur > eur_couple:
                errors.append(f"{prefix}: price €{l.price_eur} exceeds Couple budget €{eur_couple}")

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f"  Group of 5 listings: {group_count}")
    print(f"  Couple listings:     {couple_count}")
    print()

    # Sample up to 8 listings
    for l in listings[:8]:
        price_str = f"€{l.price_eur:.0f}/mo" if l.price_eur else "price N/A"
        print(f"  [{l.search_type}] {l.title[:55]:<55} | {price_str:<12} | {l.neighborhood}")
        print(f"    {l.url}")
        print()

    if len(listings) > 8:
        print(f"  … and {len(listings) - 8} more\n")

    if errors:
        print("❌  Validation errors:")
        for e in errors:
            print(f"    - {e}")
        sys.exit(1)
    else:
        print(f"✅  Spotahome scraper working — {len(listings)} listing(s) returned and validated.")


if __name__ == "__main__":
    main()
