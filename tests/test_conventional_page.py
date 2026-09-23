# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest
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


if __name__ == "__main__":
    unittest.main()
