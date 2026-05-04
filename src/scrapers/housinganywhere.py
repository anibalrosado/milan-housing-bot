"""
HousingAnywhere scraper.

Key facts:
  - Search URL:  /s/Milan--Italy/apartment-for-rent  (1BR Couple)
                 /s/Milan--Italy                     (all types, filter for 4-5BR)
  - Listing URL: /room/ut{id}/it/Milan/{street}
  - Card selector: a[href*="/room/"]
  - Card text format:
      "Apartment in Via Panfilo Castaldi, Milan\n25 m²\n1 bedroom\n€1200\n/month..."
  - Infinite scroll: page fully loads on first render (~7-20 cards visible)
  - No public API — pure DOM scrape
  - Contact info: behind messaging wall → leave Email/Phone blank, use listing URL
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
_BASE_URL = "https://housinganywhere.com"
_SEARCH_COUPLE = f"{_BASE_URL}/s/Milan--Italy/apartment-for-rent"
_SEARCH_GROUP  = f"{_BASE_URL}/s/Milan--Italy"


class HousingAnywhereScraper(BaseScraper):
    name = "HousingAnywhere"

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

                # Couple search: apartment-for-rent page (1BR)
                results.extend(
                    self._scrape_url(page, _SEARCH_COUPLE, "Couple", self.eur_budget_couple)
                )
                time.sleep(2)

                # Group of 5: broad search, filter for 4-5BR client-side
                results.extend(
                    self._scrape_url(page, _SEARCH_GROUP, "Group of 5", self.eur_budget_group)
                )
            finally:
                browser.close()

        return _dedup_by_url(results)

    # ── Per-URL scrape ─────────────────────────────────────────────────────────

    def _scrape_url(
        self, page: Page, url: str, search_type: str, max_price: float
    ) -> list[Listing]:
        try:
            page.goto(url, wait_until="load", timeout=30_000)
            time.sleep(3)
        except Exception as exc:
            logger.error("HousingAnywhere: failed to load %s: %s", url, exc)
            return []

        _scroll_to_load(page)

        cards = page.query_selector_all('a[href*="/room/"]')
        logger.info("HousingAnywhere: %d cards on %s", len(cards), url)

        listings = []
        for card in cards:
            listing = self._parse_card(card, search_type)
            if listing and self._passes_filters(listing, max_price):
                listings.append(listing)

        logger.info(
            "HousingAnywhere: %d valid listing(s) from %s", len(listings), url
        )
        return listings

    # ── Card parser ────────────────────────────────────────────────────────────

    def _parse_card(self, card, search_type: str) -> Optional[Listing]:
        try:
            href = card.get_attribute("href") or ""
            if not href:
                return None
            url = href if href.startswith("http") else f"{_BASE_URL}{href}"

            text = card.inner_text()
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if not lines:
                return None

            # Title line: "Apartment in Via ..., Milan"
            title_line = next(
                (l for l in lines if re.match(r"(Apartment|Studio|Room|Flat)\s+in\s+", l, re.I)),
                lines[0] if lines else ""
            )
            title = title_line[:200]

            # Type filter — only whole apartments for our use case
            prop_type = lines[0].split()[0].lower() if lines else ""
            if search_type == "Group of 5" and prop_type not in ("apartment", "flat"):
                return None

            # Bedrooms
            bed_match = re.search(r"(\d+)\s*bedroom", text, re.IGNORECASE)
            bedrooms = int(bed_match.group(1)) if bed_match else None

            # Assign search type from actual bedroom count
            if bedrooms is not None:
                if bedrooms in self.config["bedrooms"]["group"]:
                    search_type = "Group of 5"
                elif bedrooms in self.config["bedrooms"]["couple"]:
                    search_type = "Couple"
                else:
                    return None  # doesn't match either search

            # Price: "€1200" appears on its own line
            price_eur = None
            for line in lines:
                m = re.match(r"€\s*([\d,]+)", line)
                if m:
                    price_eur = float(m.group(1).replace(",", ""))
                    break
                # Range like "€1090 - €1190"
                m2 = re.match(r"€\s*([\d,]+)\s*[-–]\s*€\s*([\d,]+)", line)
                if m2:
                    # Use the lower bound
                    price_eur = float(m2.group(1).replace(",", ""))
                    break

            # Available from
            avail_match = re.search(r"Available\s+(?:from|now)\s*([\w\s\d]+)?", text, re.IGNORECASE)
            available_from = None
            if avail_match:
                avail_text = (avail_match.group(1) or "").strip()
                available_from = avail_text if avail_text and avail_text.lower() != "now" else None

            # Neighborhood from title address ("in Via Lanzone, Milan" → Via Lanzone)
            loc_match = re.search(r"in\s+(.+?)(?:,\s*Milan)?$", title_line, re.IGNORECASE)
            loc_text = loc_match.group(1).strip() if loc_match else title_line
            neighborhood = self._detect_neighborhood(loc_text + " " + title_line)
            walk_times = self.config.get("walk_times", {})

            return Listing(
                source=self.name,
                search_type=search_type,
                title=title,
                neighborhood=neighborhood or "Milan",
                walk_minutes=walk_times.get(neighborhood) if neighborhood else None,
                price_eur=price_eur,
                bedrooms=bedrooms,
                furnished=True,  # HousingAnywhere is always furnished
                available_from=available_from or self.config["search"]["move_in"],
                contact_name=None,
                email=None,
                phone=None,
                url=url,
            )
        except Exception as exc:
            logger.debug("HousingAnywhere: card parse error: %s", exc)
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

def _dismiss_consent(page: Page) -> None:
    page.goto(_BASE_URL, wait_until="load", timeout=25_000)
    time.sleep(3)
    for text in ["accept all", "accept cookies", "i accept", "accetta"]:
        try:
            btn = page.get_by_role("button", name=re.compile(text, re.IGNORECASE))
            if btn.count() > 0:
                btn.first.click(timeout=3_000)
                logger.info("HousingAnywhere: dismissed consent ('%s')", text)
                return
        except Exception:
            pass


def _scroll_to_load(page: Page) -> None:
    prev = 0
    for _ in range(12):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.2)
        curr = len(page.query_selector_all('a[href*="/room/"]'))
        if curr == prev and _ > 3:
            break
        prev = curr
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)


def _dedup_by_url(listings: list) -> list:
    seen: set[str] = set()
    out = []
    for l in listings:
        if l.url not in seen:
            seen.add(l.url)
            out.append(l)
    return out
