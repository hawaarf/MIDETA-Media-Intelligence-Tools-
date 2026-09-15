import unittest
from unittest.mock import Mock

from src.tiktok_browser import (
    TikTokBrowserCollector,
    TikTokBrowserMetrics,
    build_tiktok_browser_result,
)


TARGET_SOURCE = r'''<html><script type="application/json">{
  "target": {
    "id": "7684605378314669319",
    "desc": "program apresiasi mitra gojek yang memberangkatkan umroh\n\n#gojek #umroh\n\ncr. realitaojol_",
    "createTime": 1789211620,
    "author": {"uniqueId": "ojol.spill"},
    "stats": {
      "playCount": 629,
      "diggCount": 17,
      "commentCount": 1,
      "shareCount": 1,
      "collectCount": 0
    }
  },
  "recommendation": {
    "id": "9999999999999999999",
    "desc": "caption yang salah",
    "author": {"uniqueId": "akun.lain"},
    "stats": {"playCount": 9000000, "diggCount": 8000000}
  }
}</script></html>'''


class TikTokBrowserTests(unittest.TestCase):
    def test_reads_caption_and_metrics_only_from_target_video(self):
        metrics = TikTokBrowserCollector._video_metrics_from_source(
            TARGET_SOURCE,
            "7684605378314669319",
        )

        self.assertEqual(metrics.username, "ojol.spill")
        self.assertIn("program apresiasi mitra gojek", metrics.caption)
        self.assertIn("cr. realitaojol_", metrics.caption)
        self.assertEqual(metrics.views, 629)
        self.assertEqual(metrics.likes, 17)
        self.assertEqual(metrics.comments, 1)
        self.assertEqual(metrics.shares, 1)
        self.assertEqual(metrics.bookmarks, 0)

    def test_reads_followers_only_for_requested_profile(self):
        source = '''<html><script type="application/json">{
          "users": [
            {"uniqueId": "akun.lain", "stats": {"followerCount": 9789}},
            {"uniqueId": "ojol.spill", "stats": {"followerCount": 48200}}
          ]
        }</script></html>'''

        self.assertEqual(
            TikTokBrowserCollector._profile_followers_from_source(source, "ojol.spill"),
            48_200,
        )
        self.assertIsNone(
            TikTokBrowserCollector._profile_followers_from_source(source, "tidak.ada"),
        )

    def test_collect_opens_target_video_and_matching_profile(self):
        collector = TikTokBrowserCollector()
        collector.is_logged_in = Mock(return_value=True)
        collector._post_metrics = Mock(
            return_value=TikTokBrowserMetrics(
                username="ojol.spill",
                caption="Caption lengkap",
                views=629,
                likes=17,
                comments=1,
                shares=1,
            )
        )
        collector._profile_metrics = Mock(return_value=(48_200, 629))
        url = "https://www.tiktok.com/@ojol.spill/video/7684605378314669319"

        metrics = collector.collect(url)

        self.assertEqual(metrics.followers, 48_200)
        collector._post_metrics.assert_called_once_with(url, "7684605378314669319")
        collector._profile_metrics.assert_called_once_with("ojol.spill", "7684605378314669319")

    def test_build_result_does_not_fill_missing_fields_with_unrelated_zeros(self):
        result = build_tiktok_browser_result(
            "https://www.tiktok.com/@ojol.spill/video/7684605378314669319",
            TikTokBrowserMetrics(
                username="ojol.spill",
                caption="Caption lengkap",
                followers=48_200,
                views=629,
                likes=17,
                comments=1,
                shares=1,
                bookmarks=0,
            ),
        )

        self.assertEqual(result.caption.value, "Caption lengkap")
        self.assertEqual(result.followers.value, 48_200)
        self.assertEqual(result.views.value, 629)
        self.assertEqual(result.bookmarks.value, 0)
        self.assertIsNone(result.reposts.value)


if __name__ == "__main__":
    unittest.main()
