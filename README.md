# MIDETA

MIDETA membantu merapikan metadata media sosial, komentar publik, dan artikel media konvensional. Aplikasi berjalan di komputer sendiri, hasilnya bisa dicek langsung lalu diunduh sebagai CSV atau XLSX.

> **Aman untuk dijalankan secara lokal.** MIDETA tidak meminta, membaca, atau menyimpan password. Login dilakukan langsung di situs resmi melalui Chrome khusus MIDETA. Cookie sesi browser dan token API opsional hanya tersimpan secara lokal di folder yang diabaikan Git; data tersebut tidak dimasukkan ke CSV/XLSX dan tidak ikut ter-push ke GitHub. Jangan menulis password atau token langsung di source code.

> **Privacy-first local operation.** MIDETA never asks for, reads, or stores passwords. Authentication happens directly on the official website through MIDETA's dedicated Chrome profile. Browser-session cookies and optional API tokens remain in Git-ignored local folders; they are never included in CSV/XLSX exports or pushed to GitHub. Never hard-code passwords or tokens in the source code.

[Baca dalam Bahasa Indonesia](#bahasa-indonesia) · [Read in English](#english)

## Bahasa Indonesia

### Yang bisa dilakukan

MIDETA punya empat bagian utama:

- **Social Media Enrichment** untuk mengambil tanggal posting, author, caption, followers, views, likes, comments, bookmark, shares, dan repost.
- **Comment Scrapper** untuk mengambil komentar publik, membedakan komentar utama dan reply, lalu mengurutkannya berdasarkan engagement.
- **Conventional Media Enrichment** untuk membersihkan artikel berita serta melengkapi tanggal, media, scope, tier, journalist, tone, quote mention, dan jenis penyebutan direct/indirect.
- **Riwayat Analisis** untuk membuka kembali hasil yang pernah diproses.

Platform media sosial yang didukung: YouTube, TikTok, Facebook, Instagram, Threads, dan X. Conventional Media Enrichment dapat menerima URL artikel dari berbagai situs berita publik.

### Social Media Enrichment

Untuk satu platform, tempel satu URL per baris lalu mulai proses. Satu antrean dapat berisi sampai 1.000 URL.

Kalau URL-nya berasal dari beberapa platform, pilih **Enrichment All**. Tempel semua URL dalam satu kotak tanpa memilah Facebook, Instagram, YouTube, TikTok, Threads, atau X. MIDETA mengenali platform secara otomatis dan memproses platform serta URL publik secara paralel. Hasil gabungan tetap disusun sesuai urutan input. URL yang gagal atau bukan tautan media sosial tetap mendapat satu baris dengan keterangan error. Satu proses Enrichment All dapat berisi sampai 1.000 URL total.

MIDETA juga bisa membaca URL yang tercampur dengan tanggal atau teks hasil salin dari spreadsheet. Contohnya:

```text
Aug 30, 2026 https://www.instagram.com/p/contoh/
```

Hanya URL-nya yang akan dipakai. Hasil disimpan setiap kali satu URL selesai, jadi antrean panjang bisa dijeda dan dilanjutkan tanpa mulai dari awal.

URL pendek dan URL hasil tombol **Share** juga bisa langsung ditempel. Ini mencakup `youtu.be`, `vt.tiktok.com`, `vm.tiktok.com`, `fb.watch`, `fb.me`, `t.co`, serta format `/share/...` milik Facebook, Instagram, dan Threads. MIDETA mengarahkan tautan tersebut ke posting aslinya sebelum membaca data, tetapi tetap menampilkan URL yang ditempel pada baris hasil agar urutannya mudah dicocokkan.

#### Pilihan mode Facebook

Facebook menyediakan dua mode. **Fast** membaca metadata publik tanpa login. **Advanced** memakai Chrome Facebook yang sudah login, membuka post target dan profil author, lalu mencari Reel dengan ID yang sama pada halaman Reels untuk melengkapi followers/friends dan views.

Gunakan **Advanced** bila views tidak muncul pada mode Fast. MIDETA tidak mengambil angka dari kartu Reel lain: jika Reel target tidak ditemukan atau Facebook tidak menampilkan angkanya, kolom Views ditulis **Tidak tersedia**. Untuk memakainya, pilih Advanced, klik **Buka Chrome Facebook**, login langsung di Facebook, lalu klik **Periksa Login** sebelum memulai antrean.

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

#### TikTok tanpa Chrome

TikTok selalu diproses tanpa membuka Chrome dan tanpa login TikTok. MIDETA lebih dulu memakai sumber publik TikTok dan, bila hasilnya dibatasi atau kosong, mencoba sumber publik cadangan yang tetap dicocokkan dengan ID posting. Token Apify bersifat opsional, tetapi membantu memperluas cakupan data dan peluang mendapatkan followers.

Cara menyiapkannya:

1. Buat akun gratis di [Apify](https://console.apify.com/sign-up).
2. Buka **Settings → API & Integrations** di Apify dan salin API token.
3. Pilih TikTok di halaman **Social Media Enrichment**.
4. Tempel token pada kolom **Apify API token**, lalu klik **Simpan token**.
5. Masukkan URL video, foto, atau short link lalu mulai enrichment TikTok.

Token disimpan di folder privat pada komputer ini. Token tidak masuk ke Git, database MIDETA, atau file hasil. Tanpa token, MIDETA tetap mencoba tanggal, author, caption, views, likes, comments, shares, dan bookmark dari sumber publik yang tersedia. Followers atau kolom lain yang tidak diberikan sumber akan ditandai **Tidak tersedia**, bukan diisi dengan angka tebakan.

MIDETA tidak menyediakan mode Chrome TikTok agar proses tidak terganggu HTTP 403, login berulang, atau perpindahan halaman yang dibatasi TikTok.

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

Enrichment Threads mencoba halaman publik terlebih dahulu. Jika Threads mengembalikan halaman kosong atau `invalid_post` untuk post yang sebenarnya masih ada, MIDETA otomatis memakai Sesi Threads yang sama sebagai fallback. Login satu kali diperlukan hanya untuk post yang dibatasi seperti ini; nilai yang benar-benar tidak tampil tetap ditulis **Tidak tersedia**.

MIDETA dapat mengambil maksimal 2.000 komentar dari setiap URL. Progress bar menampilkan jumlah yang sudah ditemukan selama halaman di-scroll dan reply dibuka. Platform tetap dapat menyembunyikan atau membatasi sebagian komentar.

Comment Scrapper juga mendukung Split Screen dan Triple Screen, dengan hasil terpisah untuk setiap platform.

### Conventional Media Enrichment

Tempel maksimal 1.000 link artikel, satu link per baris. MIDETA memproses hingga 5 halaman publik secara paralel. Hasil CSV/XLSX tetap mengikuti urutan input, link berulang tetap dipertahankan, dan link yang gagal tidak akan menggeser baris lain.

Alur penggunaan:

1. Jika artikel memerlukan login, masukkan halaman login media lalu klik **Buka Sesi Artikel**.
2. Login langsung pada situs media di Chrome MIDETA dan biarkan jendelanya terbuka.
3. Tempel seluruh URL artikel, satu URL per baris.
4. Klik **Mulai Enrichment**, periksa status setiap baris, lalu unduh CSV atau XLSX.

MIDETA mencoba halaman publik terlebih dahulu. Artikel yang terhalang login, paywall, atau proteksi situs akan dicoba kembali melalui sesi Chrome secara berurutan agar satu sesi tidak dipakai bersamaan. Password hanya diketik pada situs media dan tidak dibaca MIDETA. Fitur ini tidak membutuhkan token Diffbot dan tidak menyimpan kredensial situs di source code.

Kolom hasil:

| Kolom | Isi |
| --- | --- |
| `date_publish` | Tanggal publikasi artikel, misalnya `Sep 23, 2026` |
| `month` | Nama bulan publikasi |
| `media_name` | Nama media yang dinormalisasi dan ditulis dengan huruf kapital |
| `media_scope` | `National`, `Regional`, atau `Inter` |
| `media_tier` | `Tier 1`, `Tier 2`, atau `Tier 3` |
| `page_link` | URL asli sesuai baris input |
| `title` | Judul artikel |
| `content` | Isi artikel tanpa iklan, menu, rekomendasi, tombol share, dan elemen tidak relevan |
| `journalist_name` | Nama penulis atau jurnalis jika tersedia |
| `tone_article` | `Negative`, `Neutral`, atau `Positive` berdasarkan keseluruhan artikel |
| `quote_mention` | Nama orang yang disebut, tanpa gelar umum dan dipisahkan dengan koma |
| `type_mention` | Nama yang sama dengan detail `(direct)` bila berbicara/dikutip atau `(indirect)` bila hanya disebut |

Status kegagalan selalu dipertahankan pada baris URL asal:

| Status | Arti |
| --- | --- |
| `[CHECK] article not available` | Artikel telah dihapus, takedown, atau halaman memang tidak tersedia |
| `[CHECK] failed to process` | Halaman masih ada, tetapi kontennya tidak berhasil diekstrak |

Klasifikasi scope, tier, tone, dan quote mention dibuat otomatis. Periksa kembali hasilnya apabila digunakan untuk laporan final atau mengikuti taksonomi internal perusahaan. MIDETA tidak melewati CAPTCHA, paywall, atau kontrol akses; pengguna tetap harus memiliki hak untuk membuka artikelnya.

### Hak cipta dan atribusi

MIDETA dibuat dan dikembangkan oleh **Hawarisma Rafanidya Singgih**. Source code memakai lisensi MIT; salinan atau bagian substansial dari software wajib mempertahankan pemberitahuan hak cipta dan izin yang ada di [LICENSE](LICENSE).

File source memiliki header copyright dan SPDX. Test otomatis akan gagal jika header, nama pemilik pada lisensi, atau kredit pengembang di aplikasi terhapus secara tidak sengaja. `.github/CODEOWNERS` juga menetapkan `@hawaarf` sebagai pemilik seluruh repository. Agar perubahan pada repository utama tidak dapat digabung tanpa persetujuan pemilik, aktifkan GitHub Ruleset atau branch protection untuk branch utama dan nyalakan **Require review from Code Owners**.

Perlindungan tersebut menjaga repository utama dan mendeteksi penghapusan tidak sengaja. Source code publik tetap dapat di-fork dan diubah oleh orang lain; tidak ada watermark source code yang secara teknis mustahil dihapus. Kewajiban atribusi berasal dari lisensi dan pemberitahuan hak cipta.

### Catatan hasil

- Angka engagement adalah snapshot saat URL diperiksa dan bisa berubah sesudahnya.
- MIDETA mencocokkan data dengan posting target. Data dari rekomendasi, caption, atau posting lain tidak dipakai sebagai engagement.
- Jika Facebook tidak menampilkan followers tetapi menampilkan friends, jumlah friends dipakai sebagai pengganti.
- Bookmark Facebook Reels hanya diisi bila Facebook benar-benar menampilkan angkanya.
- Data yang memang tidak diberikan platform ditulis **Tidak tersedia**. Nilai `0` hanya dipakai jika platform menyatakan angkanya nol.
- URL yang gagal total tetap berada pada urutan input dan ditulis **URL tidak dapat diproses**, sehingga baris hasil tidak bergeser.
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
LICENSE                    lisensi dan nama pemegang hak cipta
ATTRIBUTION.md             atribusi pembuat MIDETA
SECURITY.md                aturan keamanan dan kredensial
.github/CODEOWNERS         kepemilikan perubahan repository
pages/1_Social_Media_Enrichment.py
                           enrichment media sosial
pages/2_Comment_Scrapper.py
                           pengambilan komentar
pages/3_Riwayat_Analisis.py
                           riwayat hasil lokal
pages/4_Conventional_Media_Enrichment.py
                           enrichment artikel media konvensional
src/connectors/            pembaca data tiap platform
src/instagram_browser.py   enrichment Instagram dengan login
src/comment_browser.py     pengambilan komentar Facebook, Threads, dan X
src/conventional_media.py  enrichment dan sesi login artikel berita
src/batch.py               antrean dan pemulihan proses
src/database.py            penyimpanan riwayat lokal
src/exporters.py           pembuatan CSV dan XLSX
tests/                     automated tests
```

---

## English

MIDETA cleans up social-media metadata, public comments, and conventional-media articles. It runs on your own computer, lets you review the results, and exports them as CSV or XLSX.

### What it does

MIDETA has four main sections:

- **Social Media Enrichment** collects the post date, author, caption, followers, views, likes, comments, bookmarks, shares, and reposts.
- **Comment Scrapper** collects public comments, separates parent comments from replies, and ranks them by engagement.
- **Conventional Media Enrichment** cleans news articles and adds publication, media, journalist, tone, quoted-person, and direct/indirect mention fields.
- **Analysis History** keeps earlier results available for review.

Supported social platforms: YouTube, TikTok, Facebook, Instagram, Threads, and X. Conventional Media Enrichment accepts article URLs from a broad range of public news websites.

### Social Media Enrichment

For a single platform, paste one URL per line and start the run. A queue can contain up to 1,000 URLs.

For a mixed list, choose **Enrichment All**. Paste Facebook, Instagram, YouTube, TikTok, Threads, and X URLs into the same box. MIDETA detects each platform and processes platforms and public URLs concurrently. The combined export is restored to the original input order. Failed or unsupported URLs keep their own rows with an error message. One Enrichment All run can contain up to 1,000 URLs in total.

URLs copied together with spreadsheet text also work. For example:

```text
Aug 30, 2026 https://www.instagram.com/p/example/
```

MIDETA uses the URL and ignores the surrounding text. Each result is saved as soon as it finishes, so a large queue can be paused and resumed without starting over.

Short links and links copied from a platform's **Share** button can be pasted directly. This includes `youtu.be`, `vt.tiktok.com`, `vm.tiktok.com`, `fb.watch`, `fb.me`, `t.co`, and the `/share/...` formats used by Facebook, Instagram, and Threads. MIDETA resolves these links to the original post before collecting data while keeping the pasted URL in the result row so the original order remains easy to match.

#### Facebook modes

Facebook has two modes. **Fast** reads public metadata without login. **Advanced** uses a logged-in MIDETA Chrome profile, opens the target post and author profile, then finds the Reel with the same ID on the profile's Reels page to complete followers/friends and views.

Use **Advanced** when views are missing in Fast mode. MIDETA never borrows a number from another Reel card: if the target Reel cannot be found or Facebook does not expose its count, Views is marked **Tidak tersedia**. Select Advanced, click **Buka Chrome Facebook**, log in directly on Facebook, then click **Periksa Login** before starting the queue.

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

#### TikTok without Chrome

TikTok is always processed without opening Chrome or requiring a TikTok login. MIDETA first checks TikTok's public metadata and, when that result is restricted or empty, uses a public fallback that must match the target post ID. An Apify token is optional, but improves coverage and the chance of retrieving followers.

Setup:

1. Create a free [Apify](https://console.apify.com/sign-up) account.
2. Open **Settings → API & Integrations** in Apify and copy the API token.
3. Select TikTok on the **Social Media Enrichment** page.
4. Paste the token into **Apify API token**, then click **Simpan token**.
5. Paste video, photo, or short URLs and start TikTok enrichment.

The token stays in a private folder on this computer. It is not added to Git, the MIDETA database, or exported files. Without a token, MIDETA still attempts to collect the date, author, caption, views, likes, comments, shares, and bookmarks from available public sources. Followers or other missing fields are marked **Tidak tersedia** instead of being filled with guessed numbers.

MIDETA does not provide a TikTok Chrome mode, avoiding repeated logins, browser navigation restrictions, and TikTok HTTP 403 pages.

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

### Conventional Media Enrichment

Paste up to 1,000 article URLs, one per line. MIDETA processes up to 5 public pages concurrently. CSV/XLSX output keeps the original input order, preserves duplicate links, and retains failed URLs so later rows never shift.

Workflow:

1. If an article requires authentication, enter the publisher's login page and click **Buka Sesi Artikel**.
2. Log in directly on the publisher website in MIDETA's Chrome window and leave it open.
3. Paste all article URLs, one URL per line.
4. Click **Mulai Enrichment**, review each row's status, then download CSV or XLSX.

MIDETA tries the public page first. Articles blocked by authentication, a paywall, or site protection are retried sequentially through the active Chrome session so the same session is not used concurrently. Passwords are entered only on the publisher website and are not read by MIDETA. This feature does not require a Diffbot token and does not store website credentials in source code.

Output columns:

| Column | Content |
| --- | --- |
| `date_publish` | Article publication date, for example `Sep 23, 2026` |
| `month` | Full publication month name |
| `media_name` | Normalized uppercase media name |
| `media_scope` | `National`, `Regional`, or `Inter` |
| `media_tier` | `Tier 1`, `Tier 2`, or `Tier 3` |
| `page_link` | Original URL from the corresponding input row |
| `title` | Article title |
| `content` | Article body without ads, navigation, recommendations, share controls, or unrelated page elements |
| `journalist_name` | Author or journalist name when available |
| `tone_article` | `Negative`, `Neutral`, or `Positive`, based on the full article |
| `quote_mention` | Mentioned people without common honorifics, separated by commas |
| `type_mention` | The same names annotated as `(direct)` when speaking/quoted or `(indirect)` when only mentioned |

Failure markers remain on the original URL row:

| Marker | Meaning |
| --- | --- |
| `[CHECK] article not available` | The article was removed, taken down, or the page is genuinely unavailable |
| `[CHECK] failed to process` | The page still exists, but its content could not be extracted |

Scope, tier, tone, and quote-mention values are classified automatically. Review them before final reporting or when applying an internal corporate taxonomy. MIDETA does not bypass CAPTCHAs, paywalls, or access controls; the user must still be authorized to view the article.

### Copyright and attribution

MIDETA was created and developed by **Hawarisma Rafanidya Singgih**. The source code is licensed under the MIT License; copies or substantial portions of the software must retain the copyright and permission notice in [LICENSE](LICENSE).

Source files carry copyright and SPDX headers. Automated tests fail if a header, the license owner, or the in-app developer credit is removed accidentally. `.github/CODEOWNERS` also assigns the entire repository to `@hawaarf`. To prevent changes from being merged into the primary repository without owner approval, enable a GitHub Ruleset or branch protection on the default branch and turn on **Require review from Code Owners**.

These controls protect the primary repository and catch accidental removal. Public source code can still be forked and modified; no source-code watermark can be made technically impossible to remove. Attribution obligations come from the license and copyright notice.

### Notes about the results

- Engagement is a snapshot and may change after the run.
- MIDETA matches metrics to the target post. Values from recommendations, captions, or nearby posts are not treated as engagement.
- If Facebook has no public follower count but shows friends, MIDETA uses the friend count.
- Facebook Reel bookmarks are filled only when Facebook displays a real count.
- Data that a platform does not provide is marked **Tidak tersedia**. `0` is used only when the platform reports zero.
- A URL that fails completely stays in its original input position and is marked **URL tidak dapat diproses**, so following rows never shift.
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
LICENSE                    license and copyright owner
ATTRIBUTION.md             MIDETA creator attribution
SECURITY.md                security and credential rules
.github/CODEOWNERS         repository change ownership
pages/1_Social_Media_Enrichment.py
                           social-media enrichment
pages/2_Comment_Scrapper.py
                           comment collection
pages/3_Riwayat_Analisis.py
                           local result history
pages/4_Conventional_Media_Enrichment.py
                           conventional-media article enrichment
src/connectors/            platform data readers
src/instagram_browser.py   logged-in Instagram enrichment
src/tiktok_browser.py      shared TikTok result model and parser helpers
src/tiktok_free.py         no-login TikTok enrichment
src/comment_browser.py     Facebook, Threads, and X comment collection
src/conventional_media.py  news article enrichment and login session
src/batch.py               queues and resume support
src/database.py            local history storage
src/exporters.py           CSV and XLSX generation
tests/                     automated tests
```
