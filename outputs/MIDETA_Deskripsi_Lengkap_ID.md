# MIDETA — Deskripsi Lengkap Sistem

**Versi dokumentasi:** 29 September 2026  
**Nama lengkap:** MIDETA — Media Intelligence Tools  
**Pembuat dan pengembang:** Hawarisma Rafanidya Singgih  
**Bentuk aplikasi:** dashboard lokal berbasis Streamlit  
**Lisensi source code:** MIT License

## 1. Ringkasan

MIDETA adalah workspace media intelligence yang membantu pengguna mengubah tautan publik dari media sosial dan media online menjadi data yang lebih rapi, konsisten, dapat diperiksa, serta siap dipindahkan ke spreadsheet. Aplikasi ini menyatukan pekerjaan yang sebelumnya harus dilakukan satu per satu—membuka posting, menyalin engagement, mengambil komentar, membersihkan artikel, memeriksa followers, serta merapikan short link—ke dalam satu dashboard lokal.

Prinsip kerja MIDETA sederhana:

1. Pengguna menempelkan URL atau memasukkan profil.
2. Pengguna memilih cara pemrosesan yang sesuai.
3. MIDETA mengambil data yang tersedia secara publik atau yang dapat ditampilkan kepada akun yang sudah login.
4. Setiap input dipertahankan sebagai satu baris hasil.
5. Hasil dapat diperiksa di layar dan diunduh sebagai CSV atau XLSX.

MIDETA tidak bertujuan menjadi alat untuk melewati paywall, CAPTCHA, privasi akun, pembatasan platform, atau kontrol akses lain. Sistem hanya membaca informasi yang benar-benar tersedia pada sumber publik atau terlihat secara sah oleh akun yang digunakan pengguna.

## 2. Evolusi MIDETA: dari Google Colab menjadi aplikasi lokal

### 2.1 Tahap awal: prototipe di Google Colab

MIDETA tidak langsung dimulai sebagai aplikasi dengan dashboard. Tahap awalnya berupa rangkaian script enrichment dan scraping yang dijalankan melalui notebook Google Colab. Pada fase eksperimen, Colab merupakan pilihan yang masuk akal karena pengguna dapat membuka notebook dari browser, menjalankan Python tanpa menyiapkan lingkungan lokal yang rumit, memasang library melalui cell, lalu segera menguji apakah suatu URL dapat menghasilkan data.

Colab juga membantu pada saat kebutuhan MIDETA masih berfokus pada pembuktian konsep: membaca halaman, mencoba parser, membersihkan artikel, dan mengekspor hasil ke CSV. Perubahan kecil dapat diuji langsung dengan menjalankan ulang cell tertentu. Dengan demikian, Colab berfungsi baik sebagai laboratorium awal untuk menemukan bentuk data, kebutuhan kolom, serta pola situs yang harus ditangani.

Namun, setelah jumlah URL bertambah, platform yang ditangani semakin banyak, dan MIDETA mulai membutuhkan login serta proses yang panjang, cara kerja berbasis notebook tidak lagi cukup stabil untuk penggunaan operasional sehari-hari.

### 2.2 Masalah yang muncul ketika masih memakai Colab

Alasan utama MIDETA akhirnya tidak dilanjutkan sebagai notebook Google Colab bukan karena Colab tidak dapat menjalankan Python, melainkan karena karakter Colab kurang sesuai untuk aplikasi media intelligence yang memerlukan proses berulang, session persisten, banyak fitur, dan hubungan baris data yang harus tetap presisi.

Masalah yang ditemukan antara lain:

1. **Runtime bersifat sementara.** Sesi Colab dapat terputus, idle, atau di-reset. Ketika hal ini terjadi, library harus dipasang kembali, variabel hilang, file sementara tidak lagi tersedia, dan proses ribuan URL berisiko harus dimulai ulang.
2. **Proses panjang sulit diandalkan.** Scraping komentar, membuka banyak artikel, atau mengolah daftar URL besar membutuhkan waktu. Notebook yang terputus di tengah proses membuat status URL yang sudah dan belum diproses sulit dipastikan.
3. **Login browser tidak persisten.** Facebook, Instagram, Threads, X, serta publisher tertentu membutuhkan session login. Browser pada lingkungan Colab berjalan jauh dari komputer pengguna dan tidak terhubung secara natural dengan profil Chrome lokal. Cookie juga dapat hilang ketika runtime berakhir.
4. **Interaksi login kurang praktis.** Pengguna seharusnya memasukkan password langsung di situs resmi. Dalam notebook cloud, membuka browser interaktif, login, kembali ke proses, dan memakai session tersebut secara konsisten jauh lebih rumit.
5. **State notebook bergantung pada urutan cell.** Sebuah cell dapat memakai variabel dari cell sebelumnya tanpa terlihat jelas. Jika cell dijalankan dalam urutan yang berbeda, hasil bisa berubah atau error. Kondisi ini berisiko ketika notebook mulai memiliki banyak fungsi.
6. **Kode dan tampilan bercampur.** Logic scraping, konfigurasi, output tabel, instalasi library, dan eksperimen berada di satu notebook. Semakin banyak platform ditambahkan, semakin sulit memisahkan tanggung jawab setiap bagian.
7. **Input dan output mudah tercecer.** File yang diunggah, CSV hasil, dan revisi notebook dapat tersebar di session atau Google Drive. Sulit memastikan file mana yang merupakan hasil terbaru.
8. **Progres tidak cukup jelas untuk pengguna.** Output cell tidak memberikan dashboard yang konsisten untuk melihat berapa URL selesai, mana yang gagal, atau apakah proses masih berjalan.
9. **Sulit menjaga prinsip satu input–satu output.** Ketika beberapa request selesai tidak berurutan atau sebuah URL gagal, hasil notebook dapat kehilangan baris atau bergeser saat ditempel kembali ke spreadsheet.
10. **Pengelolaan banyak platform menjadi kompleks.** Setiap platform memiliki format URL, struktur halaman, mode login, dan pola error sendiri. Notebook tunggal cepat menjadi panjang dan sulit dirawat.
11. **Kontrol data dan kredensial kurang ideal.** MIDETA menangani session login, token opsional, URL pekerjaan, dan hasil monitoring. Menjaga seluruh data tersebut di perangkat sendiri memberikan kontrol yang lebih jelas daripada mengandalkan runtime cloud sementara.
12. **Pengujian dan versioning terbatas.** Notebook cocok untuk eksperimen, tetapi kurang nyaman untuk automated test, modul terpisah, code review, Git diff, dan pelacakan regresi ketika parser diperbarui.

