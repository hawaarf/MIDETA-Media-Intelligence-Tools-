"""MIDETA Social Media Enrichment batch page."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import time
from typing import Any

import pandas as pd
import streamlit as st

from src.batch import SOCIAL_BATCH_VERSION, compact_social_export_row, parse_url_list, social_result_row
from src.config import ENRICHMENT_BROWSER_CHUNK_SIZE, ENRICHMENT_CHUNK_SIZE, ENRICHMENT_FAST_CHUNK_SIZE, MAX_ENRICHMENT_URLS
from src.connectors import PLATFORM_OPTIONS, get_platform_connector
from src.database import add_history, create_social_job, get_latest_social_job, get_social_job, next_social_job_items, record_social_job_item, set_social_job_status
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.instagram_browser import InstagramBrowserCollector, InstagramBrowserError, InstagramLoginRequired, apply_instagram_browser_metrics
from src.models import FieldStatus, SocialResult
from src.ui import apply_theme, page_intro, render_footer, render_github_profile, render_platform_guide, status_label


st.set_page_config(page_title="Social Media Enrichment | MIDETA", page_icon="📊", layout="wide")
apply_theme()
render_github_profile()
page_intro(
    "01",
    "Social Media Enrichment",
    "Masukkan beberapa tautan YouTube, TikTok, Facebook, Instagram, Threads, atau X untuk melihat metadata publiknya.",
)
st.info(
    "Tulis satu URL pada setiap baris. MIDETA dapat menerima sampai 1.000 URL per platform dan menyimpannya bertahap. "
    "Split Screen menjalankan maksimal dua platform secara paralel dengan antrean terpisah."
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
    "TikTok": "https://www.tiktok.com/@akun/video/contoh",
    "Facebook": "https://www.facebook.com/akun/posts/contoh",
    "Instagram": "https://www.instagram.com/p/contoh",
    "Threads": "https://www.threads.net/@akun/post/contoh",
    "X": "https://x.com/akun/status/contoh",
}


@st.cache_resource(show_spinner=False)
def instagram_browser() -> InstagramBrowserCollector:
    return InstagramBrowserCollector()


def job_chunk_size(job: dict[str, Any]) -> int:
    if job.get("enrichment_mode") == "fast":
        return ENRICHMENT_FAST_CHUNK_SIZE
    if job.get("enrichment_mode") == "advanced":
        return ENRICHMENT_BROWSER_CHUNK_SIZE
    return ENRICHMENT_CHUNK_SIZE


def render_instagram_controls(slot: str) -> str:
    mode_label = st.segmented_control(
        "Mode enrichment Instagram",
        ("Fast enrichment", "Advanced enrichment"),
        default="Fast enrichment",
        help="Kedua mode memakai Chrome Instagram yang sudah login. Advanced membuka profil/Reels sehingga waktunya lebih lama.",
        key=f"instagram_enrichment_mode_{slot}",
        width="stretch",
    )
    enrichment_mode = "advanced" if mode_label == "Advanced enrichment" else "fast"
    if enrichment_mode == "fast":
        st.caption(
            "Fast: mengambil author, caption, tanggal, likes, comments, shares, dan repost dari halaman posting. "
            "Followers dan Views tidak dicari."
        )
    else:
        st.caption(
            "Advanced: mengambil seluruh data Fast, lalu membuka profil/Reels untuk Followers dan Views. Proses lebih lama."
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
    return "standard"


def validate_job_request(request: dict[str, Any]) -> str | None:
    urls = parse_url_list(request["url_text"])
    request["urls"] = urls
    if not urls:
        return f"{request['platform']}: masukkan setidaknya satu URL posting."
    if len(urls) > MAX_ENRICHMENT_URLS:
        excess = len(urls) - MAX_ENRICHMENT_URLS
        return f"{request['platform']}: maksimal {MAX_ENRICHMENT_URLS:,} URL. Kurangi {excess:,} URL lalu coba lagi."
    return None


def create_requested_jobs(requests: list[dict[str, Any]]) -> None:
    errors = [error for request in requests if (error := validate_job_request(request))]
    if not errors and any(request["platform"] == "Instagram" and not request["mock_mode"] for request in requests):
        try:
            if not instagram_browser().is_logged_in():
                errors.append("Instagram belum login. Buka Chrome Instagram dan selesaikan login sebelum memulai batch.")
        except InstagramBrowserError as exc:
            errors.append(str(exc))
    if errors:
        for error in errors:
            st.error(error)
        return
    for request in requests:
        platform = request["platform"]
        job_id = create_social_job(
            platform,
            request["urls"],
            SOCIAL_BATCH_VERSION,
            mock_mode=request["mock_mode"],
            browser_mode=platform == "Instagram",
            enrichment_mode=request["enrichment_mode"],
        )
        st.session_state[f"social_job_{platform}"] = job_id


def load_current_job(platform: str) -> dict[str, Any] | None:
    job_key = f"social_job_{platform}"
    job_id = st.session_state.get(job_key)
    current_job = get_social_job(job_id) if job_id else None
    if current_job is None:
        current_job = get_latest_social_job(platform)
        if current_job:
            st.session_state[job_key] = current_job["id"]
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
            f"Mode {mode_text}: {job_chunk_size(job)} URL per tahap. Dalam Split Screen, worker platform ini tetap terpisah."
        )
    else:
        if control_cols[0].button("Lanjutkan proses", key=f"resume_social_{slot}_{job['id']}", type="primary", width="stretch"):
            set_social_job_status(job["id"], "running")
            st.rerun()
        control_cols[1].caption("Hasil yang sudah selesai tetap tersimpan. Tekan Lanjutkan proses untuk meneruskan antrean.")


def render_job_results(job: dict[str, Any] | None, platform: str) -> None:
    if not job or not job.get("results"):
        if job and job["status"] == "completed" and job.get("errors"):
            st.warning("Proses selesai, tetapi belum ada URL yang menghasilkan metadata.")
        return
    results = [SocialResult.model_validate(item) for item in job["results"]]
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
    metric_cols[0].metric("Diproses", len(results) + len(job.get("errors", [])))
    metric_cols[1].metric("Berhasil", successful)
    metric_cols[2].metric(
        "Periksa",
        len(results) - successful + len(job.get("errors", [])) + len(job.get("browser_issues", [])),
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


def render_job_issues(job: dict[str, Any] | None) -> None:
    if not job:
        return
    if errors := job.get("errors"):
        with st.expander(f"{len(errors)} URL tidak dapat diproses", expanded=True):
            st.dataframe(pd.DataFrame(errors), width="stretch", hide_index=True)
    if browser_issues := job.get("browser_issues"):
        with st.expander(f"{len(browser_issues)} URL belum lengkap dari browser", expanded=True):
            st.dataframe(pd.DataFrame(browser_issues), width="stretch", hide_index=True)


def render_job_panel(platform: str, slot: str) -> tuple[dict[str, Any] | None, Any]:
    job = load_current_job(platform)
    if job and job["platform"] == "Instagram":
        st.caption(f"Antrean aktif menggunakan **{job['enrichment_mode'].title()} enrichment**.")
    if job:
        render_job_controls(job, slot)
    activity = st.empty()
    render_job_results(job, platform)
    render_job_issues(job)
    return job, activity


def collect_one_item(job: dict[str, Any], item: dict[str, Any], active_browser: InstagramBrowserCollector | None) -> dict[str, Any]:
    url = item["url"]
    position = item["position"]
    try:
        connector = get_platform_connector(url, job["platform"])
        if job["mock_mode"]:
            result = connector.mock_enrichment(url)
        elif active_browser is not None:
            result = connector.enrich(url, include_platform_profile=False)
        else:
            result = connector.enrich(url)

        browser_issue = None
        if active_browser is not None:
            try:
                metrics = active_browser.collect(
                    result.url,
                    result.username.value,
                    mode=job["enrichment_mode"],
                )
                result = apply_instagram_browser_metrics(result, metrics, mode=job["enrichment_mode"])
            except InstagramLoginRequired as exc:
                return {"kind": "login_required", "reason": str(exc), "position": position, "url": url}
            except InstagramBrowserError as exc:
                browser_issue = {"URL": url, "Alasan": str(exc)}
                result.note = f"{result.note} Pemeriksaan melalui browser belum berhasil: {exc}".strip()

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
    try:
        for item in task["chunk"]:
            outcome = collect_one_item(job, item, task["active_browser"])
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
        activity.error("Sesi Instagram berakhir. Login kembali, lalu lanjutkan proses.")
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
        if job["platform"] == "Instagram" and not job["mock_mode"]:
            try:
                active_browser = instagram_browser()
                if not active_browser.is_logged_in():
                    set_social_job_status(job["id"], "paused")
                    activity.error("Sesi Instagram berakhir. Login kembali, lalu lanjutkan proses.")
                    state_changed = True
                    continue
            except InstagramBrowserError as exc:
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
    with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="mideta-platform") as executor:
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
    ("Satu platform", "Split Screen"),
    default="Satu platform",
    help="Split Screen menjalankan dua platform berbeda secara paralel. Setiap platform tetap memakai parser, antrean, dan hasilnya sendiri.",
    key="social_enrichment_layout",
    width="stretch",
)

job_panels: list[tuple[dict[str, Any] | None, Any]] = []

if layout_mode == "Split Screen":
    st.caption(
        "Pilih dua platform berbeda. Keduanya diproses bersamaan dengan satu worker per platform; urutan URL di dalam setiap platform tetap dijaga agar engagement presisi."
    )
    left_col, right_col = st.columns(2, gap="large")
    with left_col:
        left_platform = st.selectbox(
            "Platform kiri",
            PLATFORM_OPTIONS,
            index=PLATFORM_OPTIONS.index("Facebook"),
            format_func=lambda value: PLATFORM_ICONS[value],
            key="split_left_platform",
        )
    right_options = [platform for platform in PLATFORM_OPTIONS if platform != left_platform]
    right_default = right_options.index("Threads") if "Threads" in right_options else 0
    with right_col:
        right_platform = st.selectbox(
            "Platform kanan",
            right_options,
            index=right_default,
            format_func=lambda value: PLATFORM_ICONS[value],
            key="split_right_platform",
        )

    with left_col:
        left_mode = render_platform_setup(left_platform, "left", compact=True)
    with right_col:
        right_mode = render_platform_setup(right_platform, "right", compact=True)

    with st.form("split_enrichment_form"):
        form_left, form_right = st.columns(2, gap="large")
        with form_left:
            left_url_text = st.text_area(
                f"Daftar URL {left_platform}",
                height=180,
                placeholder=f"{PLACEHOLDERS[left_platform]}\n{PLACEHOLDERS[left_platform]}",
                key=f"social_urls_left_{left_platform}",
            )
            left_mock = st.checkbox(
                f"Gunakan data contoh {left_platform}",
                key=f"social_mock_left_{left_platform}",
            )
        with form_right:
            right_url_text = st.text_area(
                f"Daftar URL {right_platform}",
                height=180,
                placeholder=f"{PLACEHOLDERS[right_platform]}\n{PLACEHOLDERS[right_platform]}",
                key=f"social_urls_right_{right_platform}",
            )
            right_mock = st.checkbox(
                f"Gunakan data contoh {right_platform}",
                key=f"social_mock_right_{right_platform}",
            )
        split_submitted = st.form_submit_button("Mulai Dua Proses", type="primary", width="stretch")

    if split_submitted:
        create_requested_jobs(
            [
                {
                    "platform": left_platform,
                    "url_text": left_url_text,
                    "mock_mode": left_mock,
                    "enrichment_mode": left_mode,
                },
                {
                    "platform": right_platform,
                    "url_text": right_url_text,
                    "mock_mode": right_mock,
                    "enrichment_mode": right_mode,
                },
            ]
        )

    result_left, result_right = st.columns(2, gap="large")
    with result_left:
        st.markdown(f"#### Hasil {left_platform}")
        job_panels.append(render_job_panel(left_platform, "left"))
    with result_right:
        st.markdown(f"#### Hasil {right_platform}")
        job_panels.append(render_job_panel(right_platform, "right"))
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
