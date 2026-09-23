# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from src.tiktok_browser import TikTokBrowserMetrics
from src.tiktok_free import TikTokFreeCollector, TikTokFreeError


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
            return_value=TikTokBrowserMetrics(
                caption="Caption",
                posted_at="2026-09-16T10:00:00+00:00",
                views=321,
                followers=654,
                likes=12,
                comments=3,
                shares=2,
                bookmarks=1,
                source="free",
            )
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

    def test_without_token_uses_public_post_fallback(self):
        with TemporaryDirectory() as folder:
            collector = TikTokFreeCollector(token_path=Path(folder) / "missing")
            collector._oembed_metrics = Mock(
                return_value=TikTokBrowserMetrics(
                    username="ojol.spill",
                    caption="program apresiasi mitra gojek #gojek",
                    source="free",
                )
            )
            collector._public_fallback_metrics = Mock(
                return_value=TikTokBrowserMetrics(
                    username="ojol.spill",
                    views=629,
                    likes=17,
                    comments=1,
                    shares=1,
                    bookmarks=0,
                    source="free",
                )
            )
            collector._public_profile_followers = Mock(return_value=48_200)

            metrics = collector.collect(URL)

        self.assertEqual(metrics.username, "ojol.spill")
        self.assertEqual(metrics.caption, "program apresiasi mitra gojek #gojek")
        self.assertEqual(metrics.views, 629)
        self.assertEqual(metrics.followers, 48_200)

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

    def test_public_fallback_item_is_matched_and_parsed(self):
        metrics = TikTokFreeCollector._metrics_from_public_item(
            {
                "id": "7674512043470359826",
                "title": "Hampura rada aya ambekan",
                "create_time": 1786861587,
                "play_count": 304_945,
                "digg_count": 20_021,
                "comment_count": 599,
                "share_count": 474,
                "collect_count": 463,
                "author": {"unique_id": "balataknabandung32"},
            },
            "7674512043470359826",
        )

        self.assertEqual(metrics.username, "balataknabandung32")
        self.assertEqual(metrics.caption, "Hampura rada aya ambekan")
        self.assertEqual(metrics.views, 304_945)
        self.assertEqual(metrics.likes, 20_021)
        self.assertEqual(metrics.comments, 599)
        self.assertEqual(metrics.shares, 474)
        self.assertEqual(metrics.bookmarks, 463)
        self.assertIsNotNone(metrics.posted_at)

    def test_public_fallback_item_for_another_post_is_ignored(self):
        metrics = TikTokFreeCollector._metrics_from_public_item(
            {
                "id": "9999999999999999999",
                "play_count": 8_000_000,
                "author": {"unique_id": "akun.lain"},
            },
            "7674512043470359826",
        )

        self.assertFalse(TikTokFreeCollector._has_data(metrics))

    @patch("src.tiktok_free.time.sleep")
    @patch("src.tiktok_free.requests.get")
    def test_public_fallback_retries_the_free_rate_limit(self, get, sleep):
        limited = Mock()
        limited.raise_for_status.return_value = None
        limited.json.return_value = {"code": -1, "msg": "Free Api Limit: 1 request/second."}
        success = Mock()
        success.raise_for_status.return_value = None
        success.json.return_value = {
            "code": 0,
            "data": {
                "id": "7684605378314669319",
                "play_count": 629,
                "author": {"unique_id": "ojol.spill"},
            },
        }
        get.side_effect = [limited, success]
        TikTokFreeCollector._last_fallback_request = 0.0

        metrics = TikTokFreeCollector()._public_fallback_metrics(URL)

        self.assertEqual(metrics.views, 629)
        self.assertEqual(get.call_count, 2)
        self.assertGreaterEqual(sleep.call_count, 1)

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
            collector._public_fallback_metrics = Mock(
                return_value=TikTokBrowserMetrics(source="free")
            )

            metrics = collector.collect(URL)

        self.assertEqual(metrics.caption, "Caption resmi")
        self.assertEqual(metrics.followers, 48_200)
        self.assertEqual(metrics.views, 629)
        self.assertEqual(metrics.source, "free")

    def test_apify_failure_uses_public_fallback_instead_of_empty_row(self):
        collector = TikTokFreeCollector()
        collector._resolve_post_url = Mock(return_value=URL)
        collector._oembed_metrics = Mock(return_value=TikTokBrowserMetrics(source="free"))
        collector.token = Mock(return_value="apify_api_example_token")
        collector._apify_metrics = Mock(
            side_effect=TikTokFreeError("Posting ditandai sensitif oleh provider utama.")
        )
        collector._public_fallback_metrics = Mock(
            return_value=TikTokBrowserMetrics(
                username="ojol.spill",
                caption="Caption lengkap",
                posted_at="2026-09-13T03:45:41+00:00",
                views=629,
                likes=17,
                comments=1,
                shares=1,
                bookmarks=0,
                source="free",
            )
        )
        collector._public_profile_followers = Mock(return_value=None)

        metrics = collector.collect(URL)

        self.assertEqual(metrics.caption, "Caption lengkap")
        self.assertEqual(metrics.views, 629)
        collector._public_fallback_metrics.assert_called_once_with(URL)


if __name__ == "__main__":
    unittest.main()
