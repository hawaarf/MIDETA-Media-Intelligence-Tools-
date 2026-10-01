# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class KeywordSearchPageTests(unittest.TestCase):
    @staticmethod
    def _app():
        page = Path(__file__).resolve().parents[1] / "pages" / "8_Keyword_Search.py"
        app = AppTest.from_file(page)
        app.run(timeout=10)
        return app

    def test_page_loads_without_running_a_network_search(self):
        app = self._app()

        self.assertFalse(app.exception)
        self.assertTrue(any("Keyword Search" in item.value for item in app.markdown))
        self.assertIn("Cari Mention", [button.label for button in app.button])
        self.assertEqual(len(app.text_area), 1)
        self.assertEqual(len(app.multiselect), 1)
        self.assertEqual(app.multiselect[0].value, ["TikTok", "Threads"])
        self.assertEqual(len(app.date_input), 2)
        warning_copy = " ".join(item.value for item in app.warning)
        self.assertIn("berbeda dari Meltwater", warning_copy)
        self.assertIn("Buka Sesi TikTok", [button.label for button in app.button])

    def test_empty_query_is_rejected_before_network(self):
        app = self._app()
        next(button for button in app.button if button.label == "Cari Mention").click()
        app.run(timeout=10)

        self.assertFalse(app.exception)
        self.assertTrue(any("minimal satu keyword" in item.value for item in app.error))


if __name__ == "__main__":
    unittest.main()
