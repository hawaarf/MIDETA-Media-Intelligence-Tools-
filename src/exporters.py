"""In-memory CSV and XLSX exporters."""
import io
import pandas as pd

def records_frame(records: list[dict]) -> pd.DataFrame:
    return pd.json_normalize(records, sep=".") if records else pd.DataFrame()

def to_csv_bytes(records: list[dict]) -> bytes:
    return records_frame(records).to_csv(index=False).encode("utf-8-sig")

def to_xlsx_bytes(records: list[dict], sheet_name: str = "MIDETA") -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        records_frame(records).to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return output.getvalue()
