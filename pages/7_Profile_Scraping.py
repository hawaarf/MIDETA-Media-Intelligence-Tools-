# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""MIDETA multi-account TikTok profile scraper with optional enrichment."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from src.batch import compact_social_export_row, social_result_row
from src.config import MAX_PROFILE_POSTS, MIDETA_LOGO_PATH
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.profile_enrichment import enrich_profile_rows
from src.tiktok_free import TikTokFreeCollector, TikTokFreeError
from src.tiktok_profile import (
    PROFILE_TIMELINE_OPTIONS,
    TikTokProfileCollector,
    TikTokProfileScrapeError,
    TikTokProfileScrapeResult,
    canonical_profile_url,
    parse_tiktok_profile_inputs,
    profile_timeline_range,
)
from src.ui import apply_theme, page_intro, render_footer, render_github_profile, status_label


RESULT_COLUMNS_PER_ROW = 3


def profile_collector() -> TikTokProfileCollector:
    # Recreate the lightweight object so hot-reloaded scraper fixes apply now.
    return TikTokProfileCollector()


def enrichment_collector() -> TikTokFreeCollector:
    return TikTokFreeCollector()


def default_custom_range() -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=29), today


def date_progress(start_date: date, end_date: date, oldest_date: date | None) -> float:
    if oldest_date is None:
        return 0.02
    total_days = max((end_date - start_date).days, 1)
    covered_days = (end_date - min(max(oldest_date, start_date), end_date)).days
    return min(max(covered_days / total_days, 0.02), 0.98)


def _render_apify_settings() -> None:
    collector = enrichment_collector()
    if collector.has_token():
        st.success("Token Apify sudah tersimpan. Enrichment akan memakainya untuk melengkapi data bila tersedia.")
    else:
        st.info("Token Apify opsional. Tanpa token, enrichment tetap mencoba metadata dan engagement publik TikTok.")
    token = st.text_input(
        "Apify API token",
        type="password",
        placeholder="Tempel token baru lalu simpan",
        help="Token disimpan lokal di folder privat MIDETA dan tidak masuk ke file hasil.",
        key="profile_scraping_apify_token",
    )
    save_col, delete_col, account_col = st.columns(3)
    if save_col.button(
        "Simpan token",
        key="profile_scraping_save_apify",
        disabled=not token.strip(),
        width="stretch",
    ):
        try:
            collector.save_token(token)
        except TikTokFreeError as exc:
            st.error(str(exc))
        else:
            st.success("Token Apify tersimpan.")
            st.rerun()
    if delete_col.button(
        "Hapus token",
        key="profile_scraping_delete_apify",
        disabled=not collector.has_token(),
        width="stretch",
    ):
        try:
            collector.delete_token()
        except TikTokFreeError as exc:
            st.error(str(exc))
        else:
            st.info("Token Apify sudah dihapus.")
            st.rerun()
    account_col.link_button(
        "Buat akun gratis",
        "https://console.apify.com/sign-up",
        width="stretch",
    )


def _run_profiles(
    usernames: list[str],
    start_date: date,
    end_date: date,
    *,
    enrich_posts: bool,
) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    total_accounts = len(usernames)
    progress = st.progress(0.01, text=f"Menyiapkan {total_accounts:,} akun TikTok · 1%")
    active_enrichment_collector = enrichment_collector() if enrich_posts else None

    for account_index, username in enumerate(usernames):
        discovery_weight = 0.35 if enrich_posts else 1.0

        def update_discovery(state: dict, *, current=username, index=account_index) -> None:
            profile_fraction = date_progress(start_date, end_date, state.get("oldest_date"))
            overall = (index + (discovery_weight * profile_fraction)) / total_accounts
            progress.progress(
                min(max(overall, 0.01), 0.99),
                text=(
                    f"@{current} · mencari posting · {state['posts_scanned']:,} diperiksa · "
                    f"{state['matched']:,} cocok · {round(overall * 100)}% total"
                ),
            )

        try:
            result = profile_collector().collect(
                username,
                start_date,
                end_date,
                progress_callback=update_discovery,
            )
        except TikTokProfileScrapeError as exc:
            outputs.append(
                {
                    "username": username,
                    "result": None,
                    "enriched_results": [],
                    "export_rows": [],
                    "error": str(exc),
                    "enriched": enrich_posts,
                }
            )
            overall = (account_index + 1) / total_accounts
            progress.progress(overall, text=f"@{username} gagal dibaca · lanjut ke akun berikutnya · {round(overall * 100)}%")
            continue

        enriched_results = []
        export_rows: list[dict[str, Any]] = []
        if enrich_posts and result.rows:
            discovery_done = (account_index + discovery_weight) / total_accounts
            progress.progress(
                discovery_done,
                text=f"@{username} · {len(result.rows):,} posting ditemukan · mulai enrichment",
            )

            def update_enrichment(state: dict, *, current=username, index=account_index) -> None:
                item_fraction = state["processed"] / max(state["total"], 1)
                overall = (
                    index
                    + discovery_weight
                    + ((1.0 - discovery_weight) * item_fraction)
                ) / total_accounts
                progress.progress(
                    min(max(overall, 0.01), 0.99),
                    text=(
                        f"@{current} · enrichment {state['processed']:,}/{state['total']:,} posting · "
                        f"{round(overall * 100)}% total"
                    ),
                )

            enriched_results = enrich_profile_rows(
                result.rows,
                collector=active_enrichment_collector,
                progress_callback=update_enrichment,
            )
            export_rows = [compact_social_export_row(item) for item in enriched_results]
        elif not enrich_posts:
            export_rows = list(result.rows)

        outputs.append(
            {
                "username": username,
                "result": result,
                "enriched_results": enriched_results,
                "export_rows": export_rows,
                "error": "",
                "enriched": enrich_posts,
            }
        )
        overall = (account_index + 1) / total_accounts
        progress.progress(
            overall,
            text=f"@{username} selesai · {account_index + 1:,}/{total_accounts:,} akun · {round(overall * 100)}%",
        )

    progress.progress(1.0, text=f"Profile Scraping selesai · {total_accounts:,} akun · 100%")
    return outputs