Pada titik tersebut, Colab masih berguna untuk eksperimen kecil, tetapi bukan lagi fondasi yang tepat bagi MIDETA sebagai alat kerja rutin.

### 2.3 Keputusan berpindah ke VS Code dan terminal

MIDETA kemudian dipindahkan ke project Python lokal yang dijalankan melalui terminal di VS Code. Perubahan ini bukan sekadar memindahkan file dari cloud ke laptop. Struktur sistem diubah menjadi aplikasi modular dengan virtual environment, file konfigurasi, penyimpanan lokal, automated test, dan halaman terpisah untuk setiap fungsi.

Menjalankan aplikasi secara lokal memberikan manfaat penting:

- Python dan seluruh dependensi dapat dikunci di dalam `.venv`;
- proses tidak bergantung pada umur runtime Colab;
- Chrome dapat dibuka langsung di komputer pengguna;
- session login dan cookie dapat dipakai kembali secara lokal;
- database riwayat dapat disimpan di perangkat;
- hasil dapat disimpan bertahap selama proses berlangsung;
- source code dapat dipisahkan berdasarkan platform dan fungsi;
- perubahan dapat dilacak melalui Git;
- automated test dapat dijalankan sebelum perubahan dipakai;
- password tetap diketik langsung pada situs resmi, bukan pada notebook atau form aplikasi.

VS Code berfungsi sebagai lingkungan pengembangan, sedangkan terminal menjalankan server Streamlit. Pengguna kemudian mengakses MIDETA melalui alamat lokal `http://localhost:8501`.

### 2.4 Mengapa Streamlit dipilih

Setelah beralih ke project lokal, MIDETA membutuhkan antarmuka yang lebih mudah daripada command line murni. Streamlit dipilih karena mampu mengubah fungsi Python menjadi dashboard interaktif tanpa harus membangun frontend dan backend yang sepenuhnya terpisah.

Streamlit memungkinkan MIDETA menyediakan:

- kotak input URL;
- pilihan platform dan mode;
- tombol login dan pemeriksaan session;
- progress bar;
- tabel hasil;
- status berhasil, perlu diperiksa, atau gagal;
- navigasi antarfitur pada halaman yang sama;
- tombol unduh CSV dan XLSX;
- session state untuk mempertahankan hasil selama aplikasi berjalan.

Dengan pendekatan ini, pengguna tidak lagi perlu membuka source code atau menjalankan cell secara manual. Alurnya disederhanakan menjadi **tempel URL, jalankan proses, periksa hasil, lalu unduh**.

### 2.5 Dampak perubahan arsitektur

Peralihan dari Colab ke aplikasi lokal menghasilkan perubahan mendasar:

| Google Colab | MIDETA lokal berbasis Streamlit |
| --- | --- |
| Runtime sementara | Lingkungan Python lokal yang persisten |
| Menjalankan cell satu per satu | Menggunakan tombol dan form pada dashboard |
| Login browser sulit dipertahankan | Profil Chrome khusus disimpan lokal |
| Progres terlihat sebagai output cell | Progress bar dan status per proses |
| Script dan hasil mudah bercampur | Fitur, source code, database, dan output dipisahkan |
| Sulit melanjutkan proses yang terputus | Hasil enrichment disimpan bertahap dan antrean dapat dilanjutkan |
| Pengujian manual dominan | Automated test tersedia |
| File sementara mengikuti runtime | CSV, XLSX, dan riwayat tersimpan pada perangkat |
| Cocok untuk eksperimen | Cocok untuk workflow operasional berulang |

Perubahan ini juga membawa konsekuensi. Pengguna perlu menyiapkan Python, dependensi, dan Chrome. Komputer harus tetap menyala selama proses. Kecepatan bergantung pada perangkat dan koneksi. Parser tetap harus diperbarui ketika struktur website berubah. Namun, untuk kebutuhan MIDETA—terutama login, pemrosesan batch, urutan data, serta keamanan session—keuntungan aplikasi lokal jauh lebih besar daripada mempertahankan notebook cloud sebagai sistem utama.

