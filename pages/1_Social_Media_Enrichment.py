"""MIDETA Social Media Enrichment batch page."""
import importlib
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import re
import time
from typing import Any

import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

from src.batch import SOCIAL_BATCH_VERSION, collect_threads_enrichment_with_fallback, compact_social_export_row, failed_social_result, merge_facebook_advanced_result, order_social_results_by_input, parse_url_list, social_job_results, social_result_row
import src.comment_browser as comment_browser_module
from src.config import ENRICHMENT_BROWSER_CHUNK_SIZE, ENRICHMENT_CHUNK_SIZE, ENRICHMENT_FAST_CHUNK_SIZE, MAX_ENRICHMENT_URLS, MAX_PARALLEL_PLATFORMS, MIDETA_LOGO_PATH
from src.connectors import PLATFORM_OPTIONS, detect_platform, get_platform_connector
from src.connectors.instagram import InstagramConnector
from src.database import add_history, create_social_job, get_latest_social_job, get_social_job, next_social_job_items, record_social_job_item, set_social_job_status
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.instagram_browser import InstagramBrowserCollector, InstagramBrowserError, InstagramLoginRequired, build_instagram_browser_result
from src.models import FieldStatus, SocialResult
from src.social_urls import resolve_social_url
from src.tiktok_browser import TikTokAccessDenied, TikTokBrowserCollector, TikTokBrowserError, TikTokLoginRequired, build_tiktok_browser_result
import src.connectors.tiktok as tiktok_connector_module
import src.tiktok_free as tiktok_free_module
from src.ui import apply_theme, page_intro, render_footer, render_github_profile, render_platform_guide, status_label


# Streamlit dapat mempertahankan modul lama saat hanya file parser yang berubah.
# Muat ulang satu kali agar short URL dan carousel langsung memakai parser terbaru.
if getattr(tiktok_free_module, "TIKTOK_FREE_PARSER_VERSION", 0) < 3:
    importlib.reload(tiktok_connector_module)
    tiktok_free_module = importlib.reload(tiktok_free_module)

TikTokFreeCollector = tiktok_free_module.TikTokFreeCollector
TikTokFreeError = tiktok_free_module.TikTokFreeError

# Streamlit dapat mempertahankan instance browser dari versi kelas sebelumnya
# saat aplikasi diperbarui. Pastikan Facebook Advanced selalu memakai collector
# yang sudah memiliki pembaca enrichment, lalu gunakan nama cache baru agar
# instance lama tidak diambil kembali.
if (
    getattr(comment_browser_module.CommentBrowserCollector, "RUNTIME_VERSION", 0) < 20
    or not hasattr(comment_browser_module.CommentBrowserCollector, "collect_facebook_enrichment")
):
    comment_browser_module = importlib.reload(comment_browser_module)

CommentBrowserCollector = comment_browser_module.CommentBrowserCollector
CommentBrowserError = comment_browser_module.CommentBrowserError
CommentBrowserLoginRequired = comment_browser_module.CommentBrowserLoginRequired


st.set_page_config(page_title="Social Media Enrichment | MIDETA", page_icon=str(MIDETA_LOGO_PATH), layout="wide")
apply_theme()
render_github_profile()
page_intro(
    "01",
    "Social Media Enrichment",
    "Masukkan beberapa tautan YouTube, TikTok, Facebook, Instagram, Threads, atau X untuk melihat metadata publiknya.",
)
st.info(
    "Tulis satu URL pada setiap baris. MIDETA dapat menerima sampai 1.000 URL dan menyimpannya bertahap. "
    "Setiap baris tetap diproses, termasuk saat URL yang sama muncul lebih dari sekali. "
    "URL pendek dan tautan dari tombol Share akan diarahkan ke posting aslinya secara otomatis. "
    f"Enrichment All mengenali platform secara otomatis, sedangkan Split atau Triple Screen menjalankan maksimal {MAX_PARALLEL_PLATFORMS} platform secara paralel."
)

PLATFORM_ICONS = {
    "YouTube": "▶ YouTube",
    "TikTok": "♪ TikTok",
    "Facebook": "f Facebook",
    "Instagram": "◎ Instagram",
    "Threads": "@ Threads",
    "X": "𝕏 X",
}
PLACEHOLDERS = {
    "YouTube": "https://www.youtube.com/watch?v=contoh",
    "TikTok": "https://www.tiktok.com/@akun/video/contoh atau https://vt.tiktok.com/contoh",
    "Facebook": "https://www.facebook.com/akun/posts/contoh",
    "Instagram": "https://www.instagram.com/p/contoh",
    "Threads": "https://www.threads.net/@akun/post/contoh",
    "X": "https://x.com/akun/status/contoh",
}


@st.cache_resource(show_spinner=False)
def instagram_browser() -> InstagramBrowserCollector:
    return InstagramBrowserCollector()


@st.cache_resource(show_spinner=False)
def tiktok_direct_browser_v4() -> TikTokBrowserCollector:
    return TikTokBrowserCollector()


def tiktok_browser() -> TikTokBrowserCollector:
    return tiktok_direct_browser_v4()


def tiktok_free_collector() -> TikTokFreeCollector:
    return TikTokFreeCollector()


@st.cache_resource(show_spinner=False)
def threads_metadata_browser_v6() -> CommentBrowserCollector:
    return CommentBrowserCollector("Threads")


@st.cache_resource(show_spinner=False)
def facebook_enrichment_browser_v5() -> CommentBrowserCollector:
    return CommentBrowserCollector("Facebook")


def job_chunk_size(job: dict[str, Any]) -> int:
    if job.get("enrichment_mode") == "fast":
        return ENRICHMENT_FAST_CHUNK_SIZE
    if job.get("enrichment_mode") == "advanced":
        return ENRICHMENT_BROWSER_CHUNK_SIZE
    return ENRICHMENT_CHUNK_SIZE


def recover_instagram_followers(username: str | None) -> int | None:
    """Fallback for a profile response that was temporarily empty."""
    clean_username = InstagramBrowserCollector._username(username)
    if not clean_username:
        return None
    connector = InstagramConnector()
    return connector._platform_followers(
        "",
        BeautifulSoup("", "lxml"),
        f"https://www.instagram.com/{clean_username}/",
        clean_username,
    )


