# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest

from src.models import DataField, FieldStatus, SocialResult
from src.social_reporting import (
    build_social_report_message,
    engagement_items,
    format_social_report,
)


def field(value, status=FieldStatus.AVAILABLE):
    return DataField(value=value, status=status)


def result(
    platform: str,
    url: str,
    author: str,
    posted_at: str,
    caption: str,
    *,
    likes=None,
    comments=None,
    bookmarks=None,
    shares=None,
    reposts=None,
) -> SocialResult:
    def metric(value):
        return field(value) if value is not None else field(None, FieldStatus.NOT_PUBLIC)

    return SocialResult(
        url=url,
        platform=platform,
        username=field(author),
        caption=field(caption),
        posted_at=field(posted_at),
        followers=field(None, FieldStatus.NOT_PUBLIC),
        views=field(None, FieldStatus.NOT_PUBLIC),
        likes=metric(likes),
        comments=metric(comments),
        bookmarks=metric(bookmarks),
        shares=metric(shares),
        reposts=metric(reposts),
    )


class SocialReportingTests(unittest.TestCase):
    def test_single_post_matches_compact_reporting_format(self):
        instagram = result(
            "Instagram",
            "https://www.instagram.com/reels/Ddz7ttGyHzZ/",
            "jabodetabek24info",
            "2026-09-28T10:00:00+07:00",
            "Seorang perempuan berjaket ojol diduga menggunakan uang palsu pecahan Rp100K. "
            "Kasus kemudian dilaporkan kepada pihak berwajib. #Cimahi",
            likes=4_959,
            comments=375,
            reposts=347,
        )

        report = format_social_report(
            [instagram],
            "Indonesia",
            message="Menyoroti dugaan penggunaan uang palsu oleh seorang perempuan berjaket ojol.",
        )

        self.assertEqual(
            report,
            "Instagram — 28 Sep 2026\n"
            "@jabodetabek24info — https://www.instagram.com/reels/Ddz7ttGyHzZ/\n"
            "Pesan: Menyoroti dugaan penggunaan uang palsu oleh seorang perempuan berjaket ojol.\n"
            "Engagement: Like 4,959, Comment 375, Repost 347\n"
            "Total Engagement: 5,681",
        )

    def test_multiple_posts_compile_platforms_and_total_engagement(self):
        caption = (
            "Dugaan pencurian motor milik driver Shopee oleh seseorang yang disebut sebagai driver Gojek. "
            "Kejadian disebut terekam CCTV pada 26 September 2026."
        )
        results = [
            result(
                "TikTok",
                "https://www.tiktok.com/@arifsyy1/video/7691333644505353492",
                "arifsyy1",
                "2026-09-30",
                caption,
                likes=16,
                comments=0,
                bookmarks=0,
            ),
            result(
                "Facebook",
                "https://www.facebook.com/reel/2709994866104626",
                "Arif Syaifudin",
                "2026-09-30",
                caption,
                likes=1,
            ),
            result(
                "Facebook",
                "https://www.facebook.com/watch/?v=1418485900478874",
                "Devandra Karuli - Shopee Food Driver & SPX Driver Jabodetabek",
                "2026-09-30",
                caption,
                likes=3,
                comments=0,
                shares=0,
            ),
        ]

        report = format_social_report(results, "Indonesia")

        self.assertIn("TikTok & Facebook — 30 Sep 2026 — 3 Posts", report)
        self.assertIn("Pesan: Tiga unggahan menyoroti", report)
        self.assertIn("@arifsyy1 — 30 Sep 2026", report)
        self.assertIn("Engagement: Like 16, Comment 0, Save 0", report)
        self.assertIn(
            "Devandra Karuli / Shopee Food Driver & SPX Driver Jabodetabek — 30 Sep 2026",
            report,
        )
        self.assertIn("Engagement: Like 3, Comment 0, Share 0", report)
        self.assertTrue(report.endswith("Total All Engagement: 20"))

    def test_english_option_changes_report_labels_and_message_frame(self):
        posts = [
            result(
                "X",
                "https://x.com/akun/status/1",
                "akun",
                "2026-09-28",
                "A driver reported a missing motorcycle after reviewing CCTV footage.",
                likes=5,
                reposts=2,
            ),
            result(
                "Instagram",
                "https://www.instagram.com/p/ABC/",
                "akunlain",
                "2026-09-30",
                "The recording was shared to help identify the vehicle.",
                likes=7,
                comments=1,
            ),
        ]

        report = format_social_report(posts, "English")

        self.assertIn("X & Instagram — 28–30 Sep 2026 — 2 Posts", report)
        self.assertIn("Message: Two posts highlight", report)
        self.assertNotIn("Pesan:", report)
        self.assertTrue(report.endswith("Total All Engagement: 15"))

    def test_engagement_ignores_views_and_unreadable_counters(self):
        post = result(
            "TikTok",
            "https://www.tiktok.com/@akun/video/1",
            "akun",
            "2026-09-30",
            "Caption posting yang dapat diringkas.",
            likes=10,
        )
        post.views = field(50_000)
        post.comments = field(None, FieldStatus.BLOCKED)

        items, total = engagement_items(post)

        self.assertEqual(items, [("Like", 10)])
        self.assertEqual(total, 10)

    def test_caption_message_is_deduplicated_across_reposts(self):
        caption = "Rekaman CCTV memperlihatkan kejadian yang sama. Informasi dibagikan untuk membantu pencarian."
        posts = [
            result("Facebook", f"https://facebook.com/reel/{index}", f"Akun {index}", "2026-09-30", caption, likes=1)
            for index in range(3)
        ]

        message = build_social_report_message(posts, "Indonesia")

        self.assertEqual(message.count("Rekaman CCTV"), 1)
        self.assertEqual(message.count("Informasi dibagikan"), 1)


if __name__ == "__main__":
    unittest.main()
