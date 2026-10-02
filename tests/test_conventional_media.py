# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

import json
import unittest

from src.conventional_media import (
    ARTICLE_COLUMNS,
    CHECK_ARTICLE_NOT_AVAILABLE,
    CHECK_FAILED_TO_PROCESS,
    CONVENTIONAL_MEDIA_CATALOG,
    SWA_CRAWLING_NOTICE,
    _failed_result,
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
            ("REUTERS.COM", "International", "Tier 1"),
        )
        self.assertEqual(
            media_identity("https://diskominfo.sumutprov.go.id/page/berita/contoh"),
            ("DISKOMINFO.SUMUTPROV.GO.ID", "Regional", "Tier 3"),
        )
        self.assertEqual(
            media_identity("https://www.rmol.id/read/contoh"),
            ("RMOL.ID", "National", "Tier 2"),
        )

    def test_reviewed_conventional_media_catalog_is_the_primary_identity_source(self):
        self.assertEqual(len(CONVENTIONAL_MEDIA_CATALOG), 16_209)
        self.assertEqual(
            media_identity("https://20.detik.com/berita/contoh"),
            ("DETIK.COM", "National", "Tier 1"),
        )
        self.assertEqual(
            media_identity("https://investasi.kontan.co.id/news/contoh"),
            ("INVESTASI.KONTAN.CO.ID", "National", "Tier 1"),
        )
        self.assertEqual(
            media_identity("https://zone.id/news/contoh"),
            ("ZONE.ID", "Provincial", "Tier 3"),
        )
        self.assertEqual(
            media_identity("https://bkpp.demakkab.go.id/news/contoh"),
            ("BKPP.DEMAKKAB.GO.ID", "", "Tier 3"),
        )

        international_html = ARTICLE_HTML.replace(
            "<html>",
            '<html lang="id">',
        )
        international = enrich_article_html(
            "https://01caijing.com/news/contoh",
            international_html,
        )
        self.assertEqual(international.media_scope, "International")

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
            "berita_content_sub",
            "news-detail-content",
            "bodyArticleWrapper",
            "c-detail read",
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

        for wrapper_id in ("berita_content_sub", "sub_content", "berita_panel"):
            with self.subTest(wrapper_id=wrapper_id):
                html = (
                    "<html lang='id'><head><title>Judul Berita Utama Hari Ini</title></head>"
                    f"<body><div id='{wrapper_id}'><p>{paragraph}</p></div></body></html>"
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
            "Menteri Perhubungan (Menhub) Dudy Purwagandhi memastikan layanan tetap berjalan. "
            "Deputi Bidang Usaha Kecil Kementerian UMKM Temmy Satya Permana memberikan penjelasan."
        )

        self.assertEqual(
            quote_mentions(content, {}),
            "Hans Patuwo, Dudy Purwagandhi, Temmy Satya Permana",
        )
        self.assertEqual(
            type_mentions(content, {}),
            "Hans Patuwo (indirect), Dudy Purwagandhi (indirect), Temmy Satya Permana (indirect)",
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

    def test_content_stops_before_next_article_and_publisher_footer(self):
        paragraph = " ".join(
            ["Isi berita utama menjelaskan program dan dampaknya secara lengkap bagi pembaca."] * 8
        )
        html = f"""
        <html lang="id"><head><title>Program Utama untuk Masyarakat</title></head><body>
          <article>
            <p>{paragraph}</p>
            <p>Penutup berita yang masih relevan. Artikel Selanjutnya: Promo produk lain.</p>
            <p>Pewarta: Nama Redaksi Copyright © Penerbit.</p>
            <p>Paragraf artikel lain yang terlihat valid tetapi tidak boleh ikut.</p>
          </article>
        </body></html>
        """

        result = enrich_article_html("https://contohmedia.com/program-utama", html)

        self.assertEqual(result.status, "completed")
        self.assertIn("Penutup berita yang masih relevan", result.content)
        self.assertNotIn("Artikel Selanjutnya", result.content)
        self.assertNotIn("Pewarta", result.content)
        self.assertNotIn("Promo produk lain", result.content)
        self.assertNotIn("Paragraf artikel lain", result.content)

    def test_photo_caption_section_after_article_is_excluded(self):
        paragraph = " ".join(
            ["Isi berita utama menjelaskan program dan dampaknya secara lengkap bagi pembaca."] * 8
        )
        html = f"""
        <html><head><title>Program Utama untuk Masyarakat</title></head><body>
          <div id="sub_content">
            <p>{paragraph}</p>
            <p>Penutup isi artikel yang masih relevan.</p>
            <p>Teks foto :</p>
            <p>1. Nama Acak dalam dokumentasi acara perusahaan.</p>
            <p>2. Orang Lain berdiri bersama peserta kegiatan.</p>
          </div>
        </body></html>
        """

        result = enrich_article_html("https://contohmedia.com/program-utama", html)

        self.assertEqual(result.status, "completed")
        self.assertIn("Penutup isi artikel", result.content)
        self.assertNotIn("Nama Acak", result.content)
        self.assertNotIn("Orang Lain", result.content)

    def test_promotional_access_instructions_and_signature_are_excluded(self):
        paragraph = " ".join(
            ["Isi berita utama menjelaskan program dan dampaknya secara lengkap bagi pembaca."] * 8
        )
        html = f"""
        <html><head><title>Program Utama untuk Masyarakat</title></head><body>
          <article>
            <p>{paragraph}</p>
            <p>Portal Program dapat diakses melalui https://contoh.invalid dan pendaftaran tersedia.</p>
            <p>Informasi pembelajaran bagi peserta tersedia melalui aplikasi dan kanal resmi.</p>
            <p>Penutup isi artikel tetap disimpan. ( nama redaksi )</p>
          </article>
        </body></html>
        """

        result = enrich_article_html("https://contohmedia.com/program-utama", html)

        self.assertEqual(result.status, "completed")
        self.assertNotIn("Portal Program", result.content)
        self.assertNotIn("Informasi pembelajaran", result.content)
        self.assertIn("Penutup isi artikel tetap disimpan.", result.content)
        self.assertNotIn("nama redaksi", result.content)

    def test_content_stops_before_read_full_article_link(self):
        paragraph = " ".join(
            ["Isi berita utama menjelaskan program dan dampaknya secara lengkap bagi pembaca."] * 8
        )
        html = f"""
        <html lang="id"><head><title>Program Utama untuk Masyarakat</title></head><body>
          <article>
            <p>{paragraph}</p>
            <p>Penutup berita tetap relevan. Read full article on Another Publisher</p>
          </article>
        </body></html>
        """

        result = enrich_article_html("https://contohmedia.com/program-utama", html)

        self.assertEqual(result.status, "completed")
        self.assertIn("Penutup berita tetap relevan", result.content)
        self.assertNotIn("Read full article", result.content)
        self.assertNotIn("Another Publisher", result.content)

    def test_related_links_only_page_is_not_treated_as_article(self):
        shell = " ".join(
            [
                "Campaign Strategi Perusahaan Perkuat Ekosistem Mitra.",
                "Related",
                "Berita pertama tentang layanan digital.",
                "Berita kedua tentang bisnis regional.",
                "Berita ketiga tentang program perusahaan.",
                "Latest News",
                "Berita keempat yang tidak terkait dengan URL.",
            ]
            * 3
        )
        html = f"""
        <html><head><title>Campaign Strategi Perusahaan</title></head>
          <body><main><p>{shell}</p></main></body>
        </html>
        """

        result = enrich_article_html("https://contohmedia.com/campaign-strategi", html)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.content, CHECK_FAILED_TO_PROCESS)

    def test_people_in_quotes_and_captions_are_names_only(self):
        content = (
            "Menteri Usaha Mikro, Kecil, dan Menengah Maman Abdurrahman mengatakan program dilanjutkan. "
            "Shofwim Shofwan, Mitra Instruktur; Dr. Hendrian, S.E., M.Si., Wakil Rektor Bidang Riset; "
            "dan Prof. Dr. Ali Muktiyanto, S.E., M.Si., Rektor Universitas Terbuka, mengatakan "
            "pendidikan harus mudah diakses."
        )

        self.assertEqual(
            quote_mentions(content, {}),
            "Maman Abdurrahman, Shofwim Shofwan, Hendrian, Ali Muktiyanto",
        )
        self.assertEqual(
            type_mentions(content, {}),
            "Maman Abdurrahman (direct), Shofwim Shofwan (indirect), "
            "Hendrian (indirect), Ali Muktiyanto (direct)",
        )

    def test_swa_keeps_metadata_but_respects_crawling_notice(self):
        paragraph = " ".join(["Teks larangan otomatis dari penerbit dan bukan isi artikel."] * 8)
        html = f"""
        <html lang="id"><head>
          <meta property="og:title" content="Judul Artikel SWA">
          <meta property="article:published_time" content="2026-09-25T10:00:00+07:00">
        </head><body><article><p>{paragraph}</p></article></body></html>
        """

        result = enrich_article_html("https://swa.co.id/read/123/judul-artikel-swa", html)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.content, SWA_CRAWLING_NOTICE)
        self.assertEqual(result.title, "Judul Artikel SWA")
        self.assertEqual(result.quote_mention, "")

    def test_structured_article_body_wins_over_long_page_footer(self):
        body = " ".join(["Isi berita terstruktur tetap relevan dan menjelaskan fakta utama."] * 9)
        footer = " ".join(["Daftar berita lain dan promosi situs penerbit."] * 30)
        html = f"""
        <html><head><title>Berita Terstruktur Hari Ini</title>
          <script type="application/ld+json">{{
            "@context": "https://schema.org", "@type": "NewsArticle",
            "headline": "Berita Terstruktur Hari Ini", "articleBody": "{body}"
          }}</script>
        </head><body><main><p>{body}</p><p>{footer}</p></main></body></html>
        """

        result = enrich_article_html("https://contohmedia.com/berita-terstruktur-hari-ini", html)

        self.assertEqual(result.status, "completed")
        self.assertIn("Isi berita terstruktur", result.content)
        self.assertNotIn("Daftar berita lain", result.content)

    def test_tone_uses_full_article_text(self):
        self.assertEqual(
            classify_tone(
                "Perusahaan mengumumkan hasil usaha",
                "Perusahaan mengalami kerugian, gagal membayar kewajiban, dan menghadapi krisis serta gugatan.",
            ),
            "Negative",
        )

    def test_financial_tone_tracks_headline_tickers_not_unrelated_winners(self):
        self.assertEqual(
            classify_tone(
                "Daftar Saham LQ45, GOTO dan AMMN Disorot",
                "PT GOTO kembali anjlok tajam dan turun 12,5%. "
                "PT AMMN terkoreksi dan melemah. PT CUAN menguat dan naik.",
            ),
            "Negative",
        )
        self.assertEqual(
            classify_tone(
                "Saham GOTO Tertekan, Analis Soroti Peluang Buyback",
                "Saham GOTO tertekan dan terkoreksi setelah tekanan jual. "
                "Valuasi GOTO membaik dan menarik, dengan peluang pemulihan serta pertumbuhan laba.",
            ),
            "Neutral",
        )

    def test_analyst_groups_are_normalized_to_human_names(self):
        content = (
            "Analis dari Deutsche Bank Peter Milliken menilai tekanan jual akan mereda. "
            '"Aksi jual membuat valuasi menarik," kata Ranjan Sharma, Steven Suntoso, '
            "Sigrid Qiu, Alex Yao dan Benny Kurniawan, Tim Analis JP Morgan. "
            '"Harga belum mencerminkan fundamental," kata Edo, Analis Phillip Sekuritas Indonesia. '
            '"Dampaknya kami perhitungkan," kata Hans Patuwo, Chief Executive Officer GOTO.'
        )

        self.assertEqual(
            quote_mentions(content, {}),
            "Peter Milliken, Ranjan Sharma, Steven Suntoso, Sigrid Qiu, Alex Yao, "
            "Benny Kurniawan, Edo, Hans Patuwo",
        )
        self.assertEqual(
            type_mentions(content, {}),
            "Peter Milliken (indirect), Ranjan Sharma (direct), Steven Suntoso (direct), "
            "Sigrid Qiu (direct), Alex Yao (direct), Benny Kurniawan (direct), "
            "Edo (direct), Hans Patuwo (direct)",
        )

    def test_syndication_suffix_and_editorial_prompts_are_removed(self):
        body = " ".join(
            ["Isi artikel menjelaskan penurunan saham dan ketentuan bursa secara lengkap."] * 8
        )
        payload = json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "NewsArticle",
                "headline": (
                    "Saham GOTO Merosot hingga 44% Artikel ini adalah bagian dari Mitra Promedia Group "
                    "dan sudah tayang dengan judul lain Baca selengkapnya di: https://contoh.invalid"
                ),
                "articleBody": body + " Make the article one line onlyRemove remaining article headings",
            }
        )
        html = f"<html><head><script type='application/ld+json'>{payload}</script></head><body></body></html>"

        result = enrich_article_html(
            "https://contohmedia.com/saham-goto-merosot-hingga-44-persen",
            html,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.title, "Saham GOTO Merosot hingga 44%")
        self.assertNotIn("Make the article", result.content)
        self.assertNotIn("Remove remaining", result.content)

    def test_embedded_editor_payload_recovers_complete_article_content(self):
        teaser = " ".join(["Teaser artikel berhenti sebelum kalimatnya selesai"] * 6)
        recovered = " ".join(
            ["Isi lengkap artikel membahas saham GOTO dan kinerja perusahaan secara akurat."] * 10
        )
        malformed_payload = teaser + '{"title": "Judul lain", "content": "' + recovered
        payload = json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "NewsArticle",
                "headline": "Kinerja Saham GOTO Hari Ini",
                "articleBody": malformed_payload,
            }
        )
        html = f"<html><head><script type='application/ld+json'>{payload}</script></head><body></body></html>"

        result = enrich_article_html(
            "https://contohmedia.com/kinerja-saham-goto-hari-ini",
            html,
        )

        self.assertEqual(result.status, "completed")
        self.assertTrue(result.content.startswith("Isi lengkap artikel"))
        self.assertNotIn('{"title"', result.content)
        self.assertNotIn("Teaser artikel", result.content)

    def test_byline_and_figure_caption_are_not_exported_as_content(self):
        body = " ".join(
            ["Isi berita menjelaskan saham GOTO dan pergerakan pasar secara lengkap."] * 8
        )
        html = f"""
        <html><head><title>Pergerakan Saham GOTO Hari Ini</title></head><body>
          <div class="tmpt-desk-kon">
            <p>Reporter: Hasbi Maulana | Editor: Hasbi Maulana</p>
            <p>{body}<figure class="article-media"><figcaption>
              Judul artikel rekomendasi. © 2026 Konten oleh Contoh Media
            </figcaption></figure></p>
          </div>
        </body></html>
        """

        result = enrich_article_html(
            "https://contohmedia.com/pergerakan-saham-goto-hari-ini",
            html,
        )

        self.assertEqual(result.status, "completed")
        self.assertNotIn("Reporter:", result.content)
        self.assertNotIn("artikel rekomendasi", result.content)
        self.assertNotIn("Konten oleh", result.content)

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

    def test_timestamped_syndication_url_overrides_wrong_page_date(self):
        paragraph = " ".join(
            ["Isi artikel menjelaskan perlindungan pekerja platform secara lengkap dan akurat."] * 8
        )
        html = f"""
        <html><head>
          <meta property="article:published_time" content="2026-07-01T08:00:00+07:00">
          <title>Perlindungan Pekerja Platform</title>
        </head><body><article><p>{paragraph}</p></article></body></html>
        """

        result = enrich_article_html(
            "http://antarapress.com/info/t-2608221600.html",
            html,
        )

        self.assertEqual(result.date_publish, "Aug 22, 2026")
        self.assertEqual(result.month, "August")

    def test_antara_header_date_overrides_recycled_structured_date(self):
        paragraph = " ".join(
            ["Isi artikel membahas perlindungan pekerja dan daya saing secara berimbang."] * 8
        )
        html = f"""
        <html><head>
          <meta itemprop="datePublished" content="Sun, 27 Sep 2026 19:43:40 +0700">
          <title>Perlindungan Pekerja dan Daya Saing</title>
        </head><body><main>
          <time datetime="Thu, 27 Aug 2026 08:53:43 +0700" itemprop="dateModified">
            Kamis, 27 Agustus 2026 08:53 WIB
          </time>
          <article><p>{paragraph}</p></article>
        </main></body></html>
        """

        result = enrich_article_html(
            "https://sulteng.antaranews.com/berita/391011/perlindungan-pekerja",
            html,
        )

        self.assertEqual(result.date_publish, "Aug 27, 2026")

    def test_failed_article_keeps_detectable_publish_date(self):
        html = """
        <html><head>
          <meta property="article:published_time" content="2026-08-12T09:00:00+07:00">
          <title>Artikel Memerlukan Pemeriksaan</title>
        </head><body><main>Konten tidak dimuat.</main></body></html>
        """

        result = enrich_article_html("https://contohmedia.com/artikel", html)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.date_publish, "Aug 12, 2026")
        self.assertEqual(result.month, "August")

    def test_transport_failure_still_uses_date_encoded_in_url(self):
        result = _failed_result(
            "https://ekonomi.bisnis.com/read/20260824/12/1998600/judul-artikel",
            CHECK_FAILED_TO_PROCESS,
            "Halaman tidak dapat dihubungi.",
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.date_publish, "Aug 24, 2026")
        self.assertEqual(result.month, "August")

    def test_json_ld_article_is_matched_to_requested_url(self):
        wrong_body = " ".join(["Isi rekomendasi yang bukan artikel target pengguna."] * 9)
        right_body = " ".join(["Isi artikel target membahas kebijakan pekerja digital."] * 9)
        html = f"""
        <html><head><script type="application/ld+json">[
          {{"@type":"NewsArticle","url":"https://contohmedia.com/rekomendasi",
            "headline":"Artikel Rekomendasi","datePublished":"2026-09-29","articleBody":"{wrong_body}"}},
          {{"@type":"NewsArticle","url":"https://contohmedia.com/artikel-target",
            "headline":"Artikel Target","datePublished":"2026-08-27","articleBody":"{right_body}"}}
        ]</script></head><body><article><p>{right_body}</p></article></body></html>
        """

        result = enrich_article_html("https://contohmedia.com/artikel-target", html)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.title, "Artikel Target")
        self.assertEqual(result.date_publish, "Aug 27, 2026")

    def test_obviously_stale_metadata_yields_to_contextual_article_date(self):
        lead = "Menteri membahas perlindungan pekerja platform di Jakarta, Jumat (14/8/2026). "
        paragraph = lead + " ".join(
            ["Kebijakan tersebut dijelaskan secara lengkap untuk menjaga hak para pekerja digital."] * 8
        )
        html = f"""
        <html><head>
          <meta property="article:published_time" content="2026-02-13T11:00:09+07:00">
          <title>Perlindungan Pekerja Platform Digital</title>
        </head><body><article><p>{paragraph}</p></article></body></html>
        """

        result = enrich_article_html("https://matauang.co.id/detail/587052/artikel", html)

        self.assertEqual(result.date_publish, "Aug 14, 2026")

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