def render_instagram_controls(slot: str) -> str:
    mode_label = st.segmented_control(
        "Mode enrichment Instagram",
        ("Fast enrichment", "Advanced enrichment"),
        default="Fast enrichment",
        help="Kedua mode memakai Chrome Instagram yang sudah login. Advanced juga membuka profil sehingga waktunya lebih lama.",
        key=f"instagram_enrichment_mode_{slot}",
        width="stretch",
    )
    enrichment_mode = "advanced" if mode_label == "Advanced enrichment" else "fast"
    if enrichment_mode == "fast":
        st.caption(
            "Fast: mengambil author, caption, tanggal, likes, comments, shares, dan repost dari halaman posting. "
            f"Mode ini tidak membuka profil/Reels untuk Followers dan Views, sehingga lebih cepat ({ENRICHMENT_FAST_CHUNK_SIZE} URL per tahap)."
        )
    else:
        st.caption(
            "Advanced: memeriksa halaman posting dan profil author untuk Followers. Views hanya diambil jika Instagram "
            "menyediakannya untuk video/Reels; foto dan carousel ditulis Tidak tersedia, bukan 0. "
            f"Mode ini sengaja lebih teliti dan lebih lama ({ENRICHMENT_BROWSER_CHUNK_SIZE} URL per tahap)."
        )
    st.caption(
        "Kedua mode membutuhkan login di Chrome khusus MIDETA. Password tidak dibaca aplikasi dan profil browser tidak dimasukkan ke GitHub."
    )
    login_col, check_col, close_col = st.columns(3)
    if login_col.button("Buka Chrome Instagram", key=f"open_instagram_{slot}", width="stretch"):
        try:
            instagram_browser().open_login()
            st.info("Selesaikan login di jendela Chrome yang terbuka, lalu tekan Periksa Login.")
        except InstagramBrowserError as exc:
            st.error(str(exc))
    if check_col.button("Periksa Login", key=f"check_instagram_{slot}", width="stretch"):
        try:
            if instagram_browser().is_logged_in():
                st.success("Instagram sudah login dan siap digunakan untuk Fast maupun Advanced enrichment.")
            else:
                st.warning("Login belum terdeteksi. Selesaikan login di Chrome MIDETA.")
        except InstagramBrowserError as exc:
            st.error(str(exc))
    if close_col.button("Tutup Chrome MIDETA", key=f"close_instagram_{slot}", width="stretch"):
        instagram_browser().close()
        st.info("Chrome MIDETA sudah ditutup.")
    return enrichment_mode


def render_tiktok_controls(slot: str) -> str:
    mode_label = st.segmented_control(
        "Mode enrichment TikTok",
        ("Free tanpa login", "Chrome login"),
        default="Free tanpa login",
        help="Mode Free menghindari blokir 403 browser. Chrome login tetap tersedia sebagai cadangan.",
        key=f"tiktok_enrichment_mode_{slot}",
        width="stretch",
    )
    if mode_label == "Free tanpa login":
        st.caption(
            "Caption dan author dibaca tanpa login dari metadata resmi TikTok. Views, followers, likes, comments, "
            "shares, dan bookmark diambil lewat kredit gratis Apify jika token sudah disimpan."
        )
        saved = tiktok_free_collector().has_token()
        if saved:
            st.success("Token Apify sudah tersimpan di komputer ini.")
        else:
            st.info("Tanpa token, proses tetap berjalan tetapi hanya caption dan author yang bisa tersedia.")
        token_value = st.text_input(
            "Apify API token",
            type="password",
            placeholder="Tempel token di sini lalu simpan",
            help="Token disimpan hanya di folder privat MIDETA dan tidak masuk ke Git atau file hasil.",
            key=f"apify_token_{slot}",
        )
        save_col, delete_col, account_col = st.columns(3)
        if save_col.button(
            "Simpan token",
            key=f"save_apify_{slot}",
            width="stretch",
            disabled=not token_value.strip(),
        ):
            try:
                tiktok_free_collector().save_token(token_value)
                st.success("Token tersimpan. TikTok Free Mode siap digunakan.")
                st.rerun()
            except TikTokFreeError as exc:
                st.error(str(exc))
        if delete_col.button(
            "Hapus token",
            key=f"delete_apify_{slot}",
            width="stretch",
            disabled=not saved,
        ):
            try:
                tiktok_free_collector().delete_token()
                st.info("Token Apify sudah dihapus dari komputer ini.")
                st.rerun()
            except TikTokFreeError as exc:
                st.error(str(exc))
        account_col.link_button(
            "Buat akun gratis",
            "https://console.apify.com/sign-up",
            width="stretch",
        )
        st.caption(
            "Ambil token di Apify Console → Settings → API & Integrations. Kuota mengikuti kredit gratis akun Apify."
        )
        return "free"

    st.caption(
        "Mode ini memakai Chrome khusus MIDETA yang sudah login. TikTok dapat membatasi perpindahan URL dan menampilkan HTTP 403, "
        "jadi gunakan sebagai cadangan jika Free Mode belum mendapatkan suatu data."
    )
    st.caption(
        f"Setiap URL membuka video dan profil dalam kelompok {ENRICHMENT_BROWSER_CHUNK_SIZE} URL per tahap. "
        "Password tetap diketik langsung di TikTok dan tidak dibaca MIDETA."
    )
    login_col, check_col, close_col = st.columns(3)
    if login_col.button("Buka Chrome TikTok", key=f"open_tiktok_{slot}", width="stretch"):
        try:
            tiktok_browser().open_login()
            st.info("Selesaikan login TikTok di jendela Chrome yang terbuka, lalu tekan Periksa Login.")
        except TikTokBrowserError as exc:
            st.error(str(exc))
    if check_col.button("Periksa Login", key=f"check_tiktok_{slot}", width="stretch"):
        try:
            if tiktok_browser().is_logged_in():
                st.success("TikTok sudah login dan siap digunakan untuk enrichment.")
            else:
                st.warning("Login TikTok belum terdeteksi. Selesaikan login di Chrome MIDETA.")
        except TikTokBrowserError as exc:
            st.error(str(exc))
    if close_col.button("Tutup Chrome TikTok", key=f"close_tiktok_{slot}", width="stretch"):
        tiktok_browser().close()
        st.info("Chrome TikTok MIDETA sudah ditutup.")
    return "advanced"


