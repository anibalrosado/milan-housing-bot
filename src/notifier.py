"""
Gmail email notifier.

Sends a summary email when new listings appear OR listings are marked Removed.
Silent (no send) if neither occurred.

Subject format:
  "Milan Housing: 3 new, 1 removed"
  "Milan Housing: 3 new listings found"
  "Milan Housing: 1 listing removed"

Requires GMAIL_USER and GMAIL_APP_PASSWORD in env.
Uses smtplib with SMTP_SSL on port 465.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

_CATTOLICA_COLOR = "#1a6e3c"   # dark green for header accent


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
        """
        Send summary email.
        Only fires if new_listings or removed_listings is non-empty.
        `removed_listings` is a list of dicts with keys: source, search_type, url.
        """
        if not new_listings and not removed_listings:
            logger.info("Notifier: nothing to report — skipping email")
            return

        if not self.gmail_user or not self.app_password:
            logger.warning("Notifier: GMAIL_USER or GMAIL_APP_PASSWORD not set — skipping email")
            return

        if not self.recipients:
            logger.warning("Notifier: no recipients configured — skipping email")
            return

        subject = _build_subject(new_listings, removed_listings)
        html_body = _build_html(new_listings, removed_listings, sheet_url, map_url, run_timestamp)
        text_body = _build_text(new_listings, removed_listings, sheet_url, map_url, run_timestamp)

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
            logger.info(
                "Notifier: email sent to %s — %d new, %d removed",
                ", ".join(self.recipients),
                len(new_listings),
                len(removed_listings),
            )
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


# ── HTML body ──────────────────────────────────────────────────────────────────

def _build_html(
    new_listings: list,
    removed_listings: list,
    sheet_url: str,
    map_url: str,
    run_timestamp: str,
) -> str:
    parts = [
        """<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><style>
body{font-family:Arial,sans-serif;font-size:14px;color:#222;max-width:700px;margin:0 auto}
h2{color:#1a6e3c;border-bottom:2px solid #1a6e3c;padding-bottom:6px}
h3{color:#444;margin-top:20px}
table{border-collapse:collapse;width:100%;margin:10px 0}
th{background:#1a6e3c;color:#fff;padding:8px 10px;text-align:left}
td{padding:7px 10px;border-bottom:1px solid #ddd}
tr:hover{background:#f5f5f5}
.price{font-weight:bold;color:#1a6e3c}
.removed-table th{background:#c0392b}
a{color:#1a6e3c}
.footer{font-size:12px;color:#888;margin-top:24px;border-top:1px solid #ddd;padding-top:10px}
.btn{display:inline-block;padding:10px 20px;background:#1a6e3c;color:#fff!important;
     text-decoration:none;border-radius:4px;margin:8px 4px}
</style></head>
<body>
<h2>🏠 Milan Housing Bot Update</h2>
"""
    ]

    # ── New listings ──────────────────────────────────────────────────────────
    if new_listings:
        parts.append(f"<h3>✅ {len(new_listings)} New Listing(s)</h3>")

        # Group by search type
        groups: dict[str, list] = {}
        for l in new_listings:
            groups.setdefault(l.search_type, []).append(l)

        for search_type, items in groups.items():
            parts.append(f"<h4>{search_type} ({len(items)})</h4>")
            parts.append(
                "<table>"
                "<tr><th>Title</th><th>Beds</th><th>Price</th>"
                "<th>Neighborhood</th><th>Walk</th><th>Source</th></tr>"
            )
            for l in items:
                price_str = f"€{l.price_eur:.0f}/mo" if l.price_eur else "—"
                beds_str = str(l.bedrooms) if l.bedrooms else "?"
                walk_str = f"{l.walk_minutes} min" if l.walk_minutes else "—"
                title_link = f'<a href="{l.url}">{_esc(l.title[:60])}</a>'
                parts.append(
                    f"<tr><td>{title_link}</td><td>{beds_str}</td>"
                    f"<td class='price'>{price_str}</td>"
                    f"<td>{_esc(l.neighborhood)}</td>"
                    f"<td>{walk_str}</td><td>{_esc(l.source)}</td></tr>"
                )
            parts.append("</table>")

    # ── Removed listings ──────────────────────────────────────────────────────
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

    # ── Links ─────────────────────────────────────────────────────────────────
    parts.append("<div style='margin:20px 0'>")
    if sheet_url:
        parts.append(f"<a class='btn' href='{sheet_url}'>📊 Open Sheet</a>")
    if map_url:
        parts.append(f"<a class='btn' href='{map_url}'>🗺️ View Map</a>")
    parts.append("</div>")

    # ── Footer ────────────────────────────────────────────────────────────────
    parts.append(
        f"<div class='footer'>"
        f"Run at {_esc(run_timestamp)} · Milan Housing Bot"
        f"</div></body></html>"
    )

    return "".join(parts)


# ── Plain-text body ────────────────────────────────────────────────────────────

def _build_text(
    new_listings: list,
    removed_listings: list,
    sheet_url: str,
    map_url: str,
    run_timestamp: str,
) -> str:
    lines = ["Milan Housing Bot Update", "=" * 40, ""]

    if new_listings:
        lines.append(f"NEW LISTINGS ({len(new_listings)})")
        lines.append("-" * 30)
        for l in new_listings:
            price_str = f"€{l.price_eur:.0f}/mo" if l.price_eur else "price N/A"
            beds_str = f"{l.bedrooms}BR" if l.bedrooms else "?BR"
            lines.append(f"[{l.search_type}] {l.title[:60]}")
            lines.append(f"  {beds_str} | {price_str} | {l.neighborhood} | {l.source}")
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
    if map_url:
        lines.append(f"Map:   {map_url}")
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
