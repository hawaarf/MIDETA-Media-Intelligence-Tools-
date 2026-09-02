"""MIDETA Social Media Enrichment batch page."""
import pandas as pd
import streamlit as st
from src.batch import SOCIAL_BATCH_VERSION, compact_social_export_row, is_current_social_batch, parse_url_list, social_result_row
from src.connectors import PLATFORM_OPTIONS, get_platform_connector
from src.database import add_history
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.models import FieldStatus
from src.ui import apply_theme, page_intro, status_label

st.set_page_config(page_title="Social Media Enrichment | MIDETA", page_icon="📊", layout="wide")
apply_theme()
page_intro("01", "Social Media Enrichment", "Masukkan beberapa tautan YouTube, TikTok, Facebook, Instagram, Threads, atau X untuk melihat metadata publiknya.")
st.info("Tulis satu URL pada setiap baris. Followers dan Views pada Facebook, Instagram, TikTok, serta Threads akan ditampilkan sebagai 0 jika platform tidak menyediakan angkanya.")

platform_icons = {"YouTube": "▶ YouTube", "TikTok": "♪ TikTok", "Facebook": "f Facebook", "Instagram": "◎ Instagram", "Threads": "@ Threads", "X": "𝕏 X"}
placeholders = {"YouTube": "https://www.youtube.com/watch?v=contoh", "TikTok": "https://www.tiktok.com/@akun/video/contoh", "Facebook": "https://www.facebook.com/akun/posts/contoh", "Instagram": "https://www.instagram.com/p/contoh", "Threads": "https://www.threads.net/@akun/post/contoh", "X": "https://x.com/akun/status/contoh"}
selected_platform = st.segmented_control("Pilih media sosial", PLATFORM_OPTIONS, default="YouTube", format_func=lambda value: platform_icons[value], width="stretch")
st.caption(f"Bagian ini khusus untuk URL {selected_platform}.")

with st.form(f"enrichment_form_{selected_platform}"):
    url_text = st.text_area(f"Daftar URL {selected_platform}", height=180, placeholder=f"{placeholders[selected_platform]}\n{placeholders[selected_platform]}", key=f"social_urls_{selected_platform}")
    mock_mode = st.checkbox("Gunakan data contoh", help=f"Pilihan ini menampilkan contoh hasil {selected_platform} tanpa mengambil data dari tautan.", key=f"social_mock_{selected_platform}")
    submitted = st.form_submit_button("Ambil Semua Metadata", type="primary", width="stretch")

if submitted:
    urls = parse_url_list(url_text)
    if not urls:
        st.error("Masukkan setidaknya satu URL posting.")
    else:
        progress = st.progress(0, text="Menyiapkan daftar URL…")
        results, errors = [], []
        for index, url in enumerate(urls, 1):
            try:
                connector = get_platform_connector(url, selected_platform)
                progress.progress(int((index - 1) / len(urls) * 100), text=f"Memeriksa {connector.platform} pada URL {index} dari {len(urls)}…")
                result = connector.mock_enrichment(url) if mock_mode else connector.enrich(url)
                fields = [result.username, result.caption, result.posted_at, result.followers, result.likes, result.comments, result.shares, result.views, result.bookmarks, result.reposts]
                has_data = any(field.status == FieldStatus.AVAILABLE for field in fields)
                history_status = "mock" if result.is_mock else "completed" if has_data else "failed"
                add_history("Social Media Enrichment", result.url, history_status, result.model_dump(mode="json"), result.platform)
                results.append(result.model_dump(mode="json"))
            except Exception as exc:
                errors.append({"URL": url, "Platform": selected_platform, "Alasan": str(exc)})
        progress.progress(100, text="Semua URL selesai diperiksa")
        batches = st.session_state.setdefault("social_platform_batches", {})
        batches[selected_platform] = {"schema_version": SOCIAL_BATCH_VERSION, "results": results, "errors": errors}

batches = st.session_state.setdefault("social_platform_batches", {})
stored_batch = batches.get(selected_platform, {})
if stored_batch and not is_current_social_batch(stored_batch):
    batches.pop(selected_platform, None)
    st.info("Parser MIDETA baru saja diperbarui. Jalankan kembali URL agar hasil yang tampil menggunakan pembacaan terbaru.")
current_batch = batches.get(selected_platform, {})
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
    metric_cols[2].metric("Perlu diperiksa", len(results) - successful + len(current_batch.get("errors", [])))

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
