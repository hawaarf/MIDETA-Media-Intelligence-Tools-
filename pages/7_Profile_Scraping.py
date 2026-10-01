# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""MIDETA no-login TikTok profile post URL scraper."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src.config import MAX_PROFILE_POSTS, MIDETA_LOGO_PATH
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.tiktok_profile import (
    TikTokProfileCollector,
    TikTokProfileScrapeError,
    TikTokProfileScrapeResult,
    canonical_profile_url,
    parse_tiktok_profile,
)
from src.ui import apply_theme, page_intro, render_footer, render_github_profile


def profile_collector() -> TikTokProfileCollector:
    # Lightweight object; recreate it so scraper fixes are picked up immediately
    # during Streamlit hot reload instead of retaining an older cached class.
    return TikTokProfileCollector()


def default_range() -> tuple[date, date]:
    today = date.today()
    start = date(today.year, 1, 1)
    august_end = date(today.year, 8, 31)
    return start, min(today, august_end)


def date_progress(start_date: date, end_date: date, oldest_date: date | None) -> float:
    if oldest_date is None:
        return 0.02
    total_days = max((end_date - start_date).days, 1)
    covered_days = (end_date - min(max(oldest_date, start_date), end_date)).days
    return min(max(covered_days / total_days, 0.02), 0.98)


st.set_page_config(
    page_title="Profile Scraping | MIDETA",
    page_icon=str(MIDETA_LOGO_PATH),
    layout="wide",
)
apply_theme()
render_github_profile()
page_intro(
    "07",
    "Profile Scraping",
    "Ambil URL posting publik dari satu profil TikTok berdasarkan rentang tanggal khusus.",
)

st.info(
    "Fitur ini tidak memakai login, Chrome, atau Apify. Masukkan satu profil TikTok, pilih tanggal awal dan akhir, "
    "lalu MIDETA menelusuri posting publik secara bertahap dan mengunduh URL yang tanggalnya masuk rentang."
)
st.warning(
    "Hanya posting yang tersedia secara publik yang dapat ditemukan. Profil privat, posting terhapus, pembatasan "
    "TikTok, atau perubahan struktur sumber publik dapat membuat hasil tidak lengkap; MIDETA tidak melewati kontrol akses."
)

st.markdown('<div class="section-label">LANGKAH 1 · PROFIL DAN RENTANG</div>', unsafe_allow_html=True)
with st.form("profile_scraping_form"):
    profile_value = st.text_input(
        "Profil TikTok",
        placeholder="https://www.tiktok.com/@username atau @username",
        help="Masukkan satu URL profil/username, bukan URL video atau foto.",
    )
    default_start, default_end = default_range()
    date_columns = st.columns(2)
    start_date = date_columns[0].date_input(
        "Tanggal awal",
        value=default_start,
        format="DD/MM/YYYY",
    )
    end_date = date_columns[1].date_input(
        "Tanggal akhir",
        value=default_end,
        format="DD/MM/YYYY",
    )
    submitted = st.form_submit_button(
        "Mulai Profile Scraping",
        type="primary",
        icon=":material/manage_search:",
        width="stretch",
    )

if submitted:
    if start_date > end_date:
        st.error("Tanggal awal tidak boleh melewati tanggal akhir.")
    else:
        try:
            username = parse_tiktok_profile(profile_value)
        except TikTokProfileScrapeError as exc:
            st.error(str(exc))
        else:
            st.session_state.pop("profile_scraping_result", None)
            progress = st.progress(0.01, text="Menyiapkan penelusuran profil publik…")

            def update_progress(state: dict) -> None:
                oldest = state.get("oldest_date")
                progress.progress(
                    date_progress(start_date, end_date, oldest),
                    text=(
                        f"{state['posts_scanned']:,} posting diperiksa · "
                        f"{state['matched']:,} URL dalam rentang · "
                        f"{state['pages_scanned']:,} halaman"
                    ),
                )

            try:
                result = profile_collector().collect(
                    username,
                    start_date,
                    end_date,
                    progress_callback=update_progress,
                )
            except TikTokProfileScrapeError as exc:
                progress.empty()
                st.error(str(exc))
            else:
                progress.progress(
                    1.0,
                    text=f"Selesai: {len(result.rows):,} URL posting ditemukan",
                )
                st.session_state["profile_scraping_result"] = result
                st.session_state["profile_scraping_range"] = (start_date, end_date)


result: TikTokProfileScrapeResult | None = st.session_state.get("profile_scraping_result")
if result is not None:
    selected_range = st.session_state.get("profile_scraping_range", (None, None))
    st.markdown('<div class="section-label">LANGKAH 2 · HASIL</div>', unsafe_allow_html=True)
    metrics = st.columns(4)
    metrics[0].metric("URL ditemukan", len(result.rows))
    metrics[1].metric("Posting diperiksa", result.posts_scanned)
    metrics[2].metric("Halaman", result.pages_scanned)
    metrics[3].metric("Status", "Lengkap" if result.complete else "Periksa")

    st.caption(
        f"Profil: {canonical_profile_url(result.username)} · Rentang: "
        f"{selected_range[0]} sampai {selected_range[1]} · Batas aman: {MAX_PROFILE_POSTS:,} posting."
    )
    if result.warning:
        st.warning(result.warning)
    if (
        result.complete
        and result.oldest_matching_date
        and result.newest_before_start_date
        and result.oldest_matching_date > selected_range[0]
    ):
        st.info(
            "Cakupan timeline publik: posting terakhir di dalam rentang adalah "
            f"{result.oldest_matching_date}; posting publik berikutnya yang tersedia adalah "
            f"{result.newest_before_start_date}. Tidak ditemukan posting publik di antara kedua tanggal tersebut."
        )
    if not result.complete:
        st.warning(
            "Sumber publik berhenti sebelum MIDETA memastikan seluruh rentang telah dilewati. URL yang sudah ditemukan "
            "tetap dapat diunduh, tetapi hasil perlu dianggap parsial."
        )

    if result.rows:
        copy_urls = "\n".join(str(row["URL"]) for row in result.rows)
        st.text_area(
            "URL posting siap disalin",
            value=copy_urls,
            height=220,
            help="Satu URL per baris, diurutkan dari posting terbaru ke terlama.",
        )
        st.dataframe(
            pd.DataFrame(result.rows),
            hide_index=True,
            width="stretch",
            column_order=("No", "Date Publish", "Author", "Post Type", "Caption", "URL"),
        )
        file_stub = f"mideta_tiktok_{result.username}_{selected_range[0]}_{selected_range[1]}"
        csv_col, xlsx_col = st.columns(2)
        csv_col.download_button(
            "Unduh CSV",
            to_csv_bytes(result.rows),
            f"{file_stub}.csv",
            "text/csv",
            icon=":material/download:",
            width="stretch",
        )
        xlsx_col.download_button(
            "Unduh XLSX",
            to_xlsx_bytes(result.rows, "TikTok Profile"),
            f"{file_stub}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            width="stretch",
        )
    else:
        st.info("Tidak ada posting publik yang tanggalnya masuk rentang tersebut.")

render_footer()
