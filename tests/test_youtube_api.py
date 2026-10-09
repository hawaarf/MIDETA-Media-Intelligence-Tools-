# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src.models import FieldStatus
from src.youtube_api import (
    YOUTUBE_CHANNELS_ENDPOINT,
    YOUTUBE_VIDEOS_ENDPOINT,
    YouTubeDataAPIClient,
    YouTubeDataAPIError,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.closed = False

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


class YouTubeDataAPIClientTests(unittest.TestCase):
    def test_collects_watch_and_shorts_in_one_video_and_channel_batch(self):
        calls = []

        def request_get(endpoint, **kwargs):
            calls.append((endpoint, kwargs))
            if endpoint == YOUTUBE_VIDEOS_ENDPOINT:
                self.assertEqual(kwargs["params"]["id"], "abcdefghijk,lmnopqrstuv")
                return FakeResponse(
                    {
                        "items": [
                            {
                                "id": "abcdefghijk",
                                "snippet": {
                                    "channelId": "channel-1",
                                    "channelTitle": "Channel Cepat",
                                    "description": "Baris satu.\nBaris dua.",
                                    "publishedAt": "2026-10-01T02:00:00Z",
                                },
                                "statistics": {
                                    "viewCount": "1200",
                                    "likeCount": "45",
                                    "commentCount": "0",
                                },
                            },
                            {
                                "id": "lmnopqrstuv",
                                "snippet": {
                                    "channelId": "channel-1",
                                    "channelTitle": "Channel Cepat",
                                    "description": "Shorts caption",
                                    "publishedAt": "2026-10-02T02:00:00Z",
                                },
                                "statistics": {"viewCount": "500"},
                            },
                        ]
                    }
                )
            self.assertEqual(endpoint, YOUTUBE_CHANNELS_ENDPOINT)
            self.assertEqual(kwargs["params"]["id"], "channel-1")
            return FakeResponse(
                {
                    "items": [
                        {
                            "id": "channel-1",
                            "statistics": {"subscriberCount": "6789"},
                        }
                    ]
                }
            )

        with TemporaryDirectory() as directory:
            key_path = Path(directory) / "youtube_api_key"
            client = YouTubeDataAPIClient(key_path, request_get=request_get)
            client.save_key("A" * 30)
            urls = [
                "https://www.youtube.com/watch?v=abcdefghijk",
                "https://youtube.com/shorts/lmnopqrstuv?si=test",
            ]
            results = client.collect_many(urls)

        self.assertEqual(len(calls), 2)
        self.assertEqual(results[urls[0]].username.value, "Channel Cepat")
        self.assertEqual(results[urls[0]].caption.value, "Baris satu. Baris dua.")
        self.assertEqual(results[urls[0]].followers.value, 6789)
        self.assertEqual(results[urls[0]].views.value, 1200)
        self.assertEqual(results[urls[0]].likes.value, 45)
        self.assertEqual(results[urls[0]].comments.value, 0)
        self.assertEqual(results[urls[1]].views.value, 500)
        self.assertEqual(results[urls[1]].likes.status, FieldStatus.NOT_PUBLIC)

    def test_channel_subscribers_are_cached_between_batches(self):
        channel_calls = 0

        def request_get(endpoint, **_kwargs):
            nonlocal channel_calls
            if endpoint == YOUTUBE_CHANNELS_ENDPOINT:
                channel_calls += 1
                return FakeResponse(
                    {"items": [{"id": "same-channel", "statistics": {"subscriberCount": "25"}}]}
                )
            return FakeResponse(
                {
                    "items": [
                        {
                            "id": "abcdefghijk",
                            "snippet": {"channelId": "same-channel", "channelTitle": "A"},
                            "statistics": {"viewCount": "1"},
                        }
                    ]
                }
            )

        with TemporaryDirectory() as directory:
            client = YouTubeDataAPIClient(Path(directory) / "key", request_get=request_get)
            client.save_key("B" * 30)
            url = "https://youtu.be/abcdefghijk"
            client.collect_many([url])
            client.collect_many([url])

        self.assertEqual(channel_calls, 1)

    def test_api_error_never_exposes_key(self):
        key = "SECRET-KEY-THAT-MUST-NOT-LEAK"

        def request_get(_endpoint, **_kwargs):
            return FakeResponse({"error": {"message": f"API key {key} is invalid"}}, 403)

        with TemporaryDirectory() as directory:
            client = YouTubeDataAPIClient(Path(directory) / "key", request_get=request_get)
            client.save_key(key)
            with self.assertRaises(YouTubeDataAPIError) as raised:
                client.collect_many(["https://youtu.be/abcdefghijk"])

        self.assertNotIn(key, str(raised.exception))
        self.assertIn("[API key]", str(raised.exception))

    def test_environment_key_takes_priority_without_writing_it(self):
        with TemporaryDirectory() as directory:
            key_path = Path(directory) / "key"
            key_path.write_text("L" * 30, encoding="utf-8")
            client = YouTubeDataAPIClient(key_path)
            with patch.dict(os.environ, {"YOUTUBE_API_KEY": "E" * 30}):
                self.assertEqual(client.key_source(), "environment")
                self.assertEqual(client.api_key(), "E" * 30)


if __name__ == "__main__":
    unittest.main()
