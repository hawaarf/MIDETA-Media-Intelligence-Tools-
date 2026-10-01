# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

from datetime import date, datetime
import json
import unittest
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from src.keyword_search import (
    KeywordSearchCollector,
    KeywordSearchError,
    parse_boolean_query,
    parse_search_page,
)


def page(payload: dict) -> str:
    return (
        '<html><body><script type="application/json">'
        + json.dumps(payload)
        + "</script></body></html>"
    )


def timestamp(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 12, tzinfo=ZoneInfo("Asia/Jakarta")).timestamp())


class BooleanQueryTests(unittest.TestCase):
    def test_boolean_query_supports_phrase_grouping_and_exclusion(self):
        query = parse_boolean_query(
            '("ojek online" OR gojek OR ojol) NOT (promo OR voucher)'
        )

        self.assertTrue(query.matches("Cerita ojol membantu penumpang"))
        self.assertTrue(query.matches("Gojek memperluas layanan transportasi"))
        self.assertFalse(query.matches("Promo Gojek dan voucher terbaru"))
        self.assertEqual(
            query.positive_terms(),
            ["ojek online", "gojek", "ojol"],
        )

    def test_plain_text_is_one_search_phrase(self):
        query = parse_boolean_query("ojek online")

        self.assertEqual(query.positive_terms(), ["ojek online"])
        self.assertTrue(query.matches("Kabar ojek online hari ini"))
        self.assertFalse(query.matches("Ojek pangkalan tersedia online"))

    def test_query_with_only_not_is_rejected(self):
        with self.assertRaises(KeywordSearchError):
            parse_boolean_query("NOT promo")


class PublicSearchParserTests(unittest.TestCase):
    def test_threads_search_parser_reads_post_and_metrics(self):
        source = page(
            {
                "data": {
                    "items": [
                        {
                            "post": {
                                "code": "Ddn_ggzgjAE",
                                "taken_at": timestamp(2026, 9, 20),
                                "user": {"username": "nalarpedia_id"},
                                "caption": {"text": "Diskusi ojek online hari ini"},
                                "like_count": 41,
                                "text_post_app_info": {
                                    "direct_reply_count": 7,
                                    "repost_count": 3,
                                    "reshare_count": 2,
                                },
                            }
                        }
                    ]
                }
            }
        )

        rows = parse_search_page("Threads", source, "Recent")

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["URL"],
            "https://www.threads.com/@nalarpedia_id/post/Ddn_ggzgjAE",
        )
        self.assertEqual(rows[0]["Comments"], 7)
        self.assertEqual(rows[0]["Shares"], 2)
        self.assertEqual(rows[0]["Search Type"], "Recent")

    def test_tiktok_search_parser_reads_video_and_stats(self):
        source = page(
            {
                "itemList": [
                    {
                        "id": "7674512043470359826",
                        "createTime": timestamp(2026, 8, 16),
                        "author": {"uniqueId": "balataknabandung32"},
                        "desc": "Cerita ojol Bandung",
                        "stats": {
                            "playCount": 1200,
                            "diggCount": 50,
                            "commentCount": 8,
                            "shareCount": 4,
                        },
                    }
                ]
            }
        )

        rows = parse_search_page("TikTok", source)

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["URL"],
            "https://www.tiktok.com/@balataknabandung32/video/7674512043470359826",
        )
        self.assertEqual(rows[0]["Views"], 1200)
        self.assertEqual(rows[0]["Likes"], 50)


