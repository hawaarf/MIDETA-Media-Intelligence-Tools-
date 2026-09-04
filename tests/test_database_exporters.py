import io
import tempfile
import unittest
from datetime import date
from pathlib import Path
import pandas as pd
from src.database import add_history, create_social_job, delete_history, get_latest_social_job, get_social_job, list_history, next_social_job_items, record_social_job_item, set_social_job_status
from src.exporters import to_csv_bytes, to_xlsx_bytes

class DatabaseAndExporterTests(unittest.TestCase):
    def test_social_job_accepts_one_thousand_urls_in_small_chunks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.db"
            urls = [f"https://www.facebook.com/example/posts/{number}" for number in range(1, 1001)]
            job_id = create_social_job("Facebook", urls, schema_version=20, path=path)

            saved = get_social_job(job_id, path)
            first_chunk = next_social_job_items(job_id, 20, path)
            self.assertEqual(saved["total"], 1000)
            self.assertEqual(saved["pending"], 1000)
            self.assertEqual(len(first_chunk), 20)
            self.assertEqual(first_chunk[-1]["position"], 20)

    def test_social_job_can_resume_from_the_next_pending_url(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.db"
            urls = [f"https://x.com/akun/status/{number}" for number in range(1, 46)]
            job_id = create_social_job("X", urls, schema_version=20, path=path)

            first_chunk = next_social_job_items(job_id, 20, path)
            self.assertEqual(len(first_chunk), 20)
            self.assertEqual(first_chunk[0], {"position": 1, "url": urls[0]})

            record_social_job_item(
                job_id,
                1,
                "completed",
                result={"url": urls[0], "platform": "X"},
                path=path,
            )
            record_social_job_item(
                job_id,
                2,
                "failed",
                error={"URL": urls[1], "Platform": "X", "Alasan": "Dibatasi"},
                path=path,
            )
            set_social_job_status(job_id, "paused", path)

            saved = get_social_job(job_id, path)
            self.assertEqual(saved["processed"], 2)
            self.assertEqual(saved["pending"], 43)
            self.assertEqual(saved["status"], "paused")
            self.assertEqual(len(saved["results"]), 1)
            self.assertEqual(len(saved["errors"]), 1)
            self.assertEqual(next_social_job_items(job_id, 20, path)[0]["position"], 3)
            self.assertEqual(get_latest_social_job("X", path)["id"], job_id)

    def test_social_job_completes_after_its_last_item(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.db"
            job_id = create_social_job("Threads", ["https://threads.com/@akun/post/abc"], schema_version=20, path=path)
            record_social_job_item(job_id, 1, "completed", result={"url": "abc"}, path=path)

            saved = get_social_job(job_id, path)
            self.assertEqual(saved["status"], "completed")
            self.assertEqual(saved["processed"], 1)
            self.assertEqual(saved["pending"], 0)

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
