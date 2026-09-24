# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import unittest

from src.conventional_media import (
    ARTICLE_COLUMNS,
    CHECK_ARTICLE_NOT_AVAILABLE,
    classify_tone,
    enrich_article_html,
    media_identity,
    quote_mentions,
    type_mentions,
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
        self.assertEqual(result.type_mention, "Budi Santoso (indirect), Joko Widodo (direct)")
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
        self.assertEqual(
            media_identity("https://diskominfo.sumutprov.go.id/page/berita/contoh"),
            ("DISKOMINFO.SUMUTPROV.GO.ID", "Regional", "Tier 3"),
        )
        self.assertEqual(
            media_identity("https://www.rmol.id/read/contoh"),
            ("RMOL.ID", "National", "Tier 2"),
        )

    def test_unknown_indonesian_publisher_is_not_assumed_international(self):
        self.assertEqual(
            media_identity("https://contohmedia.com/berita/judul"),
            ("CONTOHMEDIA.COM", "National", "Tier 3"),
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
            <p>Informasi utama ini tetap harus tersimpan dengan lengkap. Baca Juga: Artikel promosi lain.</p>
            <div class="related-article"><p>Baca juga: Artikel lain yang direkomendasikan.</p></div>
          </article>
        </body></html>
        """
        result = enrich_article_html("https://contohmedia.com/berita", html)

        self.assertEqual(result.status, "completed")
        self.assertNotIn("Iklan produk", result.content)
        self.assertNotIn("Baca juga", result.content)
        self.assertNotIn("Baca Juga", result.content)
        self.assertNotIn("Artikel promosi lain", result.content)
        self.assertIn("Informasi utama ini tetap harus tersimpan dengan lengkap.", result.content)
        self.assertEqual(result.media_scope, "National")

    def test_structured_content_removes_inline_related_article_prompt(self):
        html = ARTICLE_HTML.replace(
            "Pemerintah menilai capaian itu membuka peluang kerja baru bagi masyarakat.",
            "Pemerintah menilai capaian itu membuka peluang kerja baru bagi masyarakat. "
            "Baca Juga: Promosi artikel yang tidak relevan.",
        )

        result = enrich_article_html("https://finance.detik.com/berita-ekonomi/contoh", html)

        self.assertEqual(result.status, "completed")
        self.assertNotIn("Baca Juga", result.content)
        self.assertNotIn("Promosi artikel", result.content)

    def test_common_indonesian_article_wrappers_are_supported(self):
        paragraph = " ".join(
            ["Isi berita utama menjelaskan peristiwa secara lengkap dan tetap relevan bagi pembaca."] * 7
        )
        wrappers = (
            "entry-body",
            "read__content",
            "detail__content",
            "txt-article",
            "content-inner",
            "elementor-widget-theme-post-content",
            "news-text",
            "paragraph",
            "warp-desc-news-detail",
            "article",
            "content",
        )

        for wrapper in wrappers:
            with self.subTest(wrapper=wrapper):
                html = (
                    "<html lang='id'><head><title>Judul Berita Utama Hari Ini</title></head>"
                    f"<body><div class='{wrapper}'><p>{paragraph}</p></div></body></html>"
                )
                result = enrich_article_html("https://contohmedia.com/berita", html)

                self.assertEqual(result.status, "completed")
                self.assertIn("Isi berita utama", result.content)

    def test_type_mentions_removes_titles_and_merges_short_name_aliases(self):
        article_node = {
            "mentions": [
                {"@type": "Person", "name": "Andi Gani Nena Wea"},
                {"@type": "Person", "name": "Teddy"},
            ]
        }
        content = (
            "Presiden KSPSI Andi Gani mengatakan aksi berjalan damai. "
            "Jalan HR Rasuna disebut tetap ramai."
        )

        self.assertEqual(
            type_mentions(content, article_node),
            "Andi Gani Nena Wea (direct), Teddy (indirect)",
        )

    def test_role_and_action_sentence_extracts_only_person_name(self):
        content = (
            "Direktur Utama GoTo Hans Patuwo menyoroti pertumbuhan layanan keuangan digital. "
            "Menteri Perhubungan (Menhub) Dudy Purwagandhi memastikan layanan tetap berjalan."
        )

        self.assertEqual(quote_mentions(content, {}), "Hans Patuwo, Dudy Purwagandhi")
        self.assertEqual(
            type_mentions(content, {}),
            "Hans Patuwo (indirect), Dudy Purwagandhi (indirect)",
        )

    def test_quote_mentions_only_keeps_people_not_parties_or_organizations(self):
        article_node = {
            "mentions": [
                {"@type": "Person", "name": "Prabowo Subianto"},
                {"@type": "Person", "name": "Partai Golkar"},
                {"@type": "Person", "name": "Koalisi Indonesia Maju"},
            ]
        }
        content = (
            "Prabowo Subianto mengatakan pembahasan akan dilanjutkan. "
            "Koordinator Aksi Koalisi Besar Perjuangan mengatakan massa tetap tertib."
        )

        self.assertEqual(quote_mentions(content, article_node), "Prabowo Subianto")
        self.assertEqual(type_mentions(content, article_node), "Prabowo Subianto (direct)")

    def test_quote_mentions_removes_judicial_titles_and_non_people(self):
        article_node = {
            "mentions": [
                {"@type": "Person", "name": "Hakim Anggota Hotma Maya Marbun"},
                {"@type": "Person", "name": "Hakim Hotma"},
                {"@type": "Person", "name": "Majelis Hakim Subachran Hardi"},
                {"@type": "Person", "name": "Majelis Hakim PT DKI"},
                {"@type": "Person", "name": "Kapuspenkum Kejagung"},
                {"@type": "Person", "name": "Tim Hukum Nadiem"},
                {"@type": "Person", "name": "Ketua"},
                {"@type": "Person", "name": "Anggota"},
            ]
        }
        content = (
            "Hakim Anggota Hotma Maya Marbun mengatakan putusan telah dibacakan. "
            "Majelis Hakim Subachran Hardi menjelaskan pertimbangannya. "
            "Juru Bicara PT DKI Jakarta Catur Iriantoro menyampaikan jadwal sidang."
        )

        self.assertEqual(
            quote_mentions(content, article_node),
            "Hotma Maya Marbun, Subachran Hardi, Catur Iriantoro",
        )
        self.assertEqual(
            type_mentions(content, article_node),
            "Hotma Maya Marbun (direct), Subachran Hardi (direct), Catur Iriantoro (direct)",
        )

    def test_content_removes_more_information_click_here_cta(self):
        paragraph = " ".join(
            ["Isi berita utama tetap lengkap dan menjelaskan kejadian secara relevan kepada pembaca."] * 6
        )
        html = f"""
        <html lang="id"><head><title>Judul Berita Utama Hari Ini</title></head><body>
          <div class="article-content">
            <p>{paragraph}</p>
            <p>Penjelasan terakhir yang masih relevan. Lebih lanjut klik di sini&gt;&gt;&gt;</p>
          </div>
        </body></html>
        """

        result = enrich_article_html("https://contohmedia.com/berita", html)

        self.assertEqual(result.status, "completed")
        self.assertIn("Penjelasan terakhir yang masih relevan.", result.content)
        self.assertNotIn("Lebih lanjut", result.content)
        self.assertNotIn("klik di sini", result.content.casefold())

    def test_content_removes_every_inline_read_more_card(self):
        paragraph = (
            "Pembuka artikel menjelaskan perkara secara lengkap kepada pembaca. "
            "Baca Juga: Judul rekomendasi pertama tanpa tanda baca. "
            "Isi kedua artikel menjelaskan fakta lanjutan secara rinci. "
            "Baca Juga: Jaksa Sebut Kesaksian Eks Pejabat LKPP Perkuat Putusan. "
            "Penutup artikel tetap berisi kesimpulan yang relevan dan penting. "
            + " ".join(["Penjelasan tambahan tetap relevan untuk pembaca."] * 6)
        )
        html = f"""
        <html lang="id"><head><title>Judul Berita Utama Hari Ini</title></head><body>
          <div class="article-content"><p>{paragraph}</p></div>
        </body></html>
        """

        result = enrich_article_html("https://contohmedia.com/berita", html)

        self.assertEqual(result.status, "completed")
        self.assertNotIn("baca juga", result.content.casefold())
        self.assertNotIn("Kesaksian Eks Pejabat", result.quote_mention)

    def test_tone_uses_full_article_text(self):
        self.assertEqual(
            classify_tone(
                "Perusahaan mengumumkan hasil usaha",
                "Perusahaan mengalami kerugian, gagal membayar kewajiban, dan menghadapi krisis serta gugatan.",
            ),
            "Negative",
        )

    def test_title_entities_publisher_suffix_and_visible_date_are_cleaned(self):
        paragraph = " ".join(
            ["Isi artikel menjelaskan program bantuan dan manfaat untuk masyarakat secara lengkap."] * 8
        )
        html = f"""
        <html lang="id"><head><meta property="og:title" content="Program Baru untuk Warga - Medcom.id"></head>
        <body><div class="blog-date">28 JUL 2026</div><div class="artikel-body"><p>{paragraph}</p></div></body></html>
        """

        result = enrich_article_html("https://www.medcom.id/ekonomi/program-baru-untuk-warga", html)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.title, "Program Baru untuk Warga")
        self.assertEqual(result.date_publish, "Jul 28, 2026")
        self.assertEqual(result.month, "July")

    def test_recycled_page_is_marked_failed_instead_of_returning_wrong_article(self):
        paragraph = " ".join(
            ["Morgan Stanley membeli saham perusahaan pada perdagangan hari ini untuk investasi baru."] * 8
        )
        html = f"""
        <html lang="id"><head><title>Morgan Stanley Borong Saham Perusahaan</title></head>
        <body><article><p>{paragraph}</p></article></body></html>
        """

        result = enrich_article_html(
            "https://contohmedia.com/goto-laba-komisi-delapan-persen",
            html,
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("tidak sesuai", result.reason)


if __name__ == "__main__":
    unittest.main()
