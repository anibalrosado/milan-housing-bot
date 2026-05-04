"""
Wunderflats scraper — NOT APPLICABLE (Milan not in their market).

Wunderflats (furnished medium-term rentals) does not operate in Milan.
The /en/furnished-apartments/milan URL returns 503, and Milan does not
appear in their sitemap.xml. Their market is primarily German/French cities.

Confirmed via sitemap check: 2026-05-04.
"""

import logging
from .base import BaseScraper, Listing

logger = logging.getLogger(__name__)


class WunderflatsScraper(BaseScraper):
    name = "Wunderflats"

    def scrape(self) -> list[Listing]:
        logger.info(
            "Wunderflats: scraper skipped — Milan is not in Wunderflats' market"
        )
        return []
