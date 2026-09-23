# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest

from src.conventional_media import (
    ARTICLE_COLUMNS,
    CHECK_ARTICLE_NOT_AVAILABLE,
    classify_tone,
    enrich_article_html,
    media_identity,
)
from src.exporters import to_csv_bytes


ARTICLE_HTML = """
<!doctype html>
<html>
  <head>
    <title>Ekonomi Indonesia Tumbuh Positif</title>
    <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": "Ekonomi Indonesia Tumbuh Positif",
        "datePublished": "2026-09-23T10:30:00+07:00",
        "author": [{"@type": "Person", "name": "Rani Putri"}],
        "mentions": [{"@type": "Person", "name": "Dr. Budi Santoso"}],
        "articleBody": "Presiden Joko Widodo mengatakan pertumbuhan ekonomi Indonesia berhasil meningkat tahun ini. Pemerintah menilai capaian itu membuka peluang kerja baru bagi masyarakat. Kebijakan tersebut juga memperkuat investasi, menjaga konsumsi, dan membantu pelaku usaha berkembang secara berkelanjutan. Para ekonom menyebut hasil ini sebagai perkembangan positif yang perlu dijaga melalui kebijakan fiskal yang hati-hati dan dukungan pembiayaan yang merata di berbagai daerah."
      }
    </script>
  </head>
  <body>
    <nav>Menu dan iklan</nav>
    <article><p>Isi artikel utama.</p></article>
  </body>
</html>
"""


class ConventionalMediaTests(unittest.TestCase):
    def test_article_export_has_requested_column_order(self):
        result = enrich_article_html(
            "https://finance.detik.com/berita-ekonomi/contoh",
            ARTICLE_HTML,
        )

        self.assertEqual(tuple(result.to_row()), ARTICLE_COLUMNS)
        self.assertEqual(result.date_publish, "Sep 23, 2026")
        self.assertEqual(result.month, "September")
        self.assertEqual(result.media_name, "DETIK.COM")
        self.assertEqual(result.media_scope, "National")
        self.assertEqual(result.media_tier, "Tier 1")
        self.assertEqual(result.journalist, "Rani Putri")
        self.assertEqual(result.tone, "Positive")
        self.assertEqual(result.quote_mention, "Budi Santoso, Joko Widodo")
        csv_header = to_csv_bytes([result.to_row()]).decode("utf-8-sig").splitlines()[0]
        self.assertEqual(csv_header.split(","), list(ARTICLE_COLUMNS))

    def test_regional_and_international_media_are_classified(self):
        self.assertEqual(
            media_identity("https://solobalapan.jawapos.com/berita/contoh"),
            ("SOLOBALAPAN.JAWAPOS.COM", "Regional", "Tier 1"),
        )
        self.assertEqual(
            media_identity("https://www.reuters.com/world/example"),
            ("REUTERS.COM", "Inter", "Tier 1"),
        )

    def test_removed_article_uses_exact_check_marker(self):
        result = enrich_article_html(
            "https://example.com/deleted",
            "<html><head><title>404 Not Found</title></head><body>Page not found</body></html>",
        )

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.title, CHECK_ARTICLE_NOT_AVAILABLE)
        self.assertEqual(result.content, CHECK_ARTICLE_NOT_AVAILABLE)

    def test_dom_article_removes_navigation_ads_and_related_links(self):
        paragraph = " ".join(["Isi berita utama yang relevan bagi pembaca dan menjelaskan peristiwa secara lengkap."] * 6)
        html = f"""
        <html lang="id"><head><title>Judul Berita Utama Hari Ini</title></head><body>
          <nav>Menu utama dan tautan kategori</nav>
          <article>
            <div class="advertisement"><p>Iklan produk yang tidak relevan dengan berita.</p></div>
            <p>{paragraph}</p>
            <div class="related-article"><p>Baca juga: Artikel lain yang direkomendasikan.</p></div>
          </article>
        </body></html>
        """
        result = enrich_article_html("https://contohmedia.com/berita", html)

        self.assertEqual(result.status, "completed")
        self.assertNotIn("Iklan produk", result.content)
        self.assertNotIn("Baca juga", result.content)
        self.assertEqual(result.media_scope, "National")

    def test_tone_uses_full_article_text(self):
        self.assertEqual(
            classify_tone(
                "Perusahaan mengumumkan hasil usaha",
                "Perusahaan mengalami kerugian, gagal membayar kewajiban, dan menghadapi krisis serta gugatan.",
            ),
            "Negative",
        )


if __name__ == "__main__":
    unittest.main()
