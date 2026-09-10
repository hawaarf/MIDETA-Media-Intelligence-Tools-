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
    st.markdown('<div class="kicker">WORKSPACE MEDIA INTELLIGENCE</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="hero-title">Pahami percakapan. <span>Rapikan datanya.</span></h1>', unsafe_allow_html=True)
    st.markdown('<p class="hero-copy">Kumpulkan metadata, komentar, dan posting Threads dari beberapa platform dalam satu workspace lokal yang rapi.</p>', unsafe_allow_html=True)
    st.markdown('<div class="platform-strip"><span>YouTube</span><span>TikTok</span><span>Facebook</span><span>Instagram</span><span>Threads</span><span>X</span></div>', unsafe_allow_html=True)
    first, second = st.columns(2)
    first.page_link("pages/1_Social_Media_Enrichment.py", label="Mulai Analisis", icon=":material/arrow_forward:", width="stretch")
    second.link_button("Lihat Fitur", "#features", icon=":material/grid_view:", width="stretch")
with hero_visual:
    st.markdown("""<div class="preview-shell"><div class="preview-top"><span></span><span></span><span></span><b>MIDETA WORKSPACE</b></div><div class="preview-heading"><small>ALUR KERJA</small><strong>Dari tautan publik menjadi data siap pakai.</strong><p>Setiap platform diproses terpisah agar hasil lebih mudah diperiksa.</p></div><div class="workflow-track"><div><span>01</span><b>Masukkan URL</b><small>Satu tautan per baris</small></div><i></i><div><span>02</span><b>Ambil data</b><small>Per platform</small></div><i></i><div><span>03</span><b>Unduh hasil</b><small>CSV atau XLSX</small></div></div><div class="signal"><span class="pulse"></span><div><small>STATUS SISTEM</small><b>Berjalan lokal di perangkat Anda</b></div><strong>SIAP</strong></div></div>""", unsafe_allow_html=True)

st.markdown('<div id="features" class="section-anchor"></div><div class="section-label">FITUR MIDETA</div><h2>Empat alat untuk pekerjaan yang lebih rapi.</h2>', unsafe_allow_html=True)
features = [("01", "Social Media Enrichment", "Ambil metadata beberapa posting dari enam platform dalam satu proses.", "pages/1_Social_Media_Enrichment.py", "EN"), ("02", "Comment Scrapper", "Kumpulkan komentar publik dan urutkan berdasarkan engagement.", "pages/2_Comment_Scrapper.py", "CO"), ("03", "Riwayat Analisis", "Temukan kembali, periksa, dan unduh hasil yang pernah dikumpulkan.", "pages/3_Riwayat_Analisis.py", "HI"), ("04", "Threads Tracker", "Cari posting Threads berdasarkan keyword, waktu, dan tingkat engagement.", "pages/4_Threads_Tracker.py", "TR")]
columns = st.columns(4)
for column, (number, title, description, page, icon) in zip(columns, features):
    with column:
        st.markdown(f'<div class="feature-card"><div class="feature-icon"><span>{icon}</span></div><span class="number">{number}</span><h3>{title}</h3><p>{description}</p></div>', unsafe_allow_html=True)
        st.page_link(page, label="Buka Fitur", icon=":material/arrow_outward:", width="stretch")

st.markdown('<div id="about" class="section-anchor"></div>', unsafe_allow_html=True)
privacy, principles = st.columns([1, 1], gap="large", vertical_alignment="center")
with privacy:
    st.markdown('<div class="section-label">DATA TETAP TERKENDALI</div><h2>Semua proses berjalan di perangkat Anda.</h2><p class="section-copy">MIDETA hanya membaca informasi yang tersedia untuk publik. Data hasil pengumpulan tersimpan di perangkat dan tidak dikirim ke layanan berbayar.</p>', unsafe_allow_html=True)
with principles:
    st.markdown("""<div class="principles"><div><span>✓</span><b>Gratis dan terbuka</b><small>Tidak memerlukan layanan berbayar</small></div><div><span>✓</span><b>Diproses secara lokal</b><small>Data diolah langsung di perangkat Anda</small></div><div><span>✓</span><b>Tersimpan dengan rapi</b><small>Riwayat disimpan dalam database lokal</small></div><div><span>✓</span><b>Menghormati batas akses</b><small>Tidak melewati login, pembatasan, atau CAPTCHA</small></div></div>""", unsafe_allow_html=True)

st.markdown('<div class="cta"><div class="section-label">MULAI DARI SATU TAUTAN</div><h2>SIAP MELIHAT INFORMASI DENGAN LEBIH JELAS?</h2><p>Masukkan tautan publik dan MIDETA akan membantu merapikan datanya.</p></div>', unsafe_allow_html=True)
_, launch, _ = st.columns([1, 1, 1])
launch.page_link("pages/1_Social_Media_Enrichment.py", label="Buka MIDETA", icon=":material/rocket_launch:", width="stretch")
render_footer()
