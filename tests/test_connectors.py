import unittest
from unittest.mock import patch
from src.connectors import detect_platform, get_connector, get_platform_connector
from src.connectors.base import BaseConnector
from src.models import FieldStatus

SOCIAL_HTML = """<html><head><meta name="author" content="@akun"><meta property="og:description" content="Caption publik"><script type="application/ld+json">{"@type":"SocialMediaPosting","datePublished":"2026-08-30","interactionStatistic":{"interactionType":"LikeAction","userInteractionCount":42}}</script><script>{"viewCount":"1200","repostCount":"8"}</script></head></html>"""
COMMENT_HTML = """<script type="application/ld+json">{"@type":"Article","comment":[{"@type":"Comment","text":"Komentar publik","author":{"name":"Ayu"},"upvoteCount":3,"comment":[{"@type":"Comment","text":"Balasan publik","author":{"name":"Bima"},"upvoteCount":1}]}]}</script>"""
FACEBOOK_HTML = """<html><head><meta property="og:description" content="Caption tetap utuh"></head><body><script>{"owner":{"name":"Media Indonesia"},"publish_time":1788048000,"reaction_count":{"count":125},"comment_count":{"count":18},"share_count":7,"video_view_count":6400}</script></body></html>"""
FACEBOOK_META_HTML = """<html><head><meta property="og:description" content="Caption tetap utuh"><meta property="og:image:alt" content="1,2 rb tayangan · 9 suka · 3 komentar · 2 kali dibagikan | Caption tetap utuh"></head></html>"""
FACEBOOK_REEL_META_HTML = """<html><head><link rel="canonical" href="https://www.facebook.com/akun/videos/judul/123"><meta property="og:description" content="Caption Reel"><meta property="og:image:alt" content="93 tanggapan · 17 komentar | Caption Reel | Akun"></head><script>{"id":"123","comment_rendering_instance":{"comments":{"total_count":21}}}</script></html>"""
FACEBOOK_REEL_FEEDBACK_HTML = """<html><head><link rel="canonical" href="https://www.facebook.com/akun/videos/judul/123"><link rel="alternate" title="Caption Reel lengkap. Paragraf kedua juga masuk. | Akun"><meta property="og:description" content="Caption Reel lengkap..."><meta property="og:image:alt" content="450 rb tayangan · 23 rb tanggapan | Caption Reel lengkap. Paragraf kedua juga masuk. | Akun"></head><script>{"feedback":{"total_comment_count":1468,"share_count_reduced":"1,3 rb"},"post_id":"456","tracking":"{\\"top_level_post_id\\":\\"123\\",\\"video_id\\":\\"123\\"}"}</script></html>"""
FACEBOOK_CANONICAL_HTML = """<html><head><link rel="canonical" href="https://www.facebook.com/akuratco/posts/judul/789"><meta property="og:description" content="Caption"></head><script>{"id":"789","feedback":{"reaction_count":{"count":5},"share_count":{"count":1},"comment_rendering_instance":{"comments":{"total_count":0}}}}</script></html>"""
FACEBOOK_FULL_CAPTION_HTML = """<html><head><meta property="og:description" content="Paragraf pertama yang lengkap..."></head><body><div data-ad-rendering-role="story_message"><div dir="auto">Paragraf pertama yang lengkap.</div><div dir="auto">Paragraf kedua juga harus masuk.</div></div></body></html>"""
FACEBOOK_GROUP_HTML = """<html><head><meta property="og:title" content="LIOC ( LIKA LIKU OJOL &amp; CUSTOMER ) | Caption grup | Facebook"><meta property="og:description" content="Caption grup..."><meta property="og:url" content="https://www.facebook.com/groups/1657323981260301/posts/4699586193700716/"></head><body><script>{"join_action":{"group":{"id":"1657323981260301","name":"LIOC ( LIKA LIKU OJOL & CUSTOMER )"}},"node_v2":{"actors":[{"name":"Gondrong Saja"}],"message":{"text":"Caption grup lengkap. Paragraf kedua juga masuk."},"post_id":"4699586193700716"}}</script></body></html>"""

class TestPublicConnector(BaseConnector):
    platform = "Test"
    supports_public_comments = True