## 3. Tujuan MIDETA

MIDETA dibuat untuk mendukung pekerjaan seperti:

- media monitoring;
- issue monitoring;
- social listening berbasis URL;
- pemetaan media dan akun sosial;
- pengumpulan engagement posting;
- analisis komentar publik;
- pengumpulan artikel dan klasifikasi awal;
- normalisasi tautan untuk database;
- pembaruan jumlah followers;
- pengumpulan daftar posting dari profil TikTok pada periode tertentu;
- penyusunan data mentah sebelum analisis di spreadsheet atau alat lain.

Pengguna utamanya dapat berupa media analyst, public relations, corporate communication, researcher, social media analyst, dan tim monitoring. MIDETA adalah alat pengumpulan dan perapihan data, bukan pengganti penilaian analis.

## 4. Prinsip desain data

### 4.1 Satu input tetap satu output

MIDETA mempertahankan hubungan antara daftar input dan hasil. URL yang gagal tidak dihapus. URL berulang juga tidak dideduplikasi pada fitur batch karena setiap baris dapat merepresentasikan record berbeda dalam lembar kerja pengguna.

Pemrosesan dapat berlangsung secara paralel dan selesai tidak berurutan, tetapi hasil akhir dikembalikan ke urutan input semula. Prinsip ini mencegah data bergeser ketika ditempel ke spreadsheet sumber.

### 4.2 Arti nilai 0, Cek, dan error

MIDETA membedakan tiga keadaan:

- **`0`**: counter tersedia secara konsep, tetapi posting memang tidak menampilkan aktivitas pada counter tersebut.
- **`Cek`**: data tidak dapat dibaca, diblokir, tidak didukung, atau tidak ditampilkan secara jelas oleh platform.
- **`URL tidak dapat diproses`**: posting atau URL gagal dibaca secara keseluruhan. Barisnya tetap dipertahankan.

MIDETA tidak mengisi angka tebakan untuk melengkapi kolom yang tidak terbaca.

### 4.3 Snapshot, bukan data real-time permanen

Followers, views, likes, comments, shares, dan repost merupakan snapshot pada waktu pengambilan. Angka tersebut dapat berubah setelah file diunduh. Kolom waktu pengambilan membantu pengguna mengetahui kapan snapshot dibuat.

### 4.4 Pemisahan fitur

Normalisasi URL, enrichment posting, pengambilan komentar, pemeriksaan followers, dan pengambilan profil diletakkan sebagai fitur terpisah. Pemisahan ini menghindari perubahan URL atau proses tambahan yang tidak diminta saat pengguna hanya membutuhkan satu jenis pekerjaan.

## 5. Struktur fitur MIDETA

MIDETA memiliki tujuh bagian utama:

1. Social Media Enrichment
2. Comment Scrapper
3. Riwayat Analisis
4. Conventional Media Enrichment
5. Modified Link
6. Followers Checker
7. Profile Scraping

Halaman utama menyediakan tombol langsung ke setiap fitur. Navigasi terjadi dalam aplikasi yang sama, bukan membuka tab browser baru.

## 6. Social Media Enrichment

### 6.1 Fungsi

Social Media Enrichment mengambil metadata posting dan engagement dari:

- YouTube;
- TikTok;
- Facebook;
- Instagram;
- Threads; dan
- X.

Kolom hasil ringkas terdiri dari:

- `Platform`
- `URL`
- `Tanggal posting`
- `Author`
- `Caption`
- `Followers`
- `Views`
- `Likes`
- `Comments`
- `Save atau bookmark`
- `Shares`
- `Reposts`
- `Waktu pengambilan`
- `Data yang tidak tersedia`

Untuk **Enrichment All**, terdapat kolom tambahan `Error` agar URL yang tidak didukung atau gagal tetap dapat dijelaskan tanpa menghapus barisnya.

### 6.2 Kapasitas dan bentuk input

Satu proses menerima maksimal 1.000 URL. Setiap URL ditempel pada baris tersendiri. MIDETA juga dapat mengambil URL dari teks hasil salin spreadsheet, misalnya ketika tanggal atau teks lain berada di baris yang sama.

Short link dan share link yang didukung mencakup antara lain:

- `youtu.be`;
- `vt.tiktok.com` dan `vm.tiktok.com`;
- `fb.watch` dan `fb.me`;
- `t.co`;
- pola `/share/` milik Facebook, Instagram, dan Threads.

Tujuan link akan diselesaikan untuk keperluan pembacaan data, tetapi URL yang ditempel pengguna tetap dipakai sebagai identitas baris hasil.

### 6.3 Pilihan tampilan proses

- **Satu platform:** fokus pada satu platform.
- **Split Screen:** dua platform dalam satu layar.
- **Triple Screen:** maksimal tiga platform dalam satu layar.
- **Enrichment All:** menerima URL campuran dan menggabungkan semua hasil dalam satu file.

Masing-masing panel pada mode terpisah memiliki input, progres, antrean, hasil, dan unduhan sendiri. Enrichment All mendeteksi platform secara otomatis.

### 6.4 Pemrosesan paralel dan urutan hasil

