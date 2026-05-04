"""
Milan Housing Bot — entry point.
Run directly for a one-shot execution, or deploy as a Render Cron Job.

Pipeline per run:
  1. Fetch USD→EUR rate
  2. Run all scrapers (failures isolated per scraper)
  3. Deduplicate → find genuinely NEW listings
  4. Geocode new listings (Nominatim or Google, cached in SQLite)
  5. Append new listings to sheet with Listing Status = "Active"
  6. Lifecycle: increment miss_count for absent known listings;
     flip to Removed in sheet after removed_miss_threshold consecutive misses
  7. Regenerate map.html from current sheet data
  8. Email if new OR removed listings this run
"""

import json
import logging
import logging.handlers
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests
import yaml
from dotenv import load_dotenv

from src.dedupe import DedupeStore
from src.geocoder import Geocoder
from src.map_generator import MapGenerator
from src.notifier import EmailNotifier
from src.scrapers.spotahome import SpotahomeScraper
from src.scrapers.housinganywhere import HousingAnywhereScraper
from src.scrapers.uniplaces import UniplacesScraper
from src.scrapers.idealista import IdealistaScraper
from src.scrapers.immobiliare import ImmobiliareScraper
from src.sheets import SheetsWriter

load_dotenv()


# ── Logging setup ──────────────────────────────────────────────────────────────

