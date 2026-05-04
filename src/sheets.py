"""Google Sheets writer and reader."""

import logging
import time

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsWriter:
    def __init__(self, sheet_id: str, credentials_dict: dict, column_names: list[str]):
        creds = Credentials.from_service_account_info(credentials_dict, scopes=_SCOPES)
        client = gspread.authorize(creds)
        self._sheet = client.open_by_key(sheet_id).sheet1
        # 1-based column index keyed by header name
        self._col = {name: i + 1 for i, name in enumerate(column_names)}

    # ── Append ────────────────────────────────────────────────────────────────

    def append_listings(self, rows: list[list]) -> None:
        """Append new listing rows. Each row must already be fully formed."""
        self._sheet.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info("Appended %d row(s) to sheet", len(rows))

    # ── Lifecycle update ──────────────────────────────────────────────────────

    def update_listing_status(self, url: str, listing_status: str, removed_date: str = "") -> None:
        """
        Find the row with matching Listing URL and update Listing Status + Removed Date.
        Silently skips if URL is not found.
        """
        url_col = self._col["Listing URL"]
        try:
            cell = self._sheet.find(url, in_column=url_col)
        except gspread.exceptions.CellNotFound:
            logger.warning("update_listing_status: URL not found in sheet: %s", url)
            return

        row = cell.row
        ls_col = self._col["Listing Status"]
        rd_col = self._col["Removed Date"]

        # Batch both cells in one API call
        self._sheet.update(
            [[listing_status, removed_date]],
            f"{gspread.utils.rowcol_to_a1(row, ls_col)}:"
            f"{gspread.utils.rowcol_to_a1(row, rd_col)}",
        )
        logger.info("Row %d set to Listing Status=%s", row, listing_status)

    # ── Read all (for map generator) ──────────────────────────────────────────

    def read_all_listings(self) -> list[dict]:
        """
        Return all rows as dicts (keyed by header). Excludes Status = "Passed".
        """
        records = self._sheet.get_all_records()
        return [r for r in records if r.get("Status") != "Passed"]