MIDETA dapat menjalankan maksimal tiga platform secara paralel. Untuk sumber publik, sampai lima URL dapat dikerjakan bersamaan. Batch reguler menggunakan kelompok hingga 20 URL, mode Fast hingga 10 URL, dan mode browser hingga 5 URL per tahap.

Penyelesaian paralel tidak mengubah urutan file. Hasil selalu disusun kembali berdasarkan posisi URL saat ditempel.

### 6.5 Facebook

Facebook memiliki dua mode:

- **Fast:** membaca metadata publik tanpa login bila tersedia.
- **Advanced:** memakai Chrome Facebook yang sudah login untuk membuka posting target dan profil author, kemudian melengkapi followers/friends dan views jika Facebook menampilkannya.

Advanced mencocokkan ID posting/Reel target. Sistem tidak boleh meminjam views atau engagement dari kartu Reel lain. Jika posting target tidak dapat ditemukan atau nilai tidak ditampilkan, hasil ditulis `Cek`.

Bila Facebook hanya menampilkan friends dan tidak menampilkan followers, jumlah friends dapat dipakai sebagai representasi jaringan akun dengan catatan hasil tetap perlu dipahami sesuai konteks Facebook.

### 6.6 Instagram

Instagram menyediakan mode Fast dan Advanced melalui Chrome khusus MIDETA yang telah login:

- **Fast:** berfokus pada author, caption, tanggal, likes, comments, shares, dan repost.
- **Advanced:** menambahkan pemeriksaan followers dan views jika tersedia.

Views tidak tersedia untuk semua jenis post. Foto dan carousel dapat menghasilkan `Cek` pada Views. Pada Reel/video, MIDETA mencocokkan posting target agar angka tidak tertukar dengan slide carousel atau posting rekomendasi.

### 6.7 TikTok

Enrichment TikTok tidak membuka Chrome dan tidak meminta login. MIDETA mencoba sumber publik TikTok, kemudian sumber publik cadangan yang tetap dicocokkan dengan ID posting.

Token Apify bersifat opsional khusus Social Media Enrichment TikTok. Tanpa token, proses tetap mencoba mengambil tanggal, author, caption, views, likes, comments, shares, dan bookmark dari data publik. Data yang tidak dapat dibaca ditulis `Cek`.

Tidak ada mode Chrome TikTok pada enrichment agar alur tidak bergantung pada login berulang atau halaman yang sering menghasilkan HTTP 403.

### 6.8 Threads

MIDETA mencoba data publik Threads lebih dahulu. Jika halaman publik kosong atau mengembalikan status seperti `invalid_post` padahal posting masih dapat dibuka, sesi Threads yang telah login dapat digunakan sebagai fallback. Data tetap harus berasal dari posting target.

### 6.9 YouTube dan X

MIDETA membaca metadata publik yang tersedia pada URL posting. Ketersediaan counter mengikuti apa yang ditampilkan sumber. Untuk komentar X, sesi browser digunakan karena percakapan dimuat secara dinamis.

### 6.10 Antrean dan pemulihan

Hasil disimpan bertahap saat URL selesai. Antrean panjang dapat dijeda dan dilanjutkan tanpa membuang seluruh hasil yang sudah terkumpul. Progress bar merepresentasikan jumlah baris yang telah disimpan, bukan sekadar animasi waktu.

## 7. Comment Scrapper

### 7.1 Fungsi

Comment Scrapper mengumpulkan komentar publik dan reply dari URL posting YouTube, TikTok, Facebook, Instagram, Threads, dan X.

Satu platform dapat menerima maksimal 1.000 URL per permintaan. Batas pengambilan adalah 10.000 komentar per URL.

### 7.2 Cara pengambilan

Facebook, Threads, dan X menggunakan Chrome khusus MIDETA karena komentar dan reply dimuat setelah halaman dibuka. Pengguna login langsung pada situs resmi, kemudian sesi lokal digunakan kembali hingga kedaluwarsa atau pengguna logout.

Saat menggunakan browser, MIDETA berusaha:

- tetap berada pada posting target;
- melakukan scroll pada area percakapan;
- membuka tombol untuk memuat komentar berikutnya;
- membuka reply;
- membuka komentar panjang seperti “Baca selengkapnya”; dan
- berhenti ketika tidak ada data baru, target tercapai, atau batas aman tercapai.

Platform masih dapat menyembunyikan, memfilter, membatasi, atau tidak mengirim sebagian komentar. Karena itu, angka maksimal adalah batas sistem, bukan jaminan bahwa platform akan memberikan semua komentar.

### 7.3 Struktur hasil

File ringkas Comment Scrapper berisi:

- `index`
- `date`
- `author`
- `type`
- `comment`
- `like`
- `reply`
- `tone`

`type` membedakan komentar `parent` dan `reply`. Tabel detail juga menyimpan platform, URL sumber, waktu pengambilan, serta skor engagement.

### 7.4 Ranking dan tone

Komentar diurutkan terutama berdasarkan jumlah likes. Jumlah reply menjadi tie-breaker ketika likes sama. Skor engagement sederhana dihitung sebagai:

`likes + jumlah reply`

Tone komentar diklasifikasikan secara deterministik menjadi `Positive` atau `Negative` berdasarkan kata, frasa, negasi, dan emoji yang dikenali. Model ini dibuat konsisten untuk ekspor berulang, tetapi bukan pengganti analisis sentimen manusia—terutama untuk sarkasme, konteks politik, bahasa campuran, atau slang baru.

