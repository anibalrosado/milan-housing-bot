"""
Step 2.5 test: listing lifecycle tracking across simulated runs.

Run from project root:
    python tests/test_step2_5.py

Simulates 5 scraper runs against a real Google Sheet row:
  Run 1 → listing appears   → sheet: Active
  Run 2 → listing absent    → miss_count=1, still Active
  Run 3 → listing absent    → miss_count=2, still Active
  Run 4 → listing absent    → miss_count=3 → sheet: Removed
  Run 5 → listing reappears → sheet: Active, miss_count reset

Cleans up the SQLite test DB automatically.
The sheet row stays — delete it manually when done.
"""

import json
import os
import sys
from datetime import datetime

import yaml
from dotenv import load_dotenv

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
    raise EnvironmentError("No Google credentials found.")


def ok(msg):
    print(f"  ✓ {msg}")


def get_sheet_row(writer, url):
    rows = writer.read_all_listings()
    matches = [r for r in rows if r.get("Listing URL") == url]
    return matches[0] if matches else None


def simulate_run(dedupe, writer, found_listings, threshold, date_str):
    """Replicates the main.py lifecycle pipeline for one run."""
    new_listings = dedupe.filter_new(found_listings)
    reactivated = dedupe.get_reactivated(found_listings)

    if new_listings:
        rows = [l.to_sheet_row(date_str) for l in new_listings]
        writer.append_listings(rows)

    dedupe.mark_seen(found_listings)

    for record in reactivated:
        writer.update_listing_status(record["url"], "Active", "")

    this_run_hashes = {l.listing_hash() for l in found_listings}
    known_hashes = dedupe.get_all_known_hashes()
    absent_hashes = known_hashes - this_run_hashes

    newly_removed = []
    if absent_hashes:
        dedupe.increment_miss_counts(absent_hashes)
        newly_removed = dedupe.get_newly_removed(threshold)
        for record in newly_removed:
            writer.update_listing_status(record["url"], "Removed", date_str)

    return new_listings, reactivated, newly_removed


def main():
    config = load_config()
    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    creds = load_creds()
    threshold = config.get("removed_miss_threshold", 3)
    date_str = datetime.now().strftime("%m/%d/%Y")

    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    TEST_DB = "test_step2_5_listings.db"
    LISTING_URL = f"https://example.com/lifecycle-test-{run_id}"

    listing = Listing(
        source="TestSource",
        search_type="Group of 5",
        title="4BR Apartment near Cattolica [LIFECYCLE TEST — DELETE ME]",
        neighborhood="Vetra",
        walk_minutes=10,
        price_eur=4200.0,
        bedrooms=4,
        furnished=True,
        available_from="2026-09-01",
        contact_name="",
        email="",
        phone="",
        url=LISTING_URL,
        notes="Created by tests/test_step2_5.py — safe to delete",
    )

    dedupe = DedupeStore(TEST_DB)
    writer = SheetsWriter(sheet_id, creds, config["sheet_columns"])

    print(f"\nListing hash: {listing.listing_hash()[:16]}…")
    print(f"Threshold: {threshold} consecutive misses\n")

    # ── Run 1: listing appears ────────────────────────────────────────────────
    print("[ Run 1 — listing appears ]")
    new, react, removed = simulate_run(dedupe, writer, [listing], threshold, date_str)
    assert len(new) == 1, f"Expected 1 new, got {len(new)}"
    assert len(react) == 0
    assert len(removed) == 0
    row = get_sheet_row(writer, LISTING_URL)
    assert row is not None, "Row not found in sheet"
    assert row["Listing Status"] == "Active", f"Expected Active, got {row['Listing Status']}"
    ok("new listing written to sheet with Listing Status = Active")

    # ── Runs 2 & 3: listing absent, below threshold ───────────────────────────
    for run_num in [2, 3]:
        print(f"\n[ Run {run_num} — listing absent (miss {run_num - 1}/{threshold}) ]")
        new, react, removed = simulate_run(dedupe, writer, [], threshold, date_str)
        assert len(new) == 0
        assert len(removed) == 0, f"Should not be removed yet at miss {run_num - 1}"
        row = get_sheet_row(writer, LISTING_URL)
        assert row["Listing Status"] == "Active", \
            f"Run {run_num}: should still be Active, got {row['Listing Status']}"
        ok(f"miss_count={run_num - 1} — still Active in sheet (threshold not reached)")

    # ── Run 4: third miss → flips to Removed ─────────────────────────────────
    print(f"\n[ Run 4 — listing absent (miss {threshold}/{threshold} → Removed) ]")
    new, react, removed = simulate_run(dedupe, writer, [], threshold, date_str)
    assert len(removed) == 1, f"Expected 1 removed, got {len(removed)}"
    row = get_sheet_row(writer, LISTING_URL)
    assert row["Listing Status"] == "Removed", \
        f"Expected Removed, got {row['Listing Status']}"
    assert row["Removed Date"] == date_str, \
        f"Expected Removed Date={date_str}, got {row['Removed Date']}"
    ok(f"miss_count hit {threshold} → Listing Status flipped to Removed ✓")
    ok(f"Removed Date set to {date_str}")

    # ── Run 5: listing reappears → flips back to Active ───────────────────────
    print("\n[ Run 5 — listing reappears → reactivated ]")
    new, react, removed = simulate_run(dedupe, writer, [listing], threshold, date_str)
    assert len(new) == 0, "Should not be new (already in DB)"
    assert len(react) == 1, f"Expected 1 reactivated, got {len(react)}"
    assert len(removed) == 0
    row = get_sheet_row(writer, LISTING_URL)
    assert row["Listing Status"] == "Active", \
        f"Expected Active after reappearance, got {row['Listing Status']}"
    assert row["Removed Date"] == "", \
        f"Expected Removed Date cleared, got '{row['Removed Date']}'"
    ok("listing reappeared → Listing Status flipped back to Active")
    ok("Removed Date cleared")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    os.remove(TEST_DB)
    ok(f"\nCleaned up {TEST_DB}")

    print(f"""
✅  All Step 2.5 lifecycle checks passed!

The test row is still in your Google Sheet (Listing Status = Active).
Delete it manually — it's titled:
  "4BR Apartment near Cattolica [LIFECYCLE TEST — DELETE ME]"

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
