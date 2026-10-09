# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
import importlib.util
from pathlib import Path

from streamlit.testing.v1 import AppTest


class ConventionalPageTests(unittest.TestCase):
    def test_page_exposes_login_first_and_requested_flow(self):
        page = Path(__file__).resolve().parents[1] / "pages" / "4_Conventional_Media_Enrichment.py"
        app = AppTest.from_file(page)
        app.run(timeout=10)

        self.assertFalse(app.exception)
        self.assertEqual([item.label for item in app.text_input], ["Halaman login media (opsional)"])
        self.assertEqual([item.label for item in app.text_area], ["Daftar link artikel"])
        labels = [item.label for item in app.button]
        self.assertIn("Buka Sesi Artikel", labels)
        self.assertIn("Periksa Sesi", labels)
        self.assertIn("Mulai Conventional Enrichment", labels)

    def test_article_submission_order_interleaves_repeated_publishers(self):
        page = Path(__file__).resolve().parents[1] / "pages" / "4_Conventional_Media_Enrichment.py"
        spec = importlib.util.spec_from_file_location("mideta_conventional_page_test", page)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        urls = [
            "https://a.example/1",
            "https://a.example/2",
            "https://a.example/3",
            "https://b.example/1",
            "https://c.example/1",
        ]

        self.assertEqual(module.fair_article_indices(urls), [0, 3, 4, 1, 2])


if __name__ == "__main__":
    unittest.main()
