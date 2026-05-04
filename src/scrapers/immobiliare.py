"""
Immobiliare scraper — blocked by DataDome bot detection.

Immobiliare.it uses DataDome with aggressive settings that block all headless
Playwright approaches. The scraper returns [] gracefully so the rest of the
pipeline runs unaffected.

If DataDome protection changes in the future, the site uses Next.js SSR and
embeds all listing data in a __NEXT_DATA__ JSON blob. Selectors:
  Search URL:  /affitto-case/milano/?idCategoria=1&idContratto=2
               Add &nMinimoVani=4&nMassimoVani=5 for 4-5BR
               Add &nMinimoVani=1&nMassimoVani=2 for 1-2BR
               Add &pag=N for pagination
  JSON path:   data["props"]["pageProps"]["dehydratedState"]
               ["queries"][0]["state"]["data"]["results"]
  Price:       result["realEstate"]["price"]["value"]
  Bedrooms:    result["realEstate"]["properties"][0]["bedRoomsNumber"]
  URL:         result["seo"]["url"]
  Lat/Lng:     result["realEstate"]["properties"][0]["location"]["latitude/longitude"]
"""

import logging
from .base import BaseScraper, Listing

logger = logging.getLogger(__name__)


class ImmobiliareScraper(BaseScraper):
    name = "Immobiliare"

    def scrape(self) -> list[Listing]:
        logger.info(
            "Immobiliare: skipped — site is protected by DataDome bot detection "
            "(returns 0 listings; does not affect other scrapers)"
        )
        return []
