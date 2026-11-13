# Satu role fungsional per user, ditambah flag `is_admin`

Role `Admin` sebelumnya salah satu nilai `User.role`. Itu membuat developer yang memakai app sebagai SA tidak bisa ditugaskan sebagai SA, karena endpoint assignment memeriksa `sa_user.role != "SA"`. Selain itu role `Product` belum ada, padahal setiap project selalu punya Product dan boleh tanpa Sales.

Kami memutuskan (pemilik produk, 2026-11-13):

- `User.role` tetap **satu nilai fungsional wajib**: `Sales`, `Product`, `SA`, `Lead_SA`.
- `Admin` menjadi flag boolean `User.is_admin` (default `false`) yang menempel pada satu role fungsional. Tidak ada Admin murni; bila kelak dibutuhkan, `role` bisa dilonggarkan lewat migration kecil.
- Hak `is_admin` sama dengan Admin lama: kelola user, `POST /sla/process`, membuka kembali `Closed`/`Lost`, mengganti orang di project, dan "privileged" pada semua project. `privileged` menjadi `role == Lead_SA or is_admin`.
- Kandidat `assigned_sa` dan SA tambahan adalah user berrole `SA` atau `Lead_SA`. Daftar kandidat dan validasi memakai himpunan yang sama.
- `Product` memakai tingkat izin yang sama dengan `Sales`.
- Pembuat project adalah `Sales`, `Product`, `Lead_SA`, atau `is_admin`; `SA` tidak boleh membuat project.

## Alternatif yang ditolak

- **Multi-role (satu user, banyak role).** Menyentuh 74 pemakaian `.role` di 21 file backend dan sekitar 30 file frontend, dan semantiknya rancu (mis. Sales+SA bentrok dengan `cocokkan_peran` di `_ATURAN`; dashboard mana yang tampil). Kebutuhan sebenarnya hanya "admin sebagai kemampuan tambahan".
- **Dua akun per orang.** `email` dan `google_id` unik, dan Drive/Calendar terikat ke identitas Google.
- **Role switching ("login sebagai").** Berguna untuk menguji UI per peran, tetapi fitur terpisah dan bukan solusi untuk masalah ini.

## Konsekuensi

- Migration: enum `role` kehilangan `Admin` dan mendapat `Product`; user berrole `Admin` menjadi `is_admin = true` dengan role fungsional yang dipilih pemilik. Tidak ada data produksi saat keputusan ini, sehingga cukup satu langkah (tetap dengan test upgrade, downgrade, dan constraint).
- Dengan `is_admin`, user tetap privileged di semua project, sehingga pembatasan hak SA sebenarnya tidak terlihat saat menguji. Uji dengan akun Google kedua yang bukan admin.
