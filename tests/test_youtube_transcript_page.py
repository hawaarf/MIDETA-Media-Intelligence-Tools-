# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class YouTubeTranscriptPageTests(unittest.TestCase):
    @staticmethod
    def _app():
        page = Path(__file__).resolve().parents[1] / "pages" / "9_YouTube_Transcript.py"
        app = AppTest.from_file(page)
        app.run(timeout=10)
        return app

    def test_page_loads_without_network_and_explains_speaker_fallback(self):
        app = self._app()

        self.assertFalse(app.exception)
        self.assertTrue(any("YouTube Transcript" in item.value for item in app.markdown))
        self.assertEqual(len(app.text_input), 1)
        self.assertEqual(app.text_input[0].label, "URL YouTube")
        self.assertEqual(len(app.selectbox), 1)
        self.assertEqual(app.selectbox[0].value, "Otomatis (utamakan Indonesia)")
        self.assertIn("Proses Transcript", [button.label for button in app.button])
        info_text = " ".join(item.value for item in app.info)
        self.assertIn("dapat Anda rename", info_text)

    def test_empty_url_is_rejected_without_crashing(self):
        app = self._app()
        next(button for button in app.button if button.label == "Proses Transcript").click()
        app.run(timeout=10)

        self.assertFalse(app.exception)
        self.assertTrue(any("URL video YouTube" in item.value for item in app.error))


if __name__ == "__main__":
    unittest.main()
