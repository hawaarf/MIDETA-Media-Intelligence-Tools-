import os
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

    def test_enrichment_all_accepts_one_mixed_url_list(self):
        with (
            patch("src.database.get_social_job", return_value=None),
            patch("src.database.get_latest_social_job", return_value=None),
        ):
            app = self._app()
            app.get("button_group")[0].set_value("Enrichment All").run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual([widget.label for widget in app.text_area], ["Semua URL media sosial"])
        self.assertIn("Mulai Enrichment All", [widget.label for widget in app.button])

    def test_tiktok_enrichment_uses_public_mode_without_chrome_controls(self):
        with (
            patch("src.database.get_social_job", return_value=None),
            patch("src.database.get_latest_social_job", return_value=None),
        ):
            app = self._app()
            app.get("button_group")[1].set_value("TikTok").run(timeout=10)

        self.assertFalse(app.exception)
        button_labels = [widget.label for widget in app.button]
        self.assertIn("Simpan token", button_labels)
        self.assertIn("Hapus token", button_labels)
        self.assertIn("Mulai Enrichment TikTok", button_labels)
        self.assertNotIn("Buka Chrome TikTok", button_labels)
        self.assertNotIn("Periksa Login", button_labels)
        self.assertNotIn("Tutup Chrome TikTok", button_labels)

    def test_facebook_offers_advanced_enrichment_with_login_controls(self):
        with (
            patch("src.database.get_social_job", return_value=None),
            patch("src.database.get_latest_social_job", return_value=None),
        ):
            app = self._app()
            app.get("button_group")[1].set_value("Facebook").run(timeout=10)
            app.get("button_group")[2].set_value("Advanced enrichment").run(timeout=10)

        self.assertFalse(app.exception)
        button_labels = [widget.label for widget in app.button]
        self.assertIn("Buka Chrome Facebook", button_labels)
        self.assertIn("Periksa Login", button_labels)
        self.assertIn("Tutup Chrome Facebook", button_labels)
        self.assertIn("Mulai Advanced Enrichment", button_labels)

    def test_deployed_mode_uses_public_fallback_without_login_buttons(self):
        with (
            patch.dict(os.environ, {"MIDETA_BROWSER_SESSIONS": "disabled"}),
            patch("src.database.get_social_job", return_value=None),
            patch("src.database.get_latest_social_job", return_value=None),
        ):
            app = self._app()
            app.get("button_group")[1].set_value("Facebook").run(timeout=10)

        self.assertFalse(app.exception)
        button_labels = [widget.label for widget in app.button]
        self.assertNotIn("Buka Chrome Facebook", button_labels)
        self.assertNotIn("Periksa Login", button_labels)
        self.assertNotIn("Tutup Chrome Facebook", button_labels)
        self.assertIn("Mulai Fast Enrichment", button_labels)
        self.assertTrue(any("Versi web memakai Fast enrichment" in item.value for item in app.info))


if __name__ == "__main__":
    unittest.main()