def render_facebook_controls(slot: str) -> str:
    mode_label = st.segmented_control(
        "Mode enrichment Facebook",
        ("Fast enrichment", "Advanced enrichment"),
        default="Fast enrichment",
        help="Advanced memakai hasil Fast untuk metadata post, lalu sesi login hanya untuk mencari Views Reel target.",
        key=f"facebook_enrichment_mode_{slot}",
        width="stretch",
    )
    enrichment_mode = "advanced" if mode_label == "Advanced enrichment" else "fast"
    if enrichment_mode == "fast":
        st.caption(
            "Fast: membaca metadata publik dari URL post, video, atau Reel tanpa membuka profil. "
            "Gunakan Advanced bila Views tidak muncul di hasil Fast."
        )
        return enrichment_mode

    st.caption(
        "Advanced: memakai logic Fast untuk tanggal, author, caption, followers, likes, comments, shares, dan data lain. "
        "Akun Facebook yang login hanya dipakai untuk mencari Views Reel dengan ID yang sama "
        f"({ENRICHMENT_BROWSER_CHUNK_SIZE} URL per tahap)."
    )
    st.caption(
        "Password diketik langsung di Facebook dan tidak dibaca MIDETA. Jika Views target tidak ditampilkan Facebook, "
        "kolom akan ditulis Tidak tersedia dan tidak mengambil angka dari Reel lain."
    )
    open_col, check_col, close_col = st.columns(3)
    if open_col.button("Buka Chrome Facebook", key=f"open_facebook_{slot}", width="stretch"):
        try:
            if facebook_enrichment_browser_v5().open_login():
                st.success("Facebook sudah login dan siap digunakan untuk Advanced enrichment.")
            else:
                st.info("Selesaikan login di Chrome Facebook, lalu tekan Periksa Login.")
        except CommentBrowserError as exc:
            st.error(str(exc))
    if check_col.button("Periksa Login", key=f"check_facebook_{slot}", width="stretch"):
        try:
            if facebook_enrichment_browser_v5().is_logged_in():
                st.success("Facebook sudah login dan siap digunakan untuk Advanced enrichment.")
            else:
                st.warning("Login Facebook belum terdeteksi. Selesaikan login di Chrome MIDETA.")
        except CommentBrowserError as exc:
            st.error(str(exc))
    if close_col.button("Tutup Chrome Facebook", key=f"close_facebook_{slot}", width="stretch"):
        facebook_enrichment_browser_v5().close()
        st.info("Chrome Facebook MIDETA sudah ditutup.")
    return enrichment_mode


def render_threads_controls(slot: str) -> None:
    st.caption(
        "MIDETA mencoba metadata publik lebih dulu. Jika Threads mengirim halaman kosong atau invalid_post, "
        "MIDETA otomatis memakai sesi Chrome Threads untuk membaca post yang benar."
    )
    open_col, check_col, close_col = st.columns(3)
    if open_col.button("Buka Sesi Threads", key=f"open_threads_{slot}", width="stretch"):
        try:
            if threads_metadata_browser_v6().open_login():
                st.success("Sesi Threads tersimpan masih aktif.")
            else:
                st.info("Selesaikan login di Chrome MIDETA, lalu tekan Periksa Login.")
        except CommentBrowserError as exc:
            st.error(str(exc))
    if check_col.button("Periksa Login", key=f"check_threads_{slot}", width="stretch"):
        try:
            if threads_metadata_browser_v6().is_logged_in():
                st.success("Threads sudah login dan fallback enrichment siap digunakan.")
            else:
                st.warning("Login belum terdeteksi. Post publik tetap dicoba, tetapi post yang dibatasi mungkin belum terbaca.")
        except CommentBrowserError as exc:
            st.error(str(exc))
    if close_col.button("Tutup Chrome Threads", key=f"close_threads_{slot}", width="stretch"):
        threads_metadata_browser_v6().close()
        st.info("Chrome Threads MIDETA sudah ditutup.")


def render_platform_setup(platform: str, slot: str, compact: bool = False) -> str:
    if compact:
        st.subheader(PLATFORM_ICONS[platform])
        st.caption(f"Panel ini khusus untuk URL {platform}.")
        with st.expander(f"Cara pakai {platform}"):
            render_platform_guide("enrichment", platform)
    else:
        st.caption(f"Bagian ini khusus untuk URL {platform}.")
        render_platform_guide("enrichment", platform)
    if platform == "Instagram":
        return render_instagram_controls(slot)
    if platform == "TikTok":
        return render_tiktok_controls(slot)
    if platform == "Facebook":
        return render_facebook_controls(slot)
    if platform == "Threads":
        render_threads_controls(slot)
    return "standard"


def validate_job_request(request: dict[str, Any]) -> str | None:
    urls = parse_url_list(request["url_text"], preserve_repeated_rows=True)
    request["urls"] = urls
    if not urls:
        return f"{request['platform']}: masukkan setidaknya satu URL posting."
    if len(urls) > MAX_ENRICHMENT_URLS:
        excess = len(urls) - MAX_ENRICHMENT_URLS
        return f"{request['platform']}: maksimal {MAX_ENRICHMENT_URLS:,} URL. Kurangi {excess:,} URL lalu coba lagi."
    return None


def group_detected_urls(urls: list[str]) -> tuple[dict[str, list[str]], list[dict[str, str]]]:
    grouped: dict[str, list[str]] = {}
    unsupported: list[dict[str, str]] = []
    for url in urls:
        try:
            platform = detect_platform(url)
        except ValueError as exc:
            unsupported.append({"URL": url, "Alasan": str(exc)})
            continue
        grouped.setdefault(platform, []).append(url)
    return grouped, unsupported


def create_requested_jobs(requests: list[dict[str, Any]]) -> dict[str, int] | None:
    errors = [error for request in requests if (error := validate_job_request(request))]
    requests_are_valid = not errors
    if requests_are_valid and any(request["platform"] == "Instagram" and not request["mock_mode"] for request in requests):
        try:
            if not instagram_browser().is_logged_in():
                errors.append("Instagram belum login. Buka Chrome Instagram dan selesaikan login sebelum memulai batch.")
        except InstagramBrowserError as exc:
            errors.append(str(exc))
    if requests_are_valid and any(
        request["platform"] == "TikTok"
        and request["enrichment_mode"] == "advanced"
        and not request["mock_mode"]
        for request in requests
    ):
        try:
            if not tiktok_browser().is_logged_in():
                errors.append("TikTok belum login. Buka Chrome TikTok dan selesaikan login sebelum memulai batch.")
        except TikTokBrowserError as exc:
            errors.append(str(exc))
    if requests_are_valid and any(
        request["platform"] == "Facebook"
        and request["enrichment_mode"] == "advanced"
        and not request["mock_mode"]
        for request in requests
    ):
        try:
            if not facebook_enrichment_browser_v5().is_logged_in():
                errors.append("Facebook belum login. Buka Chrome Facebook dan selesaikan login sebelum memulai batch.")
        except CommentBrowserError as exc:
            errors.append(str(exc))
    if errors:
        for error in errors:
            st.error(error)
        return None
    created_jobs: dict[str, int] = {}
    for request in requests:
        platform = request["platform"]
        job_id = create_social_job(
            platform,
            request["urls"],
            SOCIAL_BATCH_VERSION,
            mock_mode=request["mock_mode"],
            browser_mode=(
                platform in {"Instagram", "Threads"}
                or (platform == "TikTok" and request["enrichment_mode"] == "advanced")
                or (platform == "Facebook" and request["enrichment_mode"] == "advanced")
            ),
            enrichment_mode=request["enrichment_mode"],
        )
        st.session_state[f"social_job_{platform}"] = job_id
        created_jobs[platform] = job_id
    return created_jobs


