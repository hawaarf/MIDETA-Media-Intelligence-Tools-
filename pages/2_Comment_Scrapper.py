"""MIDETA public comment scrapper batch page."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from typing import Any

import pandas as pd
import streamlit as st

from src.batch import COMMENT_BATCH_VERSION, compact_comment_export_rows, parse_url_list, rank_comment_rows
from src.comment_browser import CommentBrowserCollector, CommentBrowserError
from src.config import MAX_ENRICHMENT_URLS, MAX_PARALLEL_PLATFORMS, MIDETA_LOGO_PATH
from src.connectors import PLATFORM_OPTIONS, get_platform_connector
from src.database import add_history
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.models import FieldStatus
from src.ui import apply_theme, page_intro, render_footer, render_github_profile, render_platform_guide, status_label


st.set_page_config(page_title="Comment Scrapper | MIDETA", page_icon=str(MIDETA_LOGO_PATH), layout="wide")
apply_theme()
render_github_profile()
page_intro(
    "02",
    "Comment Scrapper",
    "Kumpulkan komentar publik dari YouTube, TikTok, Facebook, Instagram, Threads, atau X dan urutkan berdasarkan engagement.",
)
st.warning(
    "Tulis satu URL pada setiap baris. MIDETA hanya mengambil komentar yang dapat ditampilkan oleh platform. "
    f"Split atau Triple Screen dapat menjalankan maksimal {MAX_PARALLEL_PLATFORMS} platform dengan proses dan hasil terpisah."
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
def comment_browser(platform: str) -> CommentBrowserCollector:
    return CommentBrowserCollector(platform)


def render_browser_controls(platform: str, slot: str) -> None:
    st.info(f"Mode browser {platform} aktif otomatis karena komentar dimuat dari percakapan di Chrome MIDETA.")
    st.caption(
        f"Login cukup dilakukan sekali. Sesi {platform} disimpan di profil Chrome khusus MIDETA dan dipakai kembali "
        f"sampai sesi {platform} kedaluwarsa atau Anda logout."
    )
    open_col, check_col, close_col = st.columns(3)
    if open_col.button(f"Buka Sesi {platform}", key=f"open_comment_{slot}_{platform}", width="stretch"):
        try:
            if comment_browser(platform).open_login():
                st.success(f"Sesi {platform} tersimpan masih aktif; tidak perlu login lagi.")
            else:
                st.info("Selesaikan login satu kali di Chrome MIDETA, lalu tekan Periksa Login.")
        except CommentBrowserError as exc:
            st.error(str(exc))
    if check_col.button("Periksa Login", key=f"check_comment_{slot}_{platform}", width="stretch"):
        try:
            if comment_browser(platform).is_logged_in():
                st.success("Login tersimpan. Scraping berikutnya akan memakai sesi ini otomatis.")
            else:
                st.warning("Login belum terdeteksi. Komentar publik tetap akan dicoba; login mungkin diperlukan untuk hasil lengkap.")
        except CommentBrowserError as exc:
            st.error(str(exc))
    if close_col.button("Tutup Chrome", key=f"close_comment_{slot}_{platform}", width="stretch"):
        comment_browser(platform).close()
        st.info(f"Chrome MIDETA untuk {platform} sudah ditutup.")


def render_platform_setup(platform: str, slot: str, compact: bool = False) -> None:
    if compact:
        st.subheader(PLATFORM_ICONS[platform])
        st.caption(f"Panel ini khusus untuk komentar {platform}.")
        with st.expander(f"Cara pakai {platform}"):
            render_platform_guide("comments", platform)
    else:
        st.caption(f"Bagian ini khusus untuk komentar {platform}.")
        render_platform_guide("comments", platform)
    if platform in {"Threads", "X"}:
        render_browser_controls(platform, slot)


def validate_requests(requests: list[dict[str, Any]]) -> bool:
    valid = True
    for request in requests:
        urls = parse_url_list(request["url_text"])
        request["urls"] = urls
        if not urls:
            st.error(f"{request['platform']}: masukkan setidaknya satu URL posting.")
            valid = False
        elif len(urls) > MAX_ENRICHMENT_URLS:
            excess = len(urls) - MAX_ENRICHMENT_URLS
            st.error(
                f"{request['platform']}: maksimal {MAX_ENRICHMENT_URLS:,} URL. "
                f"Kurangi {excess:,} URL lalu coba lagi."
            )
            valid = False
    return valid


def collect_comment_url(
    request: dict[str, Any],
    url: str,
    active_browser: CommentBrowserCollector | None,
    include_preview: bool,
) -> dict[str, Any]:
    platform = request["platform"]
    try:
        connector = get_platform_connector(url, platform)
        preview = None
        if include_preview:
            preview_result = connector.mock_enrichment(url) if request["mock_mode"] else connector.enrich(url)
            preview = {
                "Platform": preview_result.platform,
                "URL": preview_result.url,
                "Author": preview_result.username.value or "Tidak tersedia",
                "Caption": preview_result.caption.value or "Tidak tersedia",
            }
        if request["mock_mode"]:
            collection = connector.mock_comments(url)
        elif active_browser is not None:
            collection = active_browser.collect(url)
        else:
            collection = connector.collect_comments(url)
        return {"kind": "completed", "collection": collection, "preview": preview}
    except Exception as exc:
        return {
            "kind": "failed",
            "issue": {
                "URL": url,
                "Platform": platform,
                "Status": "Gagal",
                "Alasan": str(exc),
            },
        }


def collect_comment_platform(task: dict[str, Any], output: Queue) -> None:
    platform = task["request"]["platform"]
    try:
        for index, url in enumerate(task["request"]["urls"]):
            outcome = collect_comment_url(
                task["request"],
                url,
                task["active_browser"],
                include_preview=index == 0,
            )
            output.put((platform, outcome))
    finally:
        output.put((platform, None))


def store_collection(state: dict[str, Any], outcome: dict[str, Any]) -> None:
    if outcome["kind"] == "failed":
        state["issues"].append(outcome["issue"])
        return
    collection = outcome["collection"]
    if state["preview"] is None and outcome.get("preview"):
        state["preview"] = outcome["preview"]
    history_status = (
        "mock"
        if collection.is_mock
        else "completed"
        if collection.status == FieldStatus.AVAILABLE
        else "failed"
    )
    add_history(
        "Comment Scrapper",
        collection.url,
        history_status,
        collection.model_dump(mode="json"),
        collection.platform,
    )
    if collection.comments:
        for comment in collection.comments:
            state["rows"].append(
                {
                    "Platform": collection.platform,
                    "URL": collection.url,
                    "Tanggal komentar": comment.commented_at,
                    "Author": comment.author,
                    "Tipe": comment.comment_type,
                    "Likes": comment.likes,
                    "Jumlah reply": comment.reply_count,
                    "Komentar": comment.comment,
                    "Waktu pengambilan": comment.collected_at.isoformat(),
                    "Data contoh": collection.is_mock,
                }
            )
    else:
        state["issues"].append(
            {
                "URL": collection.url,
                "Platform": collection.platform,
                "Status": status_label(collection.status),
                "Alasan": collection.reason or "Komentar tidak tersedia.",
            }
        )


def run_comment_requests(requests: list[dict[str, Any]], progress_targets: dict[str, Any]) -> None:
    if not validate_requests(requests):
        return
    batches = st.session_state.setdefault("comment_platform_batches", {})
    states: dict[str, dict[str, Any]] = {}
    tasks: list[dict[str, Any]] = []
    for request in requests:
        platform = request["platform"]
        states[platform] = {
            "rows": [],
            "issues": [],
            "preview": None,
            "processed": 0,
            "total": len(request["urls"]),
        }
        active_browser = None
        if platform in {"Threads", "X"} and not request["mock_mode"]:
            try:
                active_browser = comment_browser(platform)
                active_browser.start()
            except CommentBrowserError as exc:
                states[platform]["issues"].append(
                    {
                        "URL": request["urls"][0],
                        "Platform": platform,
                        "Status": "Gagal",
                        "Alasan": str(exc),
                    }
                )
                progress_targets[platform].progress(100, text=f"{platform}: Chrome tidak dapat dimulai")
                continue
        tasks.append({"request": request, "active_browser": active_browser})
        progress_targets[platform].progress(0, text=f"{platform}: menyiapkan {len(request['urls']):,} URL…")

    if tasks:
        output: Queue = Queue()
        completed_workers = 0
        with ThreadPoolExecutor(
            max_workers=min(len(tasks), MAX_PARALLEL_PLATFORMS),
            thread_name_prefix="mideta-comments",
        ) as executor:
            for task in tasks:
                executor.submit(collect_comment_platform, task, output)
            while completed_workers < len(tasks):
                platform, outcome = output.get()
                if outcome is None:
                    completed_workers += 1
                    continue
                state = states[platform]
                store_collection(state, outcome)
                state["processed"] += 1
                percentage = int(state["processed"] / state["total"] * 100)
                progress_targets[platform].progress(
                    percentage,
                    text=f"{platform}: {state['processed']:,} dari {state['total']:,} URL selesai",
                )

    for platform, state in states.items():
        batches[platform] = {
            "schema_version": COMMENT_BATCH_VERSION,
            "rows": rank_comment_rows(state["rows"]),
            "issues": state["issues"],
            "preview": state["preview"],
        }


def render_comment_result(platform: str, slot: str) -> None:
    batches = st.session_state.setdefault("comment_platform_batches", {})
    stored_batch = batches.get(platform, {})
    if stored_batch and stored_batch.get("schema_version") != COMMENT_BATCH_VERSION:
        batches.pop(platform, None)
        st.info("Format Comment Scrapper baru saja diperbarui. Jalankan kembali URL untuk memakai hasil terbaru.")
        return
    current_batch = batches.get(platform, {})
    rows = current_batch.get("rows")
    if rows:
        if any(row.get("Data contoh") for row in rows):
            st.warning("DATA CONTOH AKTIF. Komentar di bawah bukan data dari tautan.")
        if preview := current_batch.get("preview"):
            st.markdown(f"**{preview['Author']}** · {preview['Platform']}")
            st.write(preview["Caption"])
            st.link_button("Buka postingan", preview["URL"])
        metrics = st.columns(3)
        metrics[0].metric("Komentar", len(rows))
        metrics[1].metric("Parent", sum(row.get("Tipe") == "parent" for row in rows))
        metrics[2].metric("Reply", sum(row.get("Tipe") == "reply" for row in rows))
        st.success(f"Pengambilan selesai. {len(rows)} komentar ditemukan.")
        export_rows = compact_comment_export_rows(rows)
        st.dataframe(pd.DataFrame(export_rows), width="stretch", hide_index=True)
        with st.expander("Lihat sumber dan ranking"):
            detail_columns = ["Rank", "Platform", "URL", "Jumlah reply", "Skor engagement", "Waktu pengambilan"]
            st.dataframe(
                pd.DataFrame(rows).reindex(columns=detail_columns).fillna("Tidak tersedia"),
                width="stretch",
                hide_index=True,
            )
        st.caption("Ranking dihitung dari jumlah like ditambah dua kali jumlah reply.")
        csv_col, xlsx_col = st.columns(2)
        filename = platform.lower().replace(" ", "_")
        csv_col.download_button(
            "Unduh CSV",
            to_csv_bytes(export_rows),
            f"mideta_comments_{filename}.csv",
            "text/csv",
            key=f"download_comments_csv_{slot}_{platform}",
            width="stretch",
        )
        xlsx_col.download_button(
            "Unduh XLSX",
            to_xlsx_bytes(export_rows, platform),
            f"mideta_comments_{filename}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"download_comments_xlsx_{slot}_{platform}",
            width="stretch",
        )
    elif "rows" in current_batch:
        st.info("Belum ada komentar yang dapat dikumpulkan dari daftar URL tersebut.")
    if issues := current_batch.get("issues"):
        with st.expander(f"{len(issues)} URL memerlukan perhatian", expanded=True):
            st.dataframe(pd.DataFrame(issues), width="stretch", hide_index=True)


layout_mode = st.segmented_control(
    "Tampilan proses",
    ("Satu platform", "Split Screen", "Triple Screen"),
    default="Satu platform",
    help="Setiap panel memakai platform, proses, progres, hasil, dan file unduhan yang terpisah.",
    key="comment_scrapper_layout",
    width="stretch",
)

requests: list[dict[str, Any]] = []
result_specs: list[tuple[str, str]] = []
submitted = False

if layout_mode == "Satu platform":
    selected_platform = st.segmented_control(
        "Pilih media sosial",
        PLATFORM_OPTIONS,
        default="YouTube",
        format_func=lambda value: PLATFORM_ICONS[value],
        key="single_comment_platform",
        width="stretch",
    )
    render_platform_setup(selected_platform, "single")
    with st.form(f"comments_form_single_{selected_platform}"):
        url_text = st.text_area(
            f"Daftar URL {selected_platform}",
            height=180,
            placeholder=f"{PLACEHOLDERS[selected_platform]}\n{PLACEHOLDERS[selected_platform]}",
            key=f"comment_urls_single_{selected_platform}",
        )
        mock_mode = st.checkbox(
            "Gunakan data contoh",
            help=f"Pilihan ini menampilkan contoh parent dan reply {selected_platform}.",
            key=f"comment_mock_single_{selected_platform}",
        )
        submitted = st.form_submit_button("Ambil Semua Komentar", type="primary", width="stretch")
    requests = [{"platform": selected_platform, "url_text": url_text, "mock_mode": mock_mode}]
    result_specs = [(selected_platform, "single")]
else:
    panel_count = 2 if layout_mode == "Split Screen" else MAX_PARALLEL_PLATFORMS
    panel_word = "dua" if panel_count == 2 else "tiga"
    st.caption(
        f"Pilih {panel_word} platform berbeda. Satu worker memproses setiap platform secara berurutan, "
        "sementara seluruh panel berjalan bersamaan."
    )
    slot_names = ["left", "center", "right"] if panel_count == 3 else ["left", "right"]
    slot_labels = ["kiri", "tengah", "kanan"] if panel_count == 3 else ["kiri", "kanan"]
    default_platforms = ["Facebook", "Threads", "X"]
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
                key=f"multi_comment_{slot}_platform",
            )
        selected_platforms.append(platform)
    for column, platform, slot in zip(setup_columns, selected_platforms, slot_names):
        with column:
            render_platform_setup(platform, slot, compact=True)

    with st.form(f"multi_comments_form_{panel_count}"):
        form_columns = st.columns(panel_count, gap="large")
        for column, platform, slot in zip(form_columns, selected_platforms, slot_names):
            with column:
                url_text = st.text_area(
                    f"Daftar URL {platform}",
                    height=180,
                    placeholder=f"{PLACEHOLDERS[platform]}\n{PLACEHOLDERS[platform]}",
                    key=f"comment_urls_{slot}_{platform}",
                )
                mock_mode = st.checkbox(
                    f"Gunakan data contoh {platform}",
                    key=f"comment_mock_{slot}_{platform}",
                )
                requests.append({"platform": platform, "url_text": url_text, "mock_mode": mock_mode})
        button_label = "Mulai Dua Proses" if panel_count == 2 else "Mulai Tiga Proses"
        submitted = st.form_submit_button(button_label, type="primary", width="stretch")
    result_specs = list(zip(selected_platforms, slot_names))

if submitted:
    progress_columns = st.columns(len(requests), gap="large")
    progress_targets: dict[str, Any] = {}
    for column, request in zip(progress_columns, requests):
        with column:
            progress_targets[request["platform"]] = st.progress(
                0,
                text=f"{request['platform']}: menyiapkan antrean…",
            )
    run_comment_requests(requests, progress_targets)

if len(result_specs) == 1:
    render_comment_result(*result_specs[0])
else:
    result_columns = st.columns(len(result_specs), gap="large")
    for column, (platform, slot) in zip(result_columns, result_specs):
        with column:
            st.markdown(f"#### Hasil {platform}")
            render_comment_result(platform, slot)

render_footer()