class ConnectorTests(unittest.TestCase):
    def test_detects_all_initial_platforms(self):
        cases = {"https://youtube.com/watch?v=a": "YouTube", "https://youtu.be/a": "YouTube", "https://facebook.com/a": "Facebook", "https://web.facebook.com/groups/1/permalink/2": "Facebook", "https://instagram.com/p/a": "Instagram", "https://threads.net/@a/post/1": "Threads", "https://x.com/a/status/1": "X", "https://tiktok.com/@a/video/1": "TikTok"}
        for url, platform in cases.items():
            with self.subTest(url=url): self.assertEqual(detect_platform(url), platform)

    @patch("src.connectors.base.fetch_public_html", return_value=(SOCIAL_HTML, "https://instagram.com/p/a"))
    @patch("src.connectors.base.validate_public_url", return_value="https://instagram.com/p/a")
    def test_enrichment_preserves_missing_values_and_status(self, _validate, _fetch):
        result = get_connector("https://instagram.com/p/a").enrich("https://instagram.com/p/a")
        self.assertEqual(result.username.value, "@akun")
        self.assertEqual(result.likes.value, 42)
        self.assertEqual(result.views.value, 1200)
        self.assertEqual(result.reposts.value, 8)
        self.assertIsNone(result.followers.value)
        self.assertEqual(result.followers.status, FieldStatus.NOT_SUPPORTED)

    @patch("src.connectors.base.fetch_public_html", return_value=(COMMENT_HTML, "https://example.com/post"))
    @patch("src.connectors.base.validate_public_url", return_value="https://example.com/post")
    def test_collects_public_jsonld_comments(self, _validate, _fetch):
        result = TestPublicConnector().collect_comments("https://example.com/post")
        self.assertEqual(result.status, FieldStatus.AVAILABLE)
        self.assertEqual(result.comments[0].author, "Ayu")
        self.assertEqual(result.comments[0].likes, 3)
        self.assertEqual(result.comments[0].comment_type, "parent")
        self.assertEqual(result.comments[0].reply_count, 1)
        self.assertEqual(result.comments[1].comment_type, "reply")

    def test_mock_is_explicitly_labelled(self):
        result = get_connector("https://x.com/a/status/1").mock_enrichment("https://x.com/a/status/1")
        self.assertTrue(result.is_mock)
        self.assertIn("data contoh", result.note.lower())

    @patch("src.connectors.base.fetch_public_html", return_value=(FACEBOOK_HTML, "https://www.facebook.com/mediaindonesia/videos/123"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/mediaindonesia/videos/123")
    def test_facebook_reads_public_script_fields(self, _validate, _fetch):
        result = get_connector("https://www.facebook.com/mediaindonesia/videos/123").enrich("https://www.facebook.com/mediaindonesia/videos/123")
        self.assertEqual(result.caption.value, "Caption tetap utuh")
        self.assertEqual(result.username.value, "Media Indonesia")
        self.assertEqual(result.likes.value, 125)
        self.assertEqual(result.comments.value, 18)
        self.assertEqual(result.shares.value, 7)
        self.assertEqual(result.views.value, 6400)
        self.assertTrue(str(result.posted_at.value).startswith("2026"))

    @patch("src.connectors.base.fetch_public_html", return_value=("<meta property=\"og:description\" content=\"Caption\">", "https://www.facebook.com/akuratco/posts/123"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/akuratco/posts/123")
    def test_facebook_uses_public_url_slug_as_author_fallback(self, _validate, _fetch):
        result = get_connector("https://www.facebook.com/akuratco/posts/123").enrich("https://www.facebook.com/akuratco/posts/123")
        self.assertEqual(result.username.value, "akuratco")

    @patch("src.connectors.base.fetch_public_html", return_value=(FACEBOOK_META_HTML, "https://www.facebook.com/mediaindonesia/videos/123"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/mediaindonesia/videos/123")
    def test_facebook_uses_public_meta_text_as_metric_fallback(self, _validate, _fetch):
        result = get_connector("https://www.facebook.com/mediaindonesia/videos/123").enrich("https://www.facebook.com/mediaindonesia/videos/123")
        self.assertEqual(result.views.value, 1200)
        self.assertEqual(result.likes.value, 9)
        self.assertEqual(result.comments.value, 3)
        self.assertEqual(result.shares.value, 2)

    @patch("src.connectors.base.fetch_public_html", return_value=(FACEBOOK_REEL_META_HTML, "https://www.facebook.com/reel/123"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/reel/123")
    def test_facebook_reel_maps_tanggapan_to_likes(self, _validate, _fetch):
        result = get_connector("https://www.facebook.com/reel/123").enrich("https://www.facebook.com/reel/123")
        self.assertEqual(result.caption.value, "Caption Reel")
        self.assertEqual(result.likes.value, 93)
        self.assertEqual(result.comments.value, 17)

    @patch("src.connectors.base.fetch_public_html", return_value=(FACEBOOK_REEL_FEEDBACK_HTML, "https://www.facebook.com/reel/123"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/reel/123")
    def test_facebook_reel_reads_reduced_metrics_and_full_caption(self, _validate, _fetch):
        result = get_connector("https://www.facebook.com/reel/123").enrich("https://www.facebook.com/reel/123")
        self.assertEqual(result.views.value, 450000)
        self.assertEqual(result.likes.value, 23000)
        self.assertEqual(result.comments.value, 1468)
        self.assertEqual(result.shares.value, 1300)
        self.assertEqual(result.caption.value, "Caption Reel lengkap. Paragraf kedua juga masuk.")

    @patch("src.connectors.base.fetch_public_html", return_value=(FACEBOOK_FULL_CAPTION_HTML, "https://www.facebook.com/akun/posts/123"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/akun/posts/123")
    def test_facebook_post_reads_all_visible_caption_paragraphs(self, _validate, _fetch):
        result = get_connector("https://www.facebook.com/akun/posts/123").enrich("https://www.facebook.com/akun/posts/123")
        self.assertIn("Paragraf pertama yang lengkap.", result.caption.value)
        self.assertIn("Paragraf kedua juga harus masuk.", result.caption.value)
        self.assertNotIn("...", result.caption.value)

    @patch("src.connectors.base.fetch_public_html", return_value=(FACEBOOK_GROUP_HTML, "https://www.facebook.com/groups/1657323981260301/permalink/4699586193700716/"))
    @patch("src.connectors.base.validate_public_url", return_value="https://web.facebook.com/groups/1657323981260301/permalink/4699586193700716/")
    def test_facebook_group_combines_post_author_and_group_name(self, _validate, _fetch):
        url = "https://web.facebook.com/groups/1657323981260301/permalink/4699586193700716/"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.username.value, "Gondrong Saja - LIOC ( LIKA LIKU OJOL & CUSTOMER )")
        self.assertEqual(result.caption.value, "Caption grup lengkap. Paragraf kedua juga masuk.")

    @patch("src.connectors.base.fetch_public_html", return_value=(FACEBOOK_CANONICAL_HTML, "https://www.facebook.com/akuratco/posts/pfbidABC"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/akuratco/posts/pfbidABC")
    def test_facebook_uses_canonical_post_id_for_pfbid_metrics(self, _validate, _fetch):
        result = get_connector("https://www.facebook.com/akuratco/posts/pfbidABC").enrich("https://www.facebook.com/akuratco/posts/pfbidABC")
        self.assertEqual(result.likes.value, 5)
        self.assertEqual(result.comments.value, 0)
        self.assertEqual(result.shares.value, 1)

    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/akun/posts/123")
    def test_facebook_ignores_metrics_from_recommended_posts(self, _validate):
        unrelated = '<script>{"id":"999","reaction_count":{"count":999},"play_count":9999}</script>'
        schema_only = '<script>{"id":"123","schema":"' + ("reaction_count play_count feedback " * 30) + '"}</script>'
        target = '<script>{"id":"123","feedback":{"reaction_count":{"count":9},"total_comment_count":3,"play_count":1269}}</script>'
        html = unrelated + (" " * 20_000) + schema_only + (" " * 25_000) + target
        with patch("src.connectors.base.fetch_public_html", return_value=(html, "https://www.facebook.com/akun/posts/123")):
            result = get_connector("https://www.facebook.com/akun/posts/123").enrich("https://www.facebook.com/akun/posts/123")
        self.assertEqual(result.likes.value, 9)
        self.assertEqual(result.comments.value, 3)
        self.assertEqual(result.views.value, 1269)

    def test_selected_platform_rejects_a_different_platform(self):
        with self.assertRaisesRegex(ValueError, "terdeteksi sebagai X"):
            get_platform_connector("https://x.com/a/status/1", "YouTube")
