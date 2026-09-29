# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest

from src.follower_browser import ProfileFollowersCollector


class FollowerBrowserTests(unittest.TestCase):
    def test_runtime_exposes_current_profile_url_helpers(self):
        self.assertGreaterEqual(ProfileFollowersCollector.RUNTIME_VERSION, 2)
        self.assertTrue(hasattr(ProfileFollowersCollector, "platform_from_url"))
        self.assertTrue(hasattr(ProfileFollowersCollector, "account_name_from_url"))

    def test_profile_url_validation_rejects_posts(self):
        self.assertTrue(
            ProfileFollowersCollector.is_profile_url(
                "Instagram", "https://www.instagram.com/cnbcindonesia/"
            )
        )
        self.assertFalse(
            ProfileFollowersCollector.is_profile_url(
                "Instagram", "https://www.instagram.com/p/ABC123/"
            )
        )
        self.assertTrue(
            ProfileFollowersCollector.is_profile_url(
                "LinkedIn", "https://www.linkedin.com/company/cnbc-indonesia/"
            )
        )
        self.assertFalse(
            ProfileFollowersCollector.is_profile_url(
                "X", "https://x.com/cnbcindonesia/status/123"
            )
        )

    def test_visible_profile_header_is_preferred(self):
        source = '{"followers_count":999999}'
        self.assertEqual(
            ProfileFollowersCollector.extract_follower_count(
                "Instagram",
                source,
                ["CNBC Indonesia\n1,2 jt pengikut\n120 mengikuti"],
            ),
            1_200_000,
        )

    def test_structured_count_is_used_as_fallback(self):
        self.assertEqual(
            ProfileFollowersCollector.extract_follower_count(
                "TikTok", '{"followerCount":495200}', []
            ),
            495_200,
        )

    def test_youtube_subscriber_label_is_supported(self):
        self.assertEqual(
            ProfileFollowersCollector.extract_follower_count(
                "YouTube", "", ["@CNBCIndonesia • 2.9M subscribers • 10K videos"]
            ),
            2_900_000,
        )

    def test_detects_platform_and_account_name_from_profile_url(self):
        url = "https://www.linkedin.com/company/cnbc-indonesia/"
        platform = ProfileFollowersCollector.platform_from_url(url)
        self.assertEqual(platform, "LinkedIn")
        self.assertEqual(
            ProfileFollowersCollector.account_name_from_url(platform, url),
            "cnbc-indonesia",
        )

    def test_account_name_uses_social_handle(self):
        url = "https://www.tiktok.com/@cnbcindonesia"
        platform = ProfileFollowersCollector.platform_from_url(url)
        self.assertEqual(platform, "TikTok")
        self.assertEqual(
            ProfileFollowersCollector.account_name_from_url(platform, url),
            "cnbcindonesia",
        )


if __name__ == "__main__":
    unittest.main()
