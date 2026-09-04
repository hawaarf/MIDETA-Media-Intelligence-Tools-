"""Reusable Streamlit presentation helpers."""
from __future__ import annotations
import html
import streamlit as st
from src.config import ASSETS_DIR, GITHUB_AVATAR_URL, GITHUB_PROFILE_URL
from src.models import DataField


ENRICHMENT_GUIDES = {
    "YouTube": {
        "summary": "Untuk video atau Shorts publik. Tidak perlu login.",
        "steps": [
            ("Salin URL", "Buka video/Shorts lalu salin tautan publiknya."),
            ("Tempel tautan", "Masukkan satu URL per baris pada kolom YouTube."),
            ("Ambil metadata", "MIDETA membaca author, caption, tanggal, dan engagement yang tersedia."),
            ("Periksa hasil", "Cek status setiap kolom lalu unduh CSV atau XLSX."),
        ],
        "note": "Video privat, dibatasi usia, atau dibatasi wilayah dapat menghasilkan data yang tidak lengkap.",
    },
    "TikTok": {
        "summary": "Untuk video publik dengan format tiktok.com/@akun/video/…. Tidak perlu login.",
        "steps": [
            ("Salin URL video", "Gunakan tautan video, bukan hanya halaman profil akun."),
            ("Tempel tautan", "Masukkan satu atau beberapa URL TikTok, satu URL per baris."),
            ("Jalankan proses", "MIDETA membaca author, followers, views, caption, tanggal, dan engagement publik."),
            ("Review & ekspor", "Periksa nilai 0 atau status tidak tersedia sebelum mengunduh hasil."),
        ],
        "note": "Akun privat atau halaman yang meminta verifikasi/login tidak dapat dibaca otomatis.",
    },
    "Facebook": {
        "summary": "Mendukung post, Reel, video, share link, dan permalink grup yang dapat diakses publik.",
        "steps": [
            ("Salin URL publik", "Gunakan tautan posting yang bisa dibuka tanpa akun khusus."),
            ("Tempel tautan", "Masukkan URL Facebook satu per baris; share link akan diikuti ke tujuan akhirnya."),
            ("Ambil metadata", "MIDETA mencocokkan ID post agar data rekomendasi tidak tercampur."),
            ("Periksa hasil", "Review author, followers/friends, caption, views, dan engagement lalu ekspor."),
        ],
        "note": "Posting privat, grup tertutup, dan halaman yang memaksa login akan ditandai tidak tersedia atau diblokir.",
    },
    "Instagram": {
        "summary": "Pilih jalur cepat tanpa login atau jalur lengkap untuk followers, views, dan repost yang lebih akurat.",
        "modes": [
            ("Jalur cepat · tanpa login", "Matikan ‘Gunakan browser Instagram’. Cocok jika butuh caption, tanggal, likes/comments, dan metadata publik secepatnya. Repost dapat tampil 0 jika tidak diberikan publik."),
            ("Jalur lengkap · login sekali", "Aktifkan browser Instagram, buka Chrome Instagram, login satu kali, lalu Periksa Login. Gunakan jalur ini jika membutuhkan followers, views Reel, dan repost."),
        ],
        "steps": [
            ("Tentukan kebutuhan", "Pilih cepat tanpa repost lengkap, atau browser untuk data yang hanya muncul setelah login."),
            ("Siapkan sesi", "Untuk jalur lengkap, login satu kali di Chrome khusus MIDETA; sesi akan digunakan kembali."),
            ("Tempel URL", "Masukkan URL post atau Reel Instagram, satu URL per baris."),
            ("Ambil & periksa", "Jalankan proses, cek catatan browser, lalu unduh CSV atau XLSX."),
        ],
        "note": "Password diketik langsung di Instagram dan tidak dibaca MIDETA. Tanpa browser, proses tetap bisa berjalan tetapi repost/views/followers dapat 0 atau dibulatkan.",
    },
    "Threads": {
        "summary": "Untuk post Threads publik. Enrichment metadata tidak memerlukan login.",
        "steps": [
            ("Salin URL post", "Gunakan tautan dengan format threads.com/@akun/post/…."),
            ("Tempel tautan", "Masukkan satu atau beberapa URL, satu URL per baris."),
            ("Ambil metadata", "MIDETA membaca author, caption, tanggal, views, followers, dan jumlah komentar yang tersedia."),
            ("Review hasil", "Nilai yang tidak diberikan Threads akan tampil 0 atau berstatus tidak tersedia."),
        ],
        "note": "Login browser Threads hanya diperlukan pada Comment Scrapper, bukan untuk enrichment metadata publik.",
    },
    "X": {
        "summary": "Untuk status/post publik di x.com. Tidak perlu login selama datanya tersedia publik.",
        "steps": [
            ("Salin URL status", "Gunakan tautan x.com/akun/status/ID, bukan halaman profil."),
            ("Tempel tautan", "Masukkan URL X satu per baris pada bagian ini."),
            ("Ambil metadata", "MIDETA membaca author, teks, tanggal, dan engagement dari data publik."),
            ("Periksa hasil", "Cek kolom yang tidak tersedia lalu ekspor hasil yang dibutuhkan."),
        ],
        "note": "Post akun terlindungi atau halaman yang mewajibkan login tidak dapat dikumpulkan.",
    },
}


