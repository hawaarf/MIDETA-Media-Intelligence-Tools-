"""MIDETA Social Media Enrichment batch page."""
import time

import pandas as pd
import streamlit as st
from src.batch import SOCIAL_BATCH_VERSION, compact_social_export_row, is_current_social_batch, parse_url_list, social_result_row
from src.config import ENRICHMENT_BROWSER_CHUNK_SIZE, ENRICHMENT_CHUNK_SIZE, MAX_ENRICHMENT_URLS
from src.connectors import PLATFORM_OPTIONS, get_platform_connector
from src.database import add_history, create_social_job, get_latest_social_job, get_social_job, next_social_job_items, record_social_job_item, set_social_job_status
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.instagram_browser import InstagramBrowserCollector, InstagramBrowserError, apply_instagram_browser_metrics
from src.models import FieldStatus
from src.ui import apply_theme, page_intro, render_footer, render_github_profile, render_platform_guide, status_label

st.set_page_config(page_title="Social Media Enrichment | MIDETA", page_icon="📊", layout="wide")
apply_theme()
render_github_profile()
page_intro("01", "Social Media Enrichment", "Masukkan beberapa tautan YouTube, TikTok, Facebook, Instagram, Threads, atau X untuk melihat metadata publiknya.")
st.info("Tulis satu URL pada setiap baris. MIDETA dapat menerima sampai 1.000 URL dan menyimpannya bertahap agar proses tidak hilang jika aplikasi terhenti. Followers dan Views menjadi 0 jika angkanya tidak tersedia.")

platform_icons = {"YouTube": "▶ YouTube", "TikTok": "♪ TikTok", "Facebook": "f Facebook", "Instagram": "◎ Instagram", "Threads": "@ Threads", "X": "𝕏 X"}
placeholders = {"YouTube": "https://www.youtube.com/watch?v=contoh", "TikTok": "https://www.tiktok.com/@akun/video/contoh", "Facebook": "https://www.facebook.com/akun/posts/contoh", "Instagram": "https://www.instagram.com/p/contoh", "Threads": "https://www.threads.net/@akun/post/contoh", "X": "https://x.com/akun/status/contoh"}
selected_platform = st.segmented_control("Pilih media sosial", PLATFORM_OPTIONS, default="YouTube", format_func=lambda value: platform_icons[value], width="stretch")
st.caption(f"Bagian ini khusus untuk URL {selected_platform}.")
render_platform_guide("enrichment", selected_platform)

@st.cache_resource(show_spinner=False)
def instagram_browser() -> InstagramBrowserCollector:
    return InstagramBrowserCollector()

browser_mode = False
if selected_platform == "Instagram":
    browser_mode = st.toggle(
        "Gunakan browser Instagram",
        help="Mode ini memakai Chrome khusus MIDETA yang sudah login untuk membaca followers, views, dan repost yang tidak ada pada halaman publik.",
        key="instagram_browser_mode",
    )
    if browser_mode:
        st.caption("Login hanya dilakukan di Chrome khusus MIDETA. Password tidak dibaca aplikasi dan profil browser tidak dimasukkan ke GitHub.")
        login_col, check_col, close_col = st.columns(3)
        if login_col.button("Buka Chrome Instagram", width="stretch"):
            try:
                instagram_browser().open_login()
                st.info("Selesaikan login di jendela Chrome yang terbuka, lalu tekan Periksa Login.")
            except InstagramBrowserError as exc:
                st.error(str(exc))
        if check_col.button("Periksa Login", width="stretch"):
            try:
                if instagram_browser().is_logged_in():
                    st.success("Instagram sudah login dan siap digunakan.")
                else:
                    st.warning("Login belum terdeteksi. Selesaikan login di Chrome MIDETA.")
            except InstagramBrowserError as exc:
                st.error(str(exc))
        if close_col.button("Tutup Chrome MIDETA", width="stretch"):
            instagram_browser().close()
            st.info("Chrome MIDETA sudah ditutup.")

with st.form(f"enrichment_form_{selected_platform}"):
    url_text = st.text_area(f"Daftar URL {selected_platform}", height=180, placeholder=f"{placeholders[selected_platform]}\n{placeholders[selected_platform]}", key=f"social_urls_{selected_platform}")
    mock_mode = st.checkbox("Gunakan data contoh", help=f"Pilihan ini menampilkan contoh hasil {selected_platform} tanpa mengambil data dari tautan.", key=f"social_mock_{selected_platform}")
    submitted = st.form_submit_button("Ambil Semua Metadata", type="primary", width="stretch")

