# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""MIDETA Conventional Media Enrichment page."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from collections import deque
import re
import time
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from src.batch import batch_progress_fraction, parse_url_list
from src.config import MAX_PARALLEL_ARTICLES, MIDETA_LOGO_PATH
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


def fair_article_indices(urls: list[str]) -> list[int]:
    """Interleave publishers so one repeated domain cannot occupy every worker."""
    by_host: dict[str, deque[int]] = {}
    for index, url in enumerate(urls):
        host = (urlparse(url).hostname or url).casefold().removeprefix("www.")
        by_host.setdefault(host, deque()).append(index)
    ordered: list[int] = []
    while by_host:
        for host in list(by_host):
            ordered.append(by_host[host].popleft())
            if not by_host[host]:
                del by_host[host]
    return ordered


AUTOMATIC_BROWSER_RETRY_RE = re.compile(
    r"(?:akses ditolak|http\s+403\b|cloudflare|security check|"
    r"request is being verified|enable javascript|javascript diperlukan)",
    re.I,
)


def browser_retry_needed(result: ArticleResult, *, browser_ready: bool) -> bool:
    """Retry public browser challenges automatically; reuse an open session for other failures."""
    if result.status != "failed":
        return False
    if browser_ready:
        return True
    return bool(AUTOMATIC_BROWSER_RETRY_RE.search(result.reason or ""))