def load_current_job(platform: str) -> dict[str, Any] | None:
    job_key = f"social_job_{platform}"
    job_id = st.session_state.get(job_key)
    current_job = get_social_job(job_id) if job_id else None
    latest_job = get_latest_social_job(platform)
    # Setiap tab Streamlit memiliki session_state sendiri. Saat proses baru
    # dimulai dari tab lain, jangan biarkan tab lama tetap menampilkan antrean
    # sebelumnya yang sudah berhenti atau gagal.
    if latest_job and (current_job is None or latest_job["id"] > current_job["id"]):
        current_job = latest_job
        st.session_state[job_key] = latest_job["id"]
    if current_job and current_job.get("schema_version") != SOCIAL_BATCH_VERSION:
        st.session_state.pop(job_key, None)
        st.info("Parser MIDETA baru saja diperbarui. Mulai proses baru agar hasil menggunakan pembacaan terbaru.")
        return None
    return current_job


def render_job_controls(job: dict[str, Any], slot: str) -> None:
    if job["status"] not in {"running", "paused"}:
        return
    percentage = int(job["processed"] / job["total"] * 100) if job["total"] else 0
    st.progress(percentage, text=f"{job['processed']:,} dari {job['total']:,} URL sudah disimpan")
    control_cols = st.columns([2, 3])
    if job["status"] == "running":
        if control_cols[0].button("Jeda proses", key=f"pause_social_{slot}_{job['id']}", width="stretch"):
            set_social_job_status(job["id"], "paused")
            st.rerun()
        mode_text = job["enrichment_mode"].title() if job["enrichment_mode"] != "standard" else "Standard"
        control_cols[1].caption(
            f"Mode {mode_text}: {job_chunk_size(job)} URL per tahap. Dalam layar paralel, worker platform ini tetap terpisah."
        )
    else:
        if control_cols[0].button("Lanjutkan proses", key=f"resume_social_{slot}_{job['id']}", type="primary", width="stretch"):
            set_social_job_status(job["id"], "running")
            st.rerun()
        control_cols[1].caption("Hasil yang sudah selesai tetap tersimpan. Tekan Lanjutkan proses untuk meneruskan antrean.")


def render_job_results(job: dict[str, Any] | None, platform: str) -> None:
    if not job:
        return
    results = social_job_results(job)
    if not results:
        return
    if any(result.is_mock for result in results):
        st.warning("DATA CONTOH AKTIF. Informasi di bawah bukan data dari tautan.")

    def all_fields(result: SocialResult):
        return [
            result.username,
            result.caption,
            result.posted_at,
            result.followers,
            result.likes,
            result.comments,
            result.shares,
            result.views,
            result.bookmarks,
            result.reposts,
        ]

    successful = sum(any(field.status == FieldStatus.AVAILABLE for field in all_fields(result)) for result in results)
    metric_cols = st.columns(3)
    metric_cols[0].metric("Diproses", len(results))
    metric_cols[1].metric("Berhasil", successful)
    metric_cols[2].metric(
        "Periksa",
        len(results) - successful + len(job.get("browser_issues", [])),
    )

    detail_rows = [social_result_row(result) for result in results]
    for row in detail_rows:
        for key in list(row):
            if key.startswith("Status "):
                row[key] = status_label(row[key])
    export_rows = [compact_social_export_row(result) for result in results]
    st.dataframe(pd.DataFrame(export_rows).astype(str), width="stretch", hide_index=True)
    with st.expander("Lihat status setiap data"):
        detail_frame = pd.DataFrame(detail_rows)
        status_columns = ["Platform", "URL"] + [column for column in detail_frame.columns if column.startswith("Status ")] + ["Catatan"]
        st.dataframe(detail_frame.reindex(columns=status_columns).fillna("Tidak tersedia"), width="stretch", hide_index=True)
    csv_col, xlsx_col = st.columns(2)
    filename = platform.lower().replace(" ", "_")
    csv_col.download_button(
        "Unduh CSV",
        to_csv_bytes(export_rows),
        f"mideta_{filename}.csv",
        "text/csv",
        key=f"download_csv_{platform}_{job['id']}",
        width="stretch",
    )
    xlsx_col.download_button(
        "Unduh XLSX",
        to_xlsx_bytes(export_rows, platform),
        f"mideta_{filename}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"download_xlsx_{platform}_{job['id']}",
        width="stretch",
    )


def load_all_jobs() -> list[dict[str, Any]]:
    job_ids = st.session_state.get("social_all_jobs", {})
    if not isinstance(job_ids, dict):
        st.session_state.pop("social_all_jobs", None)
        return []
    current_ids: dict[str, int] = {}
    jobs: list[dict[str, Any]] = []
    stale = False
    for platform in PLATFORM_OPTIONS:
        job_id = job_ids.get(platform)
        if not job_id:
            continue
        job = get_social_job(job_id)
        if not job:
            continue
        if job.get("schema_version") != SOCIAL_BATCH_VERSION:
            stale = True
            continue
        current_ids[platform] = job_id
        jobs.append(job)
    if current_ids != job_ids:
        if current_ids:
            st.session_state["social_all_jobs"] = current_ids
        else:
            st.session_state.pop("social_all_jobs", None)
    if stale:
        st.info("Parser MIDETA baru saja diperbarui. Mulai Enrichment All baru agar hasil memakai pembacaan terbaru.")
    return jobs


def available_result_fields(result: SocialResult):
    return (
        result.username,
        result.caption,
        result.posted_at,
        result.followers,
        result.likes,
        result.comments,
        result.shares,
        result.views,
        result.bookmarks,
        result.reposts,
    )


