import unittest
from unittest.mock import Mock

from src.connectors import get_connector
from src.instagram_browser import (
    InstagramBrowserCollector,
    InstagramBrowserMetrics,
    apply_instagram_browser_metrics,
    build_instagram_browser_result,
)


class InstagramBrowserTests(unittest.TestCase):
    def test_reads_human_counts_used_by_instagram(self):
        self.assertEqual(InstagramBrowserCollector._labeled_count("2.4M followers", "followers"), 2_400_000)
        self.assertEqual(InstagramBrowserCollector._labeled_count("7,630 views", "views"), 7_630)
        self.assertEqual(InstagramBrowserCollector._labeled_count("2 reposts", "reposts"), 2)

    def test_reads_metrics_only_near_matching_shortcode(self):
        source = (
            '{"code":"PostingLain","play_count":900000,"reshare_count":88},'
            '{"code":"DcXvhSAjDVx","play_count":7630,"reshare_count":2}'
        )
        self.assertEqual(
            InstagramBrowserCollector._target_metric(source, "DcXvhSAjDVx", "play_count"),
            7_630,
        )
        self.assertEqual(
            InstagramBrowserCollector._target_metric(source, "DcXvhSAjDVx", "reshare_count"),
            2,
        )

    def test_finds_media_id_for_matching_shortcode(self):
        source = (
            '{"pk":"111","code":"PostingLain","play_count":900000},'
            '{"pk":"3969850591815677297","code":"DcXvhSAjDVx","play_count":7630}'
        )
        self.assertEqual(
            InstagramBrowserCollector._target_media_pk(source, "DcXvhSAjDVx"),
            "3969850591815677297",
        )

    def test_decodes_media_id_when_page_source_has_no_post_json(self):
        self.assertEqual(
            InstagramBrowserCollector._target_media_pk("<html></html>", "DcXvhSAjDVx"),
            "3969850591815677297",
        )

    def test_reads_authenticated_media_info(self):
        source = '''{"items":[{"pk":"3969850591815677297","code":"DcXvhSAjDVx","media_type":2,"product_type":"clips","play_count":7630,"media_repost_count":2,"like_count":59,"comment_count":3,"share_count":4,"taken_at":1788249600,"user":{"username":"liputan6"},"caption":{"text":"Caption utama"},"carousel_media":[{"like_count":9999,"comment_count":9999}]}]}'''
        self.assertEqual(
            InstagramBrowserCollector._media_info_metrics(source),
            (2, 7_630),
        )
        engagement = InstagramBrowserCollector._media_info_engagement(source)
        self.assertEqual(engagement.likes, 59)
        self.assertEqual(engagement.comments, 3)
        self.assertEqual(engagement.shares, 4)
        self.assertEqual(engagement.username, "liputan6")
        self.assertEqual(engagement.caption, "Caption utama")
        self.assertTrue(engagement.views_applicable)

    def test_carousel_uses_main_media_counts_and_skips_view_lookup(self):
        source = '''{"items":[{"media_type":8,"product_type":"carousel_container","media_repost_count":12,"like_count":958,"comment_count":21,"carousel_media":[{"like_count":9999,"comment_count":9999,"play_count":9999}]}]}'''
        engagement = InstagramBrowserCollector._media_info_engagement(source)
        self.assertEqual(engagement.likes, 958)
        self.assertEqual(engagement.comments, 21)
        self.assertEqual(engagement.reposts, 12)
        self.assertIsNone(engagement.views)
        self.assertFalse(engagement.views_applicable)

    def test_reads_exact_followers_from_authenticated_profile_info(self):
        source = '''{"data":{"user":{"username":"idx_channel","follower_count":1123456,"edge_followed_by":{"count":999}}}}'''
        self.assertEqual(
            InstagramBrowserCollector._profile_info_followers(source),
            1_123_456,
        )

    def test_reads_followers_from_matching_profile_page_payload(self):
        source = '''<html><head><script type="application/json">{"profiles":[{"username":"other_account","follower_count":999999},{"username":"bdg.info","follower_count":24400}]}</script></head></html>'''
        self.assertEqual(
            InstagramBrowserCollector._profile_page_followers(source, "bdg.info"),
            24_400,
        )

    def test_profile_page_followers_ignore_a_different_account(self):
        source = '''<html><head><script type="application/json">{"username":"recommended","follower_count":999999}</script></head></html>'''
        self.assertIsNone(
            InstagramBrowserCollector._profile_page_followers(source, "target_account")
        )

    def test_reads_rounded_followers_from_matching_profile_description(self):
        source = '''<html><head><meta property="og:description" content="24.4K Followers, 78 Following, 355 Posts - See Instagram photos and videos from Vonix Media (@vonixmedia.id)"></head></html>'''
        self.assertEqual(
            InstagramBrowserCollector._profile_page_followers(source, "vonixmedia.id"),
            24_400,
        )

    def test_browser_metrics_replace_public_fallbacks(self):
        result = get_connector("https://www.instagram.com/p/demo/").mock_enrichment(
            "https://www.instagram.com/p/demo/"
        )
        result.followers.value = 2_000_000
        result.views.value = 0
        result.reposts.value = 0
        updated = apply_instagram_browser_metrics(
            result,
            InstagramBrowserMetrics(followers=2_400_000, views=7_630, reposts=2),
        )
        self.assertEqual(updated.followers.value, 2_400_000)
        self.assertEqual(updated.views.value, 7_630)
        self.assertEqual(updated.reposts.value, 2)
        self.assertIn("browser MIDETA", updated.note)

    def test_reads_post_metadata_when_public_request_is_empty(self):
        source = """<html><head><meta property="og:description" content="1 likes, 0 comments - ctv.now on September 4, 2026: &quot;Caption lengkap dari browser&quot;"></head></html>"""
        metrics = InstagramBrowserCollector._post_metadata(
            source,
            "https://www.instagram.com/p/Dc2ayNXjxmW/",
            "Dc2ayNXjxmW",
        )
        self.assertEqual(metrics.username, "ctv.now")
        self.assertEqual(metrics.caption, "Caption lengkap dari browser")
        self.assertEqual(metrics.posted_at, "2026-09-04")
        self.assertEqual(metrics.likes, 1)
        self.assertEqual(metrics.comments, 0)

    def test_advanced_carousel_opens_profile_without_slow_view_search(self):
        collector = InstagramBrowserCollector()
        collector.is_logged_in = Mock(return_value=True)
        collector._post_metrics = Mock(
            return_value=InstagramBrowserMetrics(
                username="ctv.now",
                caption="Caption browser",
                posted_at="2026-09-04",
                likes=1,
                comments=0,
                reposts=0,
                views_applicable=False,
            )
        )
        collector._profile_metrics = Mock(return_value=(36_500, 1_211))

        metrics = collector.collect(
            "https://www.instagram.com/p/Dc2ayNXjxmW/",
            None,
            mode="advanced",
        )

        self.assertEqual(metrics.username, "ctv.now")
        self.assertEqual(metrics.followers, 36_500)
        self.assertEqual(metrics.views, 1_211)
        collector._profile_metrics.assert_called_once_with(
            "ctv.now",
            "Dc2ayNXjxmW",
            find_views=False,
        )

    def test_browser_result_keeps_original_url_and_does_not_invent_photo_views(self):
        url = "https://www.instagram.com/p/Db9aVzLkx0i/"
        result = build_instagram_browser_result(
            url,
            InstagramBrowserMetrics(
                username="idx_channel",
                followers=1_100_000,
                likes=958,
                comments=21,
                reposts=12,
                views_applicable=False,
            ),
            mode="advanced",
        )
        self.assertEqual(result.url, url)
        self.assertEqual(result.likes.value, 958)
        self.assertEqual(result.comments.value, 21)
        self.assertEqual(result.reposts.value, 12)
        self.assertIsNone(result.views.value)

    def test_fast_mode_does_not_open_profile_or_return_profile_metrics(self):
        collector = InstagramBrowserCollector()
        collector.is_logged_in = Mock(return_value=True)
        collector._post_metrics = Mock(
            return_value=InstagramBrowserMetrics(
                username="ctv.now",
                followers=36_500,
                views=1_211,
                likes=35,
                comments=0,
                shares=2,
                reposts=1,
            )
        )
        collector._profile_metrics = Mock()

        metrics = collector.collect(
            "https://www.instagram.com/p/Dc2ayNXjxmW/",
            None,
            mode="fast",
        )

        self.assertEqual(metrics.username, "ctv.now")
        self.assertIsNone(metrics.followers)
        self.assertIsNone(metrics.views)
        self.assertEqual(metrics.likes, 35)
        self.assertEqual(metrics.comments, 0)
        self.assertEqual(metrics.shares, 2)
        self.assertEqual(metrics.reposts, 1)
        collector._profile_metrics.assert_not_called()

    def test_fast_metrics_hide_public_profile_fallbacks(self):
        result = get_connector("https://www.instagram.com/p/demo/").mock_enrichment(
            "https://www.instagram.com/p/demo/"
        )
        updated = apply_instagram_browser_metrics(
            result,
            InstagramBrowserMetrics(likes=9, comments=2, shares=1, reposts=3),
            mode="fast",
        )

        self.assertIsNone(updated.followers.value)
        self.assertIsNone(updated.views.value)
        self.assertEqual(updated.likes.value, 9)
        self.assertEqual(updated.comments.value, 2)
        self.assertEqual(updated.shares.value, 1)
        self.assertEqual(updated.reposts.value, 3)
        self.assertIn("Fast enrichment", updated.note)

    def test_browser_metadata_fills_an_empty_public_result(self):
        result = get_connector("https://www.instagram.com/p/demo/").mock_enrichment(
            "https://www.instagram.com/p/demo/"
        )
        for field in (result.username, result.caption, result.posted_at, result.likes, result.comments):
            field.value = None
            field.status = "Not publicly visible"
        updated = apply_instagram_browser_metrics(
            result,
            InstagramBrowserMetrics(
                username="ctv.now",
                caption="Caption dari browser",
                posted_at="2026-09-04",
                likes=1,
                comments=0,
            ),
        )
        self.assertEqual(updated.username.value, "ctv.now")
        self.assertEqual(updated.caption.value, "Caption dari browser")
        self.assertEqual(updated.posted_at.value, "2026-09-04")
        self.assertEqual(updated.likes.value, 1)
        self.assertEqual(updated.comments.value, 0)


if __name__ == "__main__":
    unittest.main()
