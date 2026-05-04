"""
Base class for all scrapers. Each scraper must implement `scrape()` and
return a list of Listing objects.
"""

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Listing:
    source: str
    search_type: str           # "Group of 5" or "Couple"
    title: str
    neighborhood: str
    walk_minutes: Optional[int]
    price_eur: Optional[float]
    bedrooms: Optional[int]
    furnished: bool
    available_from: Optional[str]
    contact_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    url: str
    notes: str = ""
    address: Optional[str] = None  # full street address if available; used for geocoding
    lat: Optional[float] = None    # populated by Geocoder before sheet write
    lng: Optional[float] = None    # populated by Geocoder before sheet write

    def listing_hash(self) -> str:
        """Stable unique key: sha256(source + url)."""
        raw = f"{self.source}|{self.url}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def price_usd(self, eur_to_usd_rate: float) -> Optional[float]:
        if self.price_eur is None:
            return None
        return round(self.price_eur * eur_to_usd_rate, 2)

    def per_person_usd(self, eur_to_usd_rate: float) -> Optional[float]:
        usd = self.price_usd(eur_to_usd_rate)
        if usd is None:
            return None
        divisor = 5 if self.search_type == "Group of 5" else 2
        return round(usd / divisor, 2)

    # Keep for backwards compat (used in notifier before fx_rate available)
    def per_person_eur(self) -> Optional[float]:
        if self.price_eur is None:
            return None
        divisor = 5 if self.search_type == "Group of 5" else 2
        return round(self.price_eur / divisor, 2)

    def to_sheet_row(self, date_found: str, eur_to_usd_rate: float = 1.0) -> list:
        """
        Returns a list matching the sheet_columns order in config.yaml:
        Date Found | Source | Search Type | Title | Neighborhood |
        Walk to Cattolica (min) | Price ($/month) | Per Person ($/mo) | Bedrooms | Furnished |
        Available From | Listing URL |
        Status | Notes | Listing Status | Removed Date
        """
        usd = self.price_usd(eur_to_usd_rate)
        pp  = self.per_person_usd(eur_to_usd_rate)
        return [
            date_found,
            self.source,
            self.search_type,
            self.title,
            self.neighborhood,
            self.walk_minutes if self.walk_minutes is not None else "",
            round(usd) if usd is not None else "",
            round(pp)  if pp  is not None else "",
            self.bedrooms if self.bedrooms is not None else "",
            "Yes" if self.furnished else "No",
            self.available_from or "",
            self.url,
            "New",       # Status (manual dropdown — starts as New)
            self.notes,
            "Active",    # Listing Status (bot-managed)
            "",          # Removed Date (blank until removed)
        ]


class BaseScraper(ABC):
    name: str = "base"

    def __init__(self, config: dict, eur_budget_group: float, eur_budget_couple: float):
        self.config = config
        self.eur_budget_group = eur_budget_group
        self.eur_budget_couple = eur_budget_couple

    @abstractmethod
    def scrape(self) -> list[Listing]:
        """Return a list of Listing objects matching search criteria."""
        ...

    def _passes_global_filters(self, listing: Listing) -> bool:
        """
        Cross-scraper filters driven by config.yaml [filters] block.
        Returns False (and logs why) if the listing should be dropped.
        """
        cfg = self.config.get("filters", {})

        # ── Neighborhood filter ───────────────────────────────────────────────
        if cfg.get("require_known_neighborhood", False):
            if listing.neighborhood == "Milan":
                logger.debug(
                    "%s: dropped '%s' — no target neighborhood detected",
                    self.name, listing.title[:60],
                )
                return False

        # ── Availability filter ───────────────────────────────────────────────
        if cfg.get("exclude_unavailable_after_moveout", True):
            avail = _parse_date(listing.available_from)
            move_out = _parse_date(self.config["search"]["move_out"])
            if avail and move_out and avail > move_out:
                logger.debug(
                    "%s: dropped '%s' — available %s is after move-out %s",
                    self.name, listing.title[:60], listing.available_from, move_out,
                )
                return False

        return True


def _parse_date(text: str | None) -> date | None:
    """Best-effort date parse. Returns None if unparseable."""
    if not text:
        return None
    try:
        from dateutil import parser as dateutil_parser
        return dateutil_parser.parse(str(text), dayfirst=True).date()
    except Exception:
        return None
