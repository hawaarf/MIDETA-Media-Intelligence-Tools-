# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
from unittest.mock import patch

from src.social_urls import (
    SocialURLResolutionError,
    is_short_social_url,
    resolve_social_url,
)


class FakeResponse:
    def __init__(self, status_code=200, location=None, html="", url="https://example.test/"):
        self.status_code = status_code
        self.headers = {"location": location} if location else {}
        self.is_redirect = status_code in {301, 302, 303, 307, 308}
        self.is_permanent_redirect = status_code in {301, 308}
        self.encoding = "utf-8"
        self.url = url
        self._body = html.encode("utf-8")
        self.closed = False

    def iter_content(self, _size):
        yield self._body

    def close(self):
        self.closed = True


class SocialURLTests(unittest.TestCase):
    def setUp(self):
        resolve_social_url.cache_clear()

    @patch("src.social_urls.validate_public_url", side_effect=lambda value: value)
    @patch("src.social_urls.requests.get")
    def test_resolves_native_tiktok_short_url(self, request_get, _validate):
        request_get.return_value = FakeResponse(
            status_code=302,
            location="https://www.tiktok.com/@akun/video/1234567890",
            url="https://vt.tiktok.com/ABC/",
        )
        resolved = resolve_social_url("https://vt.tiktok.com/ABC/", "TikTok")
        self.assertEqual(resolved, "https://www.tiktok.com/@akun/video/1234567890")

    @patch("src.social_urls.validate_public_url", side_effect=lambda value: value)
    @patch("src.social_urls.requests.get")
    def test_resolves_share_page_from_canonical_html(self, request_get, _validate):
        request_get.return_value = FakeResponse(
            html='<link rel="canonical" href="https://www.instagram.com/reel/POST123/">',
            url="https://www.instagram.com/share/reel/ABC/",
        )
        resolved = resolve_social_url("https://www.instagram.com/share/reel/ABC/", "Instagram")
        self.assertEqual(resolved, "https://www.instagram.com/reel/POST123/")

    @patch("src.social_urls.validate_public_url", side_effect=lambda value: value)
    @patch("src.social_urls.requests.get")
    def test_direct_post_url_does_not_make_an_extra_request(self, request_get, _validate):
        url = "https://www.threads.com/@akun/post/POST123"
        self.assertEqual(resolve_social_url(url, "Threads"), url)
        request_get.assert_not_called()

    @patch("src.social_urls.validate_public_url", side_effect=lambda value: value)
    @patch("src.social_urls.requests.get")
    def test_rejects_short_url_that_leaves_the_expected_platform(self, request_get, _validate):
        request_get.return_value = FakeResponse(
            status_code=302,
            location="https://example.com/not-a-post",
            url="https://t.co/ABC",
        )
        with self.assertRaises(SocialURLResolutionError):
            resolve_social_url("https://t.co/ABC", "X")

    def test_recognizes_every_native_share_shape_that_needs_resolution(self):
        urls = (
            "https://www.facebook.com/share/r/ABC/",
            "https://www.instagram.com/share/reel/ABC/",
            "https://www.threads.com/share/ABC/",
            "https://www.tiktok.com/t/ABC/",
            "https://youtu.be/ABC",
            "https://t.co/ABC",
        )
        self.assertTrue(all(is_short_social_url(url) for url in urls))


if __name__ == "__main__":
    unittest.main()
