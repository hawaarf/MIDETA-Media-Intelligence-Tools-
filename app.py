"""Premium landing page for MIDETA."""
import streamlit as st
from src.config import MIDETA_LOGO_PATH, PAGE_TITLE
from src.ui import apply_theme, render_brand_header, render_footer, render_github_profile

st.set_page_config(page_title=PAGE_TITLE, page_icon=str(MIDETA_LOGO_PATH), layout="wide", initial_sidebar_state="collapsed")
apply_theme()
render_github_profile()
render_brand_header()

hero_text, hero_visual = st.columns([1.08, .92], gap="large", vertical_alignment="center")
with hero_text:
    st.markdown('<div class="kicker">MIDETA WORKSPACE</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="hero-title">Data sosial, <span>siap dipakai.</span></h1>', unsafe_allow_html=True)
    st.markdown('<p class="hero-copy">Pilih fitur, tempel URL, jalankan proses, lalu unduh hasilnya.</p>', unsafe_allow_html=True)
    st.markdown('<div class="platform-strip"><span>YouTube</span><span>TikTok</span><span>Facebook</span><span>Instagram</span><span>Threads</span><span>X</span></div>', unsafe_allow_html=True)
    first, second = st.columns(2)
    first.page_link("pages/1_Social_Media_Enrichment.py", label="Enrich Metadata", icon=":material/database:", width="stretch")
    second.page_link("pages/2_Comment_Scrapper.py", label="Ambil Komentar", icon=":material/forum:", width="stretch")
with hero_visual:
    st.markdown("""<div class="preview-shell"><div class="preview-top"><span></span><span></span><span></span><b>ALUR MIDETA</b></div><div class="preview-heading"><small>3 LANGKAH</small><strong>Tempel. Jalankan. Unduh.</strong><p>URL tetap berurutan agar hasil mudah dicocokkan.</p></div><div class="workflow-track"><div><span>01</span><b>Tempel URL</b><small>Satu per baris</small></div><i></i><div><span>02</span><b>Jalankan</b><small>Pilih fitur</small></div><i></i><div><span>03</span><b>Unduh</b><small>CSV atau XLSX</small></div></div><div class="signal"><span class="pulse"></span><div><small>STATUS</small><b>Siap digunakan</b></div><strong>SIAP</strong></div></div>""", unsafe_allow_html=True)

st.markdown('<div class="section-anchor"></div><div class="section-label">PILIH FITUR</div><h2>Apa yang ingin dikerjakan?</h2>', unsafe_allow_html=True)
features = [("01", "Social Media Enrichment", "Metadata posting dan engagement.", "pages/1_Social_Media_Enrichment.py", "EN", "Buka Enrichment"), ("02", "Comment Scrapper", "Komentar, reply, dan engagement.", "pages/2_Comment_Scrapper.py", "CO", "Buka Comment Scrapper"), ("03", "Riwayat Analisis", "Hasil yang pernah dikumpulkan.", "pages/3_Riwayat_Analisis.py", "HI", "Buka Riwayat")]
columns = st.columns(3)
for column, (number, title, description, page, icon, button_label) in zip(columns, features):
    with column:
        st.markdown(f'<div class="feature-card"><div class="feature-icon"><span>{icon}</span></div><span class="number">{number}</span><h3>{title}</h3><p>{description}</p></div>', unsafe_allow_html=True)
        st.page_link(page, label=button_label, icon=":material/arrow_forward:", width="stretch")
render_footer()
