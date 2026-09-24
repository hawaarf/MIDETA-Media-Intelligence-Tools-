import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const workspaceDir = "/Users/hawarisma.singgih/Documents/ChatGPT/mideta";
const SKILL_DIR = "/Users/hawarisma.singgih/.codex/plugins/cache/openai-primary-runtime/presentations/26.921.10847/skills/presentations";
const TMP_DIR = path.join(workspaceDir, ".codex-artifacts/mideta-brief-build");
const FINAL_PPTX = path.join(workspaceDir, "outputs/MIDETA_Brief_Profesional_ID_v2.pptx");
const RUNTIME_PYTHON = "/Users/hawarisma.singgih/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3";

const { resolvePresentationFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href,
);
const fontFamily = resolvePresentationFont();

const W = 1280;
const H = 720;
const C = {
  ink: "#17151B",
  muted: "#6F6874",
  line: "#E7DCE3",
  pink: "#F43F8C",
  pinkDark: "#B4145A",
  pinkSoft: "#FFF0F6",
  pinkPale: "#FFF9FC",
  green: "#16825D",
  greenSoft: "#EAF8F2",
  amber: "#A56100",
  amberSoft: "#FFF4DD",
  red: "#B42318",
  redSoft: "#FEECEB",
  white: "#FFFFFF",
};

const presentation = Presentation.create({ slideSize: { width: W, height: H } });

function addShape(slide, geometry, x, y, w, h, fill = "none", lineFill = "none", lineWidth = 0, radius = undefined) {
  return slide.shapes.add({
    geometry,
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { style: "solid", fill: lineFill, width: lineWidth },
    ...(radius ? { borderRadius: radius } : {}),
  });
}

function addText(slide, text, x, y, w, h, size = 24, color = C.ink, bold = false, align = "left") {
  const box = addShape(slide, "textbox", x, y, w, h);
  box.text = text;
  box.text.style = {
    typeface: fontFamily,
    fontSize: size,
    color,
    bold,
    alignment: align,
    autoFit: "shrinkText",
  };
  return box;
}

function addLine(slide, x, y, w, h = 0, color = C.line, width = 2) {
  return slide.shapes.add({
    geometry: "line",
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { style: "solid", fill: color, width },
  });
}

function baseSlide(title, number, kicker = "MIDETA") {
  const slide = presentation.slides.add();
  slide.background.fill = C.white;
  addShape(slide, "rect", 0, 0, W, 8, C.pink);
  addText(slide, kicker, 64, 34, 260, 24, 15, C.pinkDark, true);
  addText(slide, title, 64, 68, 1050, 58, 40, C.ink, true);
  addLine(slide, 64, 132, 1152, 0, C.line, 1);
  addText(slide, String(number).padStart(2, "0"), 1165, 40, 50, 26, 15, C.muted, true, "right");
  addText(slide, "Hawarisma Rafanidya Singgih", 64, 688, 320, 18, 12, C.muted, false);
  addText(slide, "Media Intelligence Tools", 950, 688, 266, 18, 12, C.muted, false, "right");
  return slide;
}

function note(slide, extra = "") {
  slide.speakerNotes.textFrame.setText(
    `Sumber: dokumentasi internal dan implementasi MIDETA, kondisi 23 September 2026.${extra ? `\n${extra}` : ""}`,
  );
}

function numberedMarker(slide, label, x, y, fill = C.pink) {
  addShape(slide, "ellipse", x, y, 44, 44, fill);
  addText(slide, label, x + 1, y + 7, 42, 26, 17, C.white, true, "center");
}

// 1. Cover
{
  const slide = presentation.slides.add();
  slide.background.fill = C.pinkPale;
  addShape(slide, "rect", 0, 0, 18, H, C.pink);
  const logo = await fs.readFile(path.join(workspaceDir, "assets/mideta-logo.png"));
  slide.images.add({
    blob: logo,
    contentType: "image/png",
    alt: "Logo MIDETA",
    fit: "contain",
    position: { left: 866, top: 128, width: 270, height: 270 },
    geometry: "roundRect",
    borderRadius: "rounded-3xl",
  });
  addText(slide, "MIDETA", 76, 120, 700, 90, 68, C.ink, true);
  addText(slide, "Brief produk dan perjalanan pengembangan", 80, 218, 710, 52, 30, C.pinkDark, true);
  addText(
    slide,
    "Media Intelligence Tools untuk merapikan data publik media sosial dan artikel menjadi hasil yang siap diperiksa dan diekspor.",
    80, 292, 690, 116, 24, C.muted, false,
  );
  addLine(slide, 80, 445, 650, 0, C.pink, 4);
  addText(slide, "Perjalanan / Cara kerja / Manfaat / Batasan", 80, 468, 650, 34, 18, C.ink, true);
  addText(slide, "Hawarisma Rafanidya Singgih", 80, 622, 420, 28, 18, C.ink, true);
  addText(slide, "September 2026", 80, 655, 260, 22, 15, C.muted, false);
  note(slide);
}

