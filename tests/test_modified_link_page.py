# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from streamlit.testing.v1 import AppTest


class ModifiedLinkPageTests(unittest.TestCase):
    @staticmethod
    def _app():
        page = Path(__file__).resolve().parents[1] / "pages" / "5_Modified_Link.py"
        app = AppTest.from_file(page)
        app.run(timeout=10)
        return app

    def test_page_is_separate_from_enrichment_and_keeps_result_order(self):
        app = self._app()
        app.text_area[0].set_value(
            "https://threads.net/@nalarpedia_id/post/Ddn_ggzgjAE?xmt=AQ\n"
            "https://twitter.com/akun/status/123?s=20"
        )
        app.button[0].click().run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "2")
        self.assertEqual(app.metric[1].value, "2")
        self.assertEqual(
            app.text_area[1].value.splitlines(),
            [
                "https://www.threads.com/@nalarpedia_id/post/Ddn_ggzgjAE",
                "https://x.com/akun/status/123",
            ],
        )

    @patch("src.social_urls.requests.get")
    def test_unresolved_share_link_keeps_an_error_row(self, request_get):
        request_get.side_effect = requests.RequestException("offline")
        app = self._app()
        app.text_area[0].set_value("https://www.threads.com/share/SHORT/")
        app.button[0].click().run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "1")
        self.assertEqual(app.metric[2].value, "1")
        self.assertEqual(app.text_area[1].value, "URL tidak dapat dimodifikasi")


if __name__ == "__main__":
    unittest.main()
