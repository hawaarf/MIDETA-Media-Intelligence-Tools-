import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class EnrichmentPageTests(unittest.TestCase):
    @staticmethod
    def _app():
        page = Path(__file__).resolve().parents[1] / "pages" / "1_Social_Media_Enrichment.py"
        app = AppTest.from_file(page)
        app.run(timeout=10)
        return app

    def test_split_screen_starts_with_separate_facebook_and_threads_panels(self):
        with (
            patch("src.database.get_social_job", return_value=None),
            patch("src.database.get_latest_social_job", return_value=None),
        ):
            app = self._app()
            app.get("button_group")[0].set_value("Split Screen").run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual(
            [(widget.label, widget.value) for widget in app.selectbox],
            [("Platform kiri", "Facebook"), ("Platform kanan", "Threads")],
        )
        self.assertEqual(
            [widget.label for widget in app.text_area],
            ["Daftar URL Facebook", "Daftar URL Threads"],
        )
        self.assertIn("Mulai Dua Proses", [widget.label for widget in app.button])

    def test_triple_screen_starts_with_three_distinct_platform_panels(self):
        with (
            patch("src.database.get_social_job", return_value=None),
            patch("src.database.get_latest_social_job", return_value=None),
        ):
            app = self._app()
            app.get("button_group")[0].set_value("Triple Screen").run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual(
            [(widget.label, widget.value) for widget in app.selectbox],
            [
                ("Platform kiri", "Facebook"),
                ("Platform tengah", "Threads"),
                ("Platform kanan", "Instagram"),
            ],
        )
        self.assertEqual(
            [widget.label for widget in app.text_area],
            ["Daftar URL Facebook", "Daftar URL Threads", "Daftar URL Instagram"],
        )
        self.assertIn("Mulai Tiga Proses", [widget.label for widget in app.button])


if __name__ == "__main__":
    unittest.main()
