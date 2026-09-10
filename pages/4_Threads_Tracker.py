"""MIDETA Threads keyword tracker."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.database import add_history
from src.exporters import to_csv_bytes, to_xlsx_bytes
from src.config import MIDETA_LOGO_PATH
from src.threads_tracker import (
    ThreadsTrackerCollector,
    ThreadsTrackerError,
    ThreadsTrackerLoginRequired,
)
from src.ui import apply_theme, page_intro, render_footer, render_github_profile


st.set_page_config(page_title="Threads Tracker | MIDETA", page_icon=str(MIDETA_LOGO_PATH), layout="wide")
apply_theme()
render_github_profile()
page_intro(
    "04",
    "Threads Tracker",
    "Cari posting Threads berdasarkan keyword, batasi waktunya, lalu urutkan berdasarkan engagement.",
)


@st.cache_resource(show_spinner=False)
def tracker_browser() -> ThreadsTrackerCollector:
    return ThreadsTrackerCollector()


st.info(
    "Threads Tracker memakai Chrome khusus dan memerlukan login. Hasil mengikuti posting yang diberikan pencarian Threads, "
    "jadi jumlahnya dapat berubah dan tidak selalu mencakup seluruh posting yang pernah dibuat."
)

with st.expander("Siapkan sesi Threads Tracker", expanded=True):
    st.caption(
        "Sesi tracker disimpan terpisah agar tidak mengganggu Comment Scrapper. "
        "Password diketik langsung di Threads dan tidak dibaca MIDETA."
    )
    open_col, check_col, close_col = st.columns(3)
    if open_col.button("Buka Sesi Threads", width="stretch"):
        try:
            if tracker_browser().open_login():
                st.success("Sesi Threads Tracker masih aktif.")
            else:
                st.info("Login di Chrome yang terbuka, lalu klik Periksa Login.")
        except ThreadsTrackerError as exc:
            st.error(str(exc))
    if check_col.button("Periksa Login", width="stretch"):
        try:
            if tracker_browser().is_logged_in():
                st.success("Login Threads Tracker sudah siap.")
            else:
                st.warning("Login belum terdeteksi.")
        except ThreadsTrackerError as exc:
            st.error(str(exc))
    if close_col.button("Tutup Chrome", width="stretch"):
        tracker_browser().close()
        st.info("Chrome Threads Tracker sudah ditutup.")

with st.form("threads_tracker_search"):
    keyword = st.text_input(
        "Keyword",
        placeholder="Contoh: gojek, transportasi online, saham GOTO",
    )
    period_col, order_col, limit_col = st.columns(3)
    period_label = period_col.selectbox(
        "Rentang waktu",
        ("Recent (24 jam)", "Last 7 days", "All"),
    )
    order_label = order_col.selectbox(
        "Urutan hasil",
        ("Engagement paling ramai", "Engagement paling rendah", "Terbaru"),
    )
    limit = limit_col.number_input(
        "Maksimal hasil",
        min_value=10,
        max_value=200,
        value=50,
        step=10,
    )
    submitted = st.form_submit_button("Cari Postingan Threads", width="stretch")

periods = {
    "Recent (24 jam)": "recent",
    "Last 7 days": "7d",
    "All": "all",
}
orders = {
    "Engagement paling ramai": "highest",
    "Engagement paling rendah": "lowest",
    "Terbaru": "newest",
}

if submitted:
    if not keyword.strip():
        st.warning("Masukkan keyword terlebih dahulu.")
    else:
        try:
            with st.spinner("Mencari dan membaca hasil Threads…"):
                search_url, rows = tracker_browser().search(
                    keyword,
                    period=periods[period_label],
                    order=orders[order_label],
                    limit=int(limit),
                )
            st.session_state["threads_tracker_result"] = {
                "keyword": " ".join(keyword.split()),
                "period": period_label,
                "order": order_label,
                "search_url": search_url,
                "rows": rows,
            }
            add_history(
                "Threads Tracker",
                search_url,
                "completed",
                st.session_state["threads_tracker_result"],
                "Threads",
            )
        except ThreadsTrackerLoginRequired as exc:
            st.warning(str(exc))
        except ThreadsTrackerError as exc:
            st.error(str(exc))

result = st.session_state.get("threads_tracker_result")
if result:
    rows = result["rows"]
    st.subheader(f'Hasil untuk “{result["keyword"]}”')
    st.caption(
        f'{result["period"]} · {result["order"]} · '
        "Total engagement = Likes + Comments + Reposts + Shares"
    )
    if not rows:
        st.warning("Belum ada posting yang cocok pada rentang waktu ini.")
    else:
        total_engagement = sum(int(row.get("Total engagement") or 0) for row in rows)
        post_count, engagement_total, highest = st.columns(3)
        post_count.metric("Posting ditemukan", f"{len(rows):,}")
        engagement_total.metric("Total engagement", f"{total_engagement:,}")
        highest.metric(
            "Engagement tertinggi",
            f'{max(int(row.get("Total engagement") or 0) for row in rows):,}',
        )

        frame = pd.DataFrame(rows)
        st.dataframe(
            frame,
            width="stretch",
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("URL", display_text="Buka posting"),
                "Caption": st.column_config.TextColumn("Caption", width="large"),
            },
        )
        csv_col, xlsx_col = st.columns(2)
        csv_col.download_button(
            "Unduh CSV",
            data=to_csv_bytes(rows),
            file_name=f'threads_tracker_{result["keyword"].replace(" ", "_")}.csv',
            mime="text/csv",
            width="stretch",
        )
        xlsx_col.download_button(
            "Unduh XLSX",
            data=to_xlsx_bytes(rows, "Threads Tracker"),
            file_name=f'threads_tracker_{result["keyword"].replace(" ", "_")}.xlsx',
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

render_footer()
