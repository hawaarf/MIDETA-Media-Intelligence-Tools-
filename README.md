# MIDETA

[Bahasa Indonesia](#bahasa-indonesia) · [English](#english)

## Bahasa Indonesia

MIDETA adalah aplikasi lokal untuk mengambil metadata posting dan komentar media sosial. Aplikasi ini dibuat dengan Python dan Streamlit.

Platform yang didukung:

- YouTube
- TikTok
- Facebook
- Instagram
- Threads
- X

### Fitur

#### Social Media Enrichment

Fitur ini mengambil data berikut dari sebuah posting:

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

Masukkan satu URL per baris. Maksimal 1.000 URL untuk setiap proses.

URL boleh ditempel bersama data lain dari spreadsheet. Contoh:

```text
Aug 30, 2026 https://www.instagram.com/p/contoh/
```

MIDETA akan mengambil bagian URL-nya saja.

Hasil disimpan setelah setiap URL selesai. Jika aplikasi atau koneksi terhenti, proses dapat dilanjutkan dari URL terakhir yang belum selesai.

#### Mode Instagram

Fast dan Advanced sama-sama membutuhkan login Instagram di Chrome MIDETA.

| Mode | Data yang diambil | Kecepatan |
| --- | --- | --- |
| Fast | Author, caption, tanggal, likes, comments, shares, dan repost | Lebih cepat. Tidak membuka profil atau tab Reels untuk mencari Followers dan Views. |
| Advanced | Semua data Fast, ditambah Followers dan Views | Lebih lama karena membuka posting, profil author, dan tab Reels. |

Fast memproses 10 URL per tahap. Advanced memproses 5 URL per tahap agar pemeriksaan Followers dan Views lebih stabil.

Cara login:

1. Pilih Instagram di halaman Social Media Enrichment.
2. Pilih Fast atau Advanced.
3. Tekan `Buka Chrome Instagram`.
4. Login langsung di Instagram.
5. Kembali ke MIDETA, lalu tekan `Periksa Login`.
6. Masukkan URL dan mulai enrichment.

Password hanya diketik di Instagram dan tidak dibaca oleh MIDETA.

#### Split Screen dan Triple Screen

Gunakan tampilan berikut untuk menjalankan beberapa platform sekaligus:

- `Satu platform` untuk satu proses.
- `Split Screen` untuk dua platform.
- `Triple Screen` untuk tiga platform.

Setiap panel mempunyai input, progres, hasil, dan file unduhan sendiri. Maksimal tiga platform berjalan bersamaan. URL di dalam setiap panel tetap diproses secara berurutan supaya datanya tidak tertukar.

#### Catatan platform

- Facebook mencocokkan data dengan ID posting target agar data dari posting rekomendasi tidak ikut terbaca.
- Facebook memakai jumlah followers. Jika followers tidak tersedia tetapi jumlah friends tersedia, MIDETA memakai jumlah friends.
- Bookmark Facebook Reel hanya diisi jika angkanya memang tersedia.
- Views Facebook dan Instagram Reel dicari dari posting atau daftar Reels author yang cocok.
- Threads mencocokkan tanggal, views, jumlah komentar, dan shares dengan posting target.
- Nilai engagement adalah snapshot saat URL diperiksa. Angkanya dapat berubah setelah proses selesai.
- Data yang tidak diberikan platform akan ditulis sebagai `Tidak tersedia` atau `0`, sesuai jenis datanya.

#### Comment Scrapper

Fitur ini mengambil komentar dari sebuah posting. Setiap platform mempunyai panel sendiri agar URL dan hasilnya tidak tercampur.

Untuk Threads dan X, MIDETA memakai Chrome khusus karena komentarnya dimuat melalui JavaScript. Jika posting tidak terlihat, buka sesi platform, login, periksa login, lalu jalankan kembali prosesnya.

Hasil komentar berisi:

- `index`: urutan ranking
- `date`: tanggal komentar
- `author`: username
- `type`: `parent` atau `reply`
- `comment`: isi komentar
- `like`: jumlah likes

`parent` adalah komentar langsung pada posting. `reply` adalah balasan terhadap komentar lain.

Tanggal komentar memakai format seperti `Aug 20, 2026`. Tanggal posting enrichment memakai format seperti `25-Aug-2026`.

#### Riwayat Analisis

Hasil proses disimpan di database SQLite lokal. Riwayat dapat dicari dan difilter berdasarkan fitur, platform, dan tanggal.

### Cara menjalankan

MIDETA membutuhkan Python 3.12 atau yang lebih baru. Fitur browser membutuhkan Google Chrome.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Buka `http://localhost:8501` setelah aplikasi berjalan.

Database dibuat otomatis di `data/mideta.db` dan tidak dimasukkan ke GitHub.

### Cara pakai

1. Buka Social Media Enrichment atau Comment Scrapper.
2. Pilih tampilan proses dan platform.
3. Tempel satu atau beberapa URL.
4. Untuk Instagram, pilih Fast atau Advanced dan pastikan sudah login.
5. Tekan tombol mulai.
6. Periksa hasilnya.
7. Unduh CSV atau XLSX jika diperlukan.

Untuk proses besar, gunakan tombol `Jeda proses` atau `Lanjutkan proses`. Jika platform membatasi request, MIDETA akan menjeda antrean agar dapat dilanjutkan nanti.

### Format file

- CSV berisi data teks dan tidak menyimpan pengaturan font.
- XLSX memakai font Arial ukuran 10 untuk header dan data.

### Struktur project

```text
app.py                         halaman utama
pages/                         halaman Streamlit
src/connectors/                pembaca data setiap platform
src/instagram_browser.py       browser Instagram
src/comment_browser.py         browser komentar Threads dan X
src/batch.py                   antrean URL dan hasil
src/database.py                database SQLite
src/exporters.py               pembuat CSV dan XLSX
assets/styles.css              tampilan aplikasi
sample_data/                   data contoh
tests/                         automated tests
```

### Pengujian

```bash
.venv/bin/python -m compileall app.py pages src tests
.venv/bin/python -m unittest discover -s tests -v
```

### Batasan

- Hasil bergantung pada data yang ditampilkan oleh platform.
- Struktur halaman media sosial dapat berubah dan membuat beberapa data tidak terbaca.
- Postingan privat, login yang kedaluwarsa, CAPTCHA, dan pembatasan request dapat menghentikan proses.
- MIDETA tidak melewati login, CAPTCHA, atau batas akses platform.

### Privasi

- URL diperiksa sebelum dibuka.
- Alamat lokal, jaringan privat, kredensial di URL, dan port non-web ditolak.
- Repository tidak menyimpan password, token, file `.env`, database riwayat, atau profil browser.
- Sesi Chrome MIDETA disimpan lokal di `data/browser_profiles/` dan folder tersebut tidak dimasukkan ke GitHub.

---

## English

MIDETA is a local app for collecting social media post metadata and comments. It is built with Python and Streamlit.

Supported platforms:

- YouTube
- TikTok
- Facebook
- Instagram
- Threads
- X

### Features

#### Social Media Enrichment

This feature collects the following data from a post:

1. Post date
2. Author
3. Caption
4. Followers
5. Views
6. Likes
7. Comments
8. Saves or bookmarks
9. Shares
10. Reposts

Enter one URL per line. Each run can contain up to 1,000 URLs.

You can also paste URLs with other spreadsheet data. Example:

```text
Aug 30, 2026 https://www.instagram.com/p/example/
```

MIDETA will use the URL and ignore the other text.

Each result is saved as soon as the URL is finished. If the app or connection stops, the run can continue from the last unfinished URL.

#### Instagram modes

Fast and Advanced both require an Instagram login in the MIDETA Chrome window.

| Mode | Data collected | Speed |
| --- | --- | --- |
| Fast | Author, caption, date, likes, comments, shares, and reposts | Faster. It does not open the profile or Reels tab to find Followers and Views. |
| Advanced | All Fast data, plus Followers and Views | Slower because it opens the post, author profile, and Reels tab. |

Fast processes 10 URLs per stage. Advanced processes 5 URLs per stage to make the Followers and Views checks more stable.

How to log in:

1. Select Instagram on the Social Media Enrichment page.
2. Select Fast or Advanced.
3. Click `Buka Chrome Instagram`.
4. Log in directly on Instagram.
5. Return to MIDETA and click `Periksa Login`.
6. Enter the URLs and start enrichment.

Your password is entered only on Instagram and is not read by MIDETA.

#### Split Screen and Triple Screen

Use these layouts to run more than one platform:

- `Satu platform` for one process.
- `Split Screen` for two platforms.
- `Triple Screen` for three platforms.

Each panel has its own input, progress, results, and downloads. Up to three platforms can run at the same time. URLs inside each panel are still processed in order so results do not get mixed.

#### Platform notes

- Facebook matches data to the target post ID so recommended posts are not included.
- Facebook uses the follower count. If followers are unavailable but friends are public, MIDETA uses the friend count.
- Facebook Reel bookmarks are only filled when a public count is available.
- Facebook and Instagram Reel views are checked on the matching post or the author's Reels list.
- Threads matches the date, views, comment count, and shares to the target post.
- Engagement values are a snapshot taken during the run. They may change later.
- Missing platform data is shown as `Tidak tersedia` or `0`, depending on the field.

#### Comment Scrapper

This feature collects comments from a post. Each platform has a separate panel so URLs and results do not get mixed.

For Threads and X, MIDETA uses a dedicated Chrome window because comments are loaded with JavaScript. If the post is not visible, open the platform session, log in, check the login, and run the URL again.

Comment results contain:

- `index`: ranking order
- `date`: comment date
- `author`: username
- `type`: `parent` or `reply`
- `comment`: comment text
- `like`: like count

A `parent` is a direct comment on the post. A `reply` is a response to another comment.

Comment dates use a format such as `Aug 20, 2026`. Enrichment post dates use a format such as `25-Aug-2026`.

#### Analysis History

Run results are saved in a local SQLite database. History can be searched and filtered by feature, platform, and date.

### Setup

MIDETA requires Python 3.12 or newer. Browser features also require Google Chrome.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Open `http://localhost:8501` after the app starts.

The database is created automatically at `data/mideta.db` and is not committed to GitHub.

### How to use

1. Open Social Media Enrichment or Comment Scrapper.
2. Select the process layout and platform.
3. Paste one or more URLs.
4. For Instagram, select Fast or Advanced and make sure you are logged in.
5. Start the process.
6. Review the results.
7. Download CSV or XLSX if needed.

For large runs, use `Jeda proses` or `Lanjutkan proses`. If a platform limits requests, MIDETA pauses the queue so it can be resumed later.

### File format

- CSV contains text data and cannot store font settings.
- XLSX uses Arial size 10 for headers and data.

### Project structure

```text
app.py                         main page
pages/                         Streamlit pages
src/connectors/                platform data readers
src/instagram_browser.py       Instagram browser support
src/comment_browser.py         Threads and X comment browser
src/batch.py                   URL queues and results
src/database.py                SQLite database
src/exporters.py               CSV and XLSX exports
assets/styles.css              app styles
sample_data/                   sample data
tests/                         automated tests
```

### Tests

```bash
.venv/bin/python -m compileall app.py pages src tests
.venv/bin/python -m unittest discover -s tests -v
```

### Limitations

- Results depend on the data shown by each platform.
- Social media page structures can change and may cause some fields to become unavailable.
- Private posts, expired logins, CAPTCHAs, and request limits can stop a run.
- MIDETA does not bypass logins, CAPTCHAs, or platform access limits.

### Privacy

- URLs are checked before they are opened.
- Local addresses, private networks, credentials in URLs, and non-web ports are rejected.
- The repository does not store passwords, tokens, `.env` files, history databases, or browser profiles.
- MIDETA Chrome sessions are stored locally in `data/browser_profiles/`. This folder is not committed to GitHub.