class KeywordSearchCollectorTests(unittest.TestCase):
    def test_collect_searches_in_parallel_filters_boolean_date_and_deduplicates(self):
        calls: list[tuple[str, str]] = []

        def fetcher(url: str, platform: str) -> str:
            calls.append((url, platform))
            query = parse_qs(urlparse(url).query)["q"][0]
            if platform == "TikTok":
                suffix = "6" if query == "gojek" else "9"
                return page(
                    {
                        "items": [
                            {
                                "id": f"767451204347035982{suffix}",
                                "createTime": timestamp(2026, 8, 16),
                                "author": {"uniqueId": "akun_tiktok"},
                                "desc": f"Cerita {query} untuk pengemudi",
                                "stats": {"diggCount": 10},
                            },
                            {
                                "id": "7674512043470359827",
                                "createTime": timestamp(2026, 8, 17),
                                "author": {"uniqueId": "akun_promo"},
                                "desc": f"Promo {query} dan voucher",
                            },
                            {
                                "id": "7674512043470359828",
                                "createTime": timestamp(2025, 8, 17),
                                "author": {"uniqueId": "akun_lama"},
                                "desc": f"Cerita lama {query}",
                            },
                        ]
                    }
                )
            return page(
                {
                    "items": [
                        {
                            "post": {
                                "code": "Ddn_ggzgjAE" if query == "gojek" else "Ddn_ggzgjAF",
                                "taken_at": timestamp(2026, 8, 20),
                                "user": {"username": "akun_threads"},
                                "caption": {"text": f"Diskusi {query} bersama ojol"},
                                "like_count": 20,
                            }
                        }
                    ]
                }
            )

        progress: list[dict[str, int]] = []
        collector = KeywordSearchCollector(fetcher=fetcher)
        result = collector.collect(
            '(gojek OR ojol) NOT (promo OR voucher)',
            ["TikTok", "Threads"],
            date(2026, 1, 1),
            date(2026, 8, 31),
            progress_callback=progress.append,
        )

        # Two positive seed terms: 2 TikTok pages and 4 Threads pages
        # (Top + Recent). Duplicate permalinks are emitted once.
        self.assertEqual(len(calls), 6)
        self.assertEqual(result.requests_made, 6)
        self.assertEqual(len(result.rows), 4)
        self.assertEqual(len({row["URL"] for row in result.rows}), 4)
        self.assertTrue(all("promo" not in row["Content"].casefold() for row in result.rows))
        self.assertTrue(all(row["Date Publish"].startswith("2026-") for row in result.rows))
        self.assertEqual(progress[-1]["completed"], 6)

    def test_tiktok_logged_in_searcher_is_used_without_public_tiktok_request(self):
        fetched: list[str] = []
        browser_terms: list[str] = []

        def fetcher(url: str, _platform: str) -> str:
            fetched.append(url)
            return page({})

        def browser_searcher(term: str, _limit: int) -> list[dict]:
            browser_terms.append(term)
            return [
                {
                    "Platform": "TikTok",
                    "Date Publish": datetime(
                        2026, 8, 20, 12, tzinfo=ZoneInfo("Asia/Jakarta")
                    ),
                    "Author": "akun_tiktok",
                    "Content": f"Cerita {term} dari lapangan",
                    "URL": "https://www.tiktok.com/@akun_tiktok/video/7690000000000000000",
                    "Views": None,
                    "Likes": None,
                    "Comments": None,
                    "Shares": None,
                    "Reposts": None,
                    "Search Type": "Video · sesi TikTok",
                }
            ]

        result = KeywordSearchCollector(
            fetcher=fetcher,
            tiktok_browser_searcher=browser_searcher,
        ).collect(
            "ojol",
            ["TikTok"],
            date(2026, 1, 1),
            date(2026, 8, 31),
        )

        self.assertEqual(fetched, [])
        self.assertEqual(browser_terms, ["ojol"])
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["Likes"], "Cek")

    def test_threads_logged_in_searcher_preserves_boolean_and_search_modes(self):
        fetched: list[str] = []
        browser_calls: list[tuple[str, str]] = []

        def fetcher(url: str, _platform: str) -> str:
            fetched.append(url)
            return page({})

        def browser_searcher(term: str, _limit: int, search_type: str) -> list[dict]:
            browser_calls.append((term, search_type))
            return [
                {
                    "Platform": "Threads",
                    "Date Publish": datetime(
                        2026, 8, 21, 12, tzinfo=ZoneInfo("Asia/Jakarta")
                    ),
                    "Author": "akun_threads",
                    "Content": f"Diskusi {term} tanpa promosi",
                    "URL": "https://www.threads.com/@akun_threads/post/Ddn_ggzgjAE",
                    "Views": None,
                    "Likes": 12,
                    "Comments": 3,
                    "Shares": None,
                    "Reposts": None,
                    "Search Type": f"{search_type} · sesi Threads",
                }
            ]

        result = KeywordSearchCollector(
            fetcher=fetcher,
            threads_browser_searcher=browser_searcher,
        ).collect(
            '"ojek online" NOT voucher',
            ["Threads"],
            date(2026, 1, 1),
            date(2026, 8, 31),
            search_mode="Top + Recent",
        )

        self.assertEqual(fetched, [])
        self.assertEqual(
            browser_calls,
            [("ojek online", "Top"), ("ojek online", "Recent")],
        )
        self.assertEqual(len(result.rows), 1)
        self.assertIn("Top", result.rows[0]["Search Type"])
        self.assertIn("Recent", result.rows[0]["Search Type"])


if __name__ == "__main__":
    unittest.main()
