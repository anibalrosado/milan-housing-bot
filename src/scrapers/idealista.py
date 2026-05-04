"""
Idealista scraper — blocked by DataDome bot detection.

Idealista.it uses DataDome with aggressive settings that block all headless
Playwright approaches (including playwright-stealth). The scraper returns []
gracefully so the rest of the pipeline runs unaffected.

If DataDome protection changes in the future, the selectors are:
  Search URL:  /en/affitto-case/milano-milano/con-bilocali-2,trilocali-3/  (Couple)
               /en/affitto-case/milano-milano/con-5-locali-o-piu/          (Group)
  Card:        article.item
  Link:        a.item-link
  Price:       span.item-price → "1,500€/month"
  Rooms:       first span.item-detail → "N rooms"  (locali; bedrooms = rooms - 1)
  Pagination:  /lista-N.htm suffix
"""

import logging
from .base import BaseScraper, Listing

logger = logging.getLogger(__name__)


class IdealistaScraper(BaseScraper):
    name = "Idealista"

    def scrape(self) -> list[Listing]:
        logger.info(
            "Idealista: skipped — site is protected by DataDome bot detection "
            "(returns 0 listings; does not affect other scrapers)"
        )
        return []
