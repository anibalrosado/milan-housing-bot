"""
Bakeca.it scraper — CURRENTLY BLOCKED.

Bakeca.it is protected by Cloudflare (HTTP 403 / "Verifica" challenge page)
for all automated requests including headless browsers.

To revive: investigate Cloudflare bypass options (e.g. cloudscraper library,
undetected-chromium, or a residential proxy). Until then this scraper returns
0 results and logs a warning so the zero-result health tracker fires after
5 consecutive empty runs.
"""

import logging
from .base import BaseScraper, Listing

logger = logging.getLogger(__name__)


class BakecaScraper(BaseScraper):
    name = "Bakeca"

    def scrape(self) -> list[Listing]:
        logger.warning(
            "Bakeca: scraper is disabled — site is protected by Cloudflare "
            "(returns 403 for all automated requests)"
        )
        return []