### 7.5 Tampilan paralel

Comment Scrapper menyediakan mode satu platform, Split Screen, dan Triple Screen. Maksimal tiga platform dapat diproses dalam satu tampilan dengan hasil tetap terpisah.

## 8. Conventional Media Enrichment

### 8.1 Fungsi

Fitur ini mengubah URL artikel berita menjadi dataset artikel yang lebih bersih. Satu proses menerima maksimal 1.000 URL. Hingga lima situs berbeda dapat diproses paralel, sedangkan request ke publisher yang sama diserialkan untuk mengurangi beban dan konflik.

### 8.2 Kolom hasil

Urutan kolom adalah:

1. `date_publish` — tanggal publikasi;
2. `month` — bulan publikasi;
3. `media_name` — nama media dalam huruf kapital;
4. `media_scope` — `National`, `Regional`, atau `Inter`;
5. `media_tier` — `Tier 1`, `Tier 2`, atau `Tier 3`;
6. `page_link` — URL sesuai input;
7. `title` — judul artikel;
8. `content` — isi artikel yang telah dibersihkan;
9. `journalist_name` — nama penulis bila tersedia;
10. `tone_article` — `Negative`, `Neutral`, atau `Positive`;
11. `quote_mention` — hanya nama orang yang disebut;
12. `type_mention` — nama orang disertai `(direct)` atau `(indirect)`.

### 8.3 Pembersihan artikel

MIDETA berusaha membuang bagian yang bukan isi artikel, termasuk:

- menu dan navigasi;
- iklan;
- tombol share;
- rekomendasi berita;
- artikel terkait;
- “Baca juga”;
- “Lebih lanjut”;
- “Berlangganan selanjutnya”;
- ajakan membuka artikel lain;
- footer publisher;
- elemen promo dan teks boilerplate lain.

Pembersihan dilakukan dengan aturan umum dan aturan publisher yang telah ditambahkan berdasarkan contoh hasil. Karena struktur situs berbeda-beda dan dapat berubah, hasil panjang tetap perlu ditinjau sebelum dipakai dalam laporan resmi.

### 8.4 Journalist, tone, dan mention

`journalist_name` mengambil nama manusia yang dinyatakan sebagai penulis. Nama media, kata “Redaksi”, domain, dan label nonmanusia dihindari bila dapat dikenali.

`tone_article` menilai keseluruhan artikel, bukan hanya headline. Klasifikasi bersifat rule-based/deterministik dan tetap memerlukan validasi analis untuk isu sensitif.

`quote_mention` hanya berisi nama orang. Gelar, jabatan, organisasi, partai, koalisi, dan frasa deskriptif tidak boleh menjadi mention mandiri.

`type_mention` memakai daftar nama yang sama, kemudian menandai:

- `(direct)` jika orang berbicara atau dikutip;
- `(indirect)` jika orang hanya disebut atau dibicarakan.

Jika terdapat lebih dari satu orang, setiap nama dipisahkan dengan koma.

### 8.5 Login artikel

MIDETA mencoba halaman publik lebih dahulu. Jika artikel membutuhkan sesi, pengguna dapat membuka Sesi Artikel dan login langsung di Chrome. Halaman yang belum berhasil melalui sumber publik dapat dicoba ulang secara berurutan menggunakan sesi tersebut.

MIDETA tidak melewati CAPTCHA, paywall, atau larangan akses. Pengguna tetap harus memiliki izin untuk membuka halaman. Untuk SWA yang secara eksplisit melarang crawling, kolom `content` diisi tepat dengan `dilarang craweling`; sistem tidak mencoba menerobos larangan tersebut.

### 8.6 Status kegagalan

- **`[CHECK] article not available`**: artikel dihapus, takedown, atau halaman benar-benar tidak tersedia.
- **`[CHECK] failed to process`**: halaman ada, tetapi konten gagal diekstrak, diblokir, atau tidak dapat dipahami parser.

URL yang gagal tetap menempati baris inputnya.

## 9. Modified Link

Modified Link adalah alat terpisah untuk membersihkan URL tanpa menjalankan enrichment. Platform yang didukung: YouTube, TikTok, Facebook, Instagram, Threads, dan X.

Fungsi utamanya:

- menyelesaikan short link;
- mengubah share link menjadi permalink posting;
- menghapus parameter tracking;
- menormalkan domain;
- mempertahankan URL asli;
- mempertahankan duplicate dan urutan input.

Maksimal 1.000 URL dapat diproses dengan hingga lima worker publik. Kolom output:

- `No`
- `Platform`
- `Original Link`
- `Modified Link`
- `Status`
- `Catatan`

Jika tujuan tidak ditemukan, baris tetap ada dan `Modified Link` berisi `URL tidak dapat dimodifikasi`.

## 10. Followers Checker

Followers Checker menerima URL profil dari:

- Instagram;
- Facebook;
- TikTok;
- Threads;
- X;
- YouTube; dan
- LinkedIn.

Pengguna memilih platform, membuka halaman login, dan login langsung di situs resmi melalui Chrome khusus MIDETA. Setelah login terdeteksi, satu atau banyak URL profil dapat ditempel. Batasnya 1.000 URL profil per proses.

