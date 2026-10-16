# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
import importlib.util
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.conventional_media import ArticleResult


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

    def test_public_access_denial_automatically_uses_browser_fallback(self):
        page = Path(__file__).resolve().parents[1] / "pages" / "4_Conventional_Media_Enrichment.py"
        spec = importlib.util.spec_from_file_location("mideta_conventional_retry_test", page)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        blocked = ArticleResult(
            source_url="https://peradaban.id/contoh",
            title="[CHECK] failed to process",
            content="[CHECK] failed to process",
            status="failed",
            reason="Akses ditolak. Halaman mungkin memerlukan login atau dilindungi situs.",
        )
        ordinary_failure = ArticleResult(
            source_url="https://example.com/contoh",
            title="[CHECK] failed to process",
            content="[CHECK] failed to process",
            status="failed",
            reason="Isi artikel tidak dapat dipisahkan dari halaman.",
        )
        completed = ArticleResult(
            source_url="https://example.com/selesai",
            status="completed",
        )

        self.assertTrue(module.browser_retry_needed(blocked, browser_ready=False))
        self.assertFalse(module.browser_retry_needed(ordinary_failure, browser_ready=False))
        self.assertTrue(module.browser_retry_needed(ordinary_failure, browser_ready=True))
        self.assertFalse(module.browser_retry_needed(completed, browser_ready=True))


if __name__ == "__main__":
    unittest.main()