// 2. Journey
{
  const slide = baseSlide("Perjalanan pengembangan", 2);
  addText(slide, "MIDETA berkembang dari eksperimen notebook menjadi aplikasi lokal yang dapat dipakai berulang.", 64, 151, 1040, 38, 22, C.muted);
  addLine(slide, 150, 319, 980, 0, C.line, 5);

  const stages = [
    {
      n: "01", x: 92, title: "Google Colab", year: "Prototipe awal",
      body: "Parser dan format data diuji cepat di notebook. Cocok untuk membuktikan ide dan mencoba beberapa URL.",
    },
    {
      n: "02", x: 460, title: "Kebutuhan bertambah", year: "Workflow membesar",
      body: "Login browser, antrean panjang, riwayat proses, serta banyak platform mulai sulit dikelola dalam satu notebook.",
    },
    {
      n: "03", x: 828, title: "VS Code + terminal", year: "Aplikasi lokal",
      body: "Kode dipisah per modul, sesi Chrome dapat digunakan kembali, proses tersimpan, dan hasil dapat diunduh konsisten.",
    },
  ];
  for (const s of stages) {
    numberedMarker(slide, s.n, s.x + 105, 297);
    addText(slide, s.year.toUpperCase(), s.x, 220, 260, 22, 14, C.pinkDark, true, "center");
    addText(slide, s.title, s.x, 365, 260, 36, 24, C.ink, true, "center");
    addText(slide, s.body, s.x, 418, 260, 120, 19, C.muted, false, "center");
  }
  addText(slide, "Inti perubahan", 64, 585, 170, 24, 16, C.pinkDark, true);
  addText(slide, "Dari percobaan sekali jalan menjadi workflow operasional yang dapat diulang dan diperiksa.", 235, 582, 930, 34, 22, C.ink, true);
  note(slide, "Riwayat perjalanan diringkas dari konteks pengembangan yang diberikan oleh pembuat MIDETA.");
}

// 3. Why local
{
  const slide = baseSlide("Mengapa beralih ke aplikasi lokal", 3);
  addText(slide, "Kebutuhan utama", 64, 162, 420, 30, 21, C.pinkDark, true);
  const needs = [
    ["01", "Sesi login yang dapat dipakai kembali", "Browser profile lokal mengurangi kebutuhan login berulang."],
    ["02", "Kode lebih mudah dirawat", "Connector, antrean, ekspor, dan test berada di modul terpisah."],
    ["03", "Proses panjang lebih terkendali", "Hasil dapat disimpan bertahap, dijeda, lalu dilanjutkan."],
  ];
  needs.forEach((item, i) => {
    const y = 215 + i * 112;
    numberedMarker(slide, item[0], 64, y, i === 1 ? C.pinkDark : C.pink);
    addText(slide, item[1], 124, y - 2, 435, 30, 21, C.ink, true);
    addText(slide, item[2], 124, y + 34, 430, 50, 17, C.muted);
  });
  const ui = await fs.readFile(path.join(TMP_DIR, "mideta-ui.png"));
  addShape(slide, "roundRect", 610, 166, 602, 384, C.pinkSoft, C.line, 1, "rounded-2xl");
  slide.images.add({
    blob: ui,
    contentType: "image/png",
    alt: "Tampilan aplikasi MIDETA berbasis Streamlit",
    fit: "cover",
    crop: { left: 0.13, top: 0.06, right: 0.02, bottom: 0.07 },
    position: { left: 626, top: 182, width: 570, height: 352 },
    geometry: "roundRect",
    borderRadius: "rounded-xl",
  });
  addShape(slide, "roundRect", 64, 586, 1148, 66, C.pinkSoft, "none", 0, "rounded-xl");
  addText(slide, "Pertukaran utama", 84, 605, 178, 24, 16, C.pinkDark, true);
  addText(slide, "Kemudahan setup Colab ditukar dengan kontrol, stabilitas, dan kemampuan pemeliharaan yang lebih tinggi.", 264, 600, 920, 34, 20, C.ink, true);
  note(slide, "Tangkapan layar berasal dari aplikasi MIDETA milik pengguna.");
}