def facebook_targets_from_job(job: dict[str, Any]) -> dict[str, tuple[int, str]]:
    """Restore canonical targets already completed by this Facebook job."""
    targets: dict[str, tuple[int, str]] = {}
    for item in job.get("items", []):
        result = item.get("result") or {}
        note = str(result.get("note") or "")
        match = re.search(r"Target Facebook tervalidasi:\s*(https?://\S+)", note, re.I)
        if not match:
            continue
        target = match.group(1).rstrip(".").rstrip("/").casefold()
        targets.setdefault(target, (int(item["position"]), str(item["url"])))
    return targets


def render_all_job_results(
    jobs: list[dict[str, Any]],
    unsupported_urls: list[dict[str, str]] | None = None,
) -> None:
    results = [
        result
        for job in jobs
        for result in social_job_results(job)
    ]
    results.extend(
        failed_social_result(
            item.get("URL", ""),
            "Tidak dikenali",
            item.get("Alasan"),
        )
        for item in (unsupported_urls or [])
    )
    if not results:
        if jobs and all(job["status"] == "completed" for job in jobs):
            st.warning("Proses selesai, tetapi belum ada URL yang menghasilkan metadata.")
        return

    results = order_social_results_by_input(
        results,
        st.session_state.get("social_all_order", []),
    )
    if any(result.is_mock for result in results):
        st.warning("DATA CONTOH AKTIF. Informasi di bawah bukan data dari tautan.")

    successful = sum(
        any(field.status == FieldStatus.AVAILABLE for field in available_result_fields(result))
        for result in results
    )
    browser_issue_count = sum(len(job.get("browser_issues", [])) for job in jobs)
    metric_cols = st.columns(3)
    metric_cols[0].metric("Diproses", len(results))
    metric_cols[1].metric("Berhasil", successful)
    metric_cols[2].metric("Periksa", len(results) - successful + browser_issue_count)

    detail_rows = [social_result_row(result) for result in results]
    for row in detail_rows:
        for key in list(row):
            if key.startswith("Status "):
                row[key] = status_label(row[key])
    export_rows = [compact_social_export_row(result) for result in results]
    st.dataframe(pd.DataFrame(export_rows).astype(str), width="stretch", hide_index=True)
    with st.expander("Lihat status setiap data"):
        detail_frame = pd.DataFrame(detail_rows)
        status_columns = ["Platform", "URL"] + [
            column for column in detail_frame.columns if column.startswith("Status ")
        ] + ["Catatan"]
        st.dataframe(
            detail_frame.reindex(columns=status_columns).fillna("Tidak tersedia"),
            width="stretch",
            hide_index=True,
        )
    job_key = "_".join(str(job["id"]) for job in jobs)
    csv_col, xlsx_col = st.columns(2)
    csv_col.download_button(
        "Unduh CSV Gabungan",
        to_csv_bytes(export_rows),
        "mideta_enrichment_all.csv",
        "text/csv",
        key=f"download_csv_all_{job_key}",
        width="stretch",
    )
    xlsx_col.download_button(
        "Unduh XLSX Gabungan",
        to_xlsx_bytes(export_rows, "Enrichment All"),
        "mideta_enrichment_all.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"download_xlsx_all_{job_key}",
        width="stretch",
    )


def render_job_issues(job: dict[str, Any] | None) -> None:
    if not job:
        return
    issue_slot = st.empty()
    with issue_slot.container():
        if errors := job.get("errors"):
            with st.expander(f"{len(errors)} URL tidak dapat diproses", expanded=True):
                st.dataframe(pd.DataFrame(errors), width="stretch", hide_index=True)
        if browser_issues := job.get("browser_issues"):
            with st.expander(f"{len(browser_issues)} URL belum lengkap", expanded=True):
                st.dataframe(pd.DataFrame(browser_issues), width="stretch", hide_index=True)


def render_job_panel(platform: str, slot: str) -> tuple[dict[str, Any] | None, Any]:
    job = load_current_job(platform)
    if job and job["platform"] in {"Instagram", "TikTok", "Facebook"}:
        st.caption(f"Antrean aktif menggunakan **{job['enrichment_mode'].title()} enrichment**.")
    if job:
        render_job_controls(job, slot)
    activity = st.empty()
    render_job_results(job, platform)
    render_job_issues(job)
    return job, activity


def render_all_job_panels(jobs: list[dict[str, Any]]) -> list[tuple[dict[str, Any], Any]]:
    panels: list[tuple[dict[str, Any], Any]] = []
    if not jobs:
        return panels
    st.markdown("#### Status per platform")
    for job in jobs:
        platform = job["platform"]
        with st.container(border=True):
            st.markdown(f"**{PLATFORM_ICONS[platform]}** · {job['processed']:,}/{job['total']:,} URL")
            if platform in {"Instagram", "TikTok", "Facebook"}:
                login_text = "tanpa login" if job["enrichment_mode"] == "free" else "dengan login"
                if platform == "Facebook" and job["enrichment_mode"] == "fast":
                    login_text = "tanpa login"
                st.caption(f"Mode {platform}: {job['enrichment_mode'].title()} enrichment {login_text}.")
            render_job_controls(job, f"all_{platform.lower()}")
            activity = st.empty()
            render_job_issues(job)
        panels.append((job, activity))
    return panels


