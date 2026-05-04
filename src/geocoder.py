"""
Geocoding pipeline.

Strategy (in order):
  1. Check SQLite cache via DedupeStore.get_cached_geocode()
  2a. If USE_GOOGLE_GEOCODING=true: Google Maps Geocoding API
  2b. Otherwise: Nominatim (OpenStreetMap), max 1 req/sec
  3. On failure: fall back to neighborhood centroid from config

Results cached in SQLite so each address is geocoded at most once.
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)


class Geocoder:
    def __init__(self, config: dict, dedupe_store):
        self.config = config
        self.dedupe_store = dedupe_store
        self._use_google = os.getenv("USE_GOOGLE_GEOCODING", "false").lower() == "true"
        self._google_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
        self._nominatim_url = config["geocoding"]["nominatim_url"]
        self._user_agent = config["geocoding"]["nominatim_user_agent"]
        self._delay = config["geocoding"].get("request_delay_seconds", 1.1)
        self._last_request_at: float = 0.0

    def geocode(self, listing_hash: str, address: str, neighborhood: str) -> tuple[float, float]:
        # 1. Cache hit
        cached = self.dedupe_store.get_cached_geocode(listing_hash)
        if cached:
            return cached

        # 2. Live geocode
        query = f"{address}, Milan, Italy"
        coords = None
        if self._use_google and self._google_key:
            coords = self._geocode_google(query)
        else:
            coords = self._geocode_nominatim(query)

        # 3. Fallback to neighborhood centroid
        if coords is None:
            coords = self._neighborhood_fallback(neighborhood)
            logger.debug("Geocoder: centroid fallback for '%s' → %s", address, coords)
        else:
            logger.debug("Geocoder: resolved '%s' → %s", address, coords)

        self.dedupe_store.save_geocode(listing_hash, coords[0], coords[1])
        return coords

    # ── Nominatim ──────────────────────────────────────────────────────────────

    def _geocode_nominatim(self, query: str) -> tuple[float, float] | None:
        self._rate_limit()
        try:
            resp = requests.get(
                self._nominatim_url,
                params={"q": query, "format": "json", "limit": 1, "countrycodes": "it"},
                headers={"User-Agent": self._user_agent},
                timeout=10,
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                return float(results[0]["lat"]), float(results[0]["lon"])
        except Exception as exc:
            logger.warning("Nominatim geocode failed for '%s': %s", query, exc)
        return None

    # ── Google Maps ────────────────────────────────────────────────────────────

    def _geocode_google(self, query: str) -> tuple[float, float] | None:
        self._rate_limit()
        try:
            resp = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": query, "key": self._google_key, "region": "it"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "OK" and data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                return loc["lat"], loc["lng"]
        except Exception as exc:
            logger.warning("Google geocode failed for '%s': %s", query, exc)
        return None

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        self._last_request_at = time.monotonic()

    def _neighborhood_fallback(self, neighborhood: str) -> tuple[float, float]:
        centroids = self.config.get("neighborhood_centroids", {})
        c = centroids.get(neighborhood)
        if c:
            return c["lat"], c["lng"]
        return self.config.get("cattolica_lat", 45.4625), self.config.get("cattolica_lng", 9.1801)