// 4. Product at a glance
{
  const slide = baseSlide("MIDETA saat ini", 4);
  addText(slide, "Satu workspace lokal untuk empat pekerjaan utama.", 64, 155, 820, 38, 23, C.muted);
  addShape(slide, "ellipse", 546, 262, 188, 188, C.ink);
  addText(slide, "MIDETA", 570, 319, 140, 42, 28, C.white, true, "center");
  addText(slide, "LOCAL", 589, 365, 102, 20, 14, C.pink, true, "center");
  addLine(slide, 392, 330, 154, 0, C.line, 2);
  addLine(slide, 734, 330, 154, 0, C.line, 2);
  addLine(slide, 640, 450, 0, 70, C.line, 2);

  const items = [
    ["01", "Social Media Enrichment", "Metadata posting, engagement, followers, dan views yang tersedia.", 64, 228],
    ["02", "Comment Scrapper", "Komentar utama, reply, likes, dan jumlah balasan.", 892, 228],
    ["03", "Conventional Media", "Artikel bersih, journalist, scope, tier, tone, dan quote mention.", 64, 460],
    ["04", "Riwayat Analisis", "Hasil lokal yang dapat dibuka kembali dan diunduh.", 892, 460],
  ];
  for (const [n, title, body, x, y] of items) {
    addText(slide, n, x, y, 48, 28, 17, C.pinkDark, true);
    addText(slide, title, x + 52, y, 300, 34, 22, C.ink, true);
    addText(slide, body, x + 52, y + 42, 300, 74, 18, C.muted);
  }
  addText(slide, "YouTube   TikTok   Facebook   Instagram   Threads   X   Media online", 290, 585, 700, 28, 18, C.pinkDark, true, "center");
  note(slide);
}

// 5. Workflow
{
  const slide = baseSlide("Alur kerja utama", 5);
  addText(slide, "Setiap URL tetap memiliki satu baris hasil agar data mudah dicocokkan kembali.", 64, 154, 970, 36, 22, C.muted);
  const steps = [
    ["01", "Masukkan URL", "Satu URL per baris, termasuk short link."],
    ["02", "Kenali sumber", "Platform dan format tautan diperiksa."],
    ["03", "Ambil data", "Sumber publik atau sesi login digunakan."],
    ["04", "Rapikan hasil", "Field dinormalisasi tanpa mengubah urutan."],
    ["05", "Review & ekspor", "Status diperiksa lalu diunduh ke CSV/XLSX."],
  ];
  addLine(slide, 122, 300, 1036, 0, C.line, 5);
  steps.forEach((s, i) => {
    const x = 55 + i * 240;
    numberedMarker(slide, s[0], x + 78, 278, i === 4 ? C.pinkDark : C.pink);
    addText(slide, s[1], x, 355, 200, 34, 21, C.ink, true, "center");
    addText(slide, s[2], x, 402, 200, 80, 17, C.muted, false, "center");
  });
  addShape(slide, "roundRect", 132, 538, 1016, 78, C.greenSoft, "none", 0, "rounded-xl");
  addText(slide, "URL gagal tetap dipertahankan", 158, 558, 330, 28, 18, C.green, true);
  addText(slide, "Baris tidak dihapus. MIDETA menuliskan status error sehingga posisi keluaran tetap sama dengan input.", 475, 553, 650, 40, 18, C.ink, false);
  note(slide);
}

// 6. Coverage and outputs
{
  const slide = baseSlide("Cakupan dan hasil", 6);
  addText(slide, "Kapasitas proses", 64, 158, 250, 28, 19, C.pinkDark, true);
  const metrics = [
    ["1.000", "URL per antrean enrichment"],
    ["2.000", "komentar maksimal per URL"],
    ["5", "artikel publik diproses paralel"],
  ];
  metrics.forEach((m, i) => {
    const x = 64 + i * 250;
    addText(slide, m[0], x, 200, 220, 50, 38, C.ink, true);
    addText(slide, m[1], x, 252, 220, 42, 16, C.muted);
  });
  addText(slide, "Platform sosial", 848, 158, 220, 28, 19, C.pinkDark, true);
  addText(slide, "YouTube   TikTok\nFacebook   Instagram\nThreads   X", 848, 205, 330, 96, 22, C.ink, true);
  addLine(slide, 64, 325, 1152, 0, C.line, 1);

  const groups = [
    ["POSTING", "Tanggal, author, caption, followers, views, likes, comments, bookmark, shares, dan repost."],
    ["KOMENTAR", "Tanggal, username, tipe parent/reply, isi komentar, likes, dan jumlah reply."],
    ["ARTIKEL", "Tanggal, media, scope, tier, judul, isi bersih, journalist, tone, dan quote mention."],
  ];
  groups.forEach((g, i) => {
    const x = 64 + i * 384;
    addText(slide, g[0], x, 366, 310, 28, 15, C.pinkDark, true);
    addText(slide, g[1], x, 410, 328, 112, 20, C.ink, false);
    addLine(slide, x, 543, 300, 0, i === 1 ? C.pinkDark : C.pink, 4);
  });
  addText(slide, "Format keluaran", 64, 580, 180, 24, 16, C.muted, true);
  addText(slide, "CSV untuk data teks, XLSX dengan format tabel, dan riwayat lokal untuk membuka hasil sebelumnya", 245, 576, 955, 34, 19, C.ink, true);
  note(slide);
}

