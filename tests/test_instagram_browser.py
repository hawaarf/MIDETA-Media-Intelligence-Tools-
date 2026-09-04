import unittest

from src.connectors import get_connector
from src.instagram_browser import (
    InstagramBrowserCollector,
    InstagramBrowserMetrics,
    apply_instagram_browser_metrics,
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
        source = '{"items":[{"pk":"3969850591815677297","play_count":7630,"media_repost_count":2}]}'
        self.assertEqual(
            InstagramBrowserCollector._media_info_metrics(source),
            (2, 7_630),
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


if __name__ == "__main__":
    unittest.main()
