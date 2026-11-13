# Semua proyek dapat dibaca semua pengguna; hanya akses tulis yang dibatasi

Kebijakan akses proyek (spec #87, diterapkan #97/#102) sempat membatasi akses BACA ke Lead_SA, Admin, Sales PIC, SA ditugaskan, dan collaborator, dengan pihak lain mendapat 403. Pemilik produk memutuskan pada 2026-11-10: **semua proyek dapat dilihat oleh semua pengguna terautentikasi, tanpa batas**. Yang dibatasi hanya akses **tulis** (SA ditugaskan, contributor, Lead_SA, Admin, Sales PIC menurut aturan tiap aksi di `_ATURAN`, `backend/app/core/dependencies.py`).

Mengapa tingkat `BACA` dan `STORY` tetap ada di titik keputusan alih-alih dihapus: `ensure_project_access` tetap dipanggil di tiap rute baca supaya (1) penjaga rute `tests/test_penjaga_akses_rute.py` tetap menegakkan "tidak ada rute proyek tanpa keputusan akses", dan (2) bila kebijakan dibatasi lagi nanti, cukup mengubah satu entri aturan. Aturan keduanya kini `semua_pengguna=True`; tidak ada query collaborator untuk tingkat ini.

## Cakupan

- Berlaku: detail proyek, daftar proyek dan ringkasan status (server tidak lagi menyaring per peran; `sales_pic=me` dan `assigned_to=me` tetap berfungsi sebagai penyempit), daftar dokumen, Project Story dan ringkasan AI, kolaborator, subtask, hasil BANT, SLA, rekomendasi, DQ.
- Tidak berubah: semua aksi tulis dan kelola; peran `Sales` bukan PIC tetap tidak melihat **link dokumen folder Solutions** (gating DQ Flow 2 dan izin Drive, bukan soal akses proyek); status kesiapan handover tetap khusus SA ditugaskan, Lead_SA, dan Admin karena merupakan prasyarat aksi.
- 403 tetap menjadi respons penolakan akses tulis (issue #94 diputuskan: 403, bukan 404). Pesan 403 yang berbeda per rute dibiarkan karena kontraknya sudah terkunci test.

## Konsekuensi

- Rekomendasi (RAG) yang menampilkan link Solutions proyek Closed-Win lain kepada SA bukan kebocoran lagi (issue #93 ditutup sebagai sesuai desain).
- Keputusan 2026-11-10 sebelumnya (Sales PIC boleh membaca Story) tercakup oleh kebijakan ini dan tidak lagi berdiri sendiri.
- Frontend: halaman daftar proyek Sales/SA masih memfilter milik sendiri lewat `sales_pic=me` / `assigned_to=me`; menampilkan semua proyek di UI adalah keputusan tampilan terpisah.
