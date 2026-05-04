"""
Gmail email notifier.

Two email types:
  1. send()       — alert on new/removed listings (fires only when something changed)
  2. send_recap() — nightly digest of all active listings (always fires once per day)

Both include a prominent map link at the top.
Requires GMAIL_USER and GMAIL_APP_PASSWORD in env.
Uses smtplib with SMTP_SSL on port 465.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_GREEN = "#1a6e3c"

_BASE_STYLES = """
body{font-family:Arial,sans-serif;font-size:14px;color:#222;max-width:700px;margin:0 auto}
h2{color:#1a6e3c;border-bottom:2px solid #1a6e3c;padding-bottom:6px}
h3{color:#444;margin-top:20px}
h4{color:#555;margin:14px 0 4px}
table{border-collapse:collapse;width:100%;margin:10px 0}
th{background:#1a6e3c;color:#fff;padding:8px 10px;text-align:left}
td{padding:7px 10px;border-bottom:1px solid #ddd}
tr:hover{background:#f5f5f5}
.price{font-weight:bold;color:#1a6e3c}
.removed-table th{background:#c0392b}
a{color:#1a6e3c}
.footer{font-size:12px;color:#888;margin-top:24px;border-top:1px solid #ddd;padding-top:10px}
.btn{display:inline-block;padding:10px 20px;background:#1a6e3c;color:#fff!important;
     text-decoration:none;border-radius:4px;margin:8px 4px;font-weight:bold}
.btn-map{background:#1a56a0}
.map-banner{background:#eaf3fb;border:1px solid #b3d4f0;border-radius:6px;
            padding:14px 18px;margin:16px 0;text-align:center}
.map-banner p{margin:0 0 10px;color:#333;font-size:13px}
"""


class EmailNotifier:
    def __init__(self, gmail_user: str, app_password: str, recipients: list[str]):
        self.gmail_user = gmail_user
        self.app_password = app_password
        self.recipients = recipients

    def send(
        self,
        new_listings: list,
        removed_listings: list,
        sheet_url: str,
        map_url: str,
        run_timestamp: str,
    ) -> None:
        """Alert email — only fires when new or removed listings exist."""
        if not new_listings and not removed_listings:
            logger.info("Notifier: nothing to report — skipping alert email")
            return
        self._send_message(
            subject=_build_subject(new_listings, removed_listings),
            html_body=_build_alert_html(new_listings, removed_listings, sheet_url, map_url, run_timestamp),
            text_body=_build_alert_text(new_listings, removed_listings, sheet_url, map_url, run_timestamp),
        )
        logger.info(
            "Notifier: alert email sent — %d new, %d removed",
            len(new_listings), len(removed_listings),
        )

    def send_recap(
        self,
        active_listings: list[dict],
        sheet_url: str,
        map_url: str,
        run_timestamp: str,
    ) -> None:
        """Nightly digest — always sends, summarises all active listings."""
        n = len(active_listings)
        subject = f"Milan Housing: nightly recap — {n} active listing{'s' if n != 1 else ''}"
        self._send_message(
            subject=subject,
            html_body=_build_recap_html(active_listings, sheet_url, map_url, run_timestamp),
            text_body=_build_recap_text(active_listings, sheet_url, map_url, run_timestamp),
        )
        logger.info("Notifier: nightly recap sent — %d active listing(s)", n)

    def _send_message(self, subject: str, html_body: str, text_body: str) -> None:
        if not self.gmail_user or not self.app_password:
            logger.warning("Notifier: GMAIL credentials not set — skipping email")
            return
        if not self.recipients:
            logger.warning("Notifier: no recipients configured — skipping email")
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.gmail_user
        msg["To"] = ", ".join(self.recipients)
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(self.gmail_user, self.app_password)
                smtp.sendmail(self.gmail_user, self.recipients, msg.as_string())
            logger.info("Notifier: email sent to %s", ", ".join(self.recipients))
        except Exception as exc:
            logger.error("Notifier: failed to send email: %s", exc)


# ── Subject ────────────────────────────────────────────────────────────────────

def _build_subject(new_listings: list, removed_listings: list) -> str:
    n = len(new_listings)
    r = len(removed_listings)
    if n and r:
        return f"Milan Housing: {n} new, {r} removed"
    if n:
        noun = "listing" if n == 1 else "listings"
        return f"Milan Housing: {n} new {noun} found"
    noun = "listing" if r == 1 else "listings"
    return f"Milan Housing: {r} {noun} removed"


# ── Shared HTML fragments ──────────────────────────────────────────────────────

def _html_open(title: str) -> str:
    return (
        f'<!DOCTYPE html><html><head><meta charset="UTF-8">'
        f"<style>{_BASE_STYLES}</style></head><body>"
        f"<h2>🏠 {_esc(title)}</h2>"
    )

def _html_map_banner(map_url: str) -> str:
    if not map_url:
        return ""
    return (
        f"<div class='map-banner'>"
        f"<p>View all active listings on the interactive map</p>"
        f"<a class='btn btn-map' href='{map_url}'>🗺️ Open Map</a>"
        f"</div>"
    )

def _html_action_buttons(sheet_url: str, map_url: str) -> str:
    parts = ["<div style='margin:20px 0'>"]
    if map_url:
        parts.append(f"<a class='btn btn-map' href='{map_url}'>🗺️ View Map</a>")
    if sheet_url:
        parts.append(f"<a class='btn' href='{sheet_url}'>📊 Open Sheet</a>")
    parts.append("</div>")
    return "".join(parts)

def _html_footer(run_timestamp: str) -> str:
    return (
        f"<div class='footer'>Run at {_esc(run_timestamp)} · Milan Housing Bot</div>"
        f"</body></html>"
    )


# ── Alert email (new / removed) ────────────────────────────────────────────────

def _build_alert_html(
    new_listings: list,
    removed_listings: list,
    sheet_url: str,
    map_url: str,
    run_timestamp: str,
) -> str:
    parts = [_html_open("Milan Housing Bot — New Alert"), _html_map_banner(map_url)]

    if new_listings:
        parts.append(f"<h3>✅ {len(new_listings)} New Listing(s)</h3>")
        groups: dict[str, list] = {}
        for l in new_listings:
            groups.setdefault(l.search_type, []).append(l)
        for search_type, items in groups.items():
            parts.append(f"<h4>{search_type} ({len(items)})</h4>")
            parts.append(
                "<table><tr><th>Title</th><th>Beds</th><th>Price/mo</th>"
                "<th>Per Person</th><th>Neighborhood</th><th>Walk</th><th>Source</th></tr>"
            )
            for l in items:
                price_str = f"€{l.price_eur:.0f}" if l.price_eur else "—"
                pp = l.per_person_eur()
                pp_str = f"€{pp:.0f}" if pp else "—"
                beds_str = str(l.bedrooms) if l.bedrooms else "?"
                walk_str = f"{l.walk_minutes} min" if l.walk_minutes else "—"
                title_link = f'<a href="{l.url}">{_esc(l.title[:60])}</a>'
                parts.append(
                    f"<tr><td>{title_link}</td><td>{beds_str}</td>"
                    f"<td class='price'>{price_str}</td><td>{pp_str}</td>"
                    f"<td>{_esc(l.neighborhood)}</td>"
                    f"<td>{walk_str}</td><td>{_esc(l.source)}</td></tr>"
                )
            parts.append("</table>")

    if removed_listings:
        parts.append(f"<h3>🗑️ {len(removed_listings)} Listing(s) Removed</h3>")
        parts.append(
            "<table class='removed-table'>"
            "<tr><th>Source</th><th>Search Type</th><th>URL</th></tr>"
        )
        for r in removed_listings:
            url = r.get("url", "")
            parts.append(
                f"<tr><td>{_esc(r.get('source',''))}</td>"
                f"<td>{_esc(r.get('search_type',''))}</td>"
                f"<td><a href='{url}'>{url[:60]}</a></td></tr>"
            )
        parts.append("</table>")

    parts.append(_html_action_buttons(sheet_url, map_url))
    parts.append(_html_footer(run_timestamp))
    return "".join(parts)


def _build_alert_text(
    new_listings: list,
    removed_listings: list,
    sheet_url: str,
    map_url: str,
    run_timestamp: str,
) -> str:
    lines = ["Milan Housing Bot — New Alert", "=" * 40, ""]
    if map_url:
        lines += [f"MAP: {map_url}", ""]

    if new_listings:
        lines.append(f"NEW LISTINGS ({len(new_listings)})")
        lines.append("-" * 30)
        for l in new_listings:
            pp = l.per_person_eur()
            price_str = f"€{l.price_eur:.0f}/mo" if l.price_eur else "N/A"
            pp_str = f"€{pp:.0f}/pp" if pp else ""
            beds_str = f"{l.bedrooms}BR" if l.bedrooms else "?BR"
            lines.append(f"[{l.search_type}] {l.title[:60]}")
            lines.append(f"  {beds_str} | {price_str} {pp_str} | {l.neighborhood} | {l.source}")
            lines.append(f"  {l.url}")
            lines.append("")

    if removed_listings:
        lines.append(f"REMOVED LISTINGS ({len(removed_listings)})")
        lines.append("-" * 30)
        for r in removed_listings:
            lines.append(f"[{r.get('search_type','')}] {r.get('source','')} — {r.get('url','')}")
        lines.append("")

    if sheet_url:
        lines.append(f"Sheet: {sheet_url}")
    lines.append(f"Run at: {run_timestamp}")
    return "\n".join(lines)


# ── Nightly recap email ────────────────────────────────────────────────────────

def _build_recap_html(
    active_listings: list[dict],
    sheet_url: str,
    map_url: str,
    run_timestamp: str,
) -> str:
    n = len(active_listings)
    parts = [_html_open(f"Milan Housing — Nightly Recap ({n} active)"), _html_map_banner(map_url)]

    groups: dict[str, list] = {}
    for row in active_listings:
        groups.setdefault(row.get("Search Type", "Other"), []).append(row)

    for search_type, items in groups.items():
        parts.append(f"<h3>{search_type} — {len(items)} listing(s)</h3>")
        parts.append(
            "<table><tr><th>Title</th><th>Beds</th><th>Price/mo</th>"
            "<th>Per Person</th><th>Neighborhood</th><th>Walk</th><th>Source</th></tr>"
        )
        for row in items:
            title = _esc(str(row.get("Title", ""))[:60])
            url   = row.get("Listing URL", "")
            title_cell = f'<a href="{url}">{title}</a>' if url else title

            price_raw = row.get("Price (€/month)", "")
            pp_raw    = row.get("Per Person (€/mo)", "")
            try:
                price_str = f"€{float(str(price_raw).replace(',','')):.0f}" if price_raw else "—"
            except ValueError:
                price_str = _esc(str(price_raw))
            try:
                pp_str = f"€{float(str(pp_raw).replace(',','')):.0f}" if pp_raw else "—"
            except ValueError:
                pp_str = _esc(str(pp_raw))

            beds = _esc(str(row.get("Bedrooms", "?")))
            walk = row.get("Walk to Cattolica (min)", "")
            walk_str = f"{walk} min" if walk else "—"

            parts.append(
                f"<tr><td>{title_cell}</td><td>{beds}</td>"
                f"<td class='price'>{price_str}</td><td>{pp_str}</td>"
                f"<td>{_esc(str(row.get('Neighborhood','')))}</td>"
                f"<td>{walk_str}</td><td>{_esc(str(row.get('Source','')))}</td></tr>"
            )
        parts.append("</table>")

    if not active_listings:
        parts.append("<p style='color:#888'>No active listings at this time.</p>")

    parts.append(_html_action_buttons(sheet_url, map_url))
    parts.append(_html_footer(run_timestamp))
    return "".join(parts)


def _build_recap_text(
    active_listings: list[dict],
    sheet_url: str,
    map_url: str,
    run_timestamp: str,
) -> str:
    lines = [f"Milan Housing — Nightly Recap ({len(active_listings)} active)", "=" * 40, ""]
    if map_url:
        lines += [f"MAP: {map_url}", ""]

    groups: dict[str, list] = {}
    for row in active_listings:
        groups.setdefault(row.get("Search Type", "Other"), []).append(row)

    for search_type, items in groups.items():
        lines.append(f"{search_type} ({len(items)})")
        lines.append("-" * 30)
        for row in items:
            price = row.get("Price (€/month)", "")
            pp    = row.get("Per Person (€/mo)", "")
            price_str = f"€{price}/mo" if price else "N/A"
            pp_str    = f" · €{pp}/pp" if pp else ""
            beds = row.get("Bedrooms", "?")
            walk = row.get("Walk to Cattolica (min)", "")
            walk_str = f"{walk} min walk" if walk else ""
            lines.append(f"  {row.get('Title','')[:60]}")
            lines.append(f"  {beds}BR | {price_str}{pp_str} | {row.get('Neighborhood','')} {walk_str} | {row.get('Source','')}")
            if row.get("Listing URL"):
                lines.append(f"  {row['Listing URL']}")
            lines.append("")

    if sheet_url:
        lines.append(f"Sheet: {sheet_url}")
    lines.append(f"Run at: {run_timestamp}")
    return "\n".join(lines)


# ── Helper ─────────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
