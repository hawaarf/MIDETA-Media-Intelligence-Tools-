import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from src.tiktok_browser import TikTokBrowserMetrics
from src.tiktok_free import TikTokFreeCollector


URL = "https://www.tiktok.com/@ojol.spill/video/7684605378314669319"
SHORT_URL = "https://vt.tiktok.com/ZSqxVfQaV/"
RESOLVED_URL = "https://www.tiktok.com/@raudatuljannh__/video/7685279895592684821?_r=1"
RESOLVED_PHOTO_URL = "https://www.tiktok.com/@inifhira/photo/7685282450510974228?_r=1"


class TikTokFreeTests(unittest.TestCase):
    @patch("src.tiktok_free.requests.get")
    def test_short_url_is_resolved_to_the_original_video(self, get):
        response = Mock()
        response.is_redirect = True
        response.is_permanent_redirect = False
        response.headers = {"location": RESOLVED_URL}
        get.return_value = response

        resolved = TikTokFreeCollector()._resolve_post_url(SHORT_URL)

        self.assertEqual(resolved, RESOLVED_URL)
        response.close.assert_called_once()
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    @patch("src.tiktok_free.requests.get")
    def test_short_url_can_resolve_to_a_photo_carousel(self, get):
        response = Mock()
        response.is_redirect = True
        response.is_permanent_redirect = False
        response.headers = {"location": RESOLVED_PHOTO_URL}
        get.return_value = response

        resolved = TikTokFreeCollector()._resolve_post_url(SHORT_URL)

        self.assertEqual(resolved, RESOLVED_PHOTO_URL)
        self.assertEqual(
            TikTokFreeCollector._metrics_from_apify_item(
                {"id": "7685282450510974228", "playCount": 42},
                "7685282450510974228",
            ).views,
            42,
        )

    def test_collect_sends_the_resolved_short_url_to_apify(self):
        collector = TikTokFreeCollector()
        collector._resolve_post_url = Mock(return_value=RESOLVED_URL)
        collector._oembed_metrics = Mock(return_value=TikTokBrowserMetrics(source="free"))
        collector.token = Mock(return_value="apify_api_example_token")
        collector._apify_metrics = Mock(
            return_value=TikTokBrowserMetrics(views=321, followers=654, source="free")
        )

        metrics = collector.collect(SHORT_URL)

        collector._oembed_metrics.assert_called_once_with(RESOLVED_URL)
        collector._apify_metrics.assert_called_once_with(
            RESOLVED_URL,
            "apify_api_example_token",
        )
        self.assertEqual(metrics.views, 321)
        self.assertEqual(metrics.followers, 654)

    def test_token_is_saved_privately_and_can_be_deleted(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "private" / "apify_token"
            collector = TikTokFreeCollector(token_path=path)

            collector.save_token("apify_api_example_token")

            self.assertEqual(collector.token(), "apify_api_example_token")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            collector.delete_token()
            self.assertFalse(path.exists())

    @patch("src.tiktok_free.requests.get")
    def test_without_token_returns_official_caption_and_author(self, get):
        response = Mock()
        response.json.return_value = {
            "title": "program apresiasi mitra gojek #gojek",
            "author_name": "Ojol Spill",
            "author_unique_id": "ojol.spill",
        }
        response.raise_for_status.return_value = None
        get.return_value = response
        with TemporaryDirectory() as folder:
            metrics = TikTokFreeCollector(token_path=Path(folder) / "missing").collect(URL)

        self.assertEqual(metrics.username, "ojol.spill")
        self.assertEqual(metrics.caption, "program apresiasi mitra gojek #gojek")
        self.assertIsNone(metrics.views)
        self.assertIn("Token Apify belum disimpan", metrics.warning)

    def test_apify_item_is_matched_to_the_target_video(self):
        item = {
            "id": "7684605378314669319",
            "text": "Caption lengkap",
            "createTimeISO": "2026-09-13T03:45:41.000Z",
            "authorMeta": {"name": "ojol.spill", "fans": 48_200},
            "playCount": 629,
            "diggCount": 17,
            "commentCount": 1,
            "shareCount": 1,
            "collectCount": 0,
        }

        metrics = TikTokFreeCollector._metrics_from_apify_item(
            item,
            "7684605378314669319",
        )

        self.assertEqual(metrics.username, "ojol.spill")
        self.assertEqual(metrics.followers, 48_200)
        self.assertEqual(metrics.views, 629)
        self.assertEqual(metrics.likes, 17)
        self.assertEqual(metrics.comments, 1)
        self.assertEqual(metrics.shares, 1)
        self.assertEqual(metrics.bookmarks, 0)

    def test_apify_item_for_another_video_is_ignored(self):
        metrics = TikTokFreeCollector._metrics_from_apify_item(
            {
                "id": "9999999999999999999",
                "authorMeta": {"name": "akun.lain", "fans": 9_789},
                "playCount": 9_000_000,
            },
            "7684605378314669319",
        )

        self.assertIsNone(metrics.username)
        self.assertIsNone(metrics.followers)
        self.assertIsNone(metrics.views)

    @patch("src.tiktok_free.requests.post")
    def test_apify_token_is_sent_in_header_and_result_is_parsed(self, post):
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {
                "id": "7684605378314669319",
                "authorMeta.name": "ojol.spill",
                "authorMeta.fans": 48_200,
                "playCount": 629,
            }
        ]
        post.return_value = response

        metrics = TikTokFreeCollector()._apify_metrics(URL, "apify_api_secret")

        self.assertEqual(metrics.followers, 48_200)
        self.assertEqual(metrics.views, 629)
        call = post.call_args
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer apify_api_secret")
        self.assertNotIn("token", call.kwargs["params"])

    def test_provider_metrics_are_merged_with_public_caption(self):
        with TemporaryDirectory() as folder:
            token_path = Path(folder) / "token"
            token_path.write_text("apify_api_example_token", encoding="utf-8")
            collector = TikTokFreeCollector(token_path=token_path)
            collector._oembed_metrics = Mock(
                return_value=TikTokBrowserMetrics(
                    username="ojol.spill",
                    caption="Caption resmi",
                    source="free",
                )
            )
            collector._apify_metrics = Mock(
                return_value=TikTokBrowserMetrics(
                    followers=48_200,
                    views=629,
                    likes=17,
                    source="free",
                )
            )

            metrics = collector.collect(URL)

        self.assertEqual(metrics.caption, "Caption resmi")
        self.assertEqual(metrics.followers, 48_200)
        self.assertEqual(metrics.views, 629)
        self.assertEqual(metrics.source, "free")


if __name__ == "__main__":
    unittest.main()
