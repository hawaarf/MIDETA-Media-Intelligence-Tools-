"""MIDETA public comment scrapper batch page."""
import pandas as pd
import streamlit as st
from src.batch import COMMENT_BATCH_VERSION, compact_comment_export_rows, parse_url_list, rank_comment_rows
from src.comment_browser import CommentBrowserCollector, CommentBrowserError
from src.connectors import PLATFORM_OPTIONS, get_platform_connector
from src.database import add_history
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.models import FieldStatus
from src.ui import apply_theme, page_intro, render_footer, render_github_profile, render_platform_guide, status_label

st.set_page_config(page_title="Comment Scrapper | MIDETA", page_icon="💬", layout="wide")
apply_theme()
render_github_profile()
page_intro("02", "Comment Scrapper", "Kumpulkan komentar publik dari YouTube, TikTok, Facebook, Instagram, Threads, atau X dan urutkan berdasarkan engagement.")
st.warning("Tulis satu URL pada setiap baris. MIDETA hanya mengambil komentar yang dapat ditampilkan oleh platform. Untuk Threads dan X, login dilakukan sendiri melalui Chrome khusus MIDETA jika memang diperlukan.")

platform_icons = {"YouTube": "▶ YouTube", "TikTok": "♪ TikTok", "Facebook": "f Facebook", "Instagram": "◎ Instagram", "Threads": "@ Threads", "X": "𝕏 X"}
placeholders = {"YouTube": "https://www.youtube.com/watch?v=contoh", "TikTok": "https://www.tiktok.com/@akun/video/contoh", "Facebook": "https://www.facebook.com/akun/posts/contoh", "Instagram": "https://www.instagram.com/p/contoh", "Threads": "https://www.threads.net/@akun/post/contoh", "X": "https://x.com/akun/status/contoh"}
selected_platform = st.segmented_control("Pilih media sosial", PLATFORM_OPTIONS, default="YouTube", format_func=lambda value: platform_icons[value], width="stretch")
st.caption(f"Bagian ini khusus untuk komentar {selected_platform}.")
render_platform_guide("comments", selected_platform)


@st.cache_resource(show_spinner=False)
def comment_browser(platform: str) -> CommentBrowserCollector:
    return CommentBrowserCollector(platform)


browser_mode = selected_platform in {"Threads", "X"}
if selected_platform in {"Threads", "X"}:
    st.info(
        f"Mode browser {selected_platform} aktif otomatis karena komentar dimuat langsung dari percakapan di Chrome MIDETA."
    )
    st.caption(
        f"Login cukup dilakukan sekali. Sesi {selected_platform} disimpan di profil Chrome khusus MIDETA dan dipakai kembali "
        f"sampai sesi {selected_platform} kedaluwarsa atau Anda logout."
    )
    open_col, check_col, close_col = st.columns(3)
    if open_col.button(f"Buka Sesi {selected_platform}", width="stretch"):
        try:
            if comment_browser(selected_platform).open_login():
                st.success(f"Sesi {selected_platform} tersimpan masih aktif; tidak perlu login lagi.")
            else:
                st.info("Selesaikan login satu kali di Chrome MIDETA, lalu tekan Periksa Login.")
        except CommentBrowserError as exc:
            st.error(str(exc))
    if check_col.button("Periksa Login", width="stretch"):
        try:
            if comment_browser(selected_platform).is_logged_in():
                st.success("Login tersimpan. Scraping berikutnya akan memakai sesi ini otomatis.")
            else:
                st.warning("Login belum terdeteksi. Selesaikan login di Chrome MIDETA terlebih dahulu.")
        except CommentBrowserError as exc:
            st.error(str(exc))
    if close_col.button("Tutup Chrome MIDETA", width="stretch"):
        comment_browser(selected_platform).close()
        st.info("Chrome MIDETA sudah ditutup.")

with st.form(f"comments_form_{selected_platform}"):
    url_text = st.text_area(f"Daftar URL {selected_platform}", height=180, placeholder=f"{placeholders[selected_platform]}\n{placeholders[selected_platform]}", key=f"comment_urls_{selected_platform}")
    mock_mode = st.checkbox("Gunakan data contoh", help=f"Pilihan ini menampilkan contoh parent dan reply {selected_platform}.", key=f"comment_mock_{selected_platform}")
    submitted = st.form_submit_button("Ambil Semua Komentar", type="primary", width="stretch")