if submitted:
    urls = parse_url_list(url_text)
    if not urls:
        st.error("Masukkan setidaknya satu URL posting.")
    elif len(urls) > MAX_ENRICHMENT_URLS:
        st.error(f"Maksimal {MAX_ENRICHMENT_URLS:,} URL untuk satu proses. Kurangi {len(urls) - MAX_ENRICHMENT_URLS:,} URL lalu coba lagi.")
        urls = []
    elif selected_platform == "Instagram" and browser_mode and not mock_mode:
        try:
            if not instagram_browser().is_logged_in():
                st.error("Instagram belum login. Buka Chrome Instagram dan selesaikan login sebelum memulai batch.")
                urls = []
        except InstagramBrowserError as exc:
            st.error(str(exc))
            urls = []
    if urls:
        job_id = create_social_job(
            selected_platform,
            urls,
            SOCIAL_BATCH_VERSION,
            mock_mode=mock_mode,
            browser_mode=browser_mode,
        )
        st.session_state[f"social_job_{selected_platform}"] = job_id
        st.session_state.setdefault("social_platform_batches", {}).pop(selected_platform, None)

job_key = f"social_job_{selected_platform}"
job_id = st.session_state.get(job_key)
current_job = get_social_job(job_id) if job_id else None
if current_job is None:
    current_job = get_latest_social_job(selected_platform)
    if current_job:
        st.session_state[job_key] = current_job["id"]

if current_job and current_job.get("schema_version") != SOCIAL_BATCH_VERSION:
    current_job = None
    st.session_state.pop(job_key, None)
    st.info("Parser MIDETA baru saja diperbarui. Mulai proses baru agar hasil menggunakan pembacaan terbaru.")

if current_job and current_job["status"] in {"running", "paused"}:
    percentage = int(current_job["processed"] / current_job["total"] * 100) if current_job["total"] else 0
    current_chunk_size = ENRICHMENT_BROWSER_CHUNK_SIZE if current_job["browser_mode"] else ENRICHMENT_CHUNK_SIZE
    st.progress(percentage, text=f"{current_job['processed']:,} dari {current_job['total']:,} URL sudah disimpan")
    control_cols = st.columns([2, 2, 5])
    if current_job["status"] == "running":
        if control_cols[0].button("Jeda proses", width="stretch"):
            set_social_job_status(current_job["id"], "paused")
            st.rerun()
        control_cols[2].caption(f"MIDETA memproses {current_chunk_size} URL per tahap dan melanjutkan otomatis.")
    else:
        if control_cols[0].button("Lanjutkan proses", type="primary", width="stretch"):
            set_social_job_status(current_job["id"], "running")
            st.rerun()
        control_cols[2].caption("Hasil yang sudah selesai tetap tersimpan. Tekan Lanjutkan proses untuk meneruskan antrean.")

if current_job and current_job["status"] == "running":
    active_browser = None
    if current_job["platform"] == "Instagram" and current_job["browser_mode"] and not current_job["mock_mode"]:
        try:
            active_browser = instagram_browser()
            if not active_browser.is_logged_in():
                set_social_job_status(current_job["id"], "paused")
                st.error("Sesi Instagram berakhir. Login kembali, lalu tekan Lanjutkan proses.")
                st.stop()
        except InstagramBrowserError as exc:
            set_social_job_status(current_job["id"], "paused")
            st.error(str(exc))
            st.stop()

    chunk_size = ENRICHMENT_BROWSER_CHUNK_SIZE if current_job["browser_mode"] else ENRICHMENT_CHUNK_SIZE
    chunk = next_social_job_items(current_job["id"], chunk_size)
    if not chunk:
        set_social_job_status(current_job["id"], "completed")
        st.rerun()

    progress = st.progress(
        int(current_job["processed"] / current_job["total"] * 100),
        text=f"Menyiapkan tahap berikutnya dari {current_job['total']:,} URL…",
    )
    for item in chunk:
        url = item["url"]
        position = item["position"]
        try:
            connector = get_platform_connector(url, current_job["platform"])
            progress.progress(
                int((position - 1) / current_job["total"] * 100),
                text=f"Memeriksa {connector.platform} pada URL {position:,} dari {current_job['total']:,}…",
            )
            result = connector.mock_enrichment(url) if current_job["mock_mode"] else connector.enrich(url)
            browser_issue = None
            if active_browser is not None:
                progress.progress(
                    int((position - 1) / current_job["total"] * 100),
                    text=f"Membaca tampilan Instagram pada URL {position:,} dari {current_job['total']:,}…",
                )
                try:
                    metrics = active_browser.collect(result.url, result.username.value)
                    result = apply_instagram_browser_metrics(result, metrics)
                except InstagramBrowserError as exc:
                    browser_issue = {"URL": url, "Alasan": str(exc)}
                    result.note = f"{result.note} Pemeriksaan melalui browser belum berhasil: {exc}".strip()
            fields = [result.username, result.caption, result.posted_at, result.followers, result.likes, result.comments, result.shares, result.views, result.bookmarks, result.reposts]
            has_data = any(field.status == FieldStatus.AVAILABLE for field in fields)
            history_status = "mock" if result.is_mock else "completed" if has_data else "failed"
            result_data = result.model_dump(mode="json")
            add_history("Social Media Enrichment", result.url, history_status, result_data, result.platform)
            record_social_job_item(
                current_job["id"],
                position,
                "completed",
                result=result_data,
                browser_issue=browser_issue,
            )
        except Exception as exc:
            reason = str(exc)
            if "permintaan dibatasi" in reason.casefold() or "http 429" in reason.casefold():
                set_social_job_status(current_job["id"], "paused")
                st.warning("Platform sedang membatasi request. Antrean dijeda dan URL ini akan dicoba lagi saat proses dilanjutkan.")
                st.stop()
            record_social_job_item(
                current_job["id"],
                position,
                "failed",
                error={"URL": url, "Platform": current_job["platform"], "Alasan": reason},
            )
        progress.progress(
            int(position / current_job["total"] * 100),
            text=f"{position:,} dari {current_job['total']:,} URL sudah disimpan",
        )

    updated_job = get_social_job(current_job["id"])
    if updated_job and updated_job["status"] != "completed":
        time.sleep(0.3)
    st.rerun()

