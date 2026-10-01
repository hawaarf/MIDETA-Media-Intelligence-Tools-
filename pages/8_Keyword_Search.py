# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""MIDETA keyword discovery for public TikTok and Threads posts."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.config import MAX_KEYWORD_RESULTS, MIDETA_LOGO_PATH
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.keyword_search import (
    KeywordSearchCollector,
    KeywordSearchError,
    KeywordSearchResult,
    ThreadsKeywordBrowserCollector,
    TikTokKeywordBrowserCollector,
)
from src.comment_browser import CommentBrowserError
from src.tiktok_browser import TikTokBrowserError
from src.ui import apply_theme, page_intro, render_footer, render_github_profile


RESULT_COLUMNS = (
    "No",
    "Platform",
    "Date Publish",
    "Author",
    "Content",
    "URL",
    "Views",
    "Likes",
    "Comments",
    "Shares",
    "Reposts",
    "Matched Keyword",
    "Search Type",
    "Status",
    "Waktu Pengambilan",
)


@st.cache_resource
def tiktok_search_browser() -> TikTokKeywordBrowserCollector:
    return TikTokKeywordBrowserCollector(wait_seconds=20)


@st.cache_resource
def threads_search_browser() -> ThreadsKeywordBrowserCollector:
    return ThreadsKeywordBrowserCollector(wait_seconds=20)


def keyword_collector(
    *,
    use_tiktok_session: bool = False,
    use_threads_session: bool = False,
) -> KeywordSearchCollector:
    # Recreate the lightweight collector so Streamlit hot reload immediately
    # uses parser and public-source fixes from the current local source.
    browser_searcher = tiktok_search_browser().search if use_tiktok_session else None
    threads_searcher = threads_search_browser().search if use_threads_session else None
    return KeywordSearchCollector(
        tiktok_browser_searcher=browser_searcher,
        threads_browser_searcher=threads_searcher,
    )


def integer_value(value) -> int:
    return value if isinstance(value, int) else 0


st.set_page_config(
    page_title="Keyword Search | MIDETA",
    page_icon=str(MIDETA_LOGO_PATH),
    layout="wide",
)
apply_theme()
render_github_profile()
page_intro(
    "08",
    "Keyword Search",
    "Temukan posting publik TikTok dan Threads berdasarkan keyword, Boolean, dan rentang tanggal.",
)

st.info(
    "MIDETA mengirim setiap keyword positif ke pencarian publik TikTok dan Threads secara paralel, "
    "lalu menerapkan AND, OR, NOT, rentang tanggal, serta deduplikasi secara lokal. Tidak perlu Apify. "
    "Hasil publik dicoba langsung; sesi Chrome tersimpan dapat dipakai bila platform menahan daftar hasil."
)
st.warning(
    "Cakupannya berbeda dari Meltwater: halaman publik platform hanya memberikan sampel hasil dan dapat membatasi "
    "jumlah, tanggal, atau metadata. Gunakan fitur ini untuk discovery, lalu verifikasi hasil penting sebelum laporan final."
)

st.markdown('<div class="section-label">SESI PLATFORM · OPSIONAL</div>', unsafe_allow_html=True)
st.caption(
    "TikTok dan Threads dapat mengirim halaman search tanpa daftar posting kepada request publik. Login satu kali "
    "di Chrome khusus platform agar MIDETA dapat membaca kartu hasil yang memang ditampilkan kepada akun Anda. "
    "Password tetap diketik langsung di situs TikTok/Threads dan tidak dibaca MIDETA."
)
session_panels = st.columns(2)
with session_panels[0].container(border=True):
    st.markdown("#### TikTok")
    session_columns = st.columns(3)
    if session_columns[0].button("Buka Sesi TikTok", key="open_keyword_tiktok", width="stretch"):
        try:
            tiktok_search_browser().open_login()
        except TikTokBrowserError as exc:
            st.error(str(exc))
        else:
            st.session_state["keyword_tiktok_logged_in"] = False
            st.info("Selesaikan login TikTok, lalu klik Periksa.")
    if session_columns[1].button("Periksa TikTok", key="check_keyword_tiktok", width="stretch"):
        try:
            logged_in = tiktok_search_browser().is_logged_in()
        except TikTokBrowserError as exc:
            logged_in = False
            st.error(str(exc))
        st.session_state["keyword_tiktok_logged_in"] = logged_in
    if session_columns[2].button("Tutup TikTok", key="close_keyword_tiktok", width="stretch"):
        tiktok_search_browser().close()
        st.session_state["keyword_tiktok_logged_in"] = False
    st.caption(
        "Sesi aktif; hasil dibaca dari Chrome MIDETA."
        if st.session_state.get("keyword_tiktok_logged_in")
        else "Belum aktif; aktifkan bila TikTok tidak memberi hasil publik."
    )

