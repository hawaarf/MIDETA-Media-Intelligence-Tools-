# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""MIDETA Conventional Media Enrichment page."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st

from src.batch import parse_url_list
from src.config import MAX_ENRICHMENT_URLS, MAX_PARALLEL_ARTICLES, MIDETA_LOGO_PATH
from src.conventional_media import (
    CHECK_FAILED_TO_PROCESS,
    ArticleResult,
    ConventionalMediaBrowser,
    ConventionalMediaError,
    enrich_public_article,
)
from src.database import add_history
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.ui import apply_theme, page_intro, render_footer, render_github_profile


st.set_page_config(
    page_title="Conventional Media Enrichment | MIDETA",
    page_icon=str(MIDETA_LOGO_PATH),
    layout="wide",
)
apply_theme()
render_github_profile()
page_intro(
    "04",
    "Conventional Media Enrichment",
    "Ubah daftar link berita menjadi data artikel yang bersih, konsisten, dan siap dipakai.",
)

st.info(
    "Alur: siapkan sesi login bila diperlukan → tempel satu link artikel per baris → mulai enrichment → "
    "periksa hasil → unduh CSV atau XLSX. Semua hasil tetap mengikuti urutan link awal."
)


@st.cache_resource(show_spinner=False)
def article_browser() -> ConventionalMediaBrowser:
    return ConventionalMediaBrowser()


