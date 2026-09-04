# MIDETA

MIDETA adalah aplikasi lokal untuk mengumpulkan metadata posting media sosial dan komentar. Aplikasi dibuat dengan Python dan Streamlit. Hasil pengambilan dapat diperiksa di browser, disimpan ke riwayat, lalu diunduh sebagai CSV atau XLSX.

MIDETA mendukung YouTube, TikTok, Facebook, Instagram, Threads, dan X. Setiap platform mempunyai bagian input sendiri agar URL dan proses pengambilannya tidak tercampur.

## Fitur utama

### Social Media Enrichment

Pengguna dapat memasukkan beberapa URL sekaligus dengan menulis satu URL pada setiap baris. MIDETA akan mencoba mengambil data berikut dari setiap posting:

1. Tanggal posting
2. Author
3. Caption
4. Followers
5. Views
6. Likes
7. Comments
8. Save atau bookmark
9. Shares
10. Reposts

Data yang memang tidak diberikan oleh platform akan ditandai sebagai tidak tersedia. Khusus Followers dan Views pada Facebook, Instagram, TikTok, serta Threads, MIDETA menampilkan angka 0 jika platform tidak menyediakan nilainya. Reposts Instagram juga menjadi 0 jika angkanya tidak tercantum. Untuk Facebook, jumlah followers diprioritaskan. Jika followers tidak ditampilkan tetapi jumlah friends tersedia secara publik, MIDETA menggunakan jumlah friends. Views Reel Facebook dan Instagram juga dicari dari daftar Reel publik author dengan mencocokkan ID posting yang sama. Tanggal posting pada tabel dan file unduhan menggunakan format seperti `25-Aug-2026`.

Instagram mempunyai mode browser untuk data yang hanya terlihat setelah login. Mode ini membaca followers dari profil, repost dari halaman posting, dan views dari Reel dengan shortcode yang sama. Chrome yang dipakai terpisah dari Chrome utama agar sesi MIDETA tidak tercampur dengan profil kerja atau profil pribadi lainnya.

Pada Facebook, author dan angka engagement dicocokkan dengan ID posting target. Data dari posting rekomendasi tidak dipakai. Jika Reel target tidak menampilkan angka likes atau comments, nilainya menjadi 0. Untuk posting grup, profil author juga diperiksa agar followers atau friends yang tersedia tetap dapat digunakan.

Jumlah komentar Threads dibaca dari `direct_reply_count` milik posting yang shortcode-nya sama. Cara ini mencegah jumlah reply dari posting rekomendasi ikut masuk ke hasil.

Tanggal Threads dibaca dari `taken_at` yang paling dekat dengan shortcode posting. Reposts Instagram dibaca dari field repost atau reshare milik posting yang sama.

### Comment Scrapper

Comment Scrapper membaca komentar yang tersedia pada percakapan posting. YouTube, TikTok, Facebook, Instagram, Threads, dan X mempunyai pilihan input sendiri agar URL serta hasilnya tidak tercampur.

Threads dan X memuat komentar melalui JavaScript, sehingga keduanya mempunyai mode browser khusus. Chrome MIDETA membuka percakapan, menampilkan balasan yang tersedia, lalu membaca tanggal, username author, isi komentar, likes, dan jumlah reply. Data hanya diambil dari percakapan posting target. Bagian rekomendasi tidak dimasukkan.

Tipe `parent` berarti komentar tersebut ditulis langsung pada posting. Tipe `reply` berarti komentar tersebut merupakan balasan. Urutan ranking dihitung dari kombinasi likes dan jumlah reply agar komentar dengan engagement terbesar muncul lebih dahulu.

File CSV dan XLSX mengikuti susunan `index`, `date`, `author`, `type`, `comment`, dan `like`. Kolom `index` menjadi urutan ranking. Tanggal ditulis seperti `Aug 20, 2026`, sesuai format file contoh.

Setelah proses selesai, halaman menampilkan preview postingan pertama, jumlah seluruh komentar, jumlah parent, dan jumlah reply. Jika beberapa URL ditempel sekaligus, semua komentarnya tetap digabungkan dalam satu hasil untuk platform yang sedang dipilih.

### Riwayat Analisis

Setiap proses disimpan ke database SQLite lokal. Halaman riwayat menyediakan pencarian, filter berdasarkan fitur, platform, dan tanggal, serta pilihan untuk melihat detail atau menghapus hasil.