def collect_one_item(
    job: dict[str, Any],
    item: dict[str, Any],
    active_browser: InstagramBrowserCollector | TikTokBrowserCollector | CommentBrowserCollector | None,
    facebook_targets: dict[str, tuple[int, str]] | None = None,
) -> dict[str, Any]:
    url = item["url"]
    position = item["position"]
    try:
        needs_browser_target = active_browser is not None and job["platform"] in {"Instagram", "TikTok", "Facebook"}
        processing_url = (
            resolve_social_url(url, expected_platform=job["platform"])
            if not job["mock_mode"] and needs_browser_target
            else url
        )
        connector = get_platform_connector(processing_url, job["platform"])
        if job["mock_mode"]:
            result = connector.mock_enrichment(url)
        browser_issue = None
        if active_browser is not None and not job["mock_mode"] and job["platform"] == "Instagram":
            try:
                metrics = active_browser.collect(
                    processing_url,
                    None,
                    mode=job["enrichment_mode"],
                )
                if job["enrichment_mode"] == "advanced" and metrics.followers is None:
                    metrics.followers = recover_instagram_followers(metrics.username)
                if job["enrichment_mode"] == "advanced" and metrics.followers is None:
                    browser_issue = {
                        "URL": url,
                        "Platform": "Instagram",
                        "Alasan": "Followers belum berhasil dibaca dari profil. Jalankan ulang URL ini saat pembatasan Instagram sudah reda.",
                    }
                result = build_instagram_browser_result(
                    url,
                    metrics,
                    mode=job["enrichment_mode"],
                )
            except InstagramLoginRequired as exc:
                return {"kind": "login_required", "reason": str(exc), "position": position, "url": url}
            except InstagramBrowserError as exc:
                return {
                    "kind": "failed",
                    "position": position,
                    "url": url,
                    "error": {"URL": url, "Platform": job["platform"], "Alasan": str(exc)},
                }
        elif active_browser is not None and not job["mock_mode"] and job["platform"] == "TikTok":
            try:
                metrics = active_browser.collect(processing_url, None)
                missing = []
                if not metrics.caption:
                    missing.append("Caption")
                if metrics.views is None:
                    missing.append("Views")
                if metrics.followers is None:
                    missing.append("Followers")
                if missing:
                    browser_issue = {
                        "URL": url,
                        "Platform": "TikTok",
                        "Alasan": f"{', '.join(missing)} belum berhasil dibaca dari video atau profil target. Coba jalankan ulang setelah halaman TikTok normal.",
                    }
                result = build_tiktok_browser_result(url, metrics)
            except TikTokLoginRequired as exc:
                return {"kind": "login_required", "reason": str(exc), "position": position, "url": url}
            except TikTokAccessDenied as exc:
                return {"kind": "rate_limited", "reason": str(exc), "position": position, "url": url}
            except TikTokBrowserError as exc:
                return {
                    "kind": "failed",
                    "position": position,
                    "url": url,
                    "error": {"URL": url, "Platform": job["platform"], "Alasan": str(exc)},
                }
        elif active_browser is not None and not job["mock_mode"] and job["platform"] == "Facebook":
            # Jalankan parser Fast terhadap permalink target yang sudah
            # diresolusi agar short/share URL tidak menyumbangkan preview post
            # sebelumnya atau rekomendasi lain dari halaman Facebook.
            fast_result = connector.enrich(processing_url)
            try:
                browser_result = active_browser.collect_facebook_enrichment(processing_url)
                result = merge_facebook_advanced_result(fast_result, browser_result)
                if result.views.value is None:
                    browser_issue = {
                        "URL": url,
                        "Platform": "Facebook",
                        "Alasan": (
                            "Views Reel target belum ditampilkan Facebook pada halaman post maupun halaman Reels profil. "
                            "Nilai dibiarkan Tidak tersedia agar tidak tertukar dengan Reel lain."
                        ),
                    }
            except CommentBrowserLoginRequired as exc:
                return {"kind": "login_required", "reason": str(exc), "position": position, "url": url}
            except CommentBrowserError as exc:
                result = fast_result
                browser_issue = {
                    "URL": url,
                    "Platform": "Facebook",
                    "Alasan": (
                        "Metadata Fast berhasil disimpan, tetapi Views belum dapat dibaca dari sesi Facebook: "
                        f"{exc}"
                    ),
                }
            canonical_target = str(result.url or processing_url).split("?", 1)[0].rstrip("/")
            target_note = f"Target Facebook tervalidasi: {canonical_target}."
            result.note = f"{result.note} {target_note}".strip() if result.note else target_note
            target_key = canonical_target.casefold()
            if facebook_targets is not None:
                previous = facebook_targets.get(target_key)
                if previous and previous[1] != url:
                    duplicate_reason = (
                        f"Short URL ini diarahkan Facebook ke posting yang sama dengan baris {previous[0]} "
                        f"({canonical_target}), sehingga datanya memang berulang."
                    )
                    if browser_issue:
                        browser_issue["Alasan"] = f"{browser_issue['Alasan']} {duplicate_reason}"
                    else:
                        browser_issue = {
                            "URL": url,
                            "Platform": "Facebook",
                            "Alasan": duplicate_reason,
                        }
                else:
                    facebook_targets[target_key] = (position, url)
        elif not job["mock_mode"] and job["platform"] == "TikTok" and job["enrichment_mode"] == "free":
            metrics = tiktok_free_collector().collect(processing_url)
            missing = []
            if not metrics.caption:
                missing.append("Caption")
            if metrics.views is None:
                missing.append("Views")
            if metrics.followers is None:
                missing.append("Followers")
            if metrics.warning or missing:
                detail = metrics.warning or f"{', '.join(missing)} belum tersedia dari layanan gratis."
                browser_issue = {
                    "URL": url,
                    "Platform": "TikTok",
                    "Alasan": detail,
                }
            result = build_tiktok_browser_result(url, metrics)
        elif not job["mock_mode"] and job["platform"] == "Threads":
            # Threads cukup sering menolak pembaca publik atau mengalami
            # kegagalan DNS sesaat. Enrichment All selalu menyiapkan sesi
            # Chrome agar gangguan ini tidak langsung menggagalkan baris.
            result, threads_issue = collect_threads_enrichment_with_fallback(
                connector.enrich,
                active_browser.collect_threads_enrichment if active_browser is not None else None,
                processing_url,
            )
            if threads_issue:
                browser_issue = {
                    "URL": url,
                    "Platform": "Threads",
                    "Alasan": threads_issue,
                }
        elif not job["mock_mode"]:
            result = connector.enrich(processing_url)

        # Keep the pasted URL in the exported row even when a short/share link
        # was resolved internally. This preserves the user's original order and
        # makes failed/retried rows easy to match to the source spreadsheet.
        result.url = url

        fields = [
            result.username,
            result.caption,
            result.posted_at,
            result.followers,
            result.likes,
            result.comments,
            result.shares,
            result.views,
            result.bookmarks,
            result.reposts,
        ]
        has_data = any(field.status == FieldStatus.AVAILABLE for field in fields)
        history_status = "mock" if result.is_mock else "completed" if has_data else "failed"
        return {
            "kind": "completed",
            "position": position,
            "url": url,
            "result": result.model_dump(mode="json"),
            "result_url": result.url,
            "platform": result.platform,
            "history_status": history_status,
            "browser_issue": browser_issue,
        }
    except Exception as exc:
        reason = str(exc)
        if "permintaan dibatasi" in reason.casefold() or "http 429" in reason.casefold():
            return {"kind": "rate_limited", "reason": reason, "position": position, "url": url}
        return {
            "kind": "failed",
            "position": position,
            "url": url,
            "error": {"URL": url, "Platform": job["platform"], "Alasan": reason},
        }


