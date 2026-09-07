"""In-memory CSV and XLSX exporters."""
import io

import pandas as pd
from openpyxl.styles import Font


DEFAULT_EXCEL_FONT = "Arial"
DEFAULT_EXCEL_FONT_SIZE = 10

def records_frame(records: list[dict]) -> pd.DataFrame:
    return pd.json_normalize(records, sep=".") if records else pd.DataFrame()

def to_csv_bytes(records: list[dict]) -> bytes:
    return records_frame(records).to_csv(index=False).encode("utf-8-sig")

def to_xlsx_bytes(records: list[dict], sheet_name: str = "MIDETA") -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        worksheet_name = sheet_name[:31]
        records_frame(records).to_excel(writer, index=False, sheet_name=worksheet_name)
        worksheet = writer.book[worksheet_name]
        for row in worksheet.iter_rows():
            for cell in row:
                cell.font = Font(
                    name=DEFAULT_EXCEL_FONT,
                    size=DEFAULT_EXCEL_FONT_SIZE,
                    bold=cell.row == 1,
                )
    return output.getvalue()
