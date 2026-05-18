from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from config import DATA_DIR
from db import get_results


EXPORT_COLUMNS = ["job_id", "dork", "url", "domain", "title", "emails", "phones", "status", "error", "crawled_at"]


def export_results_to_excel(job_id: int) -> str:
    export_dir = DATA_DIR / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    rows = get_results(job_id=job_id, limit=1_000_000, offset=0)
    df = pd.DataFrame(rows, columns=EXPORT_COLUMNS)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = export_dir / f"linkintel_job_{job_id}_{timestamp}.xlsx"
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="results", index=False)
        worksheet = writer.sheets["results"]
        worksheet.freeze_panes = "A2"
        for cell in worksheet[1]:
            cell.style = "Headline 4"
        for column_cells in worksheet.columns:
            width = min(max(len(str(cell.value or "")) for cell in column_cells) + 2, 80)
            worksheet.column_dimensions[column_cells[0].column_letter].width = width
    return str(filepath)
