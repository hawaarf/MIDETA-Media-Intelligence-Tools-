"""MIDETA public comment scrapper batch page."""
import pandas as pd
import streamlit as st
from src.batch import parse_url_list, rank_comment_rows
from src.connectors import PLATFORM_OPTIONS, get_platform_connector
from src.database import add_history
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.models import FieldStatus
from src.ui import apply_theme, page_intro, status_label

st.set_page_config(page_title="Comment Scrapper | MIDETA", page_icon="💬", layout="wide")
apply_theme()
page_intro("02", "Comment Scrapper", "Kumpulkan komentar publik dari YouTube, TikTok, Facebook, Instagram, Threads, atau X dan urutkan berdasarkan engagement.")
st.warning("Tulis satu URL pada setiap baris. MIDETA hanya mengambil komentar yang tersedia secara publik dan tidak melewati login atau batas akses platform.")

platform_icons = {"YouTube": "▶ YouTube", "TikTok": "♪ TikTok", "Facebook": "f Facebook", "Instagram": "◎ Instagram", "Threads": "@ Threads", "X": "𝕏 X"}
placeholders = {"YouTube": "https://www.youtube.com/watch?v=contoh", "TikTok": "https://www.tiktok.com/@akun/video/contoh", "Facebook": "https://www.facebook.com/akun/posts/contoh", "Instagram": "https://www.instagram.com/p/contoh", "Threads": "https://www.threads.net/@akun/post/contoh", "X": "https://x.com/akun/status/contoh"}
selected_platform = st.segmented_control("Pilih media sosial", PLATFORM_OPTIONS, default="YouTube", format_func=lambda value: platform_icons[value], width="stretch")
st.caption(f"Bagian ini khusus untuk komentar {selected_platform}.")

with st.form(f"comments_form_{selected_platform}"):
    url_text = st.text_area(f"Daftar URL {selected_platform}", height=180, placeholder=f"{placeholders[selected_platform]}\n{placeholders[selected_platform]}", key=f"comment_urls_{selected_platform}")
    mock_mode = st.checkbox("Gunakan data contoh", help=f"Pilihan ini menampilkan contoh parent dan reply {selected_platform}.", key=f"comment_mock_{selected_platform}")
    submitted = st.form_submit_button("Ambil Semua Komentar", type="primary", width="stretch")

if submitted:
    urls = parse_url_list(url_text)
    if not urls:
        st.error("Masukkan setidaknya satu URL posting.")
    else:
        progress = st.progress(0, text="Menyiapkan daftar URL…")
        rows, issues = [], []
        for index, url in enumerate(urls, 1):
            try:
                connector = get_platform_connector(url, selected_platform)
                progress.progress(int((index - 1) / len(urls) * 100), text=f"Mengambil komentar {connector.platform} pada URL {index} dari {len(urls)}…")
                collection = connector.mock_comments(url) if mock_mode else connector.collect_comments(url)
                history_status = "mock" if collection.is_mock else "completed" if collection.status == FieldStatus.AVAILABLE else "failed"
                add_history("Comment Scrapper", collection.url, history_status, collection.model_dump(mode="json"), collection.platform)
                if collection.comments:
                    for comment in collection.comments:
                        rows.append({"Platform": collection.platform, "URL": collection.url, "Tanggal komentar": comment.commented_at, "Author": comment.author, "Tipe": comment.comment_type, "Likes": comment.likes, "Jumlah reply": comment.reply_count, "Komentar": comment.comment, "Waktu pengambilan": comment.collected_at.isoformat(), "Data contoh": collection.is_mock})
                else:
                    issues.append({"URL": collection.url, "Platform": collection.platform, "Status": status_label(collection.status), "Alasan": collection.reason or "Komentar tidak tersedia."})
            except Exception as exc:
                issues.append({"URL": url, "Platform": selected_platform, "Status": "Gagal", "Alasan": str(exc)})
        progress.progress(100, text="Semua URL selesai diperiksa")
        batches = st.session_state.setdefault("comment_platform_batches", {})
        batches[selected_platform] = {"rows": rank_comment_rows(rows), "issues": issues}

current_batch = st.session_state.get("comment_platform_batches", {}).get(selected_platform, {})
if rows := current_batch.get("rows"):
    if any(row.get("Data contoh") for row in rows):
        st.warning("DATA CONTOH AKTIF. Komentar di bawah hanya untuk melihat bentuk hasil dan bukan data dari tautan.")
    metrics = st.columns(3)
    metrics[0].metric("Komentar terkumpul", len(rows))
    metrics[1].metric("Parent", sum(row.get("Tipe") == "parent" for row in rows))
    metrics[2].metric("Reply", sum(row.get("Tipe") == "reply" for row in rows))
    visible_columns = ["Rank", "Platform", "Tanggal komentar", "Author", "Tipe", "Likes", "Jumlah reply", "Skor engagement", "Komentar", "URL"]
    st.dataframe(pd.DataFrame(rows).reindex(columns=visible_columns).fillna("Tidak tersedia"), width="stretch", hide_index=True)
    st.caption("Ranking dihitung dari jumlah like ditambah dua kali jumlah reply. Komentar dengan engagement tertinggi ditampilkan lebih dulu.")
    csv_col, xlsx_col = st.columns(2)
    filename = selected_platform.lower().replace(" ", "_")
    csv_col.download_button("Unduh CSV", to_csv_bytes(rows), f"mideta_comments_{filename}.csv", "text/csv", width="stretch")
    xlsx_col.download_button("Unduh XLSX", to_xlsx_bytes(rows, selected_platform), f"mideta_comments_{filename}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
elif "rows" in current_batch:
    st.info("Belum ada komentar yang dapat dikumpulkan dari daftar URL tersebut.")

if issues := current_batch.get("issues"):
    with st.expander(f"{len(issues)} URL memerlukan perhatian", expanded=True):
        st.dataframe(pd.DataFrame(issues), width="stretch", hide_index=True)