def _result_status_rows(enriched_results: list) -> list[dict[str, Any]]:
    rows = [social_result_row(result) for result in enriched_results]
    for row in rows:
        for key in list(row):
            if key.startswith("Status "):
                row[key] = status_label(row[key])
    return rows


def _render_account_panel(
    output: dict[str, Any],
    *,
    start_date: date,
    end_date: date,
) -> None:
    username = output["username"]
    st.markdown(f"### @{username}")
    st.caption(f"{canonical_profile_url(username)} · {start_date} sampai {end_date}")
    if output["error"]:
        st.error(output["error"])
        return

    result: TikTokProfileScrapeResult = output["result"]
    metrics = st.columns(2)
    metrics[0].metric("Posting", len(result.rows))
    metrics[1].metric("Status", "Lengkap" if result.complete else "Periksa")
    st.caption(
        f"{result.posts_scanned:,} posting diperiksa · {result.pages_scanned:,} halaman · "
        f"batas aman {MAX_PROFILE_POSTS:,} posting"
    )
    if result.warning:
        st.warning(result.warning)
    if not result.complete:
        st.warning("Timeline publik terputus sebelum seluruh rentang dipastikan selesai; hasil akun ini bersifat parsial.")
    if not result.rows:
        st.info("Tidak ada posting publik yang tanggalnya masuk rentang ini.")
        return

    urls = "\n".join(str(row["URL"]) for row in result.rows)
    with st.expander("URL posting siap disalin"):
        st.text_area(
            f"URL @{username}",
            value=urls,
            height=180,
            key=f"profile_urls_{username}_{start_date}_{end_date}",
            label_visibility="collapsed",
        )

    export_rows = output["export_rows"]
    if output["enriched"]:
        st.caption("Format hasil sama dengan TikTok Enrichment.")
        st.dataframe(
            pd.DataFrame(export_rows).astype(str),
            hide_index=True,
            width="stretch",
            height=360,
        )
        status_rows = _result_status_rows(output["enriched_results"])
        if status_rows:
            with st.expander("Lihat status setiap data"):
                detail = pd.DataFrame(status_rows)
                status_columns = ["Platform", "URL"] + [
                    column for column in detail.columns if column.startswith("Status ")
                ] + ["Catatan"]
                st.dataframe(
                    detail.reindex(columns=status_columns).fillna("Tidak tersedia"),
                    hide_index=True,
                    width="stretch",
                )
    else:
        st.dataframe(
            pd.DataFrame(export_rows),
            hide_index=True,
            width="stretch",
            height=360,
            column_order=("No", "Date Publish", "Author", "Post Type", "Caption", "URL"),
        )

    mode = "enriched" if output["enriched"] else "urls"
    file_stub = f"mideta_tiktok_profile_{username}_{start_date}_{end_date}_{mode}"
    download_columns = st.columns(2)
    download_columns[0].download_button(
        "CSV",
        to_csv_bytes(export_rows),
        f"{file_stub}.csv",
        "text/csv",
        key=f"profile_csv_{username}_{mode}_{start_date}_{end_date}",
        icon=":material/download:",
        width="stretch",
    )
    download_columns[1].download_button(
        "XLSX",
        to_xlsx_bytes(export_rows, f"TikTok {username}"),
        f"{file_stub}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"profile_xlsx_{username}_{mode}_{start_date}_{end_date}",
        icon=":material/download:",
        width="stretch",
    )


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
    "Ambil posting publik dari banyak profil TikTok, lalu enrich hasilnya bila diperlukan.",
)

