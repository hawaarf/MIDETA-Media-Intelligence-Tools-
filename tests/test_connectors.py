import unittest
from unittest.mock import patch
from src.connectors import detect_platform, get_connector, get_platform_connector
from src.connectors.base import BaseConnector
from src.models import FieldStatus

SOCIAL_HTML = """<html><head><meta name="author" content="@akun"><meta property="og:description" content="Caption publik"><script type="application/ld+json">{"@type":"SocialMediaPosting","datePublished":"2026-08-30","interactionStatistic":{"interactionType":"LikeAction","userInteractionCount":42}}</script><script>{"viewCount":"1200","repostCount":"8"}</script></head></html>"""
INSTAGRAM_DATE_HTML = """<html><head><meta property="og:description" content="696 likes, 41 comments - nengrikagodel on August 31, 2026: &quot;Caption publik&quot;"><meta name="author" content="nengrikagodel"></head></html>"""
INSTAGRAM_PROFILE_POST_HTML = """<html><head><meta property="og:description" content="10 likes, 2 comments - profilcontoh on August 25, 2026: &quot;Caption publik&quot;"><meta name="author" content="profilcontoh"></head></html>"""
INSTAGRAM_PROFILE_HTML = """<html><head><meta property="og:description" content="136K Followers, 1,558 Following, 1,349 Posts - Profil Contoh (@profilcontoh)"></head></html>"""
INSTAGRAM_DECIMAL_PROFILE_HTML = """<html><head><meta property="og:description" content="24.4K Followers, 78 Following, 355 Posts - Vonix Media (@vonixmedia.id)"></head></html>"""
INSTAGRAM_REEL_POST_HTML = """<html><head><meta property="og:url" content="https://www.instagram.com/lambe_ojol/p/DcS9N_5TZkQ/"><meta property="og:description" content="11 likes, 0 comments - lambe_ojol on August 12, 2026: &quot;Caption Reel&quot;"><meta name="author" content="lambe_ojol"></head></html>"""
INSTAGRAM_REELS_GRID_HTML = """<html><script>{"node":{"play_count":17235,"code":"Dccw99-zaZF"}},{"node":{"play_count":412,"code":"DcS9N_5TZkQ"}},{"node":{"play_count":374,"code":"DcQpZWsz9-G"}}</script></html>"""
TIKTOK_STATS_HTML = """<html><head><meta property="og:description" content="Caption TikTok"></head><script>{"author":{"uniqueId":"akun"},"authorStats":{"followerCount":1250},"stats":{"playCount":6400},"createTime":1788048000}</script></html>"""
THREADS_POST_HTML = """<html><head><meta property="og:description" content="Caption Threads"></head><body><span>08/14/26</span><script>{"username":"jkt.feed","view_counts":4494,"text_post_app_info":{"direct_reply_count":0},"code":"DcBid9oEqtV"}</script></body></html>"""
THREADS_PROFILE_HTML = """<html><head><meta property="og:description" content="88.7K Followers • 68 Threads. See the latest conversations with @jkt.feed."></head><script>{"follower_count":88725}</script></html>"""
THREADS_COMMENT_HTML = """<html><head><meta property="og:description" content="Caption Threads"></head><script>{"text_post_app_info":{"direct_reply_count":44},"code":"PostingLain"},{"text_post_app_info":{"direct_reply_count":8},"code":"DcgoGvoAQxG"}</script></html>"""
THREADS_TWO_COMMENTS_HTML = """<html><head><meta property="og:description" content="Caption Threads"></head><script>{"view_counts":225,"text_post_app_info":{"direct_reply_count":2},"code":"DciTeqClGKc"}</script></html>"""
THREADS_TAKEN_AT_HTML = """<html><script>{"code":"PostingLain","taken_at":1788245420},{"code":"DcxnOUwk51O","text_post_app_info":{"direct_reply_count":0},"taken_at":1788331158}</script></html>"""
INSTAGRAM_REPOST_HTML = """<html><head><meta property="og:description" content="Caption Instagram"></head><script>{"code":"PostingLain","repost_count":91},{"code":"DcRepost123","reshare_count":7}</script></html>"""
INSTAGRAM_VISIBLE_REPOST_HTML = """<html><head><meta property="og:description" content="7.6K likes, 144 comments - gnfi on August 30, 2026: &quot;Caption bersih saja&quot;"><meta name="author" content="gnfi"></head><script>{"node":{"reshare_count_reduced":"70","shortcode":"DcqWqENG04A"}}</script></html>"""
COMMENT_HTML = """<script type="application/ld+json">{"@type":"Article","comment":[{"@type":"Comment","text":"Komentar publik","author":{"name":"Ayu"},"upvoteCount":3,"comment":[{"@type":"Comment","text":"Balasan publik","author":{"name":"Bima"},"upvoteCount":1}]}]}</script>"""
FACEBOOK_HTML = """<html><head><meta property="og:description" content="Caption tetap utuh"></head><body><script>{"owner":{"name":"Media Indonesia"},"publish_time":1788048000,"reaction_count":{"count":125},"comment_count":{"count":18},"share_count":7,"video_view_count":6400}</script></body></html>"""
FACEBOOK_META_HTML = """<html><head><meta property="og:description" content="Caption tetap utuh"><meta property="og:image:alt" content="1,2 rb tayangan · 9 suka · 3 komentar · 2 kali dibagikan | Caption tetap utuh"></head></html>"""
FACEBOOK_REEL_META_HTML = """<html><head><link rel="canonical" href="https://www.facebook.com/akun/videos/judul/123"><meta property="og:description" content="Caption Reel"><meta property="og:image:alt" content="93 tanggapan · 17 komentar | Caption Reel | Akun"></head><script>{"id":"123","comment_rendering_instance":{"comments":{"total_count":21}}}</script></html>"""
FACEBOOK_REEL_FEEDBACK_HTML = """<html><head><link rel="canonical" href="https://www.facebook.com/akun/videos/judul/123"><link rel="alternate" title="Caption Reel lengkap. Paragraf kedua juga masuk. | Akun"><meta property="og:description" content="Caption Reel lengkap..."><meta property="og:image:alt" content="450 rb tayangan · 23 rb tanggapan | Caption Reel lengkap. Paragraf kedua juga masuk. | Akun"></head><script>{"feedback":{"total_comment_count":1468,"share_count_reduced":"1,3 rb"},"post_id":"456","tracking":"{\\"top_level_post_id\\":\\"123\\",\\"video_id\\":\\"123\\"}"}</script></html>"""
FACEBOOK_REEL_LIKERS_HTML = """<html><head><link rel="canonical" href="https://www.facebook.com/akun/videos/judul/1407754307910903"><meta property="og:description" content="Caption Reel"></head><script>{"feedback":{"likers":{"count":3},"unified_reactors":{"count":3},"total_comment_count":1,"share_count_reduced":"0"},"tracking":"{\\"top_level_post_id\\":\\"1407754307910903\\",\\"video_id\\":\\"1407754307910903\\"}"}</script></html>"""
FACEBOOK_REEL_ZERO_LIKERS_HTML = """<html><head><link rel="canonical" href="https://www.facebook.com/akun/videos/judul/1064880916011501"><meta property="og:description" content="Caption Reel"></head><script>{"feedback":{"likers":{"count":0},"unified_reactors":{"count":0},"total_comment_count":0,"share_count_reduced":"0"},"tracking":"{\\"top_level_post_id\\":\\"1064880916011501\\",\\"video_id\\":\\"1064880916011501\\"}"}</script></html>"""
FACEBOOK_REEL_REDUCED_LIKES_HTML = """<html><head><link rel="canonical" href="https://www.facebook.com/akun/videos/judul/2586740801787372"><meta property="og:description" content="Caption Reel"></head><script>{"feedback":{"reaction_count_reduced":"1,2 rb","total_comment_count":4},"tracking":"{\\"top_level_post_id\\":\\"2586740801787372\\",\\"video_id\\":\\"2586740801787372\\"}"}</script></html>"""
FACEBOOK_CANONICAL_HTML = """<html><head><link rel="canonical" href="https://www.facebook.com/akuratco/posts/judul/789"><meta property="og:description" content="Caption"></head><script>{"id":"789","feedback":{"reaction_count":{"count":5},"share_count":{"count":1},"comment_rendering_instance":{"comments":{"total_count":0}}}}</script></html>"""
FACEBOOK_FULL_CAPTION_HTML = """<html><head><meta property="og:description" content="Paragraf pertama yang lengkap..."></head><body><div data-ad-rendering-role="story_message"><div dir="auto">Paragraf pertama yang lengkap.</div><div dir="auto">Paragraf kedua juga harus masuk.</div></div></body></html>"""
FACEBOOK_GROUP_HTML = """<html><head><meta property="og:title" content="LIOC ( LIKA LIKU OJOL &amp; CUSTOMER ) | Caption grup | Facebook"><meta property="og:description" content="Caption grup..."><meta property="og:url" content="https://www.facebook.com/groups/1657323981260301/posts/4699586193700716/"></head><body><script>{"join_action":{"group":{"id":"1657323981260301","name":"LIOC ( LIKA LIKU OJOL & CUSTOMER )"}},"node_v2":{"actors":[{"name":"Gondrong Saja","id":"100012853172729","url":null}],"message":{"text":"Caption grup lengkap. Paragraf kedua juga masuk."},"post_id":"4699586193700716"}}</script></body></html>"""
FACEBOOK_PROFILE_POST_HTML = """<html><head><link rel="canonical" href="https://www.facebook.com/profilcontoh/posts/123"><meta property="og:title" content="Profil Contoh"><meta property="og:description" content="Caption Facebook"></head></html>"""
FACEBOOK_FOLLOWER_PROFILE_HTML = r"""<html><script>{"text":"1,4\u00a0rb pengikut"}{"text":"2,2\u00a0rb teman"}</script></html>"""
FACEBOOK_FRIEND_PROFILE_HTML = r"""<html><script>{"text":"2,2\u00a0rb teman"}</script></html>"""
FACEBOOK_REEL_ZERO_VIEW_HTML = r"""<html><head><meta property="og:url" content="https://www.facebook.com/hery.umbuwole/videos/judul/3556314681183024/"><meta property="og:description" content="Caption Reel"></head><script>{"video_owner":{"url":"https:\/\/www.facebook.com\/hery.umbuwole"}}</script></html>"""
FACEBOOK_PROFILE_REELS_HTML = """<html><script>{"profile_reel_node":{"node":{"tracking":"{\\"video_id\\":\\"999\\"}","related_video_id":"3556314681183024","play_count_reduced":"9,9 rb"}}},{"profile_reel_node":{"node":{"tracking":"{\\"video_id\\":\\"111\\"}","play_count_reduced":"512"}}},{"profile_reel_node":{"node":{"tracking":"{\\"video_id\\":\\"3556314681183024\\"}","play_count_reduced":"132"}}},{"profile_reel_node":{"node":{"tracking":"{\\"video_id\\":\\"222\\"}","play_count_reduced":"336"}}}</script></html>"""

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
        self.assertEqual(result.followers.value, 0)
        self.assertEqual(result.followers.status, FieldStatus.AVAILABLE)

    @patch("src.connectors.base.fetch_public_html", return_value=(INSTAGRAM_DATE_HTML, "https://www.instagram.com/p/DctRVS_B29O/"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.instagram.com/p/DctRVS_B29O/")
    def test_instagram_reads_public_meta_date_and_defaults_missing_counts(self, _validate, _fetch):
        url = "https://www.instagram.com/p/DctRVS_B29O/"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.posted_at.value, "2026-08-31")
        self.assertEqual(result.followers.value, 0)
        self.assertEqual(result.views.value, 0)
        self.assertEqual(result.reposts.value, 0)

    @patch("src.connectors.base.fetch_public_html", return_value=(INSTAGRAM_REPOST_HTML, "https://www.instagram.com/p/DcRepost123/"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.instagram.com/p/DcRepost123/")
    def test_instagram_reads_reposts_from_matching_post(self, _validate, _fetch):
        url = "https://www.instagram.com/p/DcRepost123/"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.reposts.value, 7)

    @patch("src.connectors.base.fetch_public_html", side_effect=[
        (INSTAGRAM_VISIBLE_REPOST_HTML, "https://www.instagram.com/p/DcqWqENG04A/"),
        ("<html></html>", "https://www.instagram.com/gnfi/"),
        ("<html></html>", "https://www.instagram.com/gnfi/reels/"),
    ])
    @patch("src.connectors.base.validate_public_url", return_value="https://www.instagram.com/p/DcqWqENG04A/")
    def test_instagram_reads_visible_repost_and_keeps_only_caption(self, _validate, _fetch):
        url = "https://www.instagram.com/p/DcqWqENG04A/"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.reposts.value, 70)
        self.assertEqual(result.caption.value, "Caption bersih saja")

    @patch("src.connectors.base.fetch_public_html", side_effect=[
        (INSTAGRAM_PROFILE_POST_HTML, "https://www.instagram.com/p/profiletest/"),
        (INSTAGRAM_PROFILE_HTML, "https://www.instagram.com/profilcontoh/"),
        ("<html></html>", "https://www.instagram.com/profilcontoh/reels/"),
    ])
    @patch("src.connectors.base.validate_public_url", return_value="https://www.instagram.com/p/profiletest/")
    def test_instagram_reads_author_followers_from_public_profile(self, _validate, _fetch):
        url = "https://www.instagram.com/p/profiletest/"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.followers.value, 136000)

    @patch("src.connectors.base.fetch_public_html", side_effect=[
        ("""<html><head><meta name="author" content="vonixmedia.id"><meta property="og:description" content="Caption"></head><script>{"follower_count":24000}</script></html>""", "https://www.instagram.com/p/Dcvv9t0S2Y0/"),
        (INSTAGRAM_DECIMAL_PROFILE_HTML, "https://www.instagram.com/vonixmedia.id/"),
        ("<html></html>", "https://www.instagram.com/vonixmedia.id/reels/"),
    ])
    @patch("src.connectors.base.validate_public_url", return_value="https://www.instagram.com/p/Dcvv9t0S2Y0/")
    def test_instagram_prefers_decimal_profile_followers_over_post_page_count(self, _validate, _fetch):
        url = "https://www.instagram.com/p/Dcvv9t0S2Y0/"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.followers.value, 24400)

    @patch("src.connectors.base.fetch_public_html", side_effect=[
        (INSTAGRAM_REEL_POST_HTML, "https://www.instagram.com/p/DcS9N_5TZkQ/"),
        (INSTAGRAM_PROFILE_HTML, "https://www.instagram.com/lambe_ojol/"),
        (INSTAGRAM_REELS_GRID_HTML, "https://www.instagram.com/lambe_ojol/reels/"),
    ])
    @patch("src.connectors.base.validate_public_url", return_value="https://www.instagram.com/p/DcS9N_5TZkQ/")
    def test_instagram_reads_reel_views_from_matching_profile_grid_item(self, _validate, _fetch):
        url = "https://www.instagram.com/p/DcS9N_5TZkQ/"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.views.value, 412)

    @patch("src.connectors.base.fetch_public_html", return_value=(TIKTOK_STATS_HTML, "https://www.tiktok.com/@akun/video/123"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.tiktok.com/@akun/video/123")
    def test_tiktok_reads_author_followers_views_and_posting_date(self, _validate, _fetch):
        url = "https://www.tiktok.com/@akun/video/123"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.followers.value, 1250)
        self.assertEqual(result.views.value, 6400)
        self.assertTrue(str(result.posted_at.value).startswith("2026"))

    @patch("src.connectors.base.fetch_public_html", side_effect=[
        (THREADS_POST_HTML, "https://www.threads.com/@jkt.feed/post/DcBid9oEqtV"),
        (THREADS_PROFILE_HTML, "https://www.threads.com/@jkt.feed"),
    ])
    @patch("src.connectors.base.validate_public_url", return_value="https://www.threads.com/@jkt.feed/post/DcBid9oEqtV")
    def test_threads_reads_author_followers_views_and_posting_date(self, _validate, _fetch):
        url = "https://www.threads.com/@jkt.feed/post/DcBid9oEqtV"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.username.value, "jkt.feed")
        self.assertEqual(result.followers.value, 88725)
        self.assertEqual(result.views.value, 4494)
        self.assertEqual(result.comments.value, 0)
        self.assertEqual(result.posted_at.value, "2026-08-14")

    @patch("src.connectors.base.fetch_public_html", return_value=(THREADS_COMMENT_HTML, "https://www.threads.com/@purrplestarsss/post/DcgoGvoAQxG"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.threads.com/@purrplestarsss/post/DcgoGvoAQxG")
    def test_threads_reads_comments_from_matching_post(self, _validate, _fetch):
        url = "https://www.threads.com/@purrplestarsss/post/DcgoGvoAQxG"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.comments.value, 8)

    @patch("src.connectors.base.fetch_public_html", return_value=(THREADS_TWO_COMMENTS_HTML, "https://www.threads.com/@aimijs/post/DciTeqClGKc"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.threads.com/@aimijs/post/DciTeqClGKc")
    def test_threads_reads_two_comments_from_current_response_shape(self, _validate, _fetch):
        url = "https://www.threads.com/@aimijs/post/DciTeqClGKc"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.comments.value, 2)
        self.assertEqual(result.views.value, 225)

    @patch("src.connectors.base.fetch_public_html", return_value=(THREADS_TAKEN_AT_HTML, "https://www.threads.com/@mozaiktravel.id/post/DcxnOUwk51O"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.threads.com/@mozaiktravel.id/post/DcxnOUwk51O")
    def test_threads_reads_posting_date_from_matching_taken_at(self, _validate, _fetch):
        url = "https://www.threads.com/@mozaiktravel.id/post/DcxnOUwk51O"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.posted_at.value, "2026-09-02")

    @patch("src.connectors.base.fetch_public_html", return_value=("<meta property=\"og:description\" content=\"Caption Threads\">", "https://www.threads.com/@tanpaangka/post/1"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.threads.com/@tanpaangka/post/1")
    def test_threads_defaults_missing_followers_and_views_to_zero(self, _validate, _fetch):
        url = "https://www.threads.com/@tanpaangka/post/1"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.followers.value, 0)
        self.assertEqual(result.views.value, 0)

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
        self.assertEqual(result.followers.value, 0)
        self.assertEqual(result.views.value, 0)

    @patch("src.connectors.base.fetch_public_html", side_effect=[
        (FACEBOOK_PROFILE_POST_HTML, "https://www.facebook.com/profilcontoh/posts/123"),
        (FACEBOOK_FOLLOWER_PROFILE_HTML, "https://www.facebook.com/profilcontoh"),
    ])
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/profilcontoh/posts/123")
    def test_facebook_prefers_followers_over_friends(self, _validate, _fetch):
        url = "https://www.facebook.com/profilcontoh/posts/123"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.username.value, "Profil Contoh")
        self.assertEqual(result.followers.value, 1400)

    @patch("src.connectors.base.fetch_public_html", side_effect=[
        (FACEBOOK_PROFILE_POST_HTML.replace("profilcontoh", "profildenganteman"), "https://www.facebook.com/profildenganteman/posts/123"),
        (FACEBOOK_FRIEND_PROFILE_HTML, "https://www.facebook.com/profildenganteman"),
    ])
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/profildenganteman/posts/123")
    def test_facebook_uses_friends_when_followers_are_not_public(self, _validate, _fetch):
        url = "https://www.facebook.com/profildenganteman/posts/123"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.followers.value, 2200)

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

    @patch("src.connectors.base.fetch_public_html", return_value=(FACEBOOK_REEL_LIKERS_HTML, "https://www.facebook.com/reel/1407754307910903"))
    @patch("src.connectors.base.validate_public_url", return_value="https://web.facebook.com/share/v/1HMevHPUYY/")
    def test_facebook_share_video_reads_likers_count(self, _validate, _fetch):
        url = "https://web.facebook.com/share/v/1HMevHPUYY/"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.likes.value, 3)
        self.assertEqual(result.comments.value, 1)
        self.assertEqual(result.shares.value, 0)

    @patch("src.connectors.base.fetch_public_html", return_value=(FACEBOOK_REEL_ZERO_LIKERS_HTML, "https://www.facebook.com/reel/1064880916011501"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/share/r/1EG17CdekK/")
    def test_facebook_share_reel_keeps_public_zero_likes(self, _validate, _fetch):
        url = "https://www.facebook.com/share/r/1EG17CdekK/"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.likes.value, 0)
        self.assertEqual(result.likes.status, FieldStatus.AVAILABLE)

    @patch("src.connectors.base.fetch_public_html", return_value=(FACEBOOK_REEL_REDUCED_LIKES_HTML, "https://www.facebook.com/reel/2586740801787372"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/share/v/1CwhpsZEDD/")
    def test_facebook_share_video_reads_reduced_reaction_count(self, _validate, _fetch):
        url = "https://www.facebook.com/share/v/1CwhpsZEDD/"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.likes.value, 1200)

    def test_facebook_reads_post_identifier_from_permalink_query(self):
        url = "https://www.facebook.com/permalink.php?story_fbid=pfbidABC&id=123"
        self.assertEqual(get_connector(url)._post_identifiers(url), ["pfbidABC"])

    @patch("src.connectors.base.fetch_public_html", side_effect=[
        (FACEBOOK_REEL_ZERO_VIEW_HTML, "https://www.facebook.com/reel/3556314681183024"),
        (FACEBOOK_REEL_ZERO_VIEW_HTML, "https://www.facebook.com/hery.umbuwole"),
        (FACEBOOK_PROFILE_REELS_HTML, "https://www.facebook.com/hery.umbuwole/reels/"),
    ])
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/reel/3556314681183024")
    def test_facebook_reads_reel_views_from_matching_profile_grid_item(self, _validate, _fetch):
        url = "https://www.facebook.com/reel/3556314681183024"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.views.value, 132)

    @patch("src.connectors.base.fetch_public_html", return_value=(FACEBOOK_FULL_CAPTION_HTML, "https://www.facebook.com/akun/posts/123"))
    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/akun/posts/123")
    def test_facebook_post_reads_all_visible_caption_paragraphs(self, _validate, _fetch):
        result = get_connector("https://www.facebook.com/akun/posts/123").enrich("https://www.facebook.com/akun/posts/123")
        self.assertIn("Paragraf pertama yang lengkap.", result.caption.value)
        self.assertIn("Paragraf kedua juga harus masuk.", result.caption.value)
        self.assertNotIn("...", result.caption.value)

    @patch("src.connectors.base.fetch_public_html", side_effect=[
        (FACEBOOK_GROUP_HTML, "https://www.facebook.com/groups/1657323981260301/permalink/4699586193700716/"),
        (FACEBOOK_FRIEND_PROFILE_HTML, "https://www.facebook.com/100012853172729"),
    ])
    @patch("src.connectors.base.validate_public_url", return_value="https://web.facebook.com/groups/1657323981260301/permalink/4699586193700716/")
    def test_facebook_group_combines_post_author_and_group_name(self, _validate, _fetch):
        url = "https://web.facebook.com/groups/1657323981260301/permalink/4699586193700716/"
        result = get_connector(url).enrich(url)
        self.assertEqual(result.username.value, "Gondrong Saja - LIOC ( LIKA LIKU OJOL & CUSTOMER )")
        self.assertEqual(result.caption.value, "Caption grup lengkap. Paragraf kedua juga masuk.")
        self.assertEqual(result.followers.value, 2200)

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

    @patch("src.connectors.base.validate_public_url", return_value="https://www.facebook.com/reel/123")
    def test_facebook_reel_keeps_zero_metrics_and_target_owner(self, _validate):
        unrelated = '<script>{"video_id":"999","video_owner":{"name":"Nama Salah","id":"9999"},"feedback":{"likers":{"count":87},"total_comment_count":42,"play_count":9000}}</script>'
        target = '<script>{"video_owner":{"name":"Author Benar","id":"12345"},"feedback":{"likers":{"count":0},"total_comment_count":0,"play_count":0},"tracking":"{\\"top_level_post_id\\":\\"123\\",\\"video_id\\":\\"123\\"}"}</script>'
        html = '<meta property="og:title" content="Nama yang disebut di caption | Facebook">' + unrelated + (" " * 12_000) + target
        with patch("src.connectors.base.fetch_public_html", return_value=(html, "https://www.facebook.com/reel/123")):
            result = get_connector("https://www.facebook.com/reel/123").enrich("https://www.facebook.com/reel/123")
        self.assertEqual(result.username.value, "Author Benar")
        self.assertEqual(result.likes.value, 0)
        self.assertEqual(result.comments.value, 0)
        self.assertEqual(result.views.value, 0)

    def test_selected_platform_rejects_a_different_platform(self):
        with self.assertRaisesRegex(ValueError, "terdeteksi sebagai X"):
            get_platform_connector("https://x.com/a/status/1", "YouTube")