COMMENT_GUIDES = {
    "YouTube": {
        "summary": "Masukkan URL video publik untuk mengambil komentar yang diekspos sebagai data publik.",
        "steps": [
            ("Salin URL video", "Gunakan URL video/Shorts yang komentarnya aktif."),
            ("Tempel tautan", "Masukkan satu URL per baris pada kolom YouTube."),
            ("Ambil komentar", "MIDETA mengumpulkan parent/reply yang tersedia dan menghitung engagement."),
            ("Review & unduh", "Periksa URL yang memerlukan perhatian lalu ekspor CSV atau XLSX."),
        ],
        "note": "Jika YouTube tidak menyertakan komentar pada data publik halaman, hasil dapat kosong meskipun komentar terlihat di aplikasi YouTube.",
    },
    "TikTok": {
        "summary": "Gunakan URL video publik; login tidak diperlukan selama komentar tersedia di halaman publik.",
        "steps": [
            ("Salin URL video", "Pilih video publik dengan komentar yang aktif."),
            ("Tempel tautan", "Masukkan URL TikTok satu per baris."),
            ("Ambil komentar", "MIDETA membaca komentar terstruktur, author, tanggal, likes, dan reply."),
            ("Periksa hasil", "Review bagian ‘URL memerlukan perhatian’ bila hasilnya kosong."),
        ],
        "note": "Komentar yang hanya dimuat di aplikasi, dibatasi wilayah, atau berada di balik login mungkin tidak tersedia.",
    },
    "Facebook": {
        "summary": "Gunakan post, Reel, atau video publik yang komentarnya bisa dibuka tanpa akses khusus.",
        "steps": [
            ("Salin URL posting", "Pastikan posting dapat dibuka secara publik dan komentar tidak dimatikan."),
            ("Tempel tautan", "Masukkan satu URL Facebook per baris."),
            ("Ambil komentar", "MIDETA membaca parent/reply yang tersedia sebagai data terstruktur publik."),
            ("Review & ekspor", "Periksa status setiap URL, ranking engagement, lalu unduh hasil."),
        ],
        "note": "Komentar grup tertutup, posting privat, atau dialog komentar yang mewajibkan login tidak dapat diambil.",
    },
    "Instagram": {
        "summary": "Comment Scrapper Instagram memakai data publik dan tidak memerlukan mode browser enrichment.",
        "steps": [
            ("Salin URL post/Reel", "Pilih posting publik dengan komentar yang aktif."),
            ("Tempel tautan", "Masukkan URL Instagram satu per baris."),
            ("Ambil komentar", "MIDETA membaca komentar yang tersedia sebagai data terstruktur publik."),
            ("Periksa hasil", "Jika kosong, lihat alasan pada bagian URL yang memerlukan perhatian."),
        ],
        "note": "Login Instagram pada halaman Enrichment digunakan untuk followers/views/repost, bukan untuk membuka komentar privat di Comment Scrapper.",
    },
    "Threads": {
        "summary": "Gunakan browser Threads agar komentar dinamis, parent, dan reply dapat dibaca.",
        "modes": [
            ("Posting publik", "Biarkan mode browser aktif dan langsung jalankan URL. Banyak percakapan publik dapat dibaca tanpa login."),
            ("Jika dibatasi", "Tekan ‘Buka Sesi Threads’, login satu kali, lalu ‘Periksa Login’. Sesi tersimpan akan dipakai untuk scraping berikutnya."),
        ],
        "steps": [
            ("Aktifkan browser", "Biarkan ‘Gunakan browser Threads’ tetap aktif."),
            ("Siapkan sesi", "Login satu kali hanya jika Threads membatasi percakapan target."),
            ("Tempel URL", "Masukkan URL post Threads satu per baris lalu ambil komentar."),
            ("Review hasil", "MIDETA memisahkan parent/reply dan mengabaikan posting setelah ‘Related threads’."),
        ],
        "note": "Sesi bertahan sampai Threads mengakhirinya atau Anda logout. Password tidak dibaca oleh MIDETA.",
    },
    "X": {
        "summary": "Gunakan browser X agar reply yang dimuat dinamis dapat dibaca dari percakapan target.",
        "modes": [
            ("Posting publik", "Biarkan mode browser aktif dan langsung jalankan URL status."),
            ("Jika dibatasi", "Tekan ‘Buka Sesi X’, login satu kali, lalu ‘Periksa Login’."),
        ],
        "steps": [
            ("Salin URL status", "Gunakan x.com/akun/status/ID dari post utama."),
            ("Tempel tautan", "Masukkan satu URL per baris pada bagian X."),
            ("Ambil komentar", "MIDETA mengumpulkan reply yang terhubung ke conversation ID target dan membuka balasan yang tersedia."),
            ("Periksa hasil", "Review parent/reply, engagement, dan URL yang memerlukan perhatian."),
        ],
        "note": "Sesi X tersimpan terpisah dari Threads. Reply akun terlindungi atau balasan yang disembunyikan platform mungkin tidak terbaca.",
    },
}

