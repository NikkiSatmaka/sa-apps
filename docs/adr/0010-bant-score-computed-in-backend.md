# Skor BANT dihitung di backend; skor mentah dari klien hanya untuk override Lead SA

Sebelumnya aturan skor jalur manual hidup di frontend (`bant-manual.tsx`: MRR terisi → 25, kelengkapan PIC → 0/8/17/25, panjang teks kebutuhan → 8/17/25, tanggal terisi → 25), dan `POST /projects/{id}/score-manual` hanya menjumlahkan empat angka kiriman klien lalu menerapkan gate 60. Akibatnya Sales PIC yang memanggil API langsung bisa mengirim 25/25/25/25 dan lolos gate tanpa evidence apa pun.

Keputusan (Fase 5A): backend menghitung sub-skor dari jawaban Kuesioner kualifikasi memakai rubrik deterministik (konstanta di satu tempat). Jika proyek juga punya file, skor akhir per kriteria adalah nilai tertinggi antara skor rubrik dan skor AI dari file ("best evidence wins", konsisten dengan agregasi antar file). `score-manual` yang menerima angka mentah dibatasi untuk Lead_SA/Admin sebagai override dengan alasan wajib yang dicatat di audit log. Gate 60 tidak pernah menimpa status `Assigned` dan sesudahnya.

## Considered Options

- **Biarkan aturan di frontend** — ditolak: gate kualifikasi bisa dilewati lewat API, dan aturan tidak bisa dipakai ulang oleh backend (re-score saat jawaban diedit, jalur AI).
- **Backend hitung dari jawaban + AI dari file sebagai satu-satunya skor bila ada file** — ditolak: AI bisa menurunkan skor yang sudah dibuktikan jawaban Sales, dan kegagalan AI menjatuhkan seluruh skor.
- **Backend rubrik + max per kriteria dengan AI** — dipilih: skor tidak bisa dipalsukan klien, ada cadangan saat AI gagal, dan satu sumber kebenaran.

## Consequences

- Rubrik menjadi kontrak produk: perubahan angka berarti perubahan perilaku gate dan harus disertai test. Jawaban `schema_version` lama tetap harus bisa dinilai dengan rubrik versinya.
- Form manual BANT lama dihapus; `score-manual` berubah dari endpoint Sales menjadi endpoint override Lead_SA/Admin, sehingga klien yang memakainya harus diperbarui.
- Skor cenderung lebih tinggi karena max: Lead SA tetap menjadi penyaring saat assignment.