def process_articles(urls: list[str]) -> list[ArticleResult]:
    """Process public pages concurrently, then retry blocked pages in Chrome."""
    results: list[ArticleResult | None] = [None] * len(urls)
    retry_in_browser: list[int] = []
    completed = 0
    progress = st.progress(0.0, text=f"Menyiapkan {len(urls):,} artikel…")
    activity = st.empty()
    browser_ready = article_browser().is_running()

    workers = min(MAX_PARALLEL_ARTICLES, max(1, len(urls)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mideta-article") as executor:
        futures = {
            executor.submit(enrich_public_article, url): index
            for index, url in enumerate(urls)
        }
        for future in as_completed(futures):
            index = futures[future]
            result = future.result()
            if result.status == "failed" and browser_ready:
                retry_in_browser.append(index)
                activity.info(
                    f"Artikel publik terhalang. Menyiapkan percobaan lewat sesi Chrome: {urls[index]}"
                )
                continue
            results[index] = result
            completed += 1
            progress.progress(
                completed / len(urls),
                text=f"{completed:,} dari {len(urls):,} artikel selesai",
            )

    for index in retry_in_browser:
        activity.info(f"Membaca artikel melalui sesi login: {urls[index]}")
        results[index] = article_browser().collect(urls[index])
        completed += 1
        progress.progress(
            completed / len(urls),
            text=f"{completed:,} dari {len(urls):,} artikel selesai",
        )

    progress.progress(1.0, text=f"Selesai: {len(urls):,} artikel sudah disimpan")
    activity.empty()
    return [
        result
        if result is not None
        else ArticleResult(
            source_url=urls[index],
            title=CHECK_FAILED_TO_PROCESS,
            content=CHECK_FAILED_TO_PROCESS,
            status="failed",
            reason="Hasil artikel tidak terbentuk.",
        )
        for index, result in enumerate(results)
    ]


st.markdown('<div class="section-label">LANGKAH 1 · SESI LOGIN</div>', unsafe_allow_html=True)
st.subheader("Artikel ber-login atau berlangganan?")
st.caption(
    "Buka sesi Chrome terlebih dahulu dan login langsung di situs medianya. Sesi disimpan lokal di komputer ini; "
    "password tidak dibaca MIDETA. Jika semua artikel publik, bagian ini boleh dilewati."
)
login_url = st.text_input(
    "Halaman login media (opsional)",
    placeholder="https://nama-media.com/login",
    help="Masukkan halaman login salah satu media. Situs lain dapat dibuka langsung dari Chrome yang sama.",
)
open_col, check_col, close_col = st.columns(3)
if open_col.button("Buka Sesi Artikel", icon=":material/login:", width="stretch"):
    try:
        article_browser().open_session(login_url)
        st.info("Login di jendela Chrome yang terbuka. Setelah selesai, kembali ke MIDETA dan tekan Periksa Sesi.")
    except ConventionalMediaError as exc:
        st.error(str(exc))
if check_col.button("Periksa Sesi", icon=":material/check_circle:", width="stretch"):
    if article_browser().is_running():
        st.success("Sesi Chrome artikel aktif. URL yang terhalang akan dicoba otomatis melalui sesi ini.")
    else:
        st.warning("Sesi Chrome artikel belum aktif. Tekan Buka Sesi Artikel terlebih dahulu.")
if close_col.button("Tutup Chrome Artikel", icon=":material/close:", width="stretch"):
    article_browser().close()
    st.info("Chrome artikel MIDETA sudah ditutup.")

st.markdown('<div class="section-label">LANGKAH 2 · DAFTAR ARTIKEL</div>', unsafe_allow_html=True)
st.subheader("Tempel link berita")
raw_urls = st.text_area(
    "Daftar link artikel",
    height=230,
    placeholder="https://media-a.com/judul-artikel\nhttps://media-b.com/berita/lainnya",
    help=f"Satu link per baris. Maksimal {MAX_ENRICHMENT_URLS:,} link; link berulang tetap dipertahankan sebagai baris terpisah.",
)
st.caption(
    "MIDETA membersihkan iklan, menu, rekomendasi, dan elemen halaman lain dari isi artikel. "
    "Media scope dan tier ditentukan dari domain media; tone dan quote mention dibaca dari keseluruhan artikel."
)

if st.button(
    "Mulai Conventional Enrichment",
    type="primary",
    icon=":material/newspaper:",
    width="stretch",
):
    urls = parse_url_list(raw_urls, preserve_repeated_rows=True)
    if not urls:
        st.error("Masukkan minimal satu link artikel lengkap yang diawali http:// atau https://.")
    elif len(urls) > MAX_ENRICHMENT_URLS:
        st.error(
            f"Maksimal {MAX_ENRICHMENT_URLS:,} link per proses. Kurangi {len(urls) - MAX_ENRICHMENT_URLS:,} link lalu coba lagi."
        )
    else:
        results = process_articles(urls)
        st.session_state["conventional_media_results"] = [result.__dict__ for result in results]
        for result in results:
            add_history(
                "Conventional Media Enrichment",
                result.source_url,
                "completed" if result.status == "completed" else "failed",
                {**result.to_row(), "status": result.status, "reason": result.reason},
                "Conventional Media",
            )


stored_results = st.session_state.get("conventional_media_results", [])
if stored_results:
    results = [ArticleResult(**item) for item in stored_results]
    rows = [result.to_row() for result in results]
    completed_count = sum(result.status == "completed" for result in results)
    unavailable_count = sum(result.status == "unavailable" for result in results)
    failed_count = sum(result.status == "failed" for result in results)

    st.markdown('<div class="section-label">LANGKAH 3 · HASIL</div>', unsafe_allow_html=True)
    metrics = st.columns(4)
    metrics[0].metric("Diproses", len(results))
    metrics[1].metric("Berhasil", completed_count)
    metrics[2].metric("Article not available", unavailable_count)
    metrics[3].metric("Failed to process", failed_count)
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=430)

    with st.expander("Lihat link yang perlu diperiksa"):
        issues = [
            {
                "page_link": result.source_url,
                "status": result.content,
                "reason": result.reason or "Tidak ada detail tambahan.",
            }
            for result in results
            if result.status != "completed"
        ]
        if issues:
            st.dataframe(pd.DataFrame(issues), width="stretch", hide_index=True)
        else:
            st.success("Semua artikel berhasil diproses.")

    csv_col, xlsx_col = st.columns(2)
    csv_col.download_button(
        "Unduh CSV",
        to_csv_bytes(rows),
        "mideta_conventional_media.csv",
        "text/csv",
        icon=":material/download:",
        width="stretch",
    )
    xlsx_col.download_button(
        "Unduh XLSX",
        to_xlsx_bytes(rows, "Conventional Media"),
        "mideta_conventional_media.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        width="stretch",
    )

render_footer()
