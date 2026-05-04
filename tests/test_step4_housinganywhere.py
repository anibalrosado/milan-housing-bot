"""
Step 4 test: HousingAnywhere scraper against the live site.

Run from project root:
    python tests/test_step4_housinganywhere.py

Note: HousingAnywhere inventory for Milan is modest — especially for
4-5BR apartments. The scraper returning 0 Group of 5 results is acceptable
if the platform simply has no matching listings today.
"""

import logging
import os
import sys

import yaml
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from src.scrapers.housinganywhere import HousingAnywhereScraper


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def main():
    config = load_config()
    EUR_RATE = 0.92
    eur_group = round(config["budget"]["group_usd_total"] * EUR_RATE, 2)
    eur_couple = round(config["budget"]["couple_usd_total"] * EUR_RATE, 2)

    print(f"\nBudgets: Group ≤ €{eur_group:.0f}/mo | Couple ≤ €{eur_couple:.0f}/mo")
    print("Running HousingAnywhere scraper (this may take 60–90 seconds)…\n")

    scraper = HousingAnywhereScraper(config, eur_group, eur_couple)
    listings = scraper.scrape()

    print(f"\n{'─' * 60}")
    print(f"Total listings returned: {len(listings)}")
    print(f"{'─' * 60}\n")

    if not listings:
        print("⚠️  No listings returned.")
        print("   HousingAnywhere has limited Milan inventory for whole apartments.")
        print("   This is expected — the scraper did not crash, which is ✓.")
        return

    errors = []
    group_count = sum(1 for l in listings if l.search_type == "Group of 5")
    couple_count = sum(1 for l in listings if l.search_type == "Couple")

    for i, l in enumerate(listings):
        if not l.url:
            errors.append(f"Listing {i+1}: missing URL")
        elif "housinganywhere.com" not in l.url:
            errors.append(f"Listing {i+1}: URL not from housinganywhere.com")
        if not l.title:
            errors.append(f"Listing {i+1}: missing title")
        if l.search_type == "Group of 5" and l.price_eur and l.price_eur > eur_group:
            errors.append(f"Listing {i+1}: price €{l.price_eur} exceeds Group budget")
        if l.search_type == "Couple" and l.price_eur and l.price_eur > eur_couple:
            errors.append(f"Listing {i+1}: price €{l.price_eur} exceeds Couple budget")

    print(f"  Group of 5 listings: {group_count}")
    print(f"  Couple listings:     {couple_count}")
    print()

    for l in listings[:8]:
        price_str = f"€{l.price_eur:.0f}/mo" if l.price_eur else "price N/A"
        beds_str = f"{l.bedrooms}BR" if l.bedrooms else "?BR"
        print(f"  [{l.search_type}] {l.title[:50]:<50} | {beds_str} | {price_str:<12} | {l.neighborhood}")
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
        print(f"✅  HousingAnywhere scraper working — {len(listings)} listing(s) validated.")


if __name__ == "__main__":
    main()
