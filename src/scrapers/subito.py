"""
Subito.it scraper — Italy's largest classifieds platform.

Uses Subito's internal JSON API (hades.subito.it) which works with a mobile
User-Agent and does not require a browser. Returns Italian-language listings
as-is (no translation).

API key facts:
  - Endpoint: https://hades.subito.it/v1/search/items
  - c=7            → category Appartamenti
  - t=u            → type In affitto (rental)
  - ci=8           → city Milano (provincia)
  - rows/start     → pagination (max 100 rows per call)
  - Features:
      /room     → locali count (Italian: 1 locale = studio, 2 = 1BR, 5 = 4BR)
      /price    → "1200 €" string
      /furnished → "Sì" / "No"
  - geo.map.address  → full street address (for geocoding)
  - geo.map.latitude / longitude → coordinates already provided!
  - urls.default     → canonical listing URL

Room mapping (locali → bedrooms):
  2 locali = 1 bedroom   → Couple search (Search B)
  5 locali = 4 bedrooms  → Group of 5 search (Search A)
  6 locali = 5 bedrooms  → Group of 5 search (Search A)
  7 locali = 6 bedrooms  → Group of 5 search (Search A, oversize but ok)

We fetch both searches separately, applying the per-search budget filter,
then combine.
"""

import logging
import re
import time
from typing import Optional

import requests

from .base import BaseScraper, Listing

logger = logging.getLogger(__name__)

_API = "https://hades.subito.it/v1/search/items"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "application/json",
    "Accept-Language": "it-IT,it;q=0.9",
    "Referer": "https://www.subito.it/",
}
_BASE_URL = "https://www.subito.it"
_ROWS_PER_PAGE = 100
_MAX_PAGES = 3
_DELAY = 3.0  # seconds between API calls (be polite)


