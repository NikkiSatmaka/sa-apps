<!-- Bagian dari docs/ROADMAP.md (indeks). Checkbox fase ini di-update di sini. -->

## Fase 8A — Role dan Akses (fitur 13)

**Tujuan:** satu role fungsional per user plus flag `is_admin`, dan role `Product`. Prasyarat Fase 8B. Lihat [ADR 0012](../adr/0012-role-fungsional-tunggal-dan-flag-admin.md).

- [x] 8A.1 (#114, PR #128) Migration + model: `role` ∈ `Sales, Product, SA, Lead_SA`; kolom `is_admin` (default `false`); user berrole `Admin` dimigrasi ke `is_admin = true` dengan role fungsional yang dipilih. Test upgrade, downgrade, dan constraint.
- [x] 8A.2 `privileged` = `role == Lead_SA or is_admin`; semua cek `role in ("Lead_SA", "Admin")` dan `Admin` di backend (74 pemakaian `.role` di 21 file) dan frontend (~30 file) diganti; endpoint admin memakai `is_admin`. **Frontend selesai di #116** (`frontend/src/lib/roles.ts` memusatkan pengecekan hak; persona test `Admin` = SA + `is_admin`).
- [x] 8A.3 (#115) Kandidat dan validasi `assigned_sa`: `SA` dan `Lead_SA` (satu himpunan; hapus `sa_user.role != "SA"`).
- [x] 8A.4 Role gate `POST /projects`: `Sales`, `Product`, `Lead_SA`, `is_admin`; `SA` ditolak (menyelesaikan poin #96).
- [x] 8A.5 `Product` memakai tingkat izin yang sama dengan `Sales` di `_ATURAN`.

**Kriteria selesai:** dev bisa ditugaskan sebagai SA dengan `is_admin`; Product bisa membuat dan memantau project; tidak ada nilai `Admin` di enum role.