// 7. Pros and cons table
{
  const slide = baseSlide("Google Colab dan VS Code lokal", 7);
  addText(slide, "Perpindahan platform membawa manfaat operasional sekaligus tanggung jawab pemeliharaan baru.", 64, 154, 1080, 34, 21, C.muted);
  const values = [
    ["Aspek", "Google Colab", "VS Code + terminal"],
    ["Memulai", "+ Cepat dicoba\n− Setup ulang ketika runtime berubah", "+ Lingkungan dapat digunakan kembali\n− Perlu instalasi awal"],
    ["Sesi browser", "+ Cocok untuk akses publik sederhana\n− Login dan browser profile terbatas", "+ Sesi Chrome dapat dipakai kembali\n− Bergantung pada perangkat lokal"],
    ["Proses panjang", "+ Mudah menjalankan eksperimen kecil\n− Runtime dapat terputus atau reset", "+ Antrean dan riwayat dapat dilanjutkan\n− Komputer harus tetap aktif"],
    ["Pemeliharaan", "+ Satu notebook mudah dibagikan\n− Cepat menjadi panjang dan rapuh", "+ Modul, test, dan Git lebih rapi\n− Perubahan perlu diuji"],
    ["Penggunaan tim", "+ Tautan notebook mudah dibuka\n− Hasil bergantung pada runtime pengguna", "+ Workflow lebih konsisten\n− Distribusi membutuhkan setup atau hosting"],
  ];
  const table = slide.tables.add({
    rows: values.length,
    columns: 3,
    left: 64,
    top: 208,
    width: 1152,
    height: 414,
    columnWidths: [190, 481, 481],
    values,
  });
  table.borders.assign({ style: "solid", fill: C.line, width: 1 });
  table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 3 }).assign({
    fill: C.ink,
    textStyle: { typeface: fontFamily, fontSize: 19, color: C.white, bold: true },
    margins: { left: 12, right: 12, top: 9, bottom: 9 },
  });
  table.cells.block({ row: 1, column: 0, rowCount: 5, columnCount: 1 }).assign({
    fill: C.pinkSoft,
    textStyle: { typeface: fontFamily, fontSize: 17, color: C.pinkDark, bold: true },
    margins: { left: 12, right: 10, top: 8, bottom: 8 },
  });
  table.cells.block({ row: 1, column: 1, rowCount: 5, columnCount: 2 }).assign({
    fill: C.white,
    textStyle: { typeface: fontFamily, fontSize: 16, color: C.ink, bold: false },
    margins: { left: 14, right: 12, top: 7, bottom: 7 },
  });
  table.rows[0].height = 46;
  for (let i = 1; i < values.length; i += 1) table.rows[i].height = 73;
  note(slide);
}

