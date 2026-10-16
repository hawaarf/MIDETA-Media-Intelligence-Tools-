# Copyright (c) 2026 Hawarisma Rafanidya Singgih
# SPDX-License-Identifier: MIT

"""MIDETA multi-platform profile follower checker."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import importlib
import time

import pandas as pd
import streamlit as st

from src.batch import batch_progress_fraction, parse_url_list
from src.config import MIDETA_LOGO_PATH
from src.exporters import to_csv_bytes, to_xlsx_bytes
import src.follower_browser as follower_browser_module
from src.ui import apply_theme, page_intro, render_footer, render_github_profile


# Streamlit keeps imported modules in memory during a hot reload. Refresh an
# older follower parser before the page calls methods added by a newer build.
if (
    getattr(follower_browser_module.ProfileFollowersCollector, "RUNTIME_VERSION", 0) < 2
    or not hasattr(follower_browser_module.ProfileFollowersCollector, "platform_from_url")
    or not hasattr(follower_browser_module.ProfileFollowersCollector, "account_name_from_url")
):
    follower_browser_module = importlib.reload(follower_browser_module)

FOLLOWER_PLATFORMS = follower_browser_module.FOLLOWER_PLATFORMS
FollowerBrowserError = follower_browser_module.FollowerBrowserError
FollowerLoginRequired = follower_browser_module.FollowerLoginRequired
FollowerProfileUnavailable = follower_browser_module.FollowerProfileUnavailable
ProfileFollowersCollector = follower_browser_module.ProfileFollowersCollector


RESULT_LOGIN_REQUIRED = "Login diperlukan"
RESULT_NOT_AVAILABLE = "Tidak tersedia"
RESULT_INVALID_URL = "URL bukan profil"
RESULT_FAILED = "URL tidak dapat diproses"
RESULT_UNKNOWN = "Platform tidak didukung"
RESULT_SPACE = "space"


@st.cache_resource(show_spinner=False)
def follower_browser_v3(platform: str) -> ProfileFollowersCollector:
    return ProfileFollowersCollector(platform)


def parse_follower_input_rows(value: str) -> list[str]:
    """Keep intentional blank rows between profile URLs as ``space`` rows."""
    lines = value.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    rows: list[str] = []
    for line in lines:
        if not line.strip():
            rows.append(RESULT_SPACE)
            continue
        rows.extend(parse_url_list(line, preserve_repeated_rows=True))
    return rows


def initial_result_rows(urls: list[str]) -> list[dict[str, object]]:
    """Build one stable output row for every pasted profile URL."""
    rows: list[dict[str, object]] = []
    for url in urls:
        if url == RESULT_SPACE:
            rows.append(
                {
                    "Platform": RESULT_SPACE,
                    "Account Name": RESULT_SPACE,
                    "URL": RESULT_SPACE,
                    "Followers": RESULT_SPACE,
                }
            )
            continue
        platform = ProfileFollowersCollector.platform_from_url(url)
        rows.append(
            {
                "Platform": platform or "Tidak dikenali",
                "Account Name": ProfileFollowersCollector.account_name_from_url(platform, url),
                "URL": url,
                "Followers": "Menunggu diproses",
            }
        )
    return rows


def process_followers(urls: list[str]) -> list[dict[str, object]]:
    rows = initial_result_rows(urls)
    account_count = sum(row["URL"] != RESULT_SPACE for row in rows)
    progress = st.progress(0.0, text=f"Followers Checker · Menyiapkan {account_count:,} akun · 0%")
    activity = st.empty()
    completed = 0

    def update_progress(active_fraction: float = 0.0, detail: str = "") -> None:
        fraction = batch_progress_fraction(completed, account_count, active_fraction)
        progress.progress(
            fraction,
            text=(
                f"Followers Checker · {completed:,}/{account_count:,} akun selesai · "
                f"{round(fraction * 100)}%"
                + (f" · {detail}" if detail else "")
            ),
        )

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="mideta-followers") as executor:
        for platform in FOLLOWER_PLATFORMS:
            platform_indexes = [
                index for index, row in enumerate(rows) if row["Platform"] == platform
            ]
            if not platform_indexes:
                continue

            valid_indexes: list[int] = []
            for row_index in platform_indexes:
                url = str(rows[row_index]["URL"])
                if ProfileFollowersCollector.is_profile_url(platform, url):
                    valid_indexes.append(row_index)
                else:
                    rows[row_index]["Followers"] = RESULT_INVALID_URL
                    completed += 1
                    update_progress()

            if not valid_indexes:
                continue
            browser = follower_browser_v3(platform)
            try:
                logged_in = browser.is_logged_in()
            except FollowerBrowserError:
                logged_in = False
            if not logged_in:
                for row_index in valid_indexes:
                    rows[row_index]["Followers"] = RESULT_LOGIN_REQUIRED
                    completed += 1
                    update_progress(detail=f"{platform}: login diperlukan")
                continue

            for row_index in valid_indexes:
                url = str(rows[row_index]["URL"])
                future = executor.submit(browser.collect_profile_followers, url)
                started = time.monotonic()
                while True:
                    done, _ = wait({future}, timeout=0.4, return_when=FIRST_COMPLETED)
                    elapsed = max(time.monotonic() - started, 0.0)
                    heartbeat = min(0.9, 0.04 + (elapsed / (elapsed + 10.0)) * 0.86)
                    update_progress(
                        heartbeat,
                        detail=f"{platform}: membuka {rows[row_index]['Account Name']} · {int(elapsed):,} dtk",
                    )
                    activity.info(f"Sedang membaca profil: {url}")
                    if done:
                        break
                try:
                    followers = future.result()
                    rows[row_index]["Followers"] = (
                        followers if followers is not None else RESULT_NOT_AVAILABLE
                    )
                except FollowerLoginRequired:
                    rows[row_index]["Followers"] = RESULT_LOGIN_REQUIRED
                except (FollowerProfileUnavailable, FollowerBrowserError):
                    rows[row_index]["Followers"] = RESULT_FAILED
                except Exception:
                    rows[row_index]["Followers"] = RESULT_FAILED
                completed += 1
                update_progress(detail=f"{platform}: profil selesai")

    for row in rows:
        if row["Platform"] == "Tidak dikenali":
            row["Followers"] = RESULT_UNKNOWN
            completed += 1
            update_progress()
    progress.progress(1.0, text=f"Followers Checker selesai · {account_count:,}/{account_count:,} · 100%")
    activity.empty()
    return rows


st.set_page_config(
    page_title="Followers Checker | MIDETA",
    page_icon=str(MIDETA_LOGO_PATH),
    layout="wide",
)
apply_theme()
render_github_profile()
page_intro(
    "06",
    "Followers Checker",
    "Tempel URL profil dan dapatkan nama akun serta jumlah followers-nya.",
)

st.info(
    "Alur: login platform yang dipakai → tempel satu URL profil per baris → cek followers → unduh hasil. "
    "Urutan URL dan URL yang berulang tetap dipertahankan. Baris kosong di antara URL akan menjadi baris space."
)

st.markdown('<div class="section-label">LANGKAH 1 · LOGIN PLATFORM</div>', unsafe_allow_html=True)
st.caption(
    "Pilih lalu login hanya pada platform yang akan diperiksa. Password diketik langsung di situs resminya melalui "
    "Chrome MIDETA dan tidak dibaca atau disimpan oleh aplikasi."
)
login_platform = st.selectbox("Platform untuk login", FOLLOWER_PLATFORMS)
open_col, check_col, close_col = st.columns(3)
if open_col.button(
    f"Buka Login {login_platform}",
    icon=":material/login:",
    width="stretch",
):
    try:
        if follower_browser_v3(login_platform).open_login():
            st.success(f"Sesi {login_platform} masih aktif dan siap dipakai.")
        else:
            st.info(f"Selesaikan login {login_platform} di Chrome, lalu tekan Periksa Login.")
    except FollowerBrowserError as exc:
        st.error(str(exc))
if check_col.button("Periksa Login", icon=":material/check_circle:", width="stretch"):
    try:
        if follower_browser_v3(login_platform).is_logged_in():
            st.success(f"Login {login_platform} terdeteksi.")
        else:
            st.warning(f"Login {login_platform} belum terdeteksi.")
    except FollowerBrowserError as exc:
        st.error(str(exc))
if close_col.button("Tutup Chrome", icon=":material/close:", width="stretch"):
    follower_browser_v3(login_platform).close()
    st.info(f"Chrome MIDETA untuk {login_platform} sudah ditutup.")

st.markdown('<div class="section-label">LANGKAH 2 · URL PROFIL</div>', unsafe_allow_html=True)
raw_urls = st.text_area(
    "Daftar URL akun sosial media",
    height=270,
    placeholder=(
        "https://www.instagram.com/cnbcindonesia/\n"
        "https://www.facebook.com/cnbcindonesia/\n"
        "https://www.tiktok.com/@cnbcindonesia\n"
        "https://www.threads.com/@cnbcindonesia\n"
        "https://x.com/CNBCIndonesia\n"
        "https://www.youtube.com/@CNBCIndonesia\n"
        "https://www.linkedin.com/company/cnbc-indonesia/"
    ),
    help=(
        "Satu URL profil per baris. Jumlah URL tidak dibatasi oleh MIDETA. Gunakan URL akun/channel, bukan URL posting. "
        "URL berulang tetap menghasilkan baris terpisah; baris kosong di tengah daftar dipertahankan sebagai space."
    ),
)

if st.button(
    "Cek Semua Followers",
    type="primary",
    icon=":material/groups:",
    width="stretch",
):
    urls = parse_follower_input_rows(raw_urls)
    account_count = sum(url != RESULT_SPACE for url in urls)
    if not account_count:
        st.error("Masukkan minimal satu URL profil lengkap yang diawali http:// atau https://.")
    else:
        st.session_state["followers_checker_url_results"] = process_followers(urls)


rows = st.session_state.get("followers_checker_url_results", [])
if rows:
    account_rows = [row for row in rows if row["URL"] != RESULT_SPACE]
    available = sum(isinstance(row["Followers"], int) for row in account_rows)
    st.markdown('<div class="section-label">LANGKAH 3 · HASIL</div>', unsafe_allow_html=True)
    metrics = st.columns(3)
    metrics[0].metric("Diproses", len(account_rows))
    metrics[1].metric("Followers terbaca", available)
    metrics[2].metric("Perlu diperiksa", len(account_rows) - available)

    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_order=("Platform", "Account Name", "URL", "Followers"),
        # Keep the literal value visible so placeholder rows clearly show
        # ``space`` instead of being rendered as an invalid profile link.
        column_config={"URL": st.column_config.TextColumn("URL")},
    )
    if any(row["Followers"] == RESULT_LOGIN_REQUIRED for row in rows):
        st.warning(
            "Sebagian akun belum diproses karena login platform belum terdeteksi. Login platform tersebut, lalu jalankan kembali."
        )

    csv_col, xlsx_col = st.columns(2)
    csv_col.download_button(
        "Unduh CSV",
        to_csv_bytes(rows),
        "mideta_followers_checker.csv",
        "text/csv",
        icon=":material/download:",
        width="stretch",
    )
    xlsx_col.download_button(
        "Unduh XLSX",
        to_xlsx_bytes(rows, "Followers Checker"),
        "mideta_followers_checker.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:",
        width="stretch",
    )

render_footer()