def collect_job_chunk(task: dict[str, Any], output: Queue) -> None:
    job = task["job"]
    facebook_targets = facebook_targets_from_job(job) if job["platform"] == "Facebook" else None
    try:
        for item in task["chunk"]:
            outcome = collect_one_item(
                job,
                item,
                task["active_browser"],
                facebook_targets=facebook_targets,
            )
            output.put((job["id"], outcome))
            if outcome["kind"] in {"rate_limited", "login_required"}:
                break
    finally:
        output.put((job["id"], None))


def persist_outcome(job: dict[str, Any], outcome: dict[str, Any], activity: Any) -> bool:
    if outcome["kind"] == "rate_limited":
        set_social_job_status(job["id"], "paused")
        activity.warning("Platform sedang membatasi request. Antrean ini dijeda dan dapat dilanjutkan nanti.")
        return False
    if outcome["kind"] == "login_required":
        set_social_job_status(job["id"], "paused")
        activity.error(f"Sesi {job['platform']} berakhir. Login kembali, lalu lanjutkan proses.")
        return False
    if outcome["kind"] == "failed":
        record_social_job_item(
            job["id"],
            outcome["position"],
            "failed",
            error=outcome["error"],
        )
        return True
    add_history(
        "Social Media Enrichment",
        outcome["result_url"],
        outcome["history_status"],
        outcome["result"],
        outcome["platform"],
    )
    record_social_job_item(
        job["id"],
        outcome["position"],
        "completed",
        result=outcome["result"],
        browser_issue=outcome["browser_issue"],
    )
    return True


def run_active_jobs(job_panels: list[tuple[dict[str, Any] | None, Any]]) -> None:
    tasks: list[dict[str, Any]] = []
    state_changed = False
    seen_jobs: set[int] = set()
    for job, activity in job_panels:
        if not job or job["status"] != "running" or job["id"] in seen_jobs:
            continue
        seen_jobs.add(job["id"])
        active_browser = None
        needs_browser = (
            job["platform"] in {"Instagram", "Threads"}
            or (job["platform"] == "TikTok" and job["enrichment_mode"] == "advanced")
            or (job["platform"] == "Facebook" and job["enrichment_mode"] == "advanced")
        )
        if needs_browser and not job["mock_mode"]:
            try:
                if job["platform"] == "Instagram":
                    active_browser = instagram_browser()
                elif job["platform"] == "TikTok":
                    active_browser = tiktok_browser()
                elif job["platform"] == "Facebook":
                    active_browser = facebook_enrichment_browser_v5()
                else:
                    active_browser = threads_metadata_browser_v6()
                if job["platform"] in {"Instagram", "TikTok", "Facebook"} and not active_browser.is_logged_in():
                    set_social_job_status(job["id"], "paused")
                    activity.error(f"Sesi {job['platform']} berakhir. Login kembali, lalu lanjutkan proses.")
                    state_changed = True
                    continue
            except (InstagramBrowserError, TikTokBrowserError, CommentBrowserError) as exc:
                set_social_job_status(job["id"], "paused")
                activity.error(str(exc))
                state_changed = True
                continue
        chunk = next_social_job_items(job["id"], job_chunk_size(job))
        if not chunk:
            set_social_job_status(job["id"], "completed")
            state_changed = True
            continue
        mode_text = job["enrichment_mode"].title() if job["enrichment_mode"] != "standard" else "Standard"
        activity.info(
            f"{job['platform']} · {mode_text}: memproses URL {chunk[0]['position']:,}–{chunk[-1]['position']:,} dari {job['total']:,}."
        )
        tasks.append({"job": job, "activity": activity, "active_browser": active_browser, "chunk": chunk})

    if not tasks:
        if state_changed:
            st.rerun()
        return

    output: Queue = Queue()
    completed_workers = 0
    processed_counts = {task["job"]["id"]: task["job"]["processed"] for task in tasks}
    tasks_by_id = {task["job"]["id"]: task for task in tasks}
    with ThreadPoolExecutor(
        max_workers=min(len(tasks), MAX_PARALLEL_PLATFORMS),
        thread_name_prefix="mideta-platform",
    ) as executor:
        for task in tasks:
            executor.submit(collect_job_chunk, task, output)
        while completed_workers < len(tasks):
            job_id, outcome = output.get()
            if outcome is None:
                completed_workers += 1
                continue
            task = tasks_by_id[job_id]
            saved = persist_outcome(task["job"], outcome, task["activity"])
            if saved:
                processed_counts[job_id] += 1
                task["activity"].info(
                    f"{task['job']['platform']}: {processed_counts[job_id]:,} dari {task['job']['total']:,} URL sudah disimpan."
                )
    time.sleep(0.3)
    st.rerun()


layout_mode = st.segmented_control(
    "Tampilan proses",
    ("Satu platform", "Split Screen", "Triple Screen", "Enrichment All"),
    default="Satu platform",
    help="Enrichment All menerima URL campuran dan mengenali platform otomatis. Split dan Triple Screen memisahkan proses dalam beberapa panel.",
    key="social_enrichment_layout",
    width="stretch",
)

job_panels: list[tuple[dict[str, Any] | None, Any]] = []