def apply_theme() -> None:
    css = (ASSETS_DIR / "styles.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

def render_github_profile() -> None:
    st.markdown(
        f"""
        <div class="github-profile">
          <a href="{html.escape(GITHUB_PROFILE_URL, quote=True)}" target="_blank" rel="noopener noreferrer" aria-label="Buka profil GitHub Hawarisma">
            <img src="{html.escape(GITHUB_AVATAR_URL, quote=True)}" alt="Foto profil GitHub Hawarisma" />
            <span><small>GITHUB</small><strong>@hawaarf</strong></span>
          </a>
        </div>
        """,
        unsafe_allow_html=True,
    )

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

def render_platform_guide(feature: str, platform: str) -> None:
    guides = ENRICHMENT_GUIDES if feature == "enrichment" else COMMENT_GUIDES
    guide = guides[platform]
    feature_label = "Social Media Enrichment" if feature == "enrichment" else "Comment Scrapper"
    modes_html = ""
    if modes := guide.get("modes"):
        mode_cards = "".join(
            f'<div><strong>{html.escape(title)}</strong><p>{html.escape(description)}</p></div>'
            for title, description in modes
        )
        modes_html = f'<div class="usage-modes">{mode_cards}</div>'
    steps_html = "".join(
        f'<div><em>{index:02d}</em><strong>{html.escape(title)}</strong><p>{html.escape(description)}</p></div>'
        for index, (title, description) in enumerate(guide["steps"], 1)
    )
    st.markdown(
        f"""
        <div class="usage-guide">
          <div class="usage-guide-title"><span>CARA PAKAI · {html.escape(platform.upper())}</span><b>{html.escape(feature_label)}</b></div>
          <p class="usage-summary">{html.escape(guide['summary'])}</p>
          {modes_html}
          <div class="usage-flow">{steps_html}</div>
          <div class="usage-note"><b>Catatan</b><span>{html.escape(guide['note'])}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def render_footer() -> None:
    st.markdown(
        """
        <div class="site-footer">
          <p>Developed by Hawarisma Rafanidya Singgih</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

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