st.info(
    "Masukkan username, @username, atau URL profil TikTok—satu per baris. Pilih timeline 7/30/365 hari atau custom. "
    "Setiap akun diproses dan ditampilkan pada panel terpisah."
)
st.warning(
    "Hanya posting publik yang dapat ditemukan. Profil privat, posting terhapus, pembatasan TikTok, atau perubahan "
    "struktur sumber publik dapat membuat hasil parsial; MIDETA tidak melewati kontrol akses."
)

with st.expander("Pengaturan opsional TikTok Enrichment"):
    _render_apify_settings()

st.markdown('<div class="section-label">LANGKAH 1 · AKUN, TIMELINE, DAN MODE</div>', unsafe_allow_html=True)
timeline_option = st.segmented_control(
    "Timeline posting",
    PROFILE_TIMELINE_OPTIONS,
    default="Seminggu terakhir",
    key="profile_scraping_timeline",
    width="stretch",
) or "Seminggu terakhir"

custom_start, custom_end = default_custom_range()
if timeline_option == "Custom timeline":
    date_columns = st.columns(2)
    selected_custom_start = date_columns[0].date_input(
        "Tanggal awal",
        value=custom_start,
        format="DD/MM/YYYY",
        key="profile_custom_start",
    )
    selected_custom_end = date_columns[1].date_input(
        "Tanggal akhir",
        value=custom_end,
        format="DD/MM/YYYY",
        key="profile_custom_end",
    )
else:
    selected_custom_start = None
    selected_custom_end = None
    preview_start, preview_end = profile_timeline_range(timeline_option)
    st.caption(f"Rentang aktif: **{preview_start} sampai {preview_end}** (inklusif).")

with st.form("profile_scraping_form"):
    profile_values = st.text_area(
        "Username atau link profil TikTok",
        placeholder="@akunpertama\nakunkedua\nhttps://www.tiktok.com/@akunketiga",
        height=180,
        help="Satu akun per baris. Username biasa, @username, dan URL profil dapat dicampur.",
        key="profile_scraping_accounts",
    )
    enrich_posts = st.checkbox(
        "Langsung enrichment semua posting yang ditemukan",
        value=False,
        help="Menghasilkan kolom Platform, URL, tanggal, author, caption, followers, views, likes, comments, save, shares, dan repost seperti TikTok Enrichment.",
        key="profile_scraping_enrich_posts",
    )
    submitted = st.form_submit_button(
        "Mulai Profile Scraping",
        type="primary",
        icon=":material/manage_search:",
        width="stretch",
    )

if submitted:
    usernames, input_errors = parse_tiktok_profile_inputs(profile_values)
    if not usernames:
        if len(input_errors) == 1:
            st.error(f"{input_errors[0]['Input']}: {input_errors[0]['Alasan']}")
        else:
            st.error("Masukkan setidaknya satu username atau URL profil TikTok yang valid.")
        st.session_state["profile_scraping_input_errors"] = input_errors
    else:
        try:
            start_date, end_date = profile_timeline_range(
                timeline_option,
                custom_start=selected_custom_start,
                custom_end=selected_custom_end,
            )
        except TikTokProfileScrapeError as exc:
            st.error(str(exc))
        else:
            st.session_state.pop("profile_scraping_outputs", None)
            st.session_state["profile_scraping_input_errors"] = input_errors
            st.session_state["profile_scraping_outputs"] = _run_profiles(
                usernames,
                start_date,
                end_date,
                enrich_posts=enrich_posts,
            )
            st.session_state["profile_scraping_range"] = (start_date, end_date)
            st.session_state["profile_scraping_enriched"] = enrich_posts

input_errors = st.session_state.get("profile_scraping_input_errors", [])
if input_errors:
    with st.expander(f"{len(input_errors)} input tidak valid", expanded=True):
        st.dataframe(pd.DataFrame(input_errors), hide_index=True, width="stretch")

outputs: list[dict[str, Any]] = st.session_state.get("profile_scraping_outputs", [])
if outputs:
    start_date, end_date = st.session_state["profile_scraping_range"]
    st.markdown('<div class="section-label">LANGKAH 2 · HASIL PER AKUN</div>', unsafe_allow_html=True)
    total_posts = sum(len(output["result"].rows) for output in outputs if output["result"] is not None)
    failed_accounts = sum(bool(output["error"]) for output in outputs)
    summary = st.columns(4)
    summary[0].metric("Akun", len(outputs))
    summary[1].metric("Posting", total_posts)
    summary[2].metric("Akun gagal", failed_accounts)
    summary[3].metric("Mode", "Enrichment" if st.session_state.get("profile_scraping_enriched") else "URL saja")
    st.caption("Setiap akun berada di panel terpisah; maksimal tiga panel ditampilkan per baris.")

    for offset in range(0, len(outputs), RESULT_COLUMNS_PER_ROW):
        group = outputs[offset : offset + RESULT_COLUMNS_PER_ROW]
        columns = st.columns(len(group), gap="large")
        for column, output in zip(columns, group):
            with column:
                with st.container(border=True):
                    _render_account_panel(output, start_date=start_date, end_date=end_date)

render_footer()