if layout_mode == "Enrichment All":
    st.caption(
        "Tempel URL YouTube, TikTok, Facebook, Instagram, Threads, dan X dalam satu kotak. "
        "MIDETA akan mengenali platformnya, memproses setiap baris termasuk URL berulang, lalu menggabungkan hasil sesuai urutan input."
    )
    with st.expander("Pengaturan Instagram jika daftar berisi URL Instagram"):
        instagram_mode = render_instagram_controls("all")
    with st.expander("Pengaturan TikTok jika daftar berisi URL TikTok"):
        tiktok_mode = render_tiktok_controls("all")
    with st.expander("Pengaturan Facebook jika daftar berisi URL Facebook"):
        facebook_mode = render_facebook_controls("all")

    with st.form("enrichment_form_all"):
        all_url_text = st.text_area(
            "Semua URL media sosial",
            height=230,
            placeholder="\n".join(PLACEHOLDERS.values()),
            key="social_urls_all",
        )
        all_mock_mode = st.checkbox(
            "Gunakan data contoh",
            help="Menampilkan contoh untuk semua platform yang terdeteksi tanpa mengambil data dari tautan.",
            key="social_mock_all",
        )
        all_submitted = st.form_submit_button("Mulai Enrichment All", type="primary", width="stretch")

    if all_submitted:
        all_urls = parse_url_list(all_url_text, preserve_repeated_rows=True)
        if not all_urls:
            st.error("Masukkan setidaknya satu URL posting.")
        elif len(all_urls) > MAX_ENRICHMENT_URLS:
            excess = len(all_urls) - MAX_ENRICHMENT_URLS
            st.error(f"Enrichment All maksimal {MAX_ENRICHMENT_URLS:,} URL. Kurangi {excess:,} URL lalu coba lagi.")
        else:
            grouped_urls, unsupported_urls = group_detected_urls(all_urls)
            st.session_state["social_all_unsupported"] = unsupported_urls
            st.session_state["social_all_order"] = all_urls
            if not grouped_urls:
                st.session_state.pop("social_all_jobs", None)
                st.error("Tidak ada URL dari platform yang didukung.")
            else:
                all_requests = [
                    {
                        "platform": platform,
                        "url_text": "\n".join(grouped_urls[platform]),
                        "mock_mode": all_mock_mode,
                        "enrichment_mode": (
                            instagram_mode
                            if platform == "Instagram"
                            else tiktok_mode
                            if platform == "TikTok"
                            else facebook_mode
                            if platform == "Facebook"
                            else "standard"
                        ),
                    }
                    for platform in PLATFORM_OPTIONS
                    if platform in grouped_urls
                ]
                created_jobs = create_requested_jobs(all_requests)
                if created_jobs:
                    st.session_state["social_all_jobs"] = created_jobs

    unsupported_urls = st.session_state.get("social_all_unsupported", [])
    if unsupported_urls:
        with st.expander(f"{len(unsupported_urls)} URL tidak dikenali", expanded=True):
            st.dataframe(pd.DataFrame(unsupported_urls), width="stretch", hide_index=True)

    all_jobs = load_all_jobs()
    job_panels.extend(render_all_job_panels(all_jobs))
    if all_jobs or unsupported_urls:
        st.markdown("#### Hasil gabungan")
        render_all_job_results(all_jobs, unsupported_urls)
elif layout_mode in {"Split Screen", "Triple Screen"}:
    panel_count = 2 if layout_mode == "Split Screen" else MAX_PARALLEL_PLATFORMS
    panel_word = "dua" if panel_count == 2 else "tiga"
    st.caption(
        f"Pilih {panel_word} platform berbeda. Semuanya diproses bersamaan dengan satu worker per platform; "
        "urutan URL di dalam setiap platform tetap dijaga agar engagement presisi."
    )
    slot_names = ["left", "center", "right"] if panel_count == 3 else ["left", "right"]
    slot_labels = ["kiri", "tengah", "kanan"] if panel_count == 3 else ["kiri", "kanan"]
    default_platforms = ["Facebook", "Threads", "Instagram"]
    setup_columns = st.columns(panel_count, gap="large")
    selected_platforms: list[str] = []
    for index, (column, slot, label) in enumerate(zip(setup_columns, slot_names, slot_labels)):
        options = [platform for platform in PLATFORM_OPTIONS if platform not in selected_platforms]
        preferred = default_platforms[index]
        default_index = options.index(preferred) if preferred in options else 0
        with column:
            platform = st.selectbox(
                f"Platform {label}",
                options,
                index=default_index,
                format_func=lambda value: PLATFORM_ICONS[value],
                key=f"multi_{slot}_platform",
            )
        selected_platforms.append(platform)

    enrichment_modes: list[str] = []
    for column, platform, slot in zip(setup_columns, selected_platforms, slot_names):
        with column:
            enrichment_modes.append(render_platform_setup(platform, slot, compact=True))

    requests: list[dict[str, Any]] = []
    with st.form(f"multi_enrichment_form_{panel_count}"):
        form_columns = st.columns(panel_count, gap="large")
        for column, platform, slot, enrichment_mode in zip(
            form_columns,
            selected_platforms,
            slot_names,
            enrichment_modes,
        ):
            with column:
                url_text = st.text_area(
                    f"Daftar URL {platform}",
                    height=180,
                    placeholder=f"{PLACEHOLDERS[platform]}\n{PLACEHOLDERS[platform]}",
                    key=f"social_urls_{slot}_{platform}",
                )
                mock_mode = st.checkbox(
                    f"Gunakan data contoh {platform}",
                    key=f"social_mock_{slot}_{platform}",
                )
                requests.append(
                    {
                        "platform": platform,
                        "url_text": url_text,
                        "mock_mode": mock_mode,
                        "enrichment_mode": enrichment_mode,
                    }
                )
        button_label = "Mulai Dua Proses" if panel_count == 2 else "Mulai Tiga Proses"
        multi_submitted = st.form_submit_button(button_label, type="primary", width="stretch")

    if multi_submitted:
        create_requested_jobs(requests)

    result_columns = st.columns(panel_count, gap="large")
    for column, platform, slot in zip(result_columns, selected_platforms, slot_names):
        with column:
            st.markdown(f"#### Hasil {platform}")
            job_panels.append(render_job_panel(platform, slot))
else:
    selected_platform = st.segmented_control(
        "Pilih media sosial",
        PLATFORM_OPTIONS,
        default="YouTube",
        format_func=lambda value: PLATFORM_ICONS[value],
        key="single_enrichment_platform",
        width="stretch",
    )
    enrichment_mode = render_platform_setup(selected_platform, "single")
    with st.form(f"enrichment_form_single_{selected_platform}"):
        url_text = st.text_area(
            f"Daftar URL {selected_platform}",
            height=180,
            placeholder=f"{PLACEHOLDERS[selected_platform]}\n{PLACEHOLDERS[selected_platform]}",
            key=f"social_urls_single_{selected_platform}",
        )
        mock_mode = st.checkbox(
            "Gunakan data contoh",
            help=f"Pilihan ini menampilkan contoh hasil {selected_platform} tanpa mengambil data dari tautan.",
            key=f"social_mock_single_{selected_platform}",
        )
        submit_label = (
            "Mulai Fast Enrichment"
            if enrichment_mode == "fast"
            else "Mulai Advanced Enrichment"
            if enrichment_mode == "advanced"
            else "Mulai TikTok Free Mode"
            if enrichment_mode == "free"
            else "Ambil Semua Metadata"
        )
        submitted = st.form_submit_button(submit_label, type="primary", width="stretch")
    if submitted:
        create_requested_jobs(
            [
                {
                    "platform": selected_platform,
                    "url_text": url_text,
                    "mock_mode": mock_mode,
                    "enrichment_mode": enrichment_mode,
                }
            ]
        )
    job_panels.append(render_job_panel(selected_platform, "single"))

run_active_jobs(job_panels)
render_footer()