Output dibuat sederhana:

- `Platform`
- `Account Name`
- `URL`
- `Followers`

URL berulang tetap menghasilkan baris berulang. Baris kosong yang sengaja ditempatkan di antara URL dipertahankan sebagai baris literal `space`, sedangkan baris kosong di awal atau akhir diabaikan.

Status yang mungkin muncul:

- `Login diperlukan`
- `Tidak tersedia`
- `URL bukan profil`
- `URL tidak dapat diproses`
- `Platform tidak didukung`
- `space`

Fitur ini hanya menerima URL akun/channel, bukan URL posting.

## 11. Profile Scraping

### 11.1 Fungsi

Profile Scraping mengambil daftar posting publik dari satu profil TikTok dalam rentang tanggal khusus. Input dapat berupa:

- URL profil TikTok;
- `@username`; atau
- username biasa.

Tanggal awal dan tanggal akhir bersifat inklusif.

### 11.2 Metode

Fitur ini tidak memakai login, tidak membuka Chrome, dan tidak memakai Apify. Pengambilan dilakukan melalui extractor open-source lokal dan request publik yang dibuat menyerupai browser. Collector menelusuri timeline dari posting terbaru menuju lama, berhenti setelah melewati tanggal awal atau mencapai batas 10.000 posting.

Jika profil utama sulit dibaca, MIDETA memiliki fallback untuk memperoleh identitas publik profil dan melanjutkan pagination. Post ID dideduplikasi agar pinned post yang muncul kembali tidak dibuat dua kali.

### 11.3 Output

- `No`
- `Date Publish`
- `Author`
- `Post Type`
- `Caption`
- `URL`

Caption berasal dari deskripsi publik TikTok dan whitespace dinormalisasi. Hasil diurutkan dari posting terbaru ke terlama. Selain CSV/XLSX, URL tersedia dalam kotak satu URL per baris agar mudah disalin.

### 11.4 Cakupan dan hasil parsial

Profile Scraping hanya dapat mengambil posting yang dikirim oleh timeline publik TikTok. Profil privat, posting terhapus, pembatasan wilayah, rate limit, atau posting yang tidak disajikan oleh sumber publik tidak dapat dipaksa untuk muncul.

Jika timeline publik meloncat dari satu tanggal ke tanggal lama, MIDETA menampilkan informasi cakupan. Jika proses berhenti sebelum dapat membuktikan bahwa seluruh rentang sudah dilewati, hasil ditandai parsial tetapi URL yang ditemukan tetap dapat diunduh.

## 12. Riwayat Analisis

Riwayat Analisis menyimpan hasil tertentu secara lokal di SQLite. Saat ini riwayat mencakup:

- Social Media Enrichment;
- Comment Scrapper; dan
- Conventional Media Enrichment.

Pengguna dapat:

- mencari URL atau isi hasil;
- memfilter berdasarkan fitur;
- memfilter platform;
- memilih rentang tanggal;
- melihat detail JSON;
- mengunduh riwayat sebagai CSV/XLSX; dan
- menghapus record secara permanen setelah konfirmasi.

Database berada di `data/mideta.db` dan tidak dimasukkan ke Git.

## 13. Alur kerja yang direkomendasikan

### 13.1 Metadata media sosial

1. Buka Social Media Enrichment.
2. Pilih satu platform atau Enrichment All.
3. Siapkan login/token hanya jika mode yang dipilih memerlukannya.
4. Tempel satu URL per baris.
5. Jalankan proses dan pantau progres.
6. Periksa kolom `Data yang tidak tersedia` dan `Error`.
7. Unduh CSV/XLSX.

### 13.2 Komentar

1. Buka Comment Scrapper.
2. Pilih platform.
3. Untuk Facebook, Threads, atau X, buka sesi dan login.
4. Tempel URL posting.
5. Jalankan dan biarkan Chrome memuat komentar serta reply.
6. Periksa jumlah komentar, status parsial, dan ranking.
7. Unduh hasil.

### 13.3 Artikel

1. Buka Conventional Media Enrichment.
2. Bila diperlukan, buka Sesi Artikel dan login ke publisher.
3. Tempel URL artikel.
4. Jalankan enrichment.
5. Tinjau artikel yang berstatus `[CHECK]`.
6. Validasi tone, tier, dan mention sebelum laporan final.
7. Unduh hasil.

## 14. Arsitektur teknis

MIDETA menggunakan arsitektur modular:

- **Streamlit** untuk dashboard dan state antarmuka;
- **Pandas** untuk pembentukan tabel;
- **OpenPyXL** untuk XLSX;
- **Requests, BeautifulSoup, dan lxml** untuk pembacaan halaman publik;
- **Selenium** untuk halaman yang membutuhkan browser/session;
- **yt-dlp dan curl-cffi** untuk Profile Scraping TikTok;
- **Pydantic** untuk model data;
- **SQLite** untuk riwayat lokal.

Pembagian file utama:

- `app.py`: halaman utama dan navigasi;
- `pages/1_Social_Media_Enrichment.py`: enrichment posting;
- `pages/2_Comment_Scrapper.py`: komentar dan reply;
- `pages/3_Riwayat_Analisis.py`: riwayat lokal;
- `pages/4_Conventional_Media_Enrichment.py`: artikel berita;
- `pages/5_Modified_Link.py`: normalisasi link;
- `pages/6_Followers_Checker.py`: followers profil;
- `pages/7_Profile_Scraping.py`: timeline TikTok;
- `src/connectors/`: connector per platform;
- `src/batch.py`: parsing input, antrean, urutan hasil, dan format ekspor;
- `src/comment_browser.py`: browser komentar;
- `src/follower_browser.py`: sesi dan pembacaan followers;
- `src/instagram_browser.py`: enrichment Instagram;
- `src/tiktok_profile.py`: pagination profil TikTok;
- `src/conventional_media.py`: ekstraksi dan klasifikasi artikel;
- `src/social_urls.py`: deteksi platform dan normalisasi URL;
- `src/http_client.py`: HTTP publik dengan batas aman;
- `src/validators.py`: validasi URL dan perlindungan SSRF;
- `src/database.py`: database riwayat;
- `src/exporters.py`: CSV/XLSX;
- `src/sentiment.py`: tone komentar;
- `tests/`: pengujian otomatis.

Versi dependensi utama saat dokumentasi ini dibuat:

- Python 3.12+
- Streamlit 1.62.0
- Requests 2.34.2
- BeautifulSoup 4.15.0
- lxml 6.1.2
- Pandas 3.0.5
- OpenPyXL 3.1.5
- Pydantic 2.13.5
- Selenium 4.48.0
- yt-dlp 2026.8.19
- curl-cffi 0.16.3

## 15. Keamanan dan privasi

### 15.1 Password dan sesi

MIDETA tidak menyediakan kolom password, tidak membaca password, dan tidak menulis password ke database atau hasil ekspor. Login dilakukan langsung pada situs resmi di jendela Chrome.

Cookie dan session browser disimpan lokal di `data/browser_profiles/`. Token opsional disimpan pada area privat lokal atau environment variable. Folder tersebut diabaikan Git.

### 15.2 Data yang tidak dikirim ke GitHub

Konfigurasi `.gitignore` mengecualikan antara lain:

- virtual environment;
- `.env` dan Streamlit secrets;
- seluruh isi `data/` selain `.gitkeep`;
- database SQLite;
- cookies dan browser state;
- private key/certificate;
- log;
- file output spreadsheet;
- folder editor lokal.

Pengguna tetap wajib memeriksa `git status` sebelum push. Jika secret pernah ter-commit, secret harus dicabut atau dirotasi karena menghapus file pada commit terbaru tidak menghapusnya dari riwayat Git.

### 15.3 Perlindungan URL

Request publik hanya menerima HTTP/HTTPS pada port 80/443. URL yang memuat username/password, localhost, domain internal, IP privat, atau alamat khusus ditolak. Redirect divalidasi ulang.

Batas request saat ini:

- timeout 20 detik;
- maksimal 5 redirect;
- ukuran HTML maksimal 8 MB.

Pembatasan ini membantu mengurangi risiko SSRF, request menggantung, dan halaman yang terlalu besar.

### 15.4 Batas jaminan keamanan

Tidak ada aplikasi scraping yang dapat dijanjikan 100% bebas risiko. Platform dapat menerapkan rate limit atau membatasi akun. Pengguna harus memakai akun yang berwenang, mematuhi Terms of Service, melindungi perangkat, dan tidak mengunggah session browser ke repository.

## 16. Penyimpanan dan format ekspor

CSV memakai UTF-8 dengan BOM agar lebih mudah dibuka di spreadsheet. XLSX dibuat dengan font Arial ukuran 10; header dibuat tebal. Karakter kontrol ilegal untuk Excel dibersihkan sebelum file dibuat.

Folder penting:

- `data/mideta.db`: riwayat lokal;
- `data/browser_profiles/`: session browser;
- `outputs/`: artefak hasil lokal;
- `data/private/`: token opsional bila digunakan.

CSV tidak menyimpan format visual seperti font, warna, atau lebar kolom. Gunakan XLSX bila format spreadsheet diperlukan.

## 17. Menjalankan aplikasi

Jalankan dari folder project:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

Lalu buka:

`http://localhost:8501`

Google Chrome diperlukan untuk fitur berbasis login/session. TikTok Profile Scraping tidak memerlukan Chrome.

## 18. Pengujian dan quality control

Pemeriksaan dasar:

```bash
.venv/bin/python -m compileall app.py pages src tests
.venv/bin/python -m unittest discover -s tests -v
```

Test mencakup parsing URL, connector, urutan batch, ekspor, database, parser artikel, browser logic, sentiment, security URL, Modified Link, Followers Checker, dan Profile Scraping.

Pengujian otomatis membantu mencegah regresi, tetapi pengujian langsung dengan URL nyata tetap diperlukan karena respons platform berubah di luar repository.

## 19. Keterbatasan utama

