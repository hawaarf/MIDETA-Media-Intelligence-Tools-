"""MIDETA local analysis history page."""
from datetime import date, timedelta
import pandas as pd
import streamlit as st
from src.database import delete_history, list_history
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.ui import apply_theme, page_intro

st.set_page_config(page_title="Riwayat Analisis | MIDETA", page_icon="🗂️", layout="wide")
apply_theme()
page_intro("03", "Riwayat Analisis", "Temukan kembali dan kelola hasil yang tersimpan di perangkat Anda.")

filters = st.columns([2, 1, 1, 1, 1])
search = filters[0].text_input("Cari", placeholder="Cari URL atau isi hasil")
feature_value = filters[1].selectbox("Fitur", ["Semua", "Social Media Enrichment", "Comment Scrapper"])
platform_value = filters[2].selectbox("Platform", ["Semua", "YouTube", "TikTok", "Facebook", "Instagram", "Threads", "X"])
start = filters[3].date_input("Dari", value=date.today() - timedelta(days=30))
end = filters[4].date_input("Sampai", value=date.today())
if start > end:
    st.error("Tanggal awal tidak boleh melewati tanggal akhir.")
    records = []
else:
    records = list_history(search=search, feature=None if feature_value == "Semua" else feature_value, platform=None if platform_value == "Semua" else platform_value, start=start, end=end)

st.metric("Hasil ditemukan", len(records))
status_names = {"mock": "Data contoh", "completed": "Selesai", "failed": "Gagal"}
rows = [{"ID": record.id, "Fitur": record.feature, "Platform": record.platform or "Tidak ada", "Status": status_names.get(record.status, record.status), "URL sumber": record.source_url, "Dibuat": record.created_at.isoformat(sep=" ")} for record in records]
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
if records:
    export = [record.model_dump(mode="json") for record in records]
    csv_col, xlsx_col = st.columns(2)
    csv_col.download_button("Unduh hasil dalam CSV", to_csv_bytes(export), "mideta_history.csv", "text/csv", width="stretch")
    xlsx_col.download_button("Unduh hasil dalam XLSX", to_xlsx_bytes(export, "History"), "mideta_history.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    selected_id = st.selectbox("Lihat detail hasil", [record.id for record in records], format_func=lambda item: f"#{item} · {next(record.feature for record in records if record.id == item)}")
    selected = next(record for record in records if record.id == selected_id)
    with st.expander(f"Detail hasil #{selected.id}", expanded=True):
        st.json(selected.result)
        st.markdown(f"**URL sumber:** {selected.source_url}")
    with st.expander("Hapus hasil"):
        confirmed = st.checkbox(f"Saya yakin ingin menghapus hasil #{selected.id}", key=f"confirm_{selected.id}")
        if st.button("Hapus permanen", type="primary", disabled=not confirmed):
            if delete_history(selected.id):
                st.success(f"Hasil #{selected.id} telah dihapus.")
                st.rerun()
            else:
                st.error("Hasil tidak ditemukan.")
else:
    st.info("Belum ada riwayat yang cocok dengan filter.")
