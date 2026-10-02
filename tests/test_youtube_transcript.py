# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import json
import unittest

from src.youtube_transcript import (
    YouTubeTranscriptCollector,
    YouTubeTranscriptError,
    format_timestamp,
    format_transcript,
    format_transcript_report,
    parse_json3,
    parse_vtt,
)


class YouTubeTranscriptParserTests(unittest.TestCase):
    def test_vtt_reads_voice_tags_prefix_names_and_carries_speaker(self):
        payload = """WEBVTT

00:00:00.000 --> 00:00:02.000
<v Laila>Jujur gue sudah tidak bisa mikir.</v>

00:00:02.000 --> 00:00:04.000
Kalimat Laila berikutnya.

00:00:04.000 --> 00:00:06.000
Fani: Iya, aku paham.
"""
        segments = parse_vtt(payload)

        self.assertEqual([item.speaker for item in segments], ["Laila", "Laila", "Fani"])
        self.assertTrue(segments[0].speaker_from_caption)
        self.assertFalse(segments[1].speaker_from_caption)
        self.assertTrue(segments[2].speaker_from_caption)
        self.assertEqual(segments[2].text, "Iya, aku paham.")

    def test_vtt_uses_generic_speakers_and_understands_change_marker(self):
        payload = """WEBVTT

00:00:00.000 --> 00:00:02.000
Halo semuanya.

00:00:03.000 --> 00:00:05.000
>> Selamat datang.
"""
        segments = parse_vtt(payload)

        self.assertEqual([item.speaker for item in segments], ["Pembicara 1", "Pembicara 2"])
        self.assertFalse(any(item.speaker_from_caption for item in segments))

    def test_vtt_removes_rolling_caption_duplicates(self):
        payload = """WEBVTT

00:00:00.000 --> 00:00:02.000
Halo

00:00:01.000 --> 00:00:03.000
Halo teman-teman

00:00:02.000 --> 00:00:04.000
Halo teman-teman
"""
        segments = parse_vtt(payload)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].start_seconds, 0)
        self.assertEqual(segments[0].text, "Halo teman-teman")

    def test_json3_reads_events_and_speaker_metadata(self):
        payload = json.dumps(
            {
                "events": [
                    {
                        "tStartMs": 3723000,
                        "speakerName": "Laila",
                        "segs": [{"utf8": "Kalimat pertama."}],
                    }
                ]
            }
        )
        segments = parse_json3(payload)

        self.assertEqual(format_timestamp(segments[0].start_seconds), "01:02:03")
        self.assertEqual(segments[0].speaker, "Laila")
        self.assertEqual(segments[0].text, "Kalimat pertama.")


class YouTubeTranscriptCollectorTests(unittest.TestCase):
    @staticmethod
    def info() -> dict:
        return {
            "title": "Percakapan Laila dan Fani",
            "channel": "MIDETA Channel",
            "http_headers": {"Referer": "https://www.youtube.com/"},
            "subtitles": {
                "en": [
                    {"ext": "vtt", "url": "https://caption.test/en", "name": "English"}
                ]
            },
            "automatic_captions": {
                "id": [
                    {
                        "ext": "vtt",
                        "url": "https://caption.test/id",
                        "name": "Indonesia",
                    }
                ]
            },
        }

    def test_collector_returns_channel_spokespersons_and_requested_language(self):
        fetched: list[tuple[str, dict]] = []

        def fetcher(url, headers):
            fetched.append((url, dict(headers)))
            return """WEBVTT

00:00:00.000 --> 00:00:02.000
Laila: Jujur gue sudah tidak bisa mikir apa-apa lagi.
"""

        collector = YouTubeTranscriptCollector(
            info_provider=lambda _url: self.info(),
            subtitle_fetcher=fetcher,
        )
        result = collector.collect("https://youtu.be/abcdefghijk", language="id")

        self.assertEqual(result.channel, "MIDETA Channel")
        self.assertEqual(result.title, "Percakapan Laila dan Fani")
        self.assertEqual(result.language_code, "id")
        self.assertEqual(result.caption_source, "automatic")
        self.assertEqual(result.spokespersons, ("Laila",))
        self.assertTrue(result.has_named_speakers)
        self.assertEqual(fetched[0][0], "https://caption.test/id")
        self.assertEqual(fetched[0][1]["Referer"], "https://www.youtube.com/")

    def test_auto_prefers_manual_caption_before_automatic_caption(self):
        collector = YouTubeTranscriptCollector(
            info_provider=lambda _url: self.info(),
            subtitle_fetcher=lambda url, _headers: """WEBVTT

00:00:00.000 --> 00:00:02.000
Speaker: Hello.
""",
        )
        result = collector.collect("https://www.youtube.com/watch?v=abcdefghijk")

        self.assertEqual(result.language_code, "en")
        self.assertEqual(result.caption_source, "manual")

    def test_report_uses_editable_speaker_name_and_exact_timestamp_format(self):
        collector = YouTubeTranscriptCollector(
            info_provider=lambda _url: self.info(),
            subtitle_fetcher=lambda _url, _headers: """WEBVTT

00:00:00.000 --> 00:00:02.000
Jujur gue sudah tidak bisa mikir apa-apa lagi sih.
""",
        )
        result = collector.collect("https://www.youtube.com/watch?v=abcdefghijk", language="id")

        transcript = format_transcript(result, {"Pembicara 1": "Laila"})
        report = format_transcript_report(result, {"Pembicara 1": "Laila"})
        self.assertEqual(
            transcript,
            "(00:00:00) Laila : Jujur gue sudah tidak bisa mikir apa-apa lagi sih.",
        )
        self.assertIn("Nama Channel: MIDETA Channel", report)
        self.assertIn("Spokesperson: Laila", report)

    def test_rejects_non_video_url_before_provider_is_called(self):
        called = False

        def provider(_url):
            nonlocal called
            called = True
            return self.info()

        collector = YouTubeTranscriptCollector(info_provider=provider)
        with self.assertRaisesRegex(YouTubeTranscriptError, "satu video"):
            collector.collect("https://www.youtube.com/@mideta")
        self.assertFalse(called)

    def test_missing_captions_has_clear_error(self):
        collector = YouTubeTranscriptCollector(
            info_provider=lambda _url: {"title": "Tanpa subtitle", "channel": "Channel"}
        )
        with self.assertRaisesRegex(YouTubeTranscriptError, "tidak menyediakan subtitle"):
            collector.collect("https://www.youtube.com/watch?v=abcdefghijk")


if __name__ == "__main__":
    unittest.main()