if submitted:
    urls = parse_url_list(url_text)
    if not urls:
        st.error("Masukkan setidaknya satu URL posting.")
    else:
        active_browser = None
        if selected_platform in {"Threads", "X"} and browser_mode and not mock_mode:
            try:
                active_browser = comment_browser(selected_platform)
                active_browser.start()
            except CommentBrowserError as exc:
                st.error(str(exc))
                urls = []
    if urls:
        progress = st.progress(0, text="Menyiapkan daftar URL…")
        rows, issues, preview = [], [], None
        for index, url in enumerate(urls, 1):
            try:
                connector = get_platform_connector(url, selected_platform)
                progress.progress(int((index - 1) / len(urls) * 100), text=f"Mengambil komentar {connector.platform} pada URL {index} dari {len(urls)}…")
                if index == 1:
                    preview_result = connector.mock_enrichment(url) if mock_mode else connector.enrich(url)
                    preview = {
                        "Platform": preview_result.platform,
                        "URL": preview_result.url,
                        "Author": preview_result.username.value or "Tidak tersedia",
                        "Caption": preview_result.caption.value or "Tidak tersedia",
                    }
                if mock_mode:
                    collection = connector.mock_comments(url)
                elif active_browser is not None:
                    collection = active_browser.collect(url)
                else:
                    collection = connector.collect_comments(url)
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
        batches[selected_platform] = {"schema_version": COMMENT_BATCH_VERSION, "rows": rank_comment_rows(rows), "issues": issues, "preview": preview}

batches = st.session_state.setdefault("comment_platform_batches", {})
stored_batch = batches.get(selected_platform, {})
if stored_batch and stored_batch.get("schema_version") != COMMENT_BATCH_VERSION:
    batches.pop(selected_platform, None)
    st.info("Format Comment Scrapper baru saja diperbarui. Jalankan kembali URL untuk memakai hasil terbaru.")
current_batch = batches.get(selected_platform, {})
if rows := current_batch.get("rows"):
    if any(row.get("Data contoh") for row in rows):
        st.warning("DATA CONTOH AKTIF. Komentar di bawah hanya untuk melihat bentuk hasil dan bukan data dari tautan.")
    if preview := current_batch.get("preview"):
        st.subheader("Preview postingan pertama")
        st.markdown(f"**{preview['Author']}** · {preview['Platform']}")
        st.write(preview["Caption"])
        st.link_button("Buka postingan", preview["URL"])
    metrics = st.columns(3)
    metrics[0].metric("Komentar terkumpul", len(rows))
    metrics[1].metric("Parent", sum(row.get("Tipe") == "parent" for row in rows))
    metrics[2].metric("Reply", sum(row.get("Tipe") == "reply" for row in rows))
    st.success(f"Pengambilan selesai. {len(rows)} komentar ditemukan.")
    export_rows = compact_comment_export_rows(rows)
    st.dataframe(pd.DataFrame(export_rows), width="stretch", hide_index=True)
    with st.expander("Lihat sumber dan perhitungan ranking"):
        detail_columns = ["Rank", "Platform", "URL", "Jumlah reply", "Skor engagement", "Waktu pengambilan"]
        st.dataframe(pd.DataFrame(rows).reindex(columns=detail_columns).fillna("Tidak tersedia"), width="stretch", hide_index=True)
    st.caption("Ranking dihitung dari jumlah like ditambah dua kali jumlah reply. Komentar dengan engagement tertinggi ditampilkan lebih dulu.")
    csv_col, xlsx_col = st.columns(2)
    filename = selected_platform.lower().replace(" ", "_")
    csv_col.download_button("Unduh CSV", to_csv_bytes(export_rows), f"mideta_comments_{filename}.csv", "text/csv", width="stretch")
    xlsx_col.download_button("Unduh XLSX", to_xlsx_bytes(export_rows, selected_platform), f"mideta_comments_{filename}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
elif "rows" in current_batch:
    st.info("Belum ada komentar yang dapat dikumpulkan dari daftar URL tersebut.")

if issues := current_batch.get("issues"):
    with st.expander(f"{len(issues)} URL memerlukan perhatian", expanded=True):
        st.dataframe(pd.DataFrame(issues), width="stretch", hide_index=True)

render_footer()
