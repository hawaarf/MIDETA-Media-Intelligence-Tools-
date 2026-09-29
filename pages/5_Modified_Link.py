# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""Standalone MIDETA social-link cleaner and share-link resolver."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st

from src.batch import parse_url_list
from src.config import MAX_ENRICHMENT_URLS, MAX_PARALLEL_PUBLIC_URLS, MIDETA_LOGO_PATH
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.social_urls import (
    SocialURLResolutionError,
    canonical_social_url,
    is_short_social_url,
    platform_from_url,
    resolve_social_url,
)
from src.ui import apply_theme, page_intro, render_footer, render_github_profile


FAILED_MODIFICATION = "URL tidak dapat dimodifikasi"


def modify_one_link(position: int, url: str) -> dict[str, str | int]:
    """Resolve one social URL without invoking any enrichment connector."""
    platform = platform_from_url(url)
    if not platform:
        return {
            "No": position,
            "Platform": "Tidak dikenali",
            "Original Link": url,
            "Modified Link": FAILED_MODIFICATION,
            "Status": "Error",
            "Catatan": "URL bukan berasal dari platform sosial media yang didukung MIDETA.",
        }

    try:
        destination = (
            resolve_social_url(url, expected_platform=platform)
            if is_short_social_url(url, platform)
            else url
        )
        modified = (
            None
            if is_short_social_url(destination, platform)
            else canonical_social_url(destination, platform)
        )
    except (SocialURLResolutionError, ValueError) as exc:
        modified = None
        reason = str(exc)
    else:
        reason = ""

    if not modified:
        return {
            "No": position,
            "Platform": platform,
            "Original Link": url,
            "Modified Link": FAILED_MODIFICATION,
            "Status": "Error",
            "Catatan": reason or "Tujuan short/share link belum dapat ditemukan. Coba lagi saat link dapat dibuka.",
        }

    changed = modified.rstrip("/") != url.split("#", 1)[0].rstrip("/")
    return {
        "No": position,
        "Platform": platform,
        "Original Link": url,
        "Modified Link": modified,
        "Status": "Berhasil",
        "Catatan": "Link dibersihkan dan diarahkan ke posting asli." if changed else "Link sudah dalam format posting yang bersih.",
    }


def process_links(urls: list[str]) -> list[dict[str, str | int]]:
    """Process links in parallel and return rows in their pasted order."""
    rows: list[dict[str, str | int] | None] = [None] * len(urls)
    progress = st.progress(0.0, text=f"Menyiapkan {len(urls):,} link…")
    workers = min(MAX_PARALLEL_PUBLIC_URLS, max(1, len(urls)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mideta-modified-link") as executor:
        futures = {
            executor.submit(modify_one_link, position, url): position - 1
            for position, url in enumerate(urls, 1)
        }
        completed = 0
        for future in as_completed(futures):
            rows[futures[future]] = future.result()
            completed += 1
            progress.progress(
                completed / len(urls),
                text=f"{completed:,} dari {len(urls):,} link selesai",
            )
    progress.progress(1.0, text=f"Selesai: {len(urls):,} link sudah diperiksa")
    return [row for row in rows if row is not None]


st.set_page_config(
    page_title="Modified Link | MIDETA",
    page_icon=str(MIDETA_LOGO_PATH),
    layout="wide",
)
apply_theme()
render_github_profile()
page_intro(
    "05",
    "Modified Link",
    "Ubah short link, share link, dan URL bertanda tracking menjadi permalink posting yang bersih.",
)

st.info(
    "Fitur ini berdiri sendiri dan tidak menjalankan Social Media Enrichment. Tempel URL campuran dari "
    "YouTube, TikTok, Facebook, Instagram, Threads, atau X; hasil tetap mengikuti urutan input."
)

st.markdown('<div class="section-label">LANGKAH 1 · DAFTAR LINK</div>', unsafe_allow_html=True)
raw_urls = st.text_area(
    "URL media sosial",
    height=250,
    placeholder=(
        "https://www.threads.com/share/CONTOH/\n"
        "https://vt.tiktok.com/CONTOH/\n"
        "https://www.instagram.com/share/reel/CONTOH/"
    ),
    help=(
        f"Satu URL per baris, maksimal {MAX_ENRICHMENT_URLS:,} URL. URL berulang tetap dipertahankan "
        "sebagai baris terpisah."
    ),
)

if st.button(
    "Buat Modified Link",
    type="primary",
    icon=":material/link:",
    width="stretch",
):
    urls = parse_url_list(raw_urls, preserve_repeated_rows=True)
    if not urls:
        st.error("Masukkan minimal satu URL lengkap yang diawali http:// atau https://.")
    elif len(urls) > MAX_ENRICHMENT_URLS:
        st.error(
            f"Maksimal {MAX_ENRICHMENT_URLS:,} URL per proses. Kurangi "
            f"{len(urls) - MAX_ENRICHMENT_URLS:,} URL lalu coba lagi."
        )
    else:
        st.session_state["modified_link_results"] = process_links(urls)


rows = st.session_state.get("modified_link_results", [])
if rows:
    success_count = sum(row["Status"] == "Berhasil" for row in rows)
    st.markdown('<div class="section-label">LANGKAH 2 · HASIL</div>', unsafe_allow_html=True)
    metrics = st.columns(3)
    metrics[0].metric("Diproses", len(rows))
    metrics[1].metric("Berhasil", success_count)
    metrics[2].metric("Periksa", len(rows) - success_count)

    copy_value = "\n".join(str(row["Modified Link"]) for row in rows)
    st.text_area(
        "Modified Link siap disalin",
        value=copy_value,
        height=190,
        help="Satu hasil per baris dan urutannya sama dengan daftar input.",
    )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    csv_col, xlsx_col = st.columns(2)
    csv_col.download_button(
        "Unduh CSV",
        to_csv_bytes(rows),
        "mideta_modified_link.csv",
        "text/csv",
        icon=":material/download:",
        width="stretch",
    )
    xlsx_col.download_button(
        "Unduh XLSX",
        to_xlsx_bytes(rows, "Modified Link"),
        "mideta_modified_link.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        width="stretch",
    )

render_footer()
