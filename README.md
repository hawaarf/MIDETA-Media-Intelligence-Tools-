# MIDETA

MIDETA membantu merapikan metadata dan komentar dari posting media sosial. Aplikasi berjalan di komputer sendiri, hasilnya bisa dicek langsung lalu diunduh sebagai CSV atau XLSX.

[Baca dalam Bahasa Indonesia](#bahasa-indonesia) · [Read in English](#english)

## Bahasa Indonesia

### Yang bisa dilakukan

MIDETA punya empat bagian utama:

- **Social Media Enrichment** untuk mengambil tanggal posting, author, caption, followers, views, likes, comments, bookmark, shares, dan repost.
- **Comment Scrapper** untuk mengambil komentar publik, membedakan komentar utama dan reply, lalu mengurutkannya berdasarkan engagement.
- **Riwayat Analisis** untuk membuka kembali hasil yang pernah diproses.
- **Threads Tracker** untuk mencari posting Threads berdasarkan keyword, rentang waktu, dan engagement.

Platform yang didukung: YouTube, TikTok, Facebook, Instagram, Threads, dan X.

### Social Media Enrichment

Untuk satu platform, tempel satu URL per baris lalu mulai proses. Satu antrean dapat berisi sampai 1.000 URL.

Kalau URL-nya berasal dari beberapa platform, pilih **Enrichment All**. Tempel semua URL dalam satu kotak tanpa memilah Facebook, Instagram, YouTube, TikTok, Threads, atau X. MIDETA mengenali platform secara otomatis, menjalankan antreannya dengan pembaca yang sesuai, lalu menampilkan satu tabel dan satu file hasil gabungan. Satu proses Enrichment All dapat berisi sampai 1.000 URL total.

MIDETA juga bisa membaca URL yang tercampur dengan tanggal atau teks hasil salin dari spreadsheet. Contohnya:

```text
Aug 30, 2026 https://www.instagram.com/p/contoh/
```

Hanya URL-nya yang akan dipakai. Hasil disimpan setiap kali satu URL selesai, jadi antrean panjang bisa dijeda dan dilanjutkan tanpa mulai dari awal.

#### Pilihan mode Instagram

Fast dan Advanced sama-sama memakai Chrome khusus MIDETA yang sudah login ke Instagram.

| Mode | Cocok untuk | Data yang diperiksa |
| --- | --- | --- |
| **Fast** | Saat hanya butuh engagement dengan cepat | Author, caption, tanggal, likes, comments, shares, dan repost |
| **Advanced** | Saat followers dan views juga dibutuhkan | Semua data Fast, ditambah followers dan views jika memang tersedia |

Fast tidak membuka profil author. Advanced membuka posting dan profil, sehingga waktunya lebih lama tetapi pemeriksaannya lebih lengkap.

Instagram tidak menampilkan views untuk semua jenis posting. Foto dan carousel akan ditulis **Tidak tersedia**, bukan dipaksa menjadi `0`. Untuk video atau Reels, MIDETA mengambil views dari posting yang sesuai. Angka likes, comments, shares, dan repost juga dicocokkan ke posting target agar tidak tertukar dengan slide carousel atau posting lain.

Cara menyiapkan login Instagram:

1. Pilih Instagram di halaman **Social Media Enrichment**.
2. Pilih Fast atau Advanced.
3. Klik **Buka Chrome Instagram**.
4. Login langsung di jendela Instagram yang terbuka.
5. Kembali ke MIDETA dan klik **Periksa Login**.
6. Masukkan URL lalu mulai enrichment.

Password hanya diketik di Instagram. MIDETA tidak membaca atau menyimpannya.

#### TikTok Free Mode

Pilih **Free tanpa login** agar TikTok tidak dibuka satu per satu di Chrome. Caption dan author tetap dibaca dari metadata publik TikTok. Untuk mendapatkan views, followers, likes, comments, shares, dan bookmark, MIDETA memakai kredit gratis Apify.

Cara menyiapkannya:

1. Buat akun gratis di [Apify](https://console.apify.com/sign-up).
2. Buka **Settings → API & Integrations** di Apify dan salin API token.
3. Pilih TikTok di halaman **Social Media Enrichment**.
4. Tempel token pada kolom **Apify API token**, lalu klik **Simpan token**.
5. Masukkan URL video dan mulai TikTok Free Mode.

Token disimpan di folder privat pada komputer ini. Token tidak masuk ke Git, database MIDETA, atau file hasil. Jika token belum dipasang atau kredit gratis habis, MIDETA tetap mencoba caption dan author. Kolom lain akan ditandai belum tersedia, bukan diisi dengan angka tebakan.

Mode **Chrome login** masih tersedia sebagai cadangan. TikTok kadang memberi HTTP 403 ketika banyak URL dibuka berurutan. Jika itu terjadi, hentikan sesi browser dan gunakan Free Mode.

#### Menjalankan beberapa platform

Gunakan **Satu platform**, **Split Screen**, atau **Triple Screen** jika ingin mengatur setiap platform secara terpisah. Setiap panel punya input, antrean, progres, hasil, dan tombol unduh sendiri. Maksimal tiga platform dapat dijalankan dalam satu tampilan tanpa mencampur hasil antarplatform. Gunakan **Enrichment All** jika ingin memasukkan URL campuran dan mengunduh satu hasil gabungan.

### Comment Scrapper

Pilih platform dan masukkan URL posting yang ingin diperiksa. Hasil komentar berisi:

- tanggal komentar;
- username author;
- tipe `parent` atau `reply`;
- isi komentar;
- jumlah likes dan reply.

Facebook, Threads, dan X memakai Chrome khusus MIDETA karena komentarnya baru dimuat saat halaman dibuka. Sebelum pengambilan pertama, klik **Buka Sesi**, login di Chrome MIDETA, lalu klik **Periksa Login**. Sesi akan dipakai kembali sampai kedaluwarsa atau logout.

MIDETA dapat mengambil maksimal 2.000 komentar dari setiap URL. Progress bar menampilkan jumlah yang sudah ditemukan selama halaman di-scroll dan reply dibuka. Platform tetap dapat menyembunyikan atau membatasi sebagian komentar.

Comment Scrapper juga mendukung Split Screen dan Triple Screen, dengan hasil terpisah untuk setiap platform.

### Threads Tracker

Threads Tracker mencari posting melalui halaman pencarian Threads. Masukkan satu keyword, lalu pilih:

- **Recent (24 jam)** untuk posting dalam 24 jam terakhir;
- **Last 7 days** untuk posting dalam tujuh hari terakhir;
- **All** untuk semua hasil yang berhasil dimuat.

Hasil dapat diurutkan dari engagement paling ramai, engagement paling rendah, atau posting terbaru. Total engagement dihitung dari Likes + Comments + Reposts + Shares. Maksimal 200 hasil dapat diambil dalam satu pencarian, lalu hasilnya dapat diunduh sebagai CSV atau XLSX.

Fitur ini membutuhkan login di Chrome Threads Tracker. Sesi browsernya dibuat terpisah dari Comment Scrapper agar keduanya tidak saling mengganggu. Pilihan **All** berarti seluruh hasil yang berhasil diberikan dan dimuat oleh Threads, bukan seluruh arsip Threads tanpa batas.

### Catatan hasil

- Angka engagement adalah snapshot saat URL diperiksa dan bisa berubah sesudahnya.
- MIDETA mencocokkan data dengan posting target. Data dari rekomendasi, caption, atau posting lain tidak dipakai sebagai engagement.
- Jika Facebook tidak menampilkan followers tetapi menampilkan friends, jumlah friends dipakai sebagai pengganti.
- Bookmark Facebook Reels hanya diisi bila Facebook benar-benar menampilkan angkanya.
- Data yang memang tidak diberikan platform ditulis **Tidak tersedia**. Nilai `0` hanya dipakai jika platform menyatakan angkanya nol.
- Postingan privat, sesi login kedaluwarsa, CAPTCHA, perubahan tampilan platform, dan rate limit dapat membuat sebagian data tidak terbaca.

**Jika halaman tidak mau terbuka saat memakai akun yang login:** enrichment dalam jumlah besar kadang membuat platform membatasi akun atau sesi tersebut untuk sementara. Gejalanya bisa berupa halaman kosong, halaman gagal dimuat, atau data tidak muncul di Chrome MIDETA. Jeda prosesnya, lalu login atau pindah ke akun media sosial lain dan lanjutkan antrean. Akun sebelumnya dapat dipakai lagi setelah aksesnya kembali normal. Hindari mencoba URL yang sama terus-menerus saat akun masih dibatasi.

### Menjalankan MIDETA

Yang dibutuhkan:

- Python 3.12 atau lebih baru;
- Google Chrome untuk fitur yang membutuhkan login.

Jalankan perintah berikut dari folder project:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Setelah itu buka [http://localhost:8501](http://localhost:8501).

### File hasil dan data lokal

- CSV menyimpan data teks saja, jadi tidak memiliki pengaturan font.
- XLSX memakai Arial ukuran 10 untuk header dan isi data.
- Riwayat tersimpan di `data/mideta.db`.
- Sesi Chrome tersimpan di `data/browser_profiles/`.
- Database, sesi browser, password, token, dan file `.env` tidak dimasukkan ke GitHub.

### Menjalankan test

```bash
.venv/bin/python -m compileall app.py pages src tests
.venv/bin/python -m unittest discover -s tests -v
```

### Struktur singkat

```text
app.py                     halaman utama
pages/                     halaman fitur Streamlit
src/connectors/            pembaca data tiap platform
src/instagram_browser.py   enrichment Instagram dengan login
src/comment_browser.py     pengambilan komentar Facebook, Threads, dan X
src/threads_tracker.py     pencarian keyword dan ranking Threads
src/batch.py               antrean dan pemulihan proses
src/database.py            penyimpanan riwayat lokal
src/exporters.py           pembuatan CSV dan XLSX
tests/                     automated tests
```

---

## English

MIDETA cleans up post metadata and comments from social media. It runs on your own computer, lets you review the results, and exports them as CSV or XLSX.

### What it does

MIDETA has four main sections:

- **Social Media Enrichment** collects the post date, author, caption, followers, views, likes, comments, bookmarks, shares, and reposts.
- **Comment Scrapper** collects public comments, separates parent comments from replies, and ranks them by engagement.
- **Analysis History** keeps earlier results available for review.
- **Threads Tracker** finds Threads posts by keyword, time range, and engagement.

Supported platforms: YouTube, TikTok, Facebook, Instagram, Threads, and X.

### Social Media Enrichment

For a single platform, paste one URL per line and start the run. A queue can contain up to 1,000 URLs.

For a mixed list, choose **Enrichment All**. Paste Facebook, Instagram, YouTube, TikTok, Threads, and X URLs into the same box. MIDETA detects each platform, sends every URL to the right collector, and returns one combined table and download. One Enrichment All run can contain up to 1,000 URLs in total.

URLs copied together with spreadsheet text also work. For example:

```text
Aug 30, 2026 https://www.instagram.com/p/example/
```

MIDETA uses the URL and ignores the surrounding text. Each result is saved as soon as it finishes, so a large queue can be paused and resumed without starting over.

#### Instagram modes

Fast and Advanced both use a dedicated MIDETA Chrome profile logged in to Instagram.

| Mode | Best for | Data checked |
| --- | --- | --- |
| **Fast** | Getting engagement quickly | Author, caption, date, likes, comments, shares, and reposts |
| **Advanced** | Runs that also need followers and views | All Fast fields, plus followers and views when available |

Fast does not open the author's profile. Advanced checks both the post and profile, so it takes longer but returns more complete data.

Instagram does not publish views for every post type. Photos and carousels are marked **Tidak tersedia** instead of being forced to `0`. For videos and Reels, MIDETA looks for views that belong to the target post. Likes, comments, shares, and reposts are also matched to that post so carousel slides or nearby posts do not get mixed in.

To set up Instagram login:

1. Select Instagram on the **Social Media Enrichment** page.
2. Choose Fast or Advanced.
3. Click **Buka Chrome Instagram**.
4. Log in directly in the Instagram window.
5. Return to MIDETA and click **Periksa Login**.
6. Paste the URLs and start enrichment.

Your password is entered only on Instagram. MIDETA does not read or store it.

#### TikTok Free Mode

Choose **Free tanpa login** so MIDETA does not open every TikTok URL in Chrome. Captions and authors come from TikTok's public metadata. MIDETA uses Apify's free credits for views, followers, likes, comments, shares, and bookmarks.

Setup:

1. Create a free [Apify](https://console.apify.com/sign-up) account.
2. Open **Settings → API & Integrations** in Apify and copy the API token.
3. Select TikTok on the **Social Media Enrichment** page.
4. Paste the token into **Apify API token**, then click **Simpan token**.
5. Paste the video URLs and start TikTok Free Mode.

The token stays in a private folder on this computer. It is not added to Git, the MIDETA database, or exported files. If no token is configured or the free credits run out, MIDETA still tries to collect the caption and author. Other fields are marked unavailable instead of being filled with guessed numbers.

**Chrome login** remains available as a fallback. TikTok may return HTTP 403 when several URLs are opened in sequence. If that happens, stop the browser session and use Free Mode.

#### Running multiple platforms

Choose **Satu platform**, **Split Screen**, or **Triple Screen** when you want to manage each platform separately. Every panel has its own input, queue, progress, results, and download buttons. Up to three platforms can run in one view without mixing their results. Choose **Enrichment All** for a mixed URL list and one combined download.

### Comment Scrapper

Choose a platform and paste the post URLs. Comment results include:

- comment date;
- author username;
- `parent` or `reply` type;
- comment text;
- like and reply counts.

Facebook, Threads, and X use dedicated MIDETA Chrome profiles because their comments load inside the page. Before the first run, click **Buka Sesi**, log in through MIDETA Chrome, then click **Periksa Login**. The saved session is reused until it expires or you log out.

MIDETA can collect up to 2,000 comments from each URL. The progress bar shows how many have been found while the page is scrolled and replies are opened. The platform may still hide or limit part of a conversation.

Comment Scrapper also supports Split Screen and Triple Screen, with separate results for every platform.

### Threads Tracker

Threads Tracker searches posts through the Threads search page. Enter one keyword, then choose:

- **Recent (24 hours)** for posts from the last 24 hours;
- **Last 7 days** for posts from the last seven days;
- **All** for every result that can be loaded.

Results can be sorted by highest engagement, lowest engagement, or newest post. Total engagement is calculated as Likes + Comments + Reposts + Shares. Each search can collect up to 200 results and export them as CSV or XLSX.

This feature requires a login in its dedicated Threads Tracker Chrome profile. Its browser session is separate from Comment Scrapper so the two features do not interfere with each other. **All** means all results returned and loaded by Threads, not the platform's complete archive.

### Notes about the results

- Engagement is a snapshot and may change after the run.
- MIDETA matches metrics to the target post. Values from recommendations, captions, or nearby posts are not treated as engagement.
- If Facebook has no public follower count but shows friends, MIDETA uses the friend count.
- Facebook Reel bookmarks are filled only when Facebook displays a real count.
- Data that a platform does not provide is marked **Tidak tersedia**. `0` is used only when the platform reports zero.
- Private posts, expired sessions, CAPTCHAs, layout changes, and rate limits may leave some fields unavailable.

**If pages stop loading for the logged-in account:** a large enrichment run may cause the platform to temporarily limit that account or browser session. The page may appear blank, fail to load, or return no data in MIDETA Chrome. Pause the run, log in or switch to another social media account, and then resume the queue. The previous account can be used again after its access returns to normal. Avoid repeatedly retrying the same URLs while the account is still limited.

### Running MIDETA

Requirements:

- Python 3.12 or newer;
- Google Chrome for login-based features.

Run these commands from the project folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Then open [http://localhost:8501](http://localhost:8501).

### Exports and local data

- CSV stores plain text and cannot keep font settings.
- XLSX uses Arial size 10 for headers and data.
- History is stored in `data/mideta.db`.
- Chrome sessions are stored in `data/browser_profiles/`.
- Databases, browser sessions, passwords, tokens, and `.env` files are not committed to GitHub.

### Running the tests

```bash
.venv/bin/python -m compileall app.py pages src tests
.venv/bin/python -m unittest discover -s tests -v
```

### Project layout

```text
app.py                     home page
pages/                     Streamlit feature pages
src/connectors/            platform data readers
src/instagram_browser.py   logged-in Instagram enrichment
src/tiktok_browser.py      logged-in TikTok fallback
src/tiktok_free.py         no-login TikTok enrichment
src/comment_browser.py     Facebook, Threads, and X comment collection
src/threads_tracker.py     Threads keyword search and ranking
src/batch.py               queues and resume support
src/database.py            local history storage
src/exporters.py           CSV and XLSX generation
tests/                     automated tests
```
