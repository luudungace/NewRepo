from __future__ import annotations

from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_SERVICE_ACCOUNT_JSON
from db import get_results
from export_utils import EXPORT_COLUMNS


SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]


def _client() -> gspread.Client:
    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("Missing GOOGLE_SERVICE_ACCOUNT_JSON in .env.")
    json_path = Path(GOOGLE_SERVICE_ACCOUNT_JSON).expanduser()
    if not json_path.exists():
        raise RuntimeError(f"Service account JSON not found: {json_path}")
    creds = Credentials.from_service_account_file(str(json_path), scopes=SCOPES)
    return gspread.authorize(creds)


def push_results_to_sheet(job_id: int, spreadsheet_id: str, worksheet_name: str, append: bool = False) -> int:
    if not spreadsheet_id.strip():
        raise ValueError("Spreadsheet ID is required.")
    if not worksheet_name.strip():
        raise ValueError("Worksheet name is required.")

    rows = get_results(job_id=job_id, limit=1_000_000, offset=0)
    values = [EXPORT_COLUMNS] + [[row.get(column, "") for column in EXPORT_COLUMNS] for row in rows]

    gc = _client()
    spreadsheet = gc.open_by_key(spreadsheet_id.strip())
    try:
        worksheet = spreadsheet.worksheet(worksheet_name.strip())
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=worksheet_name.strip(), rows=max(len(values), 100), cols=len(EXPORT_COLUMNS))

    if append:
        worksheet.append_rows(values[1:], value_input_option="RAW")
    else:
        worksheet.clear()
        worksheet.update(values, value_input_option="RAW")

    try:
        worksheet.freeze(rows=1)
        worksheet.format("1:1", {"textFormat": {"bold": True}})
    except Exception:
        pass
    return len(rows)