// 8. Limitations
{
  const slide = baseSlide("Batasan MIDETA", 8);
  addShape(slide, "roundRect", 64, 156, 1152, 94, C.redSoft, "none", 0, "rounded-xl");
  addText(slide, "Batasan paling penting", 88, 176, 245, 26, 16, C.red, true);
  addText(slide, "Jika platform mengubah struktur posting, connector dapat berhenti membaca data sampai kodenya diperbarui.", 325, 170, 850, 52, 24, C.ink, true);

  const limitations = [
    ["01", "Perubahan tampilan dan struktur", "MIDETA bergantung pada HTML, data JSON, label, dan pola halaman yang ditampilkan platform."],
    ["02", "Akses terbatas", "Posting privat, artikel terhapus, paywall, batas usia atau wilayah dapat menghasilkan Tidak tersedia."],
    ["03", "Proteksi platform", "CAPTCHA, rate limit, temporary block, atau sesi kedaluwarsa dapat menghentikan proses."],
    ["04", "Kelengkapan data", "Tidak semua platform menampilkan views, followers, bookmark, share, atau seluruh komentar."],
    ["05", "Komentar tersembunyi", "Komentar yang difilter, dihapus, atau tidak dimuat oleh platform tidak dapat dikumpulkan."],
    ["06", "Data bersifat snapshot", "Angka engagement dapat berubah setelah proses selesai dan perlu diperbarui jika dipakai kembali."],
  ];
  limitations.forEach((item, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 64 + col * 576;
    const y = 286 + row * 112;
    addText(slide, item[0], x, y, 48, 26, 16, C.pinkDark, true);
    addText(slide, item[1], x + 54, y, 470, 28, 20, C.ink, true);
    addText(slide, item[2], x + 54, y + 34, 470, 58, 17, C.muted);
  });
  note(slide);
}

// 9. Operating principles and priorities
{
  const slide = baseSlide("Penggunaan hasil dan prioritas pengembangan", 9);
  addText(slide, "Posisi MIDETA", 64, 157, 220, 28, 18, C.pinkDark, true);
  addText(slide, "Alat bantu pengumpulan dan perapihan data, bukan satu-satunya sumber kebenaran.", 64, 198, 700, 66, 29, C.ink, true);
  addShape(slide, "roundRect", 830, 158, 386, 116, C.pinkSoft, "none", 0, "rounded-xl");
  addText(slide, "Prinsip pemeriksaan", 854, 179, 320, 26, 16, C.pinkDark, true);
  addText(slide, "Tinjau sampel hasil sebelum data digunakan untuk laporan atau keputusan.", 854, 216, 320, 42, 18, C.ink, true);

  addLine(slide, 64, 306, 1152, 0, C.line, 1);
  addText(slide, "Saat menggunakan hasil", 64, 342, 430, 30, 23, C.ink, true);
  const use = [
    "Periksa baris bertanda Tidak tersedia, URL tidak dapat diproses, atau [CHECK].",
    "Bandingkan beberapa URL secara manual untuk memastikan format platform belum berubah.",
    "Simpan tanggal pengambilan karena engagement merupakan snapshot.",
  ];
  use.forEach((t, i) => {
    numberedMarker(slide, String(i + 1).padStart(2, "0"), 64, 394 + i * 70, C.pink);
    addText(slide, t, 122, 393 + i * 70, 475, 48, 18, C.ink, i === 0);
  });

  addText(slide, "Prioritas pengembangan", 688, 342, 430, 30, 23, C.ink, true);
  const priorities = [
    "Pantau perubahan struktur tiap platform dan simpan contoh halaman untuk regression test.",
    "Pisahkan parser per platform agar perbaikan tidak merusak connector lain.",
    "Tampilkan alasan gagal yang spesifik agar pengguna tahu kapan perlu retry atau update parser.",
  ];
  priorities.forEach((t, i) => {
    numberedMarker(slide, String(i + 1).padStart(2, "0"), 688, 394 + i * 70, C.pinkDark);
    addText(slide, t, 746, 393 + i * 70, 470, 48, 18, C.ink, i === 0);
  });
  addLine(slide, 64, 626, 1152, 0, C.pink, 4);
  addText(slide, "Keandalan MIDETA bergantung pada pemantauan platform dan pembaruan connector secara rutin.", 64, 641, 1152, 28, 19, C.pinkDark, true, "center");
  note(slide);
}

await fs.mkdir(TMP_DIR, { recursive: true });
await fs.mkdir(path.dirname(FINAL_PPTX), { recursive: true });
const candidatePath = path.join(TMP_DIR, "candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);

const result = await finalizePresentation({
  explicitTotalSlideCount: 9,
  requiredNativeTableOwnerSlides: [7],
  requiredNativeChartOwnerSlides: [],
  workspaceDir,
  candidatePath,
  finalPath: FINAL_PPTX,
  pythonExecutable: RUNTIME_PYTHON,
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: [
    "--expected-slide-size-emu", "12192000,6858000",
    "--validate-bullet-geometry",
    "--validate-heading-fit",
    "--require-native-table-slide", "7",
  ],
  fontPolicy: { basis: "design", families: [fontFamily] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(workspaceDir, ".codex-finalizer/MIDETA_Brief_Profesional_ID_v2.validation.json"),
});

console.log(JSON.stringify({ fontFamily, finalPath: FINAL_PPTX, result }, null, 2));
