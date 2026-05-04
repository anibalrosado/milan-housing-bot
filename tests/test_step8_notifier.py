"""
Step 8 test: Email notifier.

Run from project root:
    python tests/test_step8_notifier.py

This test sends a REAL email to NOTIFY_EMAILS using the credentials in .env.
Make sure GMAIL_USER, GMAIL_APP_PASSWORD, and NOTIFY_EMAILS are set first.

To get a Gmail App Password:
  1. Enable 2-Step Verification on your Google account
  2. Go to myaccount.google.com → Security → App Passwords
  3. Create a new app password (App: Mail, Device: Other → "Milan Housing Bot")
  4. Copy the 16-character password into .env as GMAIL_APP_PASSWORD
"""

import logging
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from src.scrapers.base import Listing
from src.notifier import EmailNotifier

GMAIL_USER     = os.environ.get("GMAIL_USER", "")
APP_PASSWORD   = os.environ.get("GMAIL_APP_PASSWORD", "")
NOTIFY_EMAILS  = [e.strip() for e in os.environ.get("NOTIFY_EMAILS", "").split(",") if e.strip()]
SHEET_URL      = f"https://docs.google.com/spreadsheets/d/{os.environ.get('GOOGLE_SHEET_ID','')}/edit"
MAP_URL        = os.environ.get("RENDER_MAP_URL", "https://example.com/map.html")


def _fake_listing(i: int, search_type: str) -> Listing:
    return Listing(
        source="Spotahome" if i % 2 == 0 else "Uniplaces",
        search_type=search_type,
        title=f"Test listing {i} — beautiful apartment near Cattolica",
        neighborhood="Sant'Ambrogio",
        walk_minutes=2 if search_type == "Group of 5" else 5,
        price_eur=2500.0 + i * 100 if search_type == "Group of 5" else 1200.0 + i * 50,
        bedrooms=4 if search_type == "Group of 5" else 1,
        furnished=True,
        available_from="2026-09-01",
        contact_name=None,
        email=None,
        phone=None,
        url=f"https://www.spotahome.com/test-listing-{i}",
    )


def main():
    if not GMAIL_USER or not APP_PASSWORD:
        print("❌  GMAIL_USER and GMAIL_APP_PASSWORD must be set in .env")
        print("    See docstring at top of this file for instructions.")
        sys.exit(1)

    if not NOTIFY_EMAILS:
        print("❌  NOTIFY_EMAILS must be set in .env (comma-separated addresses)")
        sys.exit(1)

    print(f"\nGmail user:  {GMAIL_USER}")
    print(f"Recipients:  {', '.join(NOTIFY_EMAILS)}")
    print(f"Sheet URL:   {SHEET_URL}")
    print(f"Map URL:     {MAP_URL}")
    print("\nSending test email…")

    new_listings = [
        _fake_listing(1, "Group of 5"),
        _fake_listing(2, "Couple"),
        _fake_listing(3, "Couple"),
    ]
    removed_listings = [
        {"source": "HousingAnywhere", "search_type": "Couple",
         "url": "https://housinganywhere.com/room/ut12345"},
    ]

    notifier = EmailNotifier(GMAIL_USER, APP_PASSWORD, NOTIFY_EMAILS)
    notifier.send(
        new_listings=new_listings,
        removed_listings=removed_listings,
        sheet_url=SHEET_URL,
        map_url=MAP_URL,
        run_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
    )

    print(f"\n✅  Email sent. Check inbox for {', '.join(NOTIFY_EMAILS)}.")
    print("    Verify the email shows:")
    print("      • 3 new listings (1 Group of 5, 2 Couple) with prices and neighborhood")
    print("      • 1 removed listing (HousingAnywhere)")
    print("      • Links to the sheet and map")


if __name__ == "__main__":
    main()
