import io
import tempfile
import unittest
from datetime import date
from pathlib import Path
import pandas as pd
from src.database import add_history, delete_history, list_history
from src.exporters import to_csv_bytes, to_xlsx_bytes

class DatabaseAndExporterTests(unittest.TestCase):
    def test_history_crud_and_filters(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.db"
            first = add_history("Comment Scrapper", "https://example.com/a", "completed", {"comment": "Ekonomi lokal"}, path=path)
            add_history("Social Media Enrichment", "https://x.com/a/status/1", "mock", {"caption": "Demo"}, platform="X", path=path)
            records = list_history(search="Ekonomi", feature="Comment Scrapper", start=date.today(), end=date.today(), path=path)
            self.assertEqual([record.id for record in records], [first])
            self.assertTrue(delete_history(first, path))
            self.assertEqual(len(list_history(path=path)), 1)

    def test_csv_and_xlsx_are_readable(self):
        rows = [{"platform": "X", "likes": None}]
        csv = pd.read_csv(io.BytesIO(to_csv_bytes(rows)))
        xlsx = pd.read_excel(io.BytesIO(to_xlsx_bytes(rows)))
        self.assertEqual(csv.loc[0, "platform"], "X")
        self.assertEqual(xlsx.loc[0, "platform"], "X")

    def test_csv_and_xlsx_keep_the_formatted_posting_date(self):
        rows = [{"Platform": "Instagram", "Tanggal posting": "25-Aug-2026", "Followers": 0, "Views": 0}]
        csv = pd.read_csv(io.BytesIO(to_csv_bytes(rows)))
        xlsx = pd.read_excel(io.BytesIO(to_xlsx_bytes(rows)))
        self.assertEqual(csv.loc[0, "Tanggal posting"], "25-Aug-2026")
        self.assertEqual(xlsx.loc[0, "Tanggal posting"], "25-Aug-2026")
        self.assertEqual(csv.loc[0, "Followers"], 0)
        self.assertEqual(xlsx.loc[0, "Views"], 0)
