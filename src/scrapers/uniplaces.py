"""
Uniplaces scraper.

Key facts:
  - Search URL:  /accommodation/milan/f/entire-house  (whole apartments only)
  - Pagination:  ?page=N
  - Card selector: div[class*="sc-b556105b-7"]  (contains full listing text)
  - Link selector: a[href*="/accommodation/milan/"] inside card
  - Card text format:
      "Up to 2 people • 1 bedroom
       Recently renovated 1-bedroom apartment in NO.LO

       From 14 Jun 2026

       €1,000 /month"
  - Contact: behind messaging wall → leave Email/Phone blank
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
_BASE_URL  = "https://www.uniplaces.com"
_SEARCH    = f"{_BASE_URL}/accommodation/milan/f/entire-house"
_MAX_PAGES = 5


class UniplacesScraper(BaseScraper):
    name = "Uniplaces"

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
                _dismiss_consent(page)

                for page_num in range(1, _MAX_PAGES + 1):
                    url = _SEARCH if page_num == 1 else f"{_SEARCH}?page={page_num}"
                    listings = self._scrape_page(page, url)
                    results.extend(listings)
                    if not listings:
                        logger.info("Uniplaces: no cards on page %d — stopping", page_num)
                        break
                    time.sleep(2)

            finally:
                browser.close()

        return _dedup_by_url(results)

    # ── Per-page ───────────────────────────────────────────────────────────────

    def _scrape_page(self, page: Page, url: str) -> list[Listing]:
        try:
            page.goto(url, wait_until="load", timeout=30_000)
            time.sleep(3)
        except Exception as exc:
            logger.error("Uniplaces: failed to load %s: %s", url, exc)
            return []

        # Wait for listing cards
        try:
            page.wait_for_selector("div[class*='sc-b556105b-7']", timeout=10_000)
        except Exception:
            logger.warning("Uniplaces: no listing cards found on %s", url)
            return []

        cards = page.query_selector_all("div[class*='sc-b556105b-7']")
        logger.info("Uniplaces: %d cards on %s", len(cards), url)

        listings = []
        for card in cards:
            listing = self._parse_card(card)
            if listing and self._passes_filters(listing):
                listings.append(listing)

        logger.info("Uniplaces: %d valid listing(s) from %s", len(listings), url)
        return listings

    # ── Card parser ────────────────────────────────────────────────────────────

    def _parse_card(self, card) -> Optional[Listing]:
        try:
            # URL from the link inside the card
            link_el = card.query_selector("a[href*='/accommodation/milan/']")
            if not link_el:
                return None
            href = link_el.get_attribute("href") or ""
            # Strip #search-id= tracking param
            url = re.sub(r"#.*$", "", href)
            url = url if url.startswith("http") else f"{_BASE_URL}{url}"

            text = card.inner_text()
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if not lines:
                return None

            # Line 0: "Up to N people • M bedrooms"
            header = lines[0]
            bed_match = re.search(r"(\d+)\s*bedroom", header, re.IGNORECASE)
            bedrooms = int(bed_match.group(1)) if bed_match else None

            # Assign search type
            search_type = self._search_type_for_bedrooms(bedrooms)
            if not search_type:
                return None

            # Line 1: title
            title = lines[1] if len(lines) > 1 else header

            # Price: "€1,150 /month" or "€900 - €1,000 /month"
            price_eur = None
            for line in lines:
                m = re.match(r"€\s*([\d,]+)", line)
                if m:
                    price_eur = float(m.group(1).replace(",", ""))
                    break

            # Available from: "From 14 Jun 2026"
            available_from = None
            for line in lines:
                m = re.match(r"From\s+(.+)", line, re.IGNORECASE)
                if m:
                    available_from = m.group(1).strip()
                    break

            # Neighborhood from title text
            neighborhood = self._detect_neighborhood(" ".join(lines))
            walk_times = self.config.get("walk_times", {})

            return Listing(
                source=self.name,
                search_type=search_type,
                title=title[:200],
                neighborhood=neighborhood or "Milan",
                walk_minutes=walk_times.get(neighborhood) if neighborhood else None,
                price_eur=price_eur,
                bedrooms=bedrooms,
                furnished=True,  # Uniplaces listings are furnished
                available_from=available_from or self.config["search"]["move_in"],
                contact_name=None,
                email=None,
                phone=None,
                url=url,
            )
        except Exception as exc:
            logger.debug("Uniplaces: card parse error: %s", exc)
            return None

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _passes_filters(self, listing: Listing) -> bool:
        if listing.search_type == "Group of 5":
            if listing.price_eur and listing.price_eur > self.eur_budget_group:
                return False
        elif listing.search_type == "Couple":
            if listing.price_eur and listing.price_eur > self.eur_budget_couple:
                return False
        return self._passes_global_filters(listing)

    def _search_type_for_bedrooms(self, bedrooms: Optional[int]) -> Optional[str]:
        if bedrooms is None:
            return None
        if bedrooms in self.config["bedrooms"]["group"]:
            return "Group of 5"
        if bedrooms in self.config["bedrooms"]["couple"]:
            return "Couple"
        return None

    def _detect_neighborhood(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        for n in self.config["neighborhoods"]:
            if n.lower() in text_lower:
                return n
        return None


# ── Module helpers ─────────────────────────────────────────────────────────────

def _dismiss_consent(page: Page) -> None:
    page.goto(_BASE_URL, wait_until="load", timeout=25_000)
    time.sleep(3)
    for text in ["accept all", "accept cookies", "i accept", "accetta"]:
        try:
            btn = page.get_by_role("button", name=re.compile(text, re.IGNORECASE))
            if btn.count() > 0:
                btn.first.click(timeout=3_000)
                logger.info("Uniplaces: dismissed consent ('%s')", text)
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
