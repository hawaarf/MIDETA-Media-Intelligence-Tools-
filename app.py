"""Premium landing page for MIDETA."""
import streamlit as st
from src.config import PAGE_TITLE
from src.ui import apply_theme, render_brand_header

st.set_page_config(page_title=PAGE_TITLE, page_icon="◉", layout="wide", initial_sidebar_state="collapsed")
apply_theme()
render_brand_header()

hero_text, hero_visual = st.columns([1.08, .92], gap="large", vertical_alignment="center")
with hero_text:
    st.markdown('<div class="kicker">MEDIA INTELLIGENCE LOKAL</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="hero-title">PAHAMI PERCAKAPAN. <span>TEMUKAN INFORMASI PENTING.</span></h1>', unsafe_allow_html=True)
    st.markdown('<p class="hero-copy">MIDETA membantu Anda membaca aktivitas media sosial dan merapikan data publik dalam satu tempat.</p>', unsafe_allow_html=True)
    first, second = st.columns(2)
    first.page_link("pages/1_Social_Media_Enrichment.py", label="Mulai Analisis", icon=":material/arrow_forward:", width="stretch")
    second.link_button("Lihat Fitur", "#features", icon=":material/grid_view:", width="stretch")
with hero_visual:
    st.markdown("""<div class="preview-shell"><div class="preview-top"><span></span><span></span><span></span><b>RINGKASAN AKTIVITAS</b></div><div class="preview-grid"><div class="preview-metric"><small>DATA DIOLAH</small><strong>1,284</strong><em>NAIK 18.4%</em></div><div class="preview-metric"><small>SENTIMEN RATA RATA</small><strong>72%</strong><em>POSITIF</em></div></div><div class="chart"><i style="height:38%"></i><i style="height:62%"></i><i style="height:49%"></i><i style="height:81%"></i><i style="height:68%"></i><i style="height:92%"></i><i style="height:76%"></i></div><div class="signal"><span class="pulse"></span><div><small>TEMUAN UTAMA</small><b>Perhatian audiens meningkat</b></div><strong>TINGGI</strong></div></div>""", unsafe_allow_html=True)

st.markdown('<div id="features" class="section-anchor"></div><div class="section-label">FITUR MIDETA</div><h2>Tiga alat untuk pekerjaan yang lebih rapi.</h2>', unsafe_allow_html=True)
features = [("01", "Social Media Enrichment", "Ambil metadata beberapa posting dari enam platform dalam satu proses.", "pages/1_Social_Media_Enrichment.py", "hub"), ("02", "Comment Scrapper", "Kumpulkan komentar publik dan urutkan berdasarkan engagement.", "pages/2_Comment_Scrapper.py", "forum"), ("03", "Riwayat Analisis", "Temukan kembali, periksa, dan unduh hasil yang pernah dikumpulkan.", "pages/3_Riwayat_Analisis.py", "history")]
columns = st.columns(3)
for column, (number, title, description, page, icon) in zip(columns, features):
    with column:
        st.markdown(f'<div class="feature-card"><div class="feature-icon"><span class="material-symbols-rounded">{icon}</span></div><span class="number">{number}</span><h3>{title}</h3><p>{description}</p></div>', unsafe_allow_html=True)
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
st.markdown('<footer><b>MIDETA</b><span>Media Intelligence Tools · Berjalan secara lokal</span></footer>', unsafe_allow_html=True)
