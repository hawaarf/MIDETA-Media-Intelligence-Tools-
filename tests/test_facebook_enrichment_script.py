# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from facebook_enrichment import (
    collect_facebook_url,
    read_input_urls,
    write_results,
)
from src.models import DataField, FieldStatus, SocialResult


def readable_result(url: str) -> SocialResult:
    available = lambda value: DataField(value=value, status=FieldStatus.AVAILABLE)
    unavailable = DataField(value=None, status=FieldStatus.NOT_PUBLIC)
    return SocialResult(
        url=url,
        platform="Facebook",
        username=available("Akun"),
        caption=available("Caption"),
        posted_at=available("2026-10-02"),
        followers=available(100),
        likes=available(20),
        comments=available(3),
        shares=available(1),
        views=available(500),
        bookmarks=unavailable,
        reposts=unavailable,
    )


class FacebookEnrichmentScriptTests(unittest.TestCase):
    def test_reads_many_rows_and_preserves_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "urls.txt"
            input_path.write_text(
                "https://www.facebook.com/reel/123\n"
                "https://www.facebook.com/reel/123\n",
                encoding="utf-8",
            )
            self.assertEqual(
                read_input_urls(input_path, []),
                [
                    "https://www.facebook.com/reel/123",
                    "https://www.facebook.com/reel/123",
                ],
            )

    def test_non_facebook_url_becomes_an_error_row(self):
        result = collect_facebook_url("https://www.instagram.com/p/example/")
        self.assertEqual(result.url, "https://www.instagram.com/p/example/")
        self.assertTrue(all(field.status == FieldStatus.FAILED for field in (
            result.username,
            result.caption,
            result.likes,
            result.comments,
        )))

    @patch("facebook_enrichment.resolve_social_url")
    @patch("facebook_enrichment.get_platform_connector")
    def test_fast_mode_keeps_original_url_after_internal_resolution(self, connector_factory, resolve):
        original = "https://www.facebook.com/share/p/short/"
        resolved = "https://www.facebook.com/akun/posts/123"
        resolve.return_value = resolved
        connector = Mock()
        connector.enrich.return_value = readable_result(resolved)
        connector_factory.return_value = connector

        result = collect_facebook_url(original, mode="fast")

        self.assertEqual(result.url, original)
        connector.enrich.assert_called_once_with(resolved)

    def test_writes_manager_ready_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "facebook.csv"
            write_results(
                [readable_result("https://www.facebook.com/reel/123")],
                output,
            )
            frame = pd.read_csv(output)
            self.assertEqual(frame.loc[0, "Platform"], "Facebook")
            self.assertEqual(frame.loc[0, "Author"], "Akun")
            self.assertEqual(frame.loc[0, "Likes"], 20)
            self.assertEqual(frame.loc[0, "Error"], "Tidak ada")


if __name__ == "__main__":
    unittest.main()
