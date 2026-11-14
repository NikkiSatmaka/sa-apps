# Sistem Desain Portal SA

Dokumen ini menjadi fondasi visual dan interaksi Portal SA. Dokumen memisahkan **baseline** (yang ditemukan pada implementasi saat ini) dari **rekomendasi** (arah konsistensi ke depan). Rekomendasi tidak berarti seluruh UI sudah mengimplementasikannya; perubahan layar dilakukan bertahap sesuai lingkup pekerjaan.

## Arah visual

**Rekomendasi:** antarmuka B2B yang bersih, tenang, berorientasi kerja, dengan latar terang dan hierarki informasi jelas. Tema yang didukung saat ini adalah light. Hindari dekorasi yang tidak membantu pemindaian data, bayangan berat, warna mencolok tanpa makna, dan perubahan layout di luar kebutuhan fitur.

**Dasar brand:** `sample-logo/company-logo.png` menampilkan biru tua pada tulisan BERCA, merah pada lingkaran utama, serta hitam pada wordmark. Warna aksinya mengikuti biru logo; merah menjadi aksen brand dan warna semantik untuk kondisi berisiko/destruktif, bukan warna untuk seluruh aksi utama.

## Baseline saat ini

- Tailwind mendefinisikan `primary` biru (`#3b82f6` sampai `#172554`) dan skala `neutral`; sebagian status memakai warna Tailwind green, red, blue, amber, dan purple.
- Font dasar Open Sans dengan fallback system sans-serif, ukuran root 16px.
- Skala spacing mengikuti kelipatan 4px; komponen memakai radius umum `rounded-lg` (8px) dan sebagian `rounded` (4px).
- Elemen interaktif memiliki target minimum 44px pada aturan global, transisi 150ms, dan fokus terlihat.
- Checkbox asli ditemukan pada filter proyek, filter tugas, dan pengelolaan tim SA. Ukuran visual checkbox diseragamkan ke 18px; label pembungkus mempertahankan area interaksi minimum 44px.
- Ini adalah inventaris pola yang terlihat pada kode, bukan hasil audit seluruh layar atau pengukuran aksesibilitas otomatis.

## Token yang direkomendasikan

Nilai berikut adalah kontrak desain untuk penggunaan baru. Nilai yang sudah ada dapat tetap berjalan sampai layar disentuh; jangan melakukan redesign massal hanya untuk mengejar dokumen ini.

### Warna

| Token konseptual | Nilai / sumber | Penggunaan |
| --- | --- | --- |
| Aksi utama | `primary-600` `#2563eb` (baseline Tailwind) | Tombol utama, tautan, navigasi aktif, fokus kontrol |
| Aksi hover | `primary-700` `#1d4ed8` | Hover/pressed aksi biru |
| Permukaan | putih `#ffffff` | Kartu, formulir, panel konten |
| Latar halaman | `neutral-50` `#fafafa` | Latar ringan; jangan mengganti latar layar tanpa lingkup |
| Teks utama | `neutral-900` `#171717` | Konten dan heading |
| Teks sekunder | `neutral-600` `#525252` | Metadata dan label sekunder |
| Garis | `neutral-200` `#e5e5e5` | Pemisah dan border halus |
| Aksen brand merah | merah logo (perkiraan visual `#d9272e`) | Identitas brand; aksen terbatas, bukan dekorasi dominan |
| Bahaya | token red Tailwind | Error, destruktif, atau risiko; selalu disertai label/ikon |
| Sukses / perhatian / informasi | green / amber / blue semantik | Status eksplisit; jangan mengandalkan warna saja |

Merah perkiraan dari tampilan logo bukan hasil ekstraksi warna terukur. Saat token brand resmi tersedia, ganti perkiraan tersebut dengan nilai resmi dan cek kontras.

### Tipografi