## Cara menggunakan

1. Jalankan MIDETA dan buka `http://localhost:8501`.
2. Masuk ke Social Media Enrichment atau Comment Scrapper.
3. Pilih platform yang ingin diproses.
4. Tempel satu atau beberapa URL. Gunakan satu baris untuk satu URL.
5. Tekan tombol pengambilan data.
6. Periksa hasilnya, lalu unduh CSV atau XLSX jika diperlukan.

### Mode browser Instagram

1. Pilih Instagram pada halaman Social Media Enrichment.
2. Aktifkan `Gunakan browser Instagram`.
3. Tekan `Buka Chrome Instagram`.
4. Login langsung di jendela Chrome yang terbuka.
5. Kembali ke MIDETA dan tekan `Periksa Login`.
6. Masukkan URL lalu jalankan pengambilan metadata seperti biasa.

Login cukup dilakukan sekali selama sesi Instagram masih aktif. Password diketik langsung di Instagram dan tidak dibaca oleh MIDETA.

### Mode browser Threads dan X

1. Pilih Threads atau X pada halaman Comment Scrapper.
2. Biarkan pilihan browser untuk platform tersebut tetap aktif.
3. Masukkan URL posting dan tekan `Ambil Semua Komentar`.
4. Jika percakapan dibatasi, tekan tombol untuk membuka sesi platform, login langsung di Chrome MIDETA satu kali, lalu tekan `Periksa Login`.

Threads dan X memakai profil Chrome yang berbeda. Sesi otomatis dipakai kembali sampai kedaluwarsa atau pengguna logout. Password tetap diketik langsung di situs dan tidak dibaca MIDETA.

## Cara kerja Comment Scrapper untuk Threads dan X

1. URL diperiksa dan harus sesuai dengan platform yang sedang dipilih.
2. ID posting Threads atau status X dibaca dari URL.
3. MIDETA membuka halaman percakapan dan menampilkan balasan yang masih tersembunyi.
4. Pada Threads, setiap komentar dicocokkan melalui ID parent dan ID posting utama.
5. Pada X, komentar dicocokkan melalui `conversation_id` dan ID tweet yang dibalas.
6. Posting utama dan rekomendasi dibuang dari hasil.
7. Komentar langsung diberi tipe `parent`, sedangkan balasan komentar diberi tipe `reply`.
8. Likes dan jumlah reply dipakai untuk menyusun ranking.
9. Hasil disimpan ke riwayat dan dapat diunduh sebagai CSV atau XLSX.

## Cara kerja Social Media Enrichment

Proses enrichment dimulai dari URL dan berakhir sebagai baris data yang sudah seragam. Alurnya sebagai berikut:

1. `get_connector()` membaca domain URL dan memilih connector yang sesuai.
2. `validate_public_url()` memeriksa format URL, port, alamat jaringan, dan kredensial yang mungkin tersisip di URL.
3. `fetch_public_html()` membuka halaman publik dan mengikuti redirect. Tahap ini berguna untuk link singkat atau link share yang mengarah ke alamat posting asli.
4. HTML dibaca dengan BeautifulSoup. Data JSON yang terdapat di dalam tag script juga ikut diperiksa.
5. Connector mencari ID posting dari URL final atau URL canonical.
6. Data di sekitar ID tersebut dipilih agar hasil tidak tertukar dengan posting rekomendasi yang berada pada halaman yang sama.
7. Author, caption, tanggal posting, dan angka engagement diambil dari metadata, JSON LD, serta data script publik yang tersedia.
8. Hasil dinormalisasi ke struktur `SocialResult` agar semua platform mempunyai bentuk output yang sama.
9. Beberapa hasil digabungkan menjadi satu batch, disimpan ke SQLite, lalu disiapkan untuk ekspor.

## Cara kerja enrichment Facebook

Facebook mempunyai beberapa bentuk URL, antara lain post, video, reel, share, dan permalink grup. Connector Facebook menangani perbedaan tersebut dengan langkah berikut:

1. Link dibuka sampai mendapatkan URL tujuan sebenarnya.
2. ID post atau video diambil dari URL final.
3. Connector mencari bagian data Facebook yang mempunyai ID sama.
4. Author dibaca dari data `actors` atau `owning_profile` milik post tersebut.
5. Untuk posting grup, nama grup dibaca dari objek grup. Kolom Author kemudian ditulis sebagai `Nama author - Nama grup`.
6. Caption pendek dari metadata dibandingkan dengan teks post di dalam script. Jika versi lengkap tersedia, MIDETA memakai versi lengkap.
7. Views, likes, comments, dan shares dibaca dari data feedback, metadata, atau label publik yang tersedia.
8. Angka singkat seperti `23 rb` dan `1,3 jt` diubah menjadi nilai numerik agar dapat dipakai untuk analisis.

Domain Facebook yang dikenali adalah `facebook.com`, `www.facebook.com`, `web.facebook.com`, `m.facebook.com`, dan `fb.watch`.

Contoh alur fungsi dalam bentuk sederhana:

```python
def enrich(url):
    validate_public_url(url)
    connector = get_connector(url)
    html, final_url = fetch_public_html(url)

    post_id = connector.find_post_id(final_url)
    post_data = connector.find_post_data(html, post_id)

    result = connector.extract(post_data)
    return normalize_result(result)
```

Potongan di atas hanya menggambarkan alurnya. Implementasi sebenarnya memisahkan validasi, request HTTP, parsing umum, parsing khusus platform, penyimpanan, dan ekspor ke modul yang berbeda.

## Struktur project

```text
app.py                         halaman utama
pages/                         halaman fitur Streamlit
src/connectors/                parser untuk setiap platform
src/http_client.py             request HTTP dan pemeriksaan redirect
src/instagram_browser.py       pembacaan Instagram melalui Chrome yang sudah login
src/comment_browser.py         pembacaan komentar dinamis Threads dan X melalui Chrome
src/validators.py              validasi URL dan perlindungan jaringan lokal
src/models.py                  bentuk data hasil pengambilan
src/batch.py                   pemrosesan beberapa URL dan ranking komentar
src/database.py                penyimpanan riwayat SQLite
src/exporters.py               pembuatan CSV dan XLSX
assets/styles.css              tampilan aplikasi
sample_data/                   data contoh
tests/                         automated tests
```

## Instalasi

MIDETA membutuhkan Python 3.12 atau versi yang lebih baru. Mode browser Instagram, Threads, dan X juga membutuhkan Google Chrome.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Database akan dibuat otomatis di `data/mideta.db`. File database tidak dimasukkan ke repository.

## Pengujian

Jalankan pemeriksaan syntax dan seluruh automated tests dengan perintah berikut:

```bash
.venv/bin/python -m compileall app.py pages src tests
.venv/bin/python -m unittest discover -s tests -v
```

Tests mencakup validasi URL, pemilihan connector, parsing metadata, parsing Facebook Reel dan grup, pengambilan caption lengkap, pemisahan data posting utama dari rekomendasi, pembacaan angka browser Instagram, koleksi parent dan reply Threads serta X, ranking komentar, database, CSV, dan XLSX.

## Data contoh

Social Media Enrichment dan Comment Scrapper mempunyai pilihan data contoh. Pilihan ini hanya digunakan untuk melihat bentuk hasil tanpa melakukan request ke platform. Setiap hasil contoh diberi penanda agar tidak dianggap sebagai hasil pengambilan nyata.

## Batasan

Secara bawaan, MIDETA hanya membaca informasi yang diberikan pada halaman publik. Mode browser Instagram, Threads, dan X dapat menggunakan login yang dilakukan sendiri oleh pengguna. MIDETA tidak mengisi password, melewati CAPTCHA, atau mencoba menembus pembatasan platform.

Struktur halaman media sosial dapat berubah. Jika platform mengubah nama field atau susunan datanya, connector terkait perlu diperbarui. Jumlah informasi yang tersedia juga dapat berbeda pada setiap posting.

## Privasi dan keamanan

URL diperiksa sebelum request dan setelah redirect. Alamat lokal, jaringan privat, kredensial di URL, serta port yang bukan port web ditolak. Request mempunyai batas waktu dan ukuran respons dibatasi hingga 8 MB.

Repository tidak menyimpan token, password, file `.env`, Streamlit secrets, database riwayat pengguna, atau profil browser. Sesi Chrome MIDETA berada di `data/browser_profiles/` pada komputer lokal dan folder tersebut diabaikan oleh Git.
