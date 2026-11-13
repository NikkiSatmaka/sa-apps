# Enum `Projects.status` mengikuti kode; `Pending DQ` dihapus dari spec

Spec awal mendefinisikan `New, Assigned, Pending DQ, Ready, Closed-Win, Lost`, sedangkan kode punya status operasional tambahan (`Pending Assignment, Handover Complete, Need Clarification, Scoring Pending, Manual Review Required`) dan menghilangkan `Pending DQ`. Kami memutuskan status operasional kode menjadi ground truth baru (spec dikoreksi) karena mereka nyata dan dipakai oleh flow AI scoring + handover yang sudah berjalan — bukan penyimpangan niat, melainkan detail yang spec awal tidak antisipasi. Mengubah enum status sulit dibalik (menyentuh CheckConstraint DB + migration + state machine), sehingga keputusan ini dicatat agar enum yang "aneh" tidak di-"rapikan" kembali ke spec lama.

## Pembaruan 2026-11-10: `Pending DQ` dihapus

Keputusan 2026-10-21 sempat mempertahankan `Pending DQ` sebagai status Flow 2. Pemilik produk membalik keputusan itu (issue #79): **`Pending DQ` dihapus dari spec**. Alasannya, "DQ belum diisi" bukan fase proyek, melainkan keadaan data: cukup `dq_number` yang masih kosong. Status itu tidak pernah ada di kode (ditolak CHECK `chk_projects_status`, tidak ada kode yang memakainya), sedangkan perilaku yang bergantung pada DQ kosong (timer SLA, penguncian folder Solutions, banner) sudah dibaca langsung dari `dq_number`.

Konsekuensi untuk alur kerja, supaya tidak disalahartikan sebagai hilangnya aturan bisnis:

- Normalnya SA mulai bekerja pada proyek setelah DQ Number diisi Sales, sama seperti informasi lain yang diisi Sales.
- Pada kasus urgent yang jarang, SA boleh bekerja sebelum DQ terisi sebagai **prerogatif**. Portal tidak memblokirnya (tidak ada gerbang status); yang tetap berlaku hanyalah SLA DQ (reminder H+3, eskalasi H+5, penguncian link Solutions bagi Sales).
