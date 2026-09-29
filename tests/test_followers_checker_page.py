# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class FollowersCheckerPageTests(unittest.TestCase):
    @staticmethod
    def _app():
        page = Path(__file__).resolve().parents[1] / "pages" / "6_Followers_Checker.py"
        app = AppTest.from_file(page)
        app.run(timeout=10)
        return app

    def test_page_loads_without_starting_chrome(self):
        app = self._app()

        self.assertFalse(app.exception)
        self.assertTrue(any("Followers Checker" in item.value for item in app.markdown))
        self.assertIn("Cek Semua Followers", [button.label for button in app.button])
        self.assertEqual(app.selectbox[0].value, "Instagram")
        self.assertEqual(len(app.text_area), 1)

    def test_unknown_url_keeps_one_simple_result_row(self):
        app = self._app()
        app.text_area[0].set_value("https://example.com/profile")
        next(button for button in app.button if button.label == "Cek Semua Followers").click()
        app.run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "1")
        result = app.dataframe[0].value
        self.assertEqual(
            list(result.columns),
            ["Platform", "Account Name", "URL", "Followers"],
        )
        self.assertEqual(result.iloc[0]["Followers"], "Platform tidak didukung")

    def test_blank_line_between_urls_is_preserved_as_space_row(self):
        app = self._app()
        app.text_area[0].set_value(
            "https://example.com/profile-one\n   \nhttps://example.com/profile-two"
        )
        next(button for button in app.button if button.label == "Cek Semua Followers").click()
        app.run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, "2")
        result = app.dataframe[0].value
        self.assertEqual(len(result), 3)
        self.assertEqual(
            result.iloc[1].to_dict(),
            {
                "Platform": "space",
                "Account Name": "space",
                "URL": "space",
                "Followers": "space",
            },
        )

    def test_outer_blank_lines_do_not_create_space_rows(self):
        app = self._app()
        app.text_area[0].set_value("\n  \nhttps://example.com/profile\n \n")
        next(button for button in app.button if button.label == "Cek Semua Followers").click()
        app.run(timeout=10)

        self.assertFalse(app.exception)
        result = app.dataframe[0].value
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["URL"], "https://example.com/profile")


if __name__ == "__main__":
    unittest.main()
