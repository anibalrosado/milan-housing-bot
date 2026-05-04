"""
SQLite-backed deduplication and listing lifecycle tracking.

Schema (listings table):
  hash        TEXT PRIMARY KEY  — sha256(source|url)
  source      TEXT
  url         TEXT
  search_type TEXT
  first_seen  TEXT              — ISO date
  last_seen   TEXT              — ISO date, updated each run the listing appears
  miss_count  INTEGER DEFAULT 0 — consecutive absent runs; resets to 0 on re-find
  lat         REAL              — cached geocode (nullable)
  lng         REAL              — cached geocode (nullable)
  geocoded_at TEXT              — ISO date of last geocode attempt (nullable)
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS listings (
    hash        TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    url         TEXT NOT NULL,
    search_type TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    miss_count  INTEGER NOT NULL DEFAULT 0,
    lat         REAL,
    lng         REAL,
    geocoded_at TEXT
)
"""


class DedupeStore:
    def __init__(self, db_path: str = "listings.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(_CREATE_TABLE)

    # ── Step 2: deduplication ─────────────────────────────────────────────────

    def filter_new(self, listings: list) -> list:
        """Return only listings whose hash is not yet in the DB."""
        known = self.get_all_known_hashes()
        return [l for l in listings if l.listing_hash() not in known]

    def mark_seen(self, listings: list) -> None:
        """
        Insert new listings (miss_count=0) or reset miss_count=0 and update
        last_seen for listings that reappeared after being absent.
        """
        today = date.today().isoformat()
        with self._conn() as conn:
            for listing in listings:
                h = listing.listing_hash()
                conn.execute(
                    """
                    INSERT INTO listings
                        (hash, source, url, search_type, first_seen, last_seen, miss_count)
                    VALUES (?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(hash) DO UPDATE SET
                        last_seen  = excluded.last_seen,
                        miss_count = 0
                    """,
                    (h, listing.source, listing.url, listing.search_type, today, today),
                )
        logger.debug("mark_seen: persisted %d listing(s)", len(listings))

    def get_all_known_hashes(self) -> set[str]:
        """Return all hashes currently tracked in the DB."""
        with self._conn() as conn:
            rows = conn.execute("SELECT hash FROM listings").fetchall()
        return {r["hash"] for r in rows}

    # ── Step 2.5: lifecycle ───────────────────────────────────────────────────

    def increment_miss_counts(self, absent_hashes: set[str]) -> None:
        """Increment miss_count for every hash in absent_hashes."""
        if not absent_hashes:
            return
        with self._conn() as conn:
            conn.executemany(
                "UPDATE listings SET miss_count = miss_count + 1 WHERE hash = ?",
                [(h,) for h in absent_hashes],
            )
        logger.debug("Incremented miss_count for %d listing(s)", len(absent_hashes))

    def get_reactivated(self, listings: list) -> list[dict]:
        """
        Return DB records for listings in this run that have miss_count > 0.
        These were previously absent but have returned — flip them back to Active.
        Must be called BEFORE mark_seen() resets miss_count to 0.
        """
        hashes = [l.listing_hash() for l in listings]
        if not hashes:
            return []
        placeholders = ",".join("?" * len(hashes))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT hash, source, url, search_type FROM listings "
                f"WHERE hash IN ({placeholders}) AND miss_count > 0",
                hashes,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_newly_removed(self, threshold: int = 3) -> list[dict]:
        """
        Return rows whose miss_count equals exactly `threshold`.
        These are the listings to flip to Removed in the sheet this run.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT hash, source, url, search_type FROM listings WHERE miss_count = ?",
                (threshold,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Render cold-start seeding ─────────────────────────────────────────────

    def seed_from_sheet_rows(self, rows: list[dict]) -> int:
        """
        Pre-populate DB from Google Sheet rows so a cold-start container doesn't
        re-add all existing listings as "new".  Uses INSERT OR IGNORE so rows
        already in the DB (local dev) are left untouched.
        Returns the number of rows actually inserted.
        """
        import hashlib
        today = date.today().isoformat()
        params = []
        for row in rows:
            source = row.get("Source", "")
            url    = row.get("Listing URL", "")
            if not source or not url:
                continue
            h = hashlib.sha256(f"{source}|{url}".encode()).hexdigest()
            params.append((h, source, url, row.get("Search Type", ""), today, today))

        if not params:
            return 0

        with self._conn() as conn:
            before = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            conn.executemany(
                """INSERT OR IGNORE INTO listings
                       (hash, source, url, search_type, first_seen, last_seen, miss_count)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                params,
            )
            after = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        return after - before

    # ── Step 9.5: geocoding cache ─────────────────────────────────────────────

    def get_cached_geocode(self, listing_hash: str) -> tuple[float, float] | None:
        """Return (lat, lng) if this listing has been geocoded, else None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT lat, lng FROM listings WHERE hash = ? AND lat IS NOT NULL",
                (listing_hash,),
            ).fetchone()
        return (row["lat"], row["lng"]) if row else None

    def save_geocode(self, listing_hash: str, lat: float, lng: float) -> None:
        """Cache geocode result for a listing."""
        today = date.today().isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE listings SET lat = ?, lng = ?, geocoded_at = ? WHERE hash = ?",
                (lat, lng, today, listing_hash),
            )
