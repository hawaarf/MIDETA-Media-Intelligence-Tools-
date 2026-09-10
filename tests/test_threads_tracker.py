import unittest
from datetime import datetime, timezone

from src.threads_tracker import ThreadsTrackerCollector


class ThreadsTrackerTests(unittest.TestCase):
    def test_search_url_uses_recent_threads_results(self):
        self.assertEqual(
            ThreadsTrackerCollector.search_url("gojek indonesia"),
            "https://www.threads.com/search?q=gojek+indonesia&serp_type=recent",
        )

    def test_normalizes_metrics_and_media_url(self):
        row = ThreadsTrackerCollector.normalize_row(
            {
                "url": "https://www.threads.com/@akun/post/Code123/media",
                "posted_at": "2026-09-09T03:21:03.000Z",
                "caption": "  Caption   Threads Translate 1 / 3  ",
                "likes": "2K",
                "comments": "249",
                "reposts": "91",
                "shares": "360",
            }
        )

        self.assertEqual(row["URL"], "https://www.threads.com/@akun/post/Code123")
        self.assertEqual(row["Author"], "akun")
        self.assertEqual(row["Caption"], "Caption Threads")
        self.assertEqual(row["Likes"], 2_000)
        self.assertEqual(row["Total engagement"], 2_700)

    def test_filter_and_sort_by_period_and_engagement(self):
        rows = [
            {
                "URL": "recent-low",
                "Tanggal posting": "2026-09-09T18:00:00+00:00",
                "Total engagement": 10,
            },
            {
                "URL": "recent-high",
                "Tanggal posting": "2026-09-09T20:00:00+00:00",
                "Total engagement": 100,
            },
            {
                "URL": "old",
                "Tanggal posting": "2026-08-01T00:00:00+00:00",
                "Total engagement": 1_000,
            },
        ]
        now = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc)

        highest = ThreadsTrackerCollector.filter_and_sort(
            rows,
            "recent",
            "highest",
            now=now,
        )
        lowest = ThreadsTrackerCollector.filter_and_sort(
            rows,
            "7d",
            "lowest",
            now=now,
        )
        all_rows = ThreadsTrackerCollector.filter_and_sort(
            rows,
            "all",
            "newest",
            now=now,
        )

        self.assertEqual([row["URL"] for row in highest], ["recent-high", "recent-low"])
        self.assertEqual([row["URL"] for row in lowest], ["recent-low", "recent-high"])
        self.assertEqual([row["URL"] for row in all_rows], ["recent-high", "recent-low", "old"])

    def test_merge_rows_deduplicates_same_post(self):
        stored = {}
        rows = [
            {"url": "https://www.threads.com/@akun/post/Code123", "caption": "Satu", "likes": "1"},
            {"url": "https://www.threads.com/@akun/post/Code123/media", "caption": "Satu", "likes": "2"},
        ]

        added = ThreadsTrackerCollector.merge_rows(stored, rows)

        self.assertEqual(added, 1)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored["https://www.threads.com/@akun/post/Code123"]["Likes"], 2)


if __name__ == "__main__":
    unittest.main()
