"""
Step 2 test: exercises DedupeStore and SheetsWriter end-to-end.

Run from project root:
    python tests/test_step2.py

What it does:
  1. Creates a fake listing
  2. Verifies dedupe correctly identifies it as new, then filters it after mark_seen
  3. Verifies miss_count lifecycle (increment → get_newly_removed → reset)
  4. Appends the fake row to your real Google Sheet
  5. Reads it back and asserts the values are correct
  6. Flips it to Removed via update_listing_status and confirms the change
  7. Cleans up the test SQLite DB (the sheet row stays — delete it manually)
"""

import json
import os
import sys
from datetime import datetime

import yaml
from dotenv import load_dotenv

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from src.scrapers.base import Listing
from src.dedupe import DedupeStore
from src.sheets import SheetsWriter


def load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def load_creds():
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        return json.loads(raw)
    path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")
    if path:
        with open(path) as f:
            return json.load(f)
    raise EnvironmentError("No Google credentials found — check your .env file.")


def ok(msg):
    print(f"  ✓ {msg}")


def main():
    config = load_config()
    sheet_id = os.environ["GOOGLE_SHEET_ID"]

    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    fake = Listing(
        source="TestSource",
        search_type="Couple",
        title="Cozy Studio near Cattolica [STEP 2 TEST — DELETE ME]",
        neighborhood="Sant'Ambrogio",
        walk_minutes=2,
        price_eur=1100.0,
        bedrooms=1,
        furnished=True,
        available_from="2026-09-01",
        contact_name="",
        email="",
        phone="",
        url=f"https://example.com/test-listing-step2-{run_id}",
        notes="Created by tests/test_step2.py — safe to delete",
    )

    print(f"\nListing hash: {fake.listing_hash()[:16]}…\n")

    # ── 1. DedupeStore: filter_new ────────────────────────────────────────────
    print("[ DedupeStore ]")
    TEST_DB = "test_step2_listings.db"
    dedupe = DedupeStore(TEST_DB)

    new = dedupe.filter_new([fake])
    assert len(new) == 1, f"Expected 1 new listing, got {len(new)}"
    ok("filter_new: listing is correctly identified as new")

    dedupe.mark_seen([fake])
    new_again = dedupe.filter_new([fake])
    assert len(new_again) == 0, "Expected 0 after mark_seen"
    ok("mark_seen + filter_new: listing correctly deduplicated on second check")

    hashes = dedupe.get_all_known_hashes()
    assert fake.listing_hash() in hashes
    ok(f"get_all_known_hashes: {len(hashes)} hash(es) in DB")

    # ── 2. DedupeStore: lifecycle ─────────────────────────────────────────────
    print("\n[ Lifecycle ]")
    for _ in range(3):
        dedupe.increment_miss_counts({fake.listing_hash()})
    removed = dedupe.get_newly_removed(threshold=3)
    assert any(r["url"] == fake.url for r in removed), \
        "Expected listing to appear as newly removed after 3 misses"
    ok("increment_miss_counts × 3 + get_newly_removed: listing flagged correctly")

    dedupe.mark_seen([fake])
    removed_after_reset = dedupe.get_newly_removed(threshold=3)
    assert not any(r["url"] == fake.url for r in removed_after_reset), \
        "Expected listing to be gone from newly_removed after mark_seen reset"
    ok("mark_seen resets miss_count — listing no longer in newly_removed")

    # ── 3. SheetsWriter: append ───────────────────────────────────────────────
    print("\n[ SheetsWriter ]")
    creds = load_creds()
    writer = SheetsWriter(sheet_id, creds, config["sheet_columns"])

    date_found = datetime.now().strftime("%m/%d/%Y")
    row = fake.to_sheet_row(date_found)
    writer.append_listings([row])
    ok("append_listings: row written to sheet")

    # ── 4. SheetsWriter: read back ────────────────────────────────────────────
    all_rows = writer.read_all_listings()
    matches = [r for r in all_rows if r.get("Listing URL") == fake.url]
    assert len(matches) == 1, f"Expected 1 matching row, got {len(matches)}"
    r = matches[0]
    assert r["Listing Status"] == "Active", f"Expected Active, got {r['Listing Status']}"
    assert r["Status"] == "New", f"Expected New, got {r['Status']}"
    assert float(r["Price (€/month)"]) == 1100.0, f"Unexpected price: {r['Price (€/month)']}"
    ok("read_all_listings: row found with correct values")
    print(f"       Title:          {r['Title']}")
    print(f"       Search Type:    {r['Search Type']}")
    print(f"       Listing Status: {r['Listing Status']}")
    print(f"       Status:         {r['Status']}")
    print(f"       Price (€/mo):   {r['Price (€/month)']}")
    print(f"       Neighborhood:   {r['Neighborhood']}")

    # ── 5. SheetsWriter: update_listing_status ────────────────────────────────
    print()
    writer.update_listing_status(fake.url, "Removed", date_found)
    all_rows_after = writer.read_all_listings()
    match_after = [r for r in all_rows_after if r.get("Listing URL") == fake.url]
    assert len(match_after) == 1
    assert match_after[0]["Listing Status"] == "Removed", \
        f"Expected Removed, got {match_after[0]['Listing Status']}"
    assert match_after[0]["Removed Date"] == date_found
    ok("update_listing_status: row correctly flipped to Removed with today's date")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    os.remove(TEST_DB)
    ok(f"Cleaned up {TEST_DB}")

    print(f"""
✅  All Step 2 checks passed!

The test row is still in your Google Sheet (Listing Status = Removed).
You can delete it manually — it's the row titled:
  "{fake.title}"

Sheet: https://docs.google.com/spreadsheets/d/{sheet_id}
""")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n❌  ASSERTION FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌  ERROR: {e}")
        raise