def process_articles(urls: list[str]) -> list[ArticleResult]:
    """Process public pages concurrently, then retry blocked pages in Chrome.

    The main thread polls workers instead of blocking in ``as_completed`` so
    Streamlit can keep showing a heartbeat while a publisher is slow, retrying,
    or waiting for its per-domain request slot.
    """
    results: list[ArticleResult | None] = [None] * len(urls)
    retry_in_browser: list[int] = []
    final_completed = 0
    public_completed = 0
    succeeded = 0
    failed = 0
    total = len(urls)
    progress = st.progress(0.0, text=f"Fase 1/2 · Menyiapkan {total:,} artikel · 0%")
    activity = st.empty()
    browser_ready = article_browser().is_running()

    def hostname(index: int) -> str:
        return (urlparse(urls[index]).hostname or urls[index]).removeprefix("www.")

    def result_from_exception(index: int, exc: BaseException) -> ArticleResult:
        return ArticleResult(
            source_url=urls[index],
            title=CHECK_FAILED_TO_PROCESS,
            content=CHECK_FAILED_TO_PROCESS,
            status="failed",
            reason=f"Worker artikel berhenti: {exc}",
        )

    def public_progress(active_fraction: float, *, waiting_seconds: int = 0) -> None:
        # Reserve the last 15% for an optional Chrome fallback. If it is not
        # needed the bar advances directly from 85% to completion.
        phase_fraction = batch_progress_fraction(public_completed, total, active_fraction)
        overall_fraction = phase_fraction * 0.85
        percent = round(overall_fraction * 100)
        pending_count = max(total - public_completed, 0)
        wait_detail = f" · menunggu {waiting_seconds:,} dtk" if waiting_seconds else ""
        progress.progress(
            overall_fraction,
            text=(
                f"Fase 1/2 · Web publik {public_completed:,}/{total:,} diperiksa · "
                f"{pending_count:,} tersisa · {percent}%{wait_detail}"
            ),
        )

    workers = min(MAX_PARALLEL_ARTICLES, max(1, len(urls)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mideta-article") as executor:
        futures = {
            executor.submit(enrich_public_article, urls[index]): index
            for index in fair_article_indices(urls)
        }
        pending = set(futures)
        heartbeat_started = time.monotonic()
        while pending:
            done, pending = wait(pending, timeout=0.4, return_when=FIRST_COMPLETED)
            if not done:
                elapsed = max(time.monotonic() - heartbeat_started, 0.0)
                heartbeat = min(0.9, 0.04 + (elapsed / (elapsed + 10.0)) * 0.86)
                public_progress(heartbeat, waiting_seconds=int(elapsed))
                queued_domains = sorted({hostname(futures[item]) for item in pending})
                sample = ", ".join(queued_domains[:3])
                if len(queued_domains) > 3:
                    sample += f", +{len(queued_domains) - 3} domain"
                message = (
                    f"Sedang menunggu respons media: {sample}. "
                    f"{len(pending):,} artikel masih aktif atau mengantre."
                )
                if elapsed >= 20:
                    message += " MIDETA tetap berjalan; situs yang lambat akan berhenti sesuai batas waktunya."
                activity.info(message)
                continue

            heartbeat_started = time.monotonic()
            for future in done:
                index = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # One changed publisher must not abort the batch.
                    result = result_from_exception(index, exc)
                public_completed += 1
                if browser_retry_needed(result, browser_ready=browser_ready):
                    retry_in_browser.append(index)
                else:
                    results[index] = result
                    final_completed += 1
                    if result.status == "completed":
                        succeeded += 1
                    else:
                        failed += 1
                public_progress(0.0)
                activity.info(
                    f"Terakhir diperiksa: {hostname(index)} · "
                    f"{succeeded:,} berhasil · {failed:,} perlu diperiksa · "
                    f"{len(retry_in_browser):,} menunggu Chrome"
                )

    if retry_in_browser:
        browser = article_browser()
        browser_total = len(retry_in_browser)
        # Keep Selenium work serial, but run it away from the UI thread so the
        # progress heartbeat remains visible during navigation and page waits.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="mideta-article-browser") as executor:
            for position, index in enumerate(retry_in_browser):
                future = executor.submit(browser.collect, urls[index])
                heartbeat_started = time.monotonic()
                while True:
                    done, _ = wait({future}, timeout=0.4, return_when=FIRST_COMPLETED)
                    elapsed = max(time.monotonic() - heartbeat_started, 0.0)
                    heartbeat = min(0.9, 0.04 + (elapsed / (elapsed + 10.0)) * 0.86)
                    phase_fraction = batch_progress_fraction(position, browser_total, heartbeat)
                    overall_fraction = 0.85 + (phase_fraction * 0.15)
                    percent = round(overall_fraction * 100)
                    progress.progress(
                        overall_fraction,
                        text=(
                            f"Fase 2/2 · Chrome {position + 1:,}/{browser_total:,} · "
                            f"{hostname(index)} · {percent}% · menunggu {int(elapsed):,} dtk"
                        ),
                    )
                    activity.info(
                        f"Membuka artikel lewat Chrome fallback: {urls[index]} · "
                        f"{final_completed:,}/{total:,} hasil final sudah siap"
                    )
                    if done:
                        break
                try:
                    result = future.result()
                except Exception as exc:
                    result = result_from_exception(index, exc)
                results[index] = result
                final_completed += 1
                if result.status == "completed":
                    succeeded += 1
                else:
                    failed += 1

    progress.progress(
        1.0,
        text=(
            f"Selesai · {total:,}/{total:,} artikel · 100% · "
            f"{succeeded:,} berhasil · {failed:,} perlu diperiksa"
        ),
    )
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
    "password tidak dibaca MIDETA. Jika semua artikel publik, bagian ini boleh dilewati; halaman publik yang "
    "menolak request biasa akan dicoba otomatis lewat Chrome fallback."
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
    help="Satu link per baris. Jumlah link tidak dibatasi oleh MIDETA; link berulang tetap dipertahankan sebagai baris terpisah.",
)
st.caption(
    "MIDETA membersihkan iklan, menu, rekomendasi, dan elemen halaman lain dari isi artikel. "
    "Media scope dan tier ditentukan dari domain media; tone, quote mention, dan jenis penyebutan "
    "direct/indirect dibaca dari keseluruhan artikel."
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
