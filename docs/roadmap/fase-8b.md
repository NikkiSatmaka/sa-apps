<!-- Bagian dari docs/ROADMAP.md (indeks). Checkbox fase ini di-update di sini. -->

## Fase 8B — Orang per Project dan Multi-SA (fitur 13)

**Tujuan:** `product_pic` wajib, `sales_pic` opsional, `lead_sa`, `created_by`, SA tambahan, dan akses Drive/SLA/notifikasi yang mengikuti orang yang ditugaskan. Lihat [ADR 0014](../adr/0014-orang-per-project-dan-multi-sa.md) dan [ADR 0015](../adr/0015-matriks-akses-drive-dan-gate-dq.md). Sebaiknya dikerjakan setelah verifikasi Drive nyata (#27).

- [x] 8B.1 Migration + model: `created_by`, `product_pic` (wajib), `sales_pic` nullable, `lead_sa`; tabel `ProjectAssignments`. Test migration. _Kolom orang di #117 (migration 018); tabel `project_assignments` di #119 (migration 019)._
- [ ] 8B.2 Pembuatan project mengisi `created_by`/`product_pic`; Sales memilih Product; `lead_sa` terisi saat assign. _Sebagian (#117): pembuatan project dan form frontend selesai; `lead_sa` terisi saat assign selesai (#118)._
- [ ] 8B.3 Endpoint Lead_SA/Admin untuk mengganti `product_pic`/`sales_pic`/`lead_sa` dan menambah, melepas, mengganti SA utama/tambahan; aturan "minimal satu SA setelah `Assigned`"; audit log. _Sebagian: `PATCH /projects/{id}/people` + audit `people_change` + UI (#118); `GET/POST /projects/{id}/tim-sa`, `DELETE .../tim-sa/{user_id}`, `PUT .../tim-sa/utama`, minimal satu SA, audit log, UI "Tim SA" (#119). Sisa: pilihan Lead SA di UI assign._
- [ ] 8B.4 `_ATURAN` per hubungan (id) pada semua field orang dan `ProjectAssignments`; "SA ditugaskan" = SA utama atau tambahan; hak SA tambahan setara SA utama. _Sebagian (#119): "SA ditugaskan" = SA utama atau tambahan, hak setara teruji lewat matriks rute; hubungan `lead_sa` menunggu Orang-2/Orang-4._
- [ ] 8B.5 Drive: Viewer `Inventory` untuk Sales **dan Product**; Viewer `Solutions` untuk keduanya setelah DQ terisi; penggantian orang mencabut dan memberi akses; cek apakah contributor saat ini mendapat Editor.
- [ ] 8B.6 SLA dan notifikasi: reminder H+3 ke Sales dan Product (Product saja bila tanpa Sales); eskalasi H+5 ke `lead_sa` dan semua `is_admin`; `Need Clarification` ke `created_by`, `product_pic`, `sales_pic`; notifikasi "buat HLD" ke semua SA; DQ boleh diisi Sales, Product, Lead_SA; validasi format `dq_number` di PATCH (#96).
- [x] 8B.7 Subtask: assignee harus SA project (utama/tambahan) atau Lead_SA. _(#119)_

**Kriteria selesai:** project tanpa Sales berjalan penuh; dua SA bisa bekerja di satu project dengan hak setara; mengganti orang memindahkan akses Drive dan timer SLA tidak direset.
