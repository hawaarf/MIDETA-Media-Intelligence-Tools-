"""Reusable Streamlit presentation helpers."""
from __future__ import annotations
import html
import streamlit as st
from src.config import ASSETS_DIR
from src.models import DataField

def apply_theme() -> None:
    css = (ASSETS_DIR / "styles.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

def render_brand_header() -> None:
    brand, home, features, about, dashboard = st.columns([4.5, 1, 1, 1, 1.7], vertical_alignment="center")
    brand.markdown('<div class="wordmark"><span>◉</span>MIDETA<small>MEDIA INTELLIGENCE TOOLS</small></div>', unsafe_allow_html=True)
    home.link_button("Beranda", "#top", width="stretch")
    features.link_button("Fitur", "#features", width="stretch")
    about.link_button("Tentang", "#about", width="stretch")
    dashboard.page_link("pages/1_Social_Media_Enrichment.py", label="Buka Dashboard", icon=":material/arrow_forward:", width="stretch")
    st.markdown('<div class="header-rule"></div>', unsafe_allow_html=True)

def page_intro(number: str, title: str, description: str) -> None:
    st.markdown(f'<div class="kicker">MIDETA / {html.escape(number)}</div><h1 class="page-title">{html.escape(title)}</h1><p class="page-copy">{html.escape(description)}</p>', unsafe_allow_html=True)

def status_label(status: str) -> str:
    labels = {"Available": "Tersedia", "Not publicly visible": "Tidak terlihat publik", "Login required": "Memerlukan login", "Not supported": "Belum didukung", "Collection blocked": "Pengambilan diblokir", "Collection failed": "Pengambilan gagal"}
    return labels.get(str(status), str(status))

def social_rows(result) -> list[dict]:
    labels = {"username": "Author", "caption": "Caption", "posted_at": "Tanggal posting", "followers": "Followers", "views": "Views", "likes": "Likes", "comments": "Comments", "bookmarks": "Save atau bookmark", "shares": "Shares", "reposts": "Reposts"}
    rows = []
    for key, label in labels.items():
        field: DataField = getattr(result, key)
        rows.append({"Data": label, "Nilai": str(field.value) if field.value is not None else "Tidak tersedia", "Status": status_label(field.status)})
    return rows