- Font keluarga baseline: `Open Sans`, fallback system sans-serif.
- Body 16px / line-height sekitar 1.5; teks padat boleh 14px untuk metadata, bukan instruksi penting.
- Hirarki rekomendasi: halaman 24–30px, section 20px, subsection 18px, body 16px, metadata minimum 14px.
- Gunakan weight 400 untuk body, 500–600 untuk penekanan, 700 untuk judul/aksi penting. Batasi variasi.

### Spacing, radius, elevation

- Skala spacing 4px: `1=4`, `2=8`, `3=12`, `4=16`, `5=20`, `6=24`, `8=32`, `10=40`, `12=48` px. Pilih nilai skala, hindari angka arbitrer.
- Radius: 4px untuk kontrol rapat, 8px untuk input/kartu umum, 12px hanya untuk panel besar bila hierarki membutuhkannya.
- Elevation: utamakan border dan permukaan; gunakan shadow tipis hanya untuk overlay/popover/dialog yang perlu terangkat. Jangan menumpuk shadow.
- Konten desktop dibatasi sekitar 1440px; layout mobile-first dan tidak boleh memaksa scroll horizontal.

## Komponen dan state

- **Button:** aksi utama biru, aksi sekunder outline/neutral, aksi destruktif merah. Minimum target 44×44px. Sediakan hover, focus-visible, active, disabled, dan loading; disabled tetap terbaca.
- **Input/select/textarea:** label terlihat, border neutral, fokus ring biru, error border/latar merah lembut dengan pesan teks terkait. Pertahankan nilai dan struktur layar yang ada saat hanya mengubah gaya kontrol.
- **Checkbox:** gunakan kontrol native untuk perilaku dan keyboard. Kotak visual 16–18px (target 18px), aksen biru; target sentuh minimum 44×44px disediakan label/container, bukan dengan memperbesar kotaknya. Label harus bisa diklik, state disabled jelas, dan fokus keyboard terlihat.
- **Status/badge:** selalu tampilkan teks; warna hanya penguat. Gunakan palet semantik konsisten, bukan warna per role tanpa alasan.
- **Card/table/navigation:** permukaan putih, garis netral, heading dan metadata memiliki hirarki jelas; navigasi aktif menggunakan biru. Pertahankan layout halaman yang ada kecuali diminta eksplisit.
- **Feedback:** error menjelaskan cara pulih, sukses ringkas, loading tidak menghilangkan konteks, dan empty state memberi tindakan berikutnya bila tersedia.

Semua komponen interaktif perlu state default, hover, focus-visible, active, disabled, loading (bila operasi asynchronous), error, dan success sesuai relevansinya.

## Accessibility dan responsive

- Target pointer sekurangnya 44×44px dan jarak antar target memadai. Checkbox dapat terlihat kecil tetapi label hit-area harus tetap besar.
- Semua kontrol memiliki label programatik; gunakan elemen native sebelum ARIA kustom. Urutan tab mengikuti urutan visual/logis.
- Fokus terlihat dan tidak hanya ditandai dengan perubahan warna yang samar. Teks normal menargetkan kontras 4.5:1, teks besar dan komponen grafis 3:1.
- Status tidak dibedakan dengan warna saja. Hormati `prefers-reduced-motion`; animasi tidak boleh menjadi prasyarat memahami state.
- Uji layout pada lebar 320px, 768px, 1024px, dan 1440px. Di layar sempit, susun konten menjadi satu kolom, jaga kontrol utama dapat dijangkau, dan hindari overflow horizontal.
- Tema light adalah baseline. Tema gelap belum menjadi komitmen dan tidak boleh diasumsikan tersedia.

## Cara menerapkan

Gunakan token Tailwind yang tersedia (`primary`, `neutral`, spacing, dan radius) untuk perubahan berikutnya. Bila rekomendasi membutuhkan token teknis baru, tambahkan pada konfigurasi bersama dan dokumentasikan di sini. Perubahan kosmetik lintas halaman harus menjadi pekerjaan tersendiri; tiket checkbox hanya boleh mengubah ukuran visual checkbox dan target sentuh terkait.