with session_panels[1].container(border=True):
    st.markdown("#### Threads")
    session_columns = st.columns(3)
    if session_columns[0].button("Buka Sesi Threads", key="open_keyword_threads", width="stretch"):
        try:
            logged_in = threads_search_browser().open_login()
        except CommentBrowserError as exc:
            logged_in = False
            st.error(str(exc))
        st.session_state["keyword_threads_logged_in"] = logged_in
        if not logged_in:
            st.info("Selesaikan login Threads, lalu klik Periksa.")
    if session_columns[1].button("Periksa Threads", key="check_keyword_threads", width="stretch"):
        try:
            logged_in = threads_search_browser().is_logged_in()
        except CommentBrowserError as exc:
            logged_in = False
            st.error(str(exc))
        st.session_state["keyword_threads_logged_in"] = logged_in
    if session_columns[2].button("Tutup Threads", key="close_keyword_threads", width="stretch"):
        threads_search_browser().close()
        st.session_state["keyword_threads_logged_in"] = False
    st.caption(
        "Sesi aktif; hasil dibaca dari Chrome MIDETA."
        if st.session_state.get("keyword_threads_logged_in")
        else "Belum aktif; pencarian publik tetap dicoba lebih dulu."
    )

st.markdown('<div class="section-label">LANGKAH 1 · SUSUN PENCARIAN</div>', unsafe_allow_html=True)
with st.form("keyword_search_form"):
    query_value = st.text_area(
        "Keyword atau query Boolean",
        placeholder='("ojol" OR "ojek online" OR gojek) NOT (promo OR voucher)',
        height=130,
        help=(
            "Gunakan AND untuk mewajibkan dua istilah, OR untuk salah satu, NOT untuk mengecualikan, "
            "tanda kutip untuk frasa, dan kurung untuk pengelompokan. Teks biasa dianggap satu frasa."
        ),
    )
    first, second = st.columns(2)
    platforms = first.multiselect(
        "Platform",
        ["TikTok", "Threads"],
        default=["TikTok", "Threads"],
        help="Versi awal diprioritaskan untuk TikTok dan Threads.",
    )
    search_mode = second.selectbox(
        "Tipe hasil Threads",
        ["Top + Recent", "Terbaru", "Teratas"],
        help="TikTok tetap memakai hasil video publik; pilihan ini hanya mengatur Threads.",
    )

    today = date.today()
    date_columns = st.columns(2)
    start_date = date_columns[0].date_input(
        "Tanggal awal",
        value=today - timedelta(days=30),
        format="DD/MM/YYYY",
    )
    end_date = date_columns[1].date_input(
        "Tanggal akhir",
        value=today,
        format="DD/MM/YYYY",
    )
    max_results = st.number_input(
        "Maksimal hasil",
        min_value=20,
        max_value=MAX_KEYWORD_RESULTS,
        value=200,
        step=20,
        help="Batas output, bukan jaminan jumlah hasil dari platform.",
    )
    submitted = st.form_submit_button(
        "Cari Mention",
        type="primary",
        icon=":material/search:",
        width="stretch",
    )

