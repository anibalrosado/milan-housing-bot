"""
Spotahome scraper.

Key facts discovered via DOM inspection:
  - Search URLs: /s/milan/for-rent:apartments/bedrooms:3more  (4+ BR)
                 /s/milan/for-rent:apartments/bedrooms:1      (1 BR)
  - Listing card selector: div.l-list__item
  - Listing link:          a[href*="/milan/for-rent:"]
  - Card text format:      "... 4-bedroom apartment for rent in Neighbourhood, Milan\n\n3700 €/month ..."
  - Pagination:            /s/milan/for-rent:apartments/bedrooms:3more/page:2
"""

import logging
import re
import time
from typing import Optional

from playwright.sync_api import sync_playwright, Page

from .base import BaseScraper, Listing

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_BASE_URL = "https://www.spotahome.com"

# bedrooms:3more covers 3+ bedrooms — we filter to 4/5 ourselves
_SEARCH_URLS = {
    "Group of 5": f"{_BASE_URL}/s/milan/for-rent:apartments/bedrooms:3more",
    "Couple":     f"{_BASE_URL}/s/milan/for-rent:apartments/bedrooms:1",
}
_PAGES_TO_SCRAPE = 3


class SpotahomeScraper(BaseScraper):
    name = "Spotahome"

    def scrape(self) -> list[Listing]:
        results = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            try:
                page = context.new_page()
                _dismiss_consent_on_first_load(page)

                for search_type, base_url in _SEARCH_URLS.items():
                    budget = (
                        self.eur_budget_group
                        if search_type == "Group of 5"
                        else self.eur_budget_couple
                    )
                    for page_num in range(1, _PAGES_TO_SCRAPE + 1):
                        url = base_url if page_num == 1 else f"{base_url}/page:{page_num}"
                        listings = self._scrape_page(page, url, search_type, budget)
                        results.extend(listings)
                        if len(listings) == 0:
                            break  # no more results
                        time.sleep(2)

            finally:
                browser.close()

        return _dedup_by_url(results)

    # ── Per-page scrape ────────────────────────────────────────────────────────

    def _scrape_page(
        self, page: Page, url: str, search_type: str, max_price: float
    ) -> list[Listing]:
        try:
            page.goto(url, wait_until="load", timeout=45_000)
            time.sleep(3)
        except Exception as exc:
            logger.error("Spotahome: failed to load %s: %s", url, exc)
            return []

        # Wait for listing cards
        try:
            page.wait_for_selector("div.l-list__item", timeout=12_000)
        except Exception:
            logger.warning("Spotahome: no cards on %s", url)
            return []

        cards = page.query_selector_all("div.l-list__item")
        logger.info("Spotahome: %d cards on %s", len(cards), url)

        listings = []
        for card in cards:
            listing = self._parse_card(card, search_type)
            if listing and self._passes_filters(listing, max_price):
                listings.append(listing)

        logger.info(
            "Spotahome: %d valid listing(s) from %s after filtering", len(listings), url
        )
        return listings

    # ── Card parser ────────────────────────────────────────────────────────────

    def _parse_card(self, card, search_type: str) -> Optional[Listing]:
        try:
            link_el = card.query_selector("a[href*='/milan/for-rent:']")
            if not link_el:
                return None
            href = link_el.get_attribute("href") or ""
            url = href if href.startswith("http") else f"{_BASE_URL}{href}"

            text = card.inner_text()

            # Title: "N-bedroom apartment for rent in Location, Milan"
            title_match = re.search(
                r"(\d+[\-\s]bedroom\s+\w+\s+for\s+rent[^\n]+)", text, re.IGNORECASE
            )
            title = title_match.group(1).strip() if title_match else _first_long_line(text)
            if not title:
                return None

            # Bedrooms from title
            bed_match = re.search(r"(\d+)[\-\s]bedroom", title, re.IGNORECASE)
            bedrooms = int(bed_match.group(1)) if bed_match else None

            # Search type override based on actual bedroom count
            if bedrooms is not None:
                if bedrooms in self.config["bedrooms"]["group"]:
                    search_type = "Group of 5"
                elif bedrooms in self.config["bedrooms"]["couple"]:
                    search_type = "Couple"
                else:
                    return None  # doesn't match either search

            # Price: "3700 €/month"
            price_match = re.search(r"([\d,]+)\s*€\s*/\s*month", text, re.IGNORECASE)
            price_eur = float(price_match.group(1).replace(",", "")) if price_match else None

            # Neighborhood from title: "for rent in <Location>, Milan"
            loc_match = re.search(r"for\s+rent\s+in\s+([^,\n]+)", title, re.IGNORECASE)
            loc_text = loc_match.group(1).strip() if loc_match else title
            neighborhood = self._detect_neighborhood(loc_text + " " + text)

            walk_times = self.config.get("walk_times", {})

            return Listing(
                source=self.name,
                search_type=search_type,
                title=title[:200],
                neighborhood=neighborhood or "Milan",
                walk_minutes=walk_times.get(neighborhood) if neighborhood else None,
                price_eur=price_eur,
                bedrooms=bedrooms,
                furnished=True,  # Spotahome requires furnished
                available_from=self.config["search"]["move_in"],
                contact_name=None,
                email=None,
                phone=None,
                url=url,
            )
        except Exception as exc:
            logger.debug("Spotahome: card parse error: %s", exc)
            return None

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _passes_filters(self, listing: Listing, max_price: float) -> bool:
        if listing.price_eur and listing.price_eur > max_price:
            return False
        if listing.search_type == "Group of 5":
            if listing.bedrooms is not None and listing.bedrooms not in self.config["bedrooms"]["group"]:
                return False
        return self._passes_global_filters(listing)

    def _detect_neighborhood(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        for n in self.config["neighborhoods"]:
            if n.lower() in text_lower:
                return n
        return None


# ── Module helpers ─────────────────────────────────────────────────────────────

def _dismiss_consent_on_first_load(page: Page) -> None:
    """Load homepage once to set consent cookie, then dismiss banner."""
    page.goto(_BASE_URL, wait_until="load", timeout=30_000)
    time.sleep(3)
    for text in ["accept all", "accept cookies", "i accept", "accetta"]:
        try:
            btn = page.get_by_role("button", name=re.compile(text, re.IGNORECASE))
            if btn.count() > 0:
                btn.first.click(timeout=3_000)
                logger.info("Spotahome: dismissed consent ('%s')", text)
                time.sleep(1)
                return
        except Exception:
            pass
    for sel in ["#onetrust-accept-btn-handler", "[class*='accept'][class*='cookie']"]:
        try:
            el = page.query_selector(sel)
            if el:
                el.click(timeout=3_000)
                logger.info("Spotahome: dismissed consent via %s", sel)
                return
        except Exception:
            pass


def _dedup_by_url(listings: list) -> list:
    seen: set[str] = set()
    out = []
    for l in listings:
        if l.url not in seen:
            seen.add(l.url)
            out.append(l)
    return out


def _first_long_line(text: str, min_len: int = 20) -> str:
    for line in text.splitlines():
        line = line.strip()
        if len(line) >= min_len and not line.startswith("■") and "€" not in line:
            return line
    return ""
