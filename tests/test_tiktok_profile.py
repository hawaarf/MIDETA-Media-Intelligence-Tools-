# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

from datetime import date, datetime
import unittest
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from yt_dlp.utils import DownloadError

from src.tiktok_profile import (
    TikTokProfileCollector,
    TikTokProfileScrapeError,
    _sec_uid_from_html,
    parse_tiktok_profile,
)


def timestamp(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 12, tzinfo=ZoneInfo("Asia/Jakarta")).timestamp())


class TikTokProfileTests(unittest.TestCase):
    def test_profile_parser_accepts_url_at_username_and_plain_username(self):
        self.assertEqual(parse_tiktok_profile("https://www.tiktok.com/@media.id/"), "media.id")
        self.assertEqual(parse_tiktok_profile("@media.id"), "media.id")
        self.assertEqual(parse_tiktok_profile("media.id"), "media.id")

    def test_profile_parser_rejects_a_post_url(self):
        with self.assertRaises(TikTokProfileScrapeError):
            parse_tiktok_profile("https://www.tiktok.com/@media.id/video/123")

    def test_public_profile_id_is_read_from_hydration_html(self):
        source = '<script>{"user":{"secUid":"MS4wLjABAAAA_public-id_123"}}</script>'

        self.assertEqual(
            _sec_uid_from_html(source),
            "MS4wLjABAAAA_public-id_123",
        )

    def test_missing_secondary_id_uses_public_profile_fallback(self):
        collector = TikTokProfileCollector(max_posts=10)
        collector._public_sec_uid = Mock(return_value="MS4wLjABAAAA_public-id_123")
        collector._extract_profile_info = Mock(
            side_effect=[
                DownloadError("Unable to extract secondary user ID"),
                {
                    "entries": [
                        {
                            "id": "800",
                            "timestamp": timestamp(2026, 8, 31),
                            "url": "https://www.tiktok.com/@officialinews/video/800",
                        }
                    ]
                },
            ]
        )

        result = collector.collect(
            "officialinews",
            date(2026, 1, 1),
            date(2026, 8, 31),
        )

        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["Author"], "officialinews")
        collector._extract_profile_info.assert_called_with(
            "tiktokuser:MS4wLjABAAAA_public-id_123"
        )

    def test_collect_filters_inclusive_range_and_builds_canonical_urls(self):
        entries = [
            {
                "id": "900",
                "timestamp": timestamp(2026, 9, 2),
                "uploader_id": "media.id",
                "url": "https://www.tiktok.com/@media.id/video/900",
            },
            {
                "id": "800",
                "timestamp": timestamp(2026, 8, 31),
                "uploader_id": "media.id",
                "description": "Caption lengkap   dengan jarak.\nBaris kedua.",
                "url": "https://www.tiktok.com/@media.id/video/800",
            },
            {
                "id": "101",
                "timestamp": timestamp(2026, 1, 1),
                "uploader_id": "media.id",
                "url": "https://www.tiktok.com/@media.id/photo/101",
            },
            *[
                {"id": f"old-{index}", "timestamp": timestamp(2025, 12, 31)}
                for index in range(20)
            ],
        ]
        collector = TikTokProfileCollector(
            max_posts=100,
            entry_provider=lambda _username: entries,
        )

        result = collector.collect(
            "@media.id",
            date(2026, 1, 1),
            date(2026, 8, 31),
        )

        self.assertTrue(result.complete)
        self.assertTrue(result.reached_start_date)
        self.assertEqual(result.posts_scanned, 23)
        self.assertEqual(
            [row["URL"] for row in result.rows],
            [
                "https://www.tiktok.com/@media.id/video/800",
                "https://www.tiktok.com/@media.id/photo/101",
            ],
        )
        self.assertEqual([row["Date Publish"] for row in result.rows], ["2026-08-31", "2026-01-01"])
        self.assertEqual(
            result.rows[0]["Caption"],
            "Caption lengkap dengan jarak. Baris kedua.",
        )
        self.assertEqual(result.oldest_matching_date, date(2026, 1, 1))
        self.assertEqual(result.newest_before_start_date, date(2025, 12, 31))

    def test_duplicate_pinned_post_does_not_duplicate_output_or_block_stop(self):
        entries = [
            {"id": "pinned", "timestamp": timestamp(2026, 7, 1)},
            {"id": "feb", "timestamp": timestamp(2026, 2, 1)},
            {"id": "pinned", "timestamp": timestamp(2026, 7, 1)},
            *[
                {"id": f"old-{index}", "timestamp": timestamp(2025, 12, 1)}
                for index in range(20)
            ],
        ]
        collector = TikTokProfileCollector(
            max_posts=100,
            entry_provider=lambda _username: entries,
        )

        result = collector.collect("media", date(2026, 1, 1), date(2026, 8, 31))

        self.assertEqual(len(result.rows), 2)
        self.assertTrue(result.complete)
        self.assertEqual(result.posts_scanned, 22)

    def test_safe_limit_returns_partial_result_with_warning(self):
        collector = TikTokProfileCollector(
            max_posts=1,
            entry_provider=lambda _username: [
                {"id": "aug", "timestamp": timestamp(2026, 8, 1)},
                {"id": "jul", "timestamp": timestamp(2026, 7, 1)},
            ],
        )

        result = collector.collect("media", date(2026, 1, 1), date(2026, 8, 31))

        self.assertFalse(result.complete)
        self.assertIn("batas aman", result.warning.casefold())
        self.assertEqual(len(result.rows), 1)


if __name__ == "__main__":
    unittest.main()