if submitted:
    st.session_state.pop("keyword_search_result", None)
    progress = st.progress(0.01, text="Menyiapkan pencarian publik…")

    def update_progress(state: dict[str, int]) -> None:
        total = max(state["total"], 1)
        progress.progress(
            min(state["completed"] / total, 0.98),
            text=(
                f"{state['completed']} dari {state['total']} pencarian selesai · "
                f"{state['discovered']:,} posting cocok ditemukan"
            ),
        )

    try:
        use_tiktok_session = bool(
            "TikTok" in platforms and st.session_state.get("keyword_tiktok_logged_in")
        )
        use_threads_session = bool(
            "Threads" in platforms and st.session_state.get("keyword_threads_logged_in")
        )
        result = keyword_collector(
            use_tiktok_session=use_tiktok_session,
            use_threads_session=use_threads_session,
        ).collect(
            query_value,
            platforms,
            start_date,
            end_date,
            search_mode=search_mode,
            max_results=int(max_results),
            progress_callback=update_progress,
        )
    except KeywordSearchError as exc:
        progress.empty()
        st.error(str(exc))
    else:
        progress.progress(1.0, text=f"Selesai: {len(result.rows):,} mention unik ditemukan")
        st.session_state["keyword_search_result"] = result
        st.session_state["keyword_search_range"] = (start_date, end_date)


result: KeywordSearchResult | None = st.session_state.get("keyword_search_result")
if result is not None:
    st.markdown('<div class="section-label">LANGKAH 2 · HASIL DISCOVERY</div>', unsafe_allow_html=True)
    frame = pd.DataFrame(result.rows)
    total_engagement = sum(
        integer_value(row.get(field))
        for row in result.rows
        for field in ("Likes", "Comments", "Shares", "Reposts")
    )
    metric_columns = st.columns(5)
    metric_columns[0].metric("Total mention", len(result.rows))
    metric_columns[1].metric(
        "TikTok",
        sum(row.get("Platform") == "TikTok" for row in result.rows),
    )
    metric_columns[2].metric(
        "Threads",
        sum(row.get("Platform") == "Threads" for row in result.rows),
    )
    metric_columns[3].metric(
        "Author unik",
        len({str(row.get("Author")) for row in result.rows if row.get("Author")}),
    )
    metric_columns[4].metric("Engagement terbaca", f"{total_engagement:,}")

    selected_range = st.session_state.get("keyword_search_range", (None, None))
    st.caption(
        f'Query: {result.query} · Rentang: {selected_range[0]} sampai {selected_range[1]} · '
        f"{result.requests_made} permintaan publik, {result.request_failures} gagal."
    )
    if result.warning:
        st.warning(result.warning)

    if result.rows:
        chart_frame = frame[frame["Date Publish"] != "Cek"].copy()
        if not chart_frame.empty:
            chart_frame["Date Publish"] = pd.to_datetime(chart_frame["Date Publish"])
            trend = (
                chart_frame.groupby(["Date Publish", "Platform"])
                .size()
                .unstack(fill_value=0)
                .sort_index()
            )
            st.markdown("#### Tren mention yang ditemukan")
            st.line_chart(trend, x_label="Tanggal", y_label="Mention")

        st.dataframe(
            frame,
            hide_index=True,
            width="stretch",
            column_order=RESULT_COLUMNS,
            column_config={
                "URL": st.column_config.LinkColumn("URL"),
                "Content": st.column_config.TextColumn("Content", width="large"),
            },
        )
        st.text_area(
            "URL hasil siap disalin",
            value="\n".join(str(row["URL"]) for row in result.rows),
            height=180,
        )
        file_stub = f"mideta_keyword_search_{selected_range[0]}_{selected_range[1]}"
        csv_column, xlsx_column = st.columns(2)
        csv_column.download_button(
            "Unduh CSV",
            to_csv_bytes(result.rows),
            f"{file_stub}.csv",
            "text/csv",
            icon=":material/download:",
            width="stretch",
        )
        xlsx_column.download_button(
            "Unduh XLSX",
            to_xlsx_bytes(result.rows, "Keyword Search"),
            f"{file_stub}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
            width="stretch",
        )
    else:
        st.info(
            "Belum ada hasil publik yang cocok. Coba perlebar rentang tanggal, sederhanakan query, "
            "atau jalankan ulang ketika platform tidak sedang membatasi pencarian."
        )

render_footer()