def setup_logging(config: dict) -> None:
    log_file = config.get("log_file", "logs/bot.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=config.get("log_max_bytes", 5_242_880),
        backupCount=config.get("log_backup_count", 3),
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


logger = logging.getLogger(__name__)


# ── Config helpers ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def load_google_credentials() -> dict:
    """Return parsed service account dict. Prefers inline JSON over file path."""
    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw_json:
        return json.loads(raw_json)

    json_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_PATH")
    if json_path:
        with open(json_path) as f:
            return json.load(f)

    raise EnvironmentError(
        "Neither GOOGLE_SERVICE_ACCOUNT_JSON nor GOOGLE_SERVICE_ACCOUNT_JSON_PATH is set."
    )


def fetch_usd_to_eur(fx_url: str) -> float:
    try:
        resp = requests.get(fx_url, timeout=10)
        resp.raise_for_status()
        rate = resp.json()["rates"]["EUR"]
        logger.info("USD→EUR rate: %.4f", rate)
        return rate
    except Exception as exc:
        logger.warning("FX fetch failed (%s), falling back to 0.92", exc)
        return 0.92


# ── Main run ───────────────────────────────────────────────────────────────────

def run() -> None:
    config = load_config()
    setup_logging(config)

    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    logger.info("=== Milan Housing Bot run started: %s ===", run_ts)

    # FX conversion
    rate = fetch_usd_to_eur(config["fx_api_url"])
    eur_budget_group = round(config["budget"]["group_usd_total"] * rate, 2)
    eur_budget_couple = round(config["budget"]["couple_usd_total"] * rate, 2)
    logger.info(
        "Budgets: Group ≤ €%.0f/mo | Couple ≤ €%.0f/mo",
        eur_budget_group,
        eur_budget_couple,
    )

    # Google credentials
    try:
        creds = load_google_credentials()
    except Exception as exc:
        logger.critical("Failed to load Google credentials: %s", exc)
        sys.exit(1)

    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    sheets_writer = SheetsWriter(sheet_id, creds, config["sheet_columns"])
    dedupe = DedupeStore()
    geocoder = Geocoder(config, dedupe)
    map_generator = MapGenerator(config, sheets_writer, geocoder, sheet_id)

    # ── Cold-start: seed DB from sheet if empty ───────────────────────────────
    # Render Cron Jobs use ephemeral containers — DB is empty on every run.
    # Seeding from the sheet prevents re-adding existing listings as "new".
    if not dedupe.get_all_known_hashes():
        logger.info("DB is empty — seeding from Google Sheet to prevent duplicate writes")
        try:
            sheet_rows = sheets_writer.read_all_listings()
            seeded = dedupe.seed_from_sheet_rows(sheet_rows)
            logger.info("Cold-start seeded %d listing(s) from sheet", seeded)
        except Exception as exc:
            logger.warning("Sheet seeding failed (continuing without seed): %s", exc)

    # ── Step 1: Scrape ────────────────────────────────────────────────────────
    scraper_classes = [
        SpotahomeScraper,
        HousingAnywhereScraper,
        UniplacesScraper,
        IdealistaScraper,
        ImmobiliareScraper,
    ]

    this_run_listings: list = []
    for scraper_cls in scraper_classes:
        try:
            scraper = scraper_cls(config, eur_budget_group, eur_budget_couple)
            results = scraper.scrape()
            logger.info("%s returned %d candidate(s)", scraper.name, len(results))
            this_run_listings.extend(results)
        except Exception as exc:
            logger.error("Scraper %s failed: %s", scraper_cls.__name__, exc, exc_info=True)

    # ── Step 2: Deduplication → new listings ─────────────────────────────────
    new_listings = dedupe.filter_new(this_run_listings)
    logger.info("%d new listing(s) after deduplication", len(new_listings))

    # ── Step 3: Geocode new listings ──────────────────────────────────────────
    for listing in new_listings:
        if listing.neighborhood == "Milan":
            # No target neighborhood detected — centroid fallback only, skip Nominatim
            listing.lat = config["cattolica_lat"]
            listing.lng = config["cattolica_lng"]
            continue
        address = getattr(listing, "address", None) or listing.neighborhood
        listing.lat, listing.lng = geocoder.geocode(
            listing.listing_hash(), address, listing.neighborhood
        )

    # ── Step 3b: Distance filter — drop listings geocoded too far from Cattolica ─
    max_km = config.get("filters", {}).get("max_distance_from_cattolica_km")
    if max_km:
        before = len(new_listings)
        new_listings = [
            l for l in new_listings
            if l.lat is None or l.lng is None or
            _haversine_km(l.lat, l.lng, config["cattolica_lat"], config["cattolica_lng"]) <= max_km
        ]
        dropped = before - len(new_listings)
        if dropped:
            logger.info("Distance filter: dropped %d listing(s) > %.1f km from Cattolica", dropped, max_km)

    # ── Step 4: Write new listings to sheet ───────────────────────────────────
    removed_listings: list[dict] = []
    date_found = datetime.now().strftime("%m/%d/%Y")

    # Detect reactivated listings BEFORE mark_seen resets miss_count
    reactivated = dedupe.get_reactivated(this_run_listings)

    if new_listings:
        rows = [listing.to_sheet_row(date_found) for listing in new_listings]
        for attempt in range(1, 4):
            try:
                sheets_writer.append_listings(rows)
                break
            except Exception as exc:
                logger.error("Sheets write attempt %d/3 failed: %s", attempt, exc)
                if attempt == 3:
                    logger.critical("All Sheets retries exhausted — exiting with error.")
                    sys.exit(1)
                time.sleep(2 ** attempt)

    # Mark ALL found listings seen (resets miss_count for returning listings too)
    dedupe.mark_seen(this_run_listings)

    # Flip reactivated listings back to Active in sheet
    for record in reactivated:
        try:
            sheets_writer.update_listing_status(record["url"], "Active", "")
            logger.info("Reactivated listing: %s", record["url"])
        except Exception as exc:
            logger.error("Failed to reactivate listing in sheet: %s", exc)

    # ── Step 5: Lifecycle — absent listings ───────────────────────────────────
    this_run_hashes = {l.listing_hash() for l in this_run_listings}
    known_hashes = dedupe.get_all_known_hashes()
    absent_hashes = known_hashes - this_run_hashes

    if absent_hashes:
        dedupe.increment_miss_counts(absent_hashes)
        threshold = config.get("removed_miss_threshold", 3)
        newly_removed = dedupe.get_newly_removed(threshold)
        for record in newly_removed:
            try:
                sheets_writer.update_listing_status(
                    url=record["url"],
                    listing_status="Removed",
                    removed_date=date_found,
                )
                removed_listings.append(record)
            except Exception as exc:
                logger.error("Failed to mark listing removed in sheet: %s", exc)

    logger.info("%d listing(s) marked Removed this run", len(removed_listings))

    # ── Step 6: Regenerate map ────────────────────────────────────────────────
    try:
        map_path = map_generator.generate()
        logger.info("Map written to %s", map_path)
        _push_map_to_github(map_path, run_ts)
    except Exception as exc:
        logger.error("Map generation failed (non-fatal): %s", exc)

    # ── Step 7: Email ─────────────────────────────────────────────────────────
    if not new_listings and not removed_listings:
        logger.info("Nothing new or removed — skipping email.")
        logger.info("=== Run complete (no changes) ===")
        return

    map_url = os.getenv("RENDER_MAP_URL", "")
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    notifier = EmailNotifier(
        os.environ["GMAIL_USER"],
        os.environ["GMAIL_APP_PASSWORD"],
        [e.strip() for e in os.environ["NOTIFY_EMAILS"].split(",")],
    )
    try:
        notifier.send(new_listings, removed_listings, sheet_url, map_url, run_ts)
    except Exception as exc:
        logger.error("Email notification failed (non-fatal): %s", exc)

    logger.info(
        "=== Run complete: %d new, %d removed ===",
        len(new_listings),
        len(removed_listings),
    )


def _push_map_to_github(map_path: str, run_ts: str) -> None:
    """Commit and push the updated map to GitHub so GitHub Pages stays current."""
    token = os.getenv("GITHUB_TOKEN", "")
    repo  = os.getenv("GITHUB_REPO", "")   # e.g. "anibalrosado/milan-housing-bot"
    if not token or not repo:
        logger.debug("GitHub push skipped (GITHUB_TOKEN/GITHUB_REPO not configured)")
        return
    try:
        remote = f"https://x-access-token:{token}@github.com/{repo}.git"
        _git("config", "user.email", "milan-bot@render")
        _git("config", "user.name",  "Milan Housing Bot")
        _git("add", map_path)
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"], capture_output=True
        )
        if diff.returncode == 0:
            logger.info("Map unchanged — skipping GitHub push")
            return
        _git("commit", "-m", f"Update map [{run_ts}]")
        _git("push", remote, "HEAD:main")
        logger.info("Map pushed to GitHub Pages (%s)", repo)
    except Exception as exc:
        logger.warning("GitHub push failed (non-fatal): %s", exc)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


if __name__ == "__main__":
    run()