class SubitoScraper(BaseScraper):
    name = "Subito"

    def _passes_global_filters(self, listing) -> bool:
        """
        Override: skip the require_known_neighborhood check for Subito because
        the API provides actual lat/lng coordinates. The 2.5km distance filter
        in main.py handles location filtering instead.
        """
        cfg = self.config.get("filters", {})
        # Only apply the availability date filter; skip neighborhood gate
        from .base import _parse_date
        if cfg.get("exclude_unavailable_after_moveout", True):
            avail = _parse_date(listing.available_from)
            move_out = _parse_date(self.config["search"]["move_out"])
            if avail and move_out and avail > move_out:
                return False
        return True

    def scrape(self) -> list[Listing]:
        results = []

        # Search A: Group of 5 — 5-7 locali (= 4-6 bedrooms)
        results.extend(
            self._search(
                search_type="Group of 5",
                room_min=5,
                room_max=7,
                max_price_eur=self.eur_budget_group,
            )
        )

        time.sleep(_DELAY)

        # Search B: Couple — 2-3 locali (= 1-2 bedrooms)
        results.extend(
            self._search(
                search_type="Couple",
                room_min=2,
                room_max=3,
                max_price_eur=self.eur_budget_couple,
            )
        )

        return _dedup_by_url(results)

    def _search(
        self,
        search_type: str,
        room_min: int,
        room_max: int,
        max_price_eur: float,
    ) -> list[Listing]:
        listings = []
        for page in range(_MAX_PAGES):
            start = page * _ROWS_PER_PAGE
            params = {
                "c": 7,           # Appartamenti
                "t": "u",         # In affitto
                "ci": 8,          # Milano provincia
                "rows": _ROWS_PER_PAGE,
                "start": start,
            }
            try:
                resp = requests.get(_API, headers=_HEADERS, params=params, timeout=15)
                if resp.status_code == 403:
                    if page == 0:
                        # First page rate-limited — back off and retry once
                        logger.warning("Subito: rate limited on page 1 — backing off 10s and retrying")
                        time.sleep(10)
                        resp = requests.get(_API, headers=_HEADERS, params=params, timeout=15)
                        if resp.status_code == 403:
                            logger.warning("Subito: still rate limited after retry — skipping %s", search_type)
                            break
                    else:
                        logger.warning("Subito: rate limited on page %d — stopping pagination", page + 1)
                        break
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.error("Subito API error (page %d): %s", page, exc)
                break

            ads = data.get("ads", [])
            if not ads:
                break

            for ad in ads:
                listing = self._parse_ad(ad, search_type, room_min, room_max, max_price_eur)
                if listing and self._passes_global_filters(listing):
                    listings.append(listing)

            total = data.get("count_all", 0)
            logger.debug(
                "Subito %s page %d: %d ads (total %d)",
                search_type, page + 1, len(ads), total,
            )

            if start + _ROWS_PER_PAGE >= total:
                break

            time.sleep(_DELAY)

        logger.info("Subito %s: %d listing(s) found", search_type, len(listings))
        return listings

    def _parse_ad(
        self,
        ad: dict,
        search_type: str,
        room_min: int,
        room_max: int,
        max_price_eur: float,
    ) -> Optional[Listing]:
        try:
            # Only rental apartments (category 7, type u)
            if ad.get("category", {}).get("key") != "7":
                return None
            if ad.get("type", {}).get("key") != "u":
                return None

            # Must be in Milano comune (not just provincia)
            geo = ad.get("geo", {})
            town = geo.get("town", {}).get("value", "")
            city_key = geo.get("city", {}).get("key", "")
            if city_key != "8" or town != "Milano":
                return None

            features = _parse_features(ad.get("features", []))

            # Room count filter
            rooms_raw = features.get("room")
            try:
                rooms = int(rooms_raw) if rooms_raw is not None else None
            except (ValueError, TypeError):
                rooms = None
            if rooms is None or not (room_min <= rooms <= room_max):
                return None

            # Price filter
            price_raw = features.get("price", "")
            price_eur = _parse_price(str(price_raw))
            if price_eur is None or price_eur > max_price_eur:
                return None

            # Furnished
            furnished_raw = features.get("furnished", "")
            furnished = str(furnished_raw).strip().lower() in ("sì", "si", "1", "yes")

            # Title & URL
            title = ad.get("subject", "").strip()
            url = ad.get("urls", {}).get("default", "")
            if not url:
                return None
            if not url.startswith("http"):
                url = _BASE_URL + url

            # Address & coordinates from geo.map
            geo_map = geo.get("map", {})
            address = geo_map.get("address", "")
            lat = _safe_float(geo_map.get("latitude"))
            lng = _safe_float(geo_map.get("longitude"))

            # Neighborhood detection
            neighborhood = _detect_neighborhood(
                f"{title} {address} {town}",
                self.config.get("neighborhoods", []),
            )

            # Bedrooms: locali - 1 (living room) approximately
            bedrooms = max(1, rooms - 1) if rooms else None

            # Walk time
            walk_minutes = self.config.get("walk_times", {}).get(neighborhood)

            # Phone (sometimes exposed)
            advertiser = ad.get("advertiser", {})
            phone = advertiser.get("phone", "") or ""

            return Listing(
                source="Subito",
                search_type=search_type,
                title=title,
                neighborhood=neighborhood,
                walk_minutes=walk_minutes,
                price_eur=price_eur,
                bedrooms=bedrooms,
                furnished=furnished,
                available_from=None,  # rarely in API; skip
                contact_name=advertiser.get("name", "") or None,
                email=None,
                phone=phone or None,
                url=url,
                notes="",
                address=address or None,
                lat=lat,
                lng=lng,
            )

        except Exception as exc:
            logger.debug("Subito: failed to parse ad %s: %s", ad.get("urn", "?"), exc)
            return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_features(features_list: list) -> dict:
    """Convert features array → {key: value} dict."""
    out = {}
    for f in features_list:
        key = f.get("uri", "").split("/")[-1]
        values = f.get("values", [])
        if values:
            out[key] = values[0].get("value")
    return out


def _parse_price(text: str) -> Optional[float]:
    """Extract numeric price from '1200 €' or '1.200 €' etc."""
    cleaned = re.sub(r"[^\d.,]", "", text).replace(".", "").replace(",", ".")
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if val not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _detect_neighborhood(text: str, neighborhoods: list) -> str:
    """Return first matching neighborhood name found in text, else 'Milan'."""
    text_lower = text.lower()
    for nb in neighborhoods:
        if nb.lower() in text_lower:
            return nb
    return "Milan"


def _dedup_by_url(listings: list) -> list:
    seen = set()
    out = []
    for l in listings:
        if l.url not in seen:
            seen.add(l.url)
            out.append(l)
    return out
