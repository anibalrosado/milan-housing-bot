"""
Erasmusu.com scraper — SKIPPED (Spotahome reseller).

Erasmusu aggregates Spotahome listings exclusively for the Milan market.
Every listing on Erasmusu is already captured by the Spotahome scraper,
so adding this source would only create duplicates.

Confirmed: 1,280+ Spotahome photo/URL references on a single Erasmusu
Milan search results page (2026-05-04 investigation).
"""

import logging
from .base import BaseScraper, Listing

logger = logging.getLogger(__name__)


class ErasmusuScraper(BaseScraper):
    name = "Erasmusu"

    def scrape(self) -> list[Listing]:
        logger.info(
            "Erasmusu: scraper skipped — site is a Spotahome reseller; "
            "all listings are already captured by the Spotahome scraper"
        )
        return []