if current_job:
    current_batch = {
        "schema_version": current_job["schema_version"],
        "results": current_job["results"],
        "errors": current_job["errors"],
        "browser_issues": current_job["browser_issues"],
        "processed": current_job["processed"],
        "total": current_job["total"],
        "status": current_job["status"],
    }
else:
    batches = st.session_state.setdefault("social_platform_batches", {})
    stored_batch = batches.get(selected_platform, {})
    if stored_batch and not is_current_social_batch(stored_batch):
        batches.pop(selected_platform, None)
        stored_batch = {}
    current_batch = stored_batch
if raw_results := current_batch.get("results"):
    from src.models import SocialResult
    results = [SocialResult.model_validate(item) for item in raw_results]
    if any(result.is_mock for result in results):
        st.warning("DATA CONTOH AKTIF. Informasi di bawah hanya untuk melihat bentuk hasil dan bukan data dari tautan.")
    all_fields = lambda result: [result.username, result.caption, result.posted_at, result.followers, result.likes, result.comments, result.shares, result.views, result.bookmarks, result.reposts]
    successful = sum(any(field.status == FieldStatus.AVAILABLE for field in all_fields(result)) for result in results)
    metric_cols = st.columns(3)
    metric_cols[0].metric("URL diproses", len(results) + len(current_batch.get("errors", [])))
    metric_cols[1].metric("Berhasil", successful)
    metric_cols[2].metric("Perlu diperiksa", len(results) - successful + len(current_batch.get("errors", [])) + len(current_batch.get("browser_issues", [])))

    detail_rows = [social_result_row(result) for result in results]
    for row in detail_rows:
        for key in list(row):
            if key.startswith("Status "):
                row[key] = status_label(row[key])
    export_rows = [compact_social_export_row(result) for result in results]
    visible_frame = pd.DataFrame(export_rows).astype(str)
    st.dataframe(visible_frame, width="stretch", hide_index=True)
    with st.expander("Lihat status setiap data"):
        status_columns = ["Platform", "URL"] + [column for column in pd.DataFrame(detail_rows).columns if column.startswith("Status ")] + ["Catatan"]
        st.dataframe(pd.DataFrame(detail_rows).reindex(columns=status_columns).fillna("Tidak tersedia"), width="stretch", hide_index=True)
    csv_col, xlsx_col = st.columns(2)
    filename = selected_platform.lower().replace(" ", "_")
    csv_col.download_button("Unduh CSV", to_csv_bytes(export_rows), f"mideta_{filename}.csv", "text/csv", width="stretch")
    xlsx_col.download_button("Unduh XLSX", to_xlsx_bytes(export_rows, selected_platform), f"mideta_{filename}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")

if errors := current_batch.get("errors"):
    with st.expander(f"{len(errors)} URL tidak dapat diproses", expanded=True):
        st.dataframe(pd.DataFrame(errors), width="stretch", hide_index=True)

if browser_issues := current_batch.get("browser_issues"):
    with st.expander(f"{len(browser_issues)} URL belum lengkap dari browser", expanded=True):
        st.dataframe(pd.DataFrame(browser_issues), width="stretch", hide_index=True)

render_footer()
