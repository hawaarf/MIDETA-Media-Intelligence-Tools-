# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
from unittest.mock import Mock

from src.batch import compact_social_export_row
from src.models import FieldStatus
from src.profile_enrichment import enrich_profile_rows
from src.tiktok_browser import TikTokBrowserMetrics


class ProfileEnrichmentTests(unittest.TestCase):
    def test_rows_use_the_same_compact_format_as_tiktok_enrichment(self):
        collector = Mock()
        collector.collect.return_value = TikTokBrowserMetrics(
            username="akun",
            caption="Caption hasil enrichment",
            posted_at="2026-10-15T10:00:00+07:00",
            followers=1200,
            views=9000,
            likes=500,
            comments=20,
            shares=8,
            bookmarks=31,
            source="free",
        )
        source = [
            {
                "Date Publish": "2026-10-15",
                "Author": "akun",
                "Caption": "Caption discovery",
                "URL": "https://www.tiktok.com/@akun/video/123",
            }
        ]

        results = enrich_profile_rows(source, collector=collector)
        row = compact_social_export_row(results[0])

        self.assertEqual(
            list(row),
            [
                "Platform",
                "URL",
                "Tanggal posting",
                "Author",
                "Caption",
                "Followers",
                "Views",
                "Likes",
                "Comments",
                "Save atau bookmark",
                "Shares",
                "Reposts",
                "Waktu pengambilan",
                "Data yang tidak tersedia",
            ],
        )
        self.assertEqual(row["Platform"], "TikTok")
        self.assertEqual(row["Followers"], 1200)
        self.assertEqual(row["Views"], 9000)

    def test_failed_enrichment_keeps_discovered_metadata_and_marks_counts_failed(self):
        collector = Mock()
        collector.collect.side_effect = RuntimeError("provider unavailable")
        source = [
            {
                "Date Publish": "2026-10-15",
                "Author": "akun",
                "Caption": "Caption discovery",
                "URL": "https://www.tiktok.com/@akun/video/123",
            }
        ]

        result = enrich_profile_rows(source, collector=collector)[0]
        row = compact_social_export_row(result)

        self.assertEqual(result.username.value, "akun")
        self.assertEqual(result.caption.value, "Caption discovery")
        self.assertEqual(result.views.status, FieldStatus.FAILED)
        self.assertEqual(row["Views"], "Cek")
        self.assertIn("provider unavailable", result.note)

    def test_enrichment_preserves_input_order_and_reports_progress(self):
        collector = Mock()
        collector.collect.return_value = TikTokBrowserMetrics(source="free")
        rows = [
            {"Author": "akun", "URL": f"https://www.tiktok.com/@akun/video/{post_id}"}
            for post_id in ("3", "2", "1")
        ]
        updates = []

        results = enrich_profile_rows(rows, collector=collector, progress_callback=updates.append)

        self.assertEqual([result.url.rsplit("/", 1)[-1] for result in results], ["3", "2", "1"])
        self.assertEqual(updates[-1]["processed"], 3)
        self.assertEqual(updates[-1]["total"], 3)


if __name__ == "__main__":
    unittest.main()
