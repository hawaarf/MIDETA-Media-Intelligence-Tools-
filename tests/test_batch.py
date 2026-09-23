# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
from src.batch import FAILED_URL_MESSAGE, SOCIAL_BATCH_VERSION, batch_progress_fraction, collect_threads_enrichment_with_fallback, compact_comment_export_rows, compact_social_all_export_row, compact_social_export_row, failed_social_result, format_comment_date, format_posting_date, group_social_urls, is_current_social_batch, merge_facebook_advanced_result, order_social_results_by_input, parse_url_list, rank_comment_rows, social_job_results, social_result_row
from src.models import DataField, FieldStatus
from src.connectors import get_connector

class BatchTests(unittest.TestCase):
    def test_batch_progress_moves_during_active_url_without_finishing_early(self):
        self.assertEqual(batch_progress_fraction(0, 10), 0.0)
        self.assertGreater(batch_progress_fraction(0, 10, 0.5), 0.0)
        self.assertLess(batch_progress_fraction(9, 10, 0.95), 1.0)
        self.assertEqual(batch_progress_fraction(10, 10, 0.5), 1.0)

    def test_parse_url_list_removes_blanks_and_duplicates(self):
        value = "https://youtube.com/watch?v=1\n\nhttps://x.com/a/status/2\nhttps://youtube.com/watch?v=1"
        self.assertEqual(parse_url_list(value), ["https://youtube.com/watch?v=1", "https://x.com/a/status/2"])

    def test_parse_url_list_extracts_urls_from_pasted_spreadsheet_rows(self):
        value = (
            "Aug 30, 2026 https://www.instagram.com/p/DcpQElkziXD/\n"
            "Aug 31, 2026,https://www.instagram.com/p/Dcspim8kilm/,Organic\n"
            "[https://www.instagram.com/p/DcpQElkziXD/](https://www.instagram.com/p/DcpQElkziXD/)"
        )
        self.assertEqual(
            parse_url_list(value),
            [
                "https://www.instagram.com/p/DcpQElkziXD/",
                "https://www.instagram.com/p/Dcspim8kilm/",
            ],
        )

    def test_parse_url_list_can_preserve_repeated_spreadsheet_rows(self):
        url = "https://www.instagram.com/p/ABC/"
        value = f"{url}\n{url}\n[{url}]({url})"

        self.assertEqual(
            parse_url_list(value, preserve_repeated_rows=True),
            [url, url, url],
        )

    def test_parse_url_list_accepts_one_thousand_enrichment_rows(self):
        urls = [f"https://x.com/akun/status/{index}" for index in range(1_000)]

        parsed = parse_url_list("\n".join(urls), preserve_repeated_rows=True)

        self.assertEqual(parsed, urls)

    def test_combined_results_keep_repeated_urls_in_original_input_order(self):
        instagram_url = "https://www.instagram.com/p/ABC/"
        facebook_url = "https://www.facebook.com/reel/123"
        threads_url = "https://www.threads.com/@akun/post/DEF"
        first_instagram = get_connector(instagram_url).mock_enrichment(instagram_url)
        first_instagram.caption.value = "Instagram pertama"
        second_instagram = get_connector(instagram_url).mock_enrichment(instagram_url)
        second_instagram.caption.value = "Instagram kedua"
        facebook = get_connector(facebook_url).mock_enrichment(facebook_url)
        threads = get_connector(threads_url).mock_enrichment(threads_url)

        ordered = order_social_results_by_input(
            [first_instagram, second_instagram, facebook, threads],
            [instagram_url, facebook_url, instagram_url, threads_url],
        )

        self.assertEqual(
            [result.url for result in ordered],
            [instagram_url, facebook_url, instagram_url, threads_url],
        )
        self.assertEqual(ordered[0].caption.value, "Instagram pertama")
        self.assertEqual(ordered[2].caption.value, "Instagram kedua")

    def test_parse_url_list_ignores_rows_without_urls(self):
        value = "Aug 30, 2026\ncaption tanpa tautan\nhttps://www.threads.com/@akun/post/ABC."
        self.assertEqual(parse_url_list(value), ["https://www.threads.com/@akun/post/ABC"])

    def test_group_social_urls_detects_mixed_platforms_and_reports_unknown_urls(self):
        grouped, unsupported = group_social_urls(
            [
                "https://youtu.be/video",
                "https://www.facebook.com/reel/123",
                "https://www.instagram.com/p/ABC/",
                "https://www.threads.com/@akun/post/DEF",
                "https://twitter.com/akun/status/456",
                "https://vt.tiktok.com/SHORT/",
                "https://t.co/SHORT",
                "https://example.com/post/789",
            ]
        )
        self.assertEqual(grouped["YouTube"], ["https://youtu.be/video"])
        self.assertEqual(grouped["Facebook"], ["https://www.facebook.com/reel/123"])
        self.assertEqual(grouped["Instagram"], ["https://www.instagram.com/p/ABC/"])
        self.assertEqual(grouped["Threads"], ["https://www.threads.com/@akun/post/DEF"])
        self.assertEqual(grouped["TikTok"], ["https://vt.tiktok.com/SHORT/"])
        self.assertEqual(grouped["X"], ["https://twitter.com/akun/status/456", "https://t.co/SHORT"])
        self.assertEqual(unsupported[0]["URL"], "https://example.com/post/789")

    def test_stale_social_batch_is_rejected_after_parser_update(self):
        self.assertFalse(is_current_social_batch({"results": []}))
        self.assertFalse(is_current_social_batch({"schema_version": SOCIAL_BATCH_VERSION - 1, "results": []}))
        self.assertTrue(is_current_social_batch({"schema_version": SOCIAL_BATCH_VERSION, "results": []}))

    def test_comment_ranking_uses_likes_and_replies(self):
        rows = [{"Komentar": "A", "Likes": 12, "Jumlah reply": 0}, {"Komentar": "B", "Likes": 8, "Jumlah reply": 4}, {"Komentar": "C", "Likes": None, "Jumlah reply": 1}]
        ranked = rank_comment_rows(rows)
        self.assertEqual([row["Komentar"] for row in ranked], ["B", "A", "C"])
        self.assertEqual([row["Rank"] for row in ranked], [1, 2, 3])

    def test_comment_export_matches_reference_columns_and_date(self):
        rows = rank_comment_rows([
            {
                "Tanggal komentar": "2026-08-20T12:15:00+00:00",
                "Author": "@ayu",
                "Tipe": "parent",
                "Komentar": "Baris pertama\nbaris kedua",
                "Likes": 11,
                "Jumlah reply": 2,
            }
        ])
        exported = compact_comment_export_rows(rows)
        self.assertEqual(list(exported[0]), ["index", "date", "author", "type", "comment", "like"])
        self.assertEqual(exported[0]["date"], "Aug 20, 2026")
        self.assertEqual(exported[0]["author"], "ayu")
        self.assertEqual(exported[0]["comment"], "Baris pertama baris kedua")
        self.assertEqual(exported[0]["like"], 11)

    def test_comment_date_keeps_reference_format(self):
        self.assertEqual(format_comment_date("Aug 20, 2026"), "Aug 20, 2026")

    def test_social_export_contains_requested_metrics(self):
        result = get_connector("https://youtu.be/demo").mock_enrichment("https://youtu.be/demo")
        row = social_result_row(result)
        for key in ("Tanggal posting", "Author", "Caption", "Followers", "Views", "Likes", "Comments", "Save atau bookmark", "Shares", "Reposts"):
            self.assertIn(key, row)

    def test_facebook_advanced_keeps_fast_metadata_and_only_adds_browser_views(self):
        fast = get_connector("https://www.facebook.com/reel/123").mock_enrichment(
            "https://www.facebook.com/reel/123"
        )
        fast.username = DataField(value="author_fast", status=FieldStatus.AVAILABLE)
        fast.caption = DataField(value="caption fast", status=FieldStatus.AVAILABLE)
        fast.likes = DataField(value=123, status=FieldStatus.AVAILABLE)
        fast.comments = DataField(value=45, status=FieldStatus.AVAILABLE)
        fast.views = DataField(value=None, status=FieldStatus.NOT_PUBLIC)

        browser = fast.model_copy(deep=True)
        browser.username = DataField(value=None, status=FieldStatus.NOT_PUBLIC)
        browser.caption = DataField(value=None, status=FieldStatus.NOT_PUBLIC)
        browser.likes = DataField(value=None, status=FieldStatus.NOT_PUBLIC)
        browser.comments = DataField(value=None, status=FieldStatus.NOT_PUBLIC)
        browser.views = DataField(value=8_120, status=FieldStatus.AVAILABLE)

        merged = merge_facebook_advanced_result(fast, browser)

        self.assertEqual(merged.username.value, "author_fast")
        self.assertEqual(merged.caption.value, "caption fast")
        self.assertEqual(merged.likes.value, 123)
        self.assertEqual(merged.comments.value, 45)
        self.assertEqual(merged.views.value, 8_120)

    def test_facebook_advanced_keeps_fast_views_when_browser_has_none(self):
        fast = get_connector("https://www.facebook.com/reel/123").mock_enrichment(
            "https://www.facebook.com/reel/123"
        )
        fast.views = DataField(value=900, status=FieldStatus.AVAILABLE)
        browser = fast.model_copy(deep=True)
        browser.views = DataField(value=None, status=FieldStatus.NOT_PUBLIC)

        merged = merge_facebook_advanced_result(fast, browser)

        self.assertEqual(merged.views.value, 900)
        self.assertEqual(merged.views.status, FieldStatus.AVAILABLE)

    def test_threads_uses_browser_when_public_reader_fails(self):
        url = "https://www.threads.com/@akun/post/ABC"
        browser_result = get_connector(url).mock_enrichment(url)
        browser_calls = []

        def public_collect(_url):
            raise RuntimeError("Domain tidak dapat ditemukan.")

        def browser_collect(target_url):
            browser_calls.append(target_url)
            return browser_result

        result, issue = collect_threads_enrichment_with_fallback(
            public_collect,
            browser_collect,
            url,
        )

        self.assertIs(result, browser_result)
        self.assertIsNone(issue)
        self.assertEqual(browser_calls, [url])

    def test_threads_reports_both_failures_when_public_and_browser_are_unavailable(self):
        url = "https://www.threads.com/@akun/post/ABC"

        def public_collect(_url):
            raise RuntimeError("Domain tidak dapat ditemukan.")

        def browser_collect(_url):
            raise RuntimeError("Chrome tidak merespons.")

        with self.assertRaisesRegex(
            RuntimeError,
            "Pembaca publik Threads gagal.*Chrome tidak merespons",
        ):
            collect_threads_enrichment_with_fallback(
                public_collect,
                browser_collect,
                url,
            )

    def test_compact_social_export_has_no_blank_cells_or_repeated_status_columns(self):
        result = get_connector("https://youtu.be/demo").mock_enrichment("https://youtu.be/demo")
        result.caption.value = "Baris pertama\n\nBaris kedua"
        result.followers.value = None
        row = compact_social_export_row(result)
        self.assertNotIn("\n", row["Caption"])
        self.assertEqual(row["Followers"], "Tidak tersedia")
        self.assertIn("Followers", row["Data yang tidak tersedia"])
        self.assertFalse(any(column.startswith("Status ") for column in row))
        self.assertFalse(any(value in (None, "") for value in row.values()))
        self.assertEqual(len(row), 14)

    def test_posting_date_uses_requested_export_format(self):
        self.assertEqual(format_posting_date("2026-08-25T14:30:00+07:00"), "25-Aug-2026")
        self.assertEqual(format_posting_date("2026-09-01"), "01-Sep-2026")
        self.assertEqual(format_posting_date("Tanggal tidak diketahui"), "Tanggal tidak diketahui")

    def test_posting_date_converts_utc_to_jakarta_before_formatting(self):
        self.assertEqual(format_posting_date("2026-09-07T18:30:00+00:00"), "08-Sep-2026")

    def test_compact_export_formats_date_and_keeps_zero_counts(self):
        result = get_connector("https://www.instagram.com/p/demo").mock_enrichment("https://www.instagram.com/p/demo")
        result.posted_at.value = "2026-08-25T10:00:00+07:00"
        result.followers.value = 0
        result.views.value = 0
        row = compact_social_export_row(result)
        self.assertEqual(row["Tanggal posting"], "25-Aug-2026")
        self.assertEqual(row["Followers"], 0)
        self.assertEqual(row["Views"], 0)

    def test_failed_url_keeps_its_row_and_original_position(self):
        first_url = "https://x.com/akun/status/1"
        failed_url = "https://x.com/akun/status/2"
        third_url = "https://x.com/akun/status/3"
        first = get_connector(first_url).mock_enrichment(first_url)
        third = get_connector(third_url).mock_enrichment(third_url)
        job = {
            "platform": "X",
            "items": [
                {"position": 1, "url": first_url, "status": "completed", "result": first.model_dump(mode="json")},
                {
                    "position": 2,
                    "url": failed_url,
                    "status": "failed",
                    "result": None,
                    "error": {"URL": failed_url, "Platform": "X", "Alasan": "Dibatasi"},
                },
                {"position": 3, "url": third_url, "status": "completed", "result": third.model_dump(mode="json")},
            ],
        }

        results = social_job_results(job)
        failed_row = compact_social_export_row(results[1])

        self.assertEqual([result.url for result in results], [first_url, failed_url, third_url])
        self.assertEqual(failed_row["Caption"], FAILED_URL_MESSAGE)
        self.assertEqual(failed_row["Likes"], FAILED_URL_MESSAGE)
        self.assertEqual(failed_row["Data yang tidak tersedia"], FAILED_URL_MESSAGE)

    def test_unknown_platform_can_be_exported_as_a_failed_row(self):
        result = failed_social_result(
            "https://example.com/post/1",
            "Tidak dikenali",
            "Platform belum didukung",
        )

        row = compact_social_export_row(result)

        self.assertEqual(row["URL"], "https://example.com/post/1")
        self.assertEqual(row["Platform"], "Tidak dikenali")
        self.assertEqual(row["Caption"], FAILED_URL_MESSAGE)
        self.assertEqual(row["Data yang tidak tersedia"], FAILED_URL_MESSAGE)
        self.assertTrue(result.note.startswith(FAILED_URL_MESSAGE))

    def test_combined_export_restores_input_order_after_out_of_order_completion(self):
        youtube_url = "https://youtu.be/first"
        unknown_url = "https://example.com/not-social"
        x_url = "https://x.com/akun/status/last"
        youtube = get_connector(youtube_url).mock_enrichment(youtube_url)
        unknown = failed_social_result(unknown_url, "Tidak dikenali", "Platform belum didukung")
        x_result = get_connector(x_url).mock_enrichment(x_url)

        # Simulasikan URL terakhir selesai lebih dulu dan URL pertama selesai
        # paling akhir. Export harus tetap mengikuti urutan input.
        ordered = order_social_results_by_input(
            [x_result, unknown, youtube],
            [youtube_url, unknown_url, x_url],
        )
        exported = [compact_social_all_export_row(result) for result in ordered]

        self.assertEqual(
            [row["URL"] for row in exported],
            [youtube_url, unknown_url, x_url],
        )
        self.assertEqual(exported[1]["Caption"], FAILED_URL_MESSAGE)
        self.assertIn("Platform belum didukung", exported[1]["Error"])
        self.assertEqual(exported[0]["Error"], "Tidak ada")