1. **Struktur platform dapat berubah.** Selector atau bentuk data yang baru dapat membuat parser tidak mengenali posting.
2. **Tidak semua counter bersifat publik.** Views, bookmark, shares, repost, atau followers dapat disembunyikan.
3. **Login dapat kedaluwarsa.** Pengguna perlu login kembali jika session habis.
4. **Rate limit dapat terjadi.** Proses besar dapat diperlambat atau dibatasi platform.
5. **Data privat tidak dapat diambil.** Akun privat, posting terhapus, atau konten terbatas tidak diterobos.
6. **Jumlah komentar tidak selalu lengkap.** Platform dapat menyaring, mengurutkan, atau tidak mengirim semua komentar.
7. **Klasifikasi otomatis bukan keputusan final.** Tone, tier, scope, journalist, dan mention perlu verifikasi manusia.
8. **Profile Scraping bergantung pada timeline publik TikTok.** Rentang tanggal tidak menjamin semua posting historis tersedia.
9. **Short link membutuhkan redirect aktif.** Link kedaluwarsa atau diblokir mungkin tidak dapat diselesaikan.
10. **Aplikasi lokal bergantung pada perangkat.** Koneksi, Chrome, RAM, penyimpanan, dan proses terminal memengaruhi stabilitas.
11. **Cloud deployment tidak setara dengan lokal.** Fitur yang membutuhkan Chrome lokal/session login paling cocok dijalankan melalui VS Code pada perangkat pengguna.
12. **Perubahan situs memerlukan maintenance.** Jika bentuk posting terbaru belum dikenal, parser harus diperbarui dan diuji.

## 20. Kelebihan dan kekurangan

### Kelebihan

- satu dashboard untuk banyak kebutuhan media intelligence;
- output konsisten dan siap ditempel ke spreadsheet;
- urutan dan duplicate dipertahankan;
- error tidak menghilangkan baris;
- mendukung proses paralel dengan hasil tetap berurutan;
- local-first dan tidak menyimpan password;
- CSV serta XLSX tersedia;
- pemisahan parent/reply dan ranking komentar;
- artikel dibersihkan dan diperkaya;
- source code modular dan memiliki test;
- dapat terus ditambah aturan berdasarkan perubahan platform.

### Kekurangan

- membutuhkan instalasi lokal dan terminal;
- beberapa fitur memerlukan login manual;
- scraping skala besar memerlukan waktu;
- hasil bergantung pada akses yang diberikan platform;
- parser perlu maintenance berkala;
- tidak semua data dapat diperoleh tanpa API resmi;
- klasifikasi tone/mention otomatis masih memerlukan review;
- session browser menambah konsumsi sumber daya komputer.

## 21. Penggunaan yang bertanggung jawab

MIDETA sebaiknya digunakan hanya untuk data yang memang berhak diakses pengguna. Jangan gunakan alat ini untuk:

- mengumpulkan data privat;
- melewati paywall, CAPTCHA, atau kontrol akses;
- mengambil data pribadi sensitif untuk profiling yang merugikan;
- membebani situs dengan request berlebihan;
- mengabaikan hak cipta isi artikel;
- mempublikasikan cookie, token, atau dataset privat.

Untuk kutipan artikel, gunakan hasil sebagai bahan analisis internal dan tetap patuhi aturan hak cipta serta atribusi sumber.

## 22. Kepemilikan dan lisensi

MIDETA dibuat dan dikembangkan oleh **Hawarisma Rafanidya Singgih**. Copyright © 2026 Hawarisma Rafanidya Singgih.

Repository menggunakan MIT License. Lisensi tersebut mengizinkan penggunaan, modifikasi, distribusi, sublicensing, dan penjualan salinan, dengan syarat pemberitahuan copyright dan izin tetap disertakan pada salinan atau bagian substansial software.

Source file memiliki header copyright dan SPDX. Repository juga memiliki `ATTRIBUTION.md`, `LICENSE`, dan `.github/CODEOWNERS`. Perlindungan branch GitHub dan review CODEOWNERS dapat melindungi repository utama, tetapi source code publik tetap dapat di-fork. Tidak ada watermark source code yang secara teknis mustahil dihapus; perlindungan atribusi berasal dari lisensi, bukti riwayat Git, dan kebijakan repository.

## 23. Definisi MIDETA dalam satu paragraf

MIDETA adalah aplikasi media intelligence lokal berbasis Streamlit yang mengubah URL publik media sosial dan media online menjadi dataset terstruktur. MIDETA menyediakan enrichment metadata dan engagement, pengambilan serta ranking komentar, ekstraksi artikel bersih, normalisasi link, pemeriksaan followers, pengambilan posting profil TikTok berdasarkan tanggal, dan riwayat analisis lokal. Sistem dirancang untuk mempertahankan urutan setiap input, tidak menghapus baris gagal, membedakan nilai nol dari data yang tidak terbaca, melindungi password dengan mengarahkan login langsung ke situs resmi, dan menghasilkan CSV/XLSX yang siap dipakai untuk pekerjaan monitoring dan analisis lanjutan.

## 24. Deskripsi singkat untuk presentasi atau profil proyek

**MIDETA (Media Intelligence Tools)** adalah workspace lokal untuk mengumpulkan, merapikan, dan mengekspor data media sosial serta artikel berita. Pengguna cukup menempelkan URL, menjalankan fitur yang dibutuhkan, memeriksa hasil, lalu mengunduh CSV/XLSX. MIDETA mendukung enrichment enam platform sosial, comment scraping hingga 10.000 komentar per URL, artikel media konvensional, normalisasi short/share link, pengecekan followers lintas platform, serta TikTok profile scraping berdasarkan rentang tanggal. Seluruh proses dirancang dengan prinsip local-first, urutan data stabil, dan transparansi status ketika data tidak tersedia.
