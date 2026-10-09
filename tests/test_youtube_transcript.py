# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import json
import unittest

from src.youtube_transcript import (
    YouTubeTranscriptCollector,
    YouTubeTranscriptError,
    format_timestamp,
    format_transcript,
    format_transcript_metadata,
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

    def test_youtube_word_timing_tags_do_not_become_speaker_names(self):
        payload = """WEBVTT

00:00:00.240 --> 00:00:01.670 align:start position:0%
Asalamualaikum<00:00:00.760><c> B.</c><00:00:01.000><c> Selamat</c><00:00:01.199><c> datang</c><00:00:01.439><c> kembali</c>

00:00:01.670 --> 00:00:01.680 align:start position:0%
Asalamualaikum B. Selamat datang kembali

00:00:01.680 --> 00:00:03.790 align:start position:0%
Asalamualaikum B. Selamat datang kembali
di<00:00:01.880><c> Guru</c><00:00:02.080><c> Gembul</c><00:00:02.399><c> Channel.</c><00:00:03.000><c> Eh,</c><00:00:03.280><c> akhir-akhir</c>

00:00:03.790 --> 00:00:03.800 align:start position:0%
di Guru Gembul Channel. Eh, akhir-akhir

00:00:03.800 --> 00:00:05.749 align:start position:0%
di Guru Gembul Channel. Eh, akhir-akhir
ini<00:00:04.160><c> media-media</c><00:00:04.720><c> sosial</c><00:00:05.080><c> dan</c><00:00:05.240><c> media</c><00:00:05.520><c> massa</c>
"""

        segments = parse_vtt(payload)

        self.assertEqual({segment.speaker for segment in segments}, {"Pembicara 1"})
        self.assertFalse(any(segment.speaker_from_caption for segment in segments))
        self.assertFalse(any("<00" in segment.text for segment in segments))
        self.assertEqual(
            segments[0].text,
            "Asalamualaikum B. Selamat datang kembali di Guru Gembul Channel. "
            "Eh, akhir-akhir ini media-media sosial dan media massa",
        )

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

    def test_collector_reports_clear_ordered_progress_stages(self):
        updates: list[tuple[float, str]] = []
        collector = YouTubeTranscriptCollector(
            info_provider=lambda _url: self.info(),
            subtitle_fetcher=lambda _url, _headers: """WEBVTT

00:00:00.000 --> 00:00:02.000
Kalimat pembuka.
""",
        )

        collector.collect(
            "https://www.youtube.com/watch?v=abcdefghijk",
            language="id",
            progress_callback=lambda fraction, detail: updates.append((fraction, detail)),
        )

        self.assertEqual(updates[-1][0], 1.0)
        self.assertEqual([fraction for fraction, _ in updates], sorted(fraction for fraction, _ in updates))
        self.assertTrue(any("metadata" in detail for _, detail in updates))
        self.assertTrue(any("subtitle" in detail for _, detail in updates))

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
        metadata = format_transcript_metadata(result, {"Pembicara 1": "Laila"})
        self.assertEqual(
            transcript,
            "(00:00:00) Laila : Jujur gue sudah tidak bisa mikir apa-apa lagi sih.",
        )
        self.assertIn("Nama Channel: MIDETA Channel", report)
        self.assertIn("Spokesperson: Laila", report)
        self.assertIn("Nama Channel: MIDETA Channel", metadata)
        self.assertIn("Spokesperson: Laila", metadata)
        self.assertNotIn("Transcript:", metadata.splitlines())

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
