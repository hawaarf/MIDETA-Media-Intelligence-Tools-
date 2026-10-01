# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class ProfileScrapingPageTests(unittest.TestCase):
    @staticmethod
    def _app():
        page = Path(__file__).resolve().parents[1] / "pages" / "7_Profile_Scraping.py"
        app = AppTest.from_file(page)
        app.run(timeout=10)
        return app

    def test_page_loads_without_login_or_network_request(self):
        app = self._app()

        self.assertFalse(app.exception)
        self.assertTrue(any("Profile Scraping" in item.value for item in app.markdown))
        self.assertIn("Mulai Profile Scraping", [button.label for button in app.button])
        self.assertEqual(len(app.text_input), 1)
        self.assertEqual(len(app.date_input), 2)
        page_copy = " ".join(item.value for item in app.info)
        self.assertIn("tidak memakai login", page_copy)
        self.assertIn("Apify", page_copy)

    def test_invalid_profile_is_rejected_without_network(self):
        app = self._app()
        app.text_input[0].set_value("https://www.tiktok.com/@akun/video/123")
        next(button for button in app.button if button.label == "Mulai Profile Scraping").click()
        app.run(timeout=10)

        self.assertFalse(app.exception)
        self.assertTrue(any("bukan URL posting" in item.value for item in app.error))


if __name__ == "__main__":
    unittest.main()
