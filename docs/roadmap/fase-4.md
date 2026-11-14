<!-- Bagian dari docs/ROADMAP.md (indeks). Checkbox fase ini di-update di sini. -->

## Fase 4 — Subtask yang Bisa Di-assign (fitur 6)

**Tujuan:** mengubah "subtask" dari kategori activity-log bebas pilih menjadi work item yang nyata dan bisa di-track. **Ini perubahan model** — effort lebih besar.

- [x] 4.1 Tambah entity `Subtask`: `id`, `id_project`, `title`/`category`, `assigned_sa`, `status` (open → in_progress → done), timestamp. Migration + model + schema.
- [x] 4.2 Endpoint: buat subtask (Lead SA / template), list per proyek, update status, assign/reassign ke SA.
- [x] 4.3 Tautkan `ActivityLog` ke subtask (FK `id_subtask` opsional) agar mencatat aktivitas bisa memajukan/menutup subtask ("respons subtask"). **Mendarat (T2):** activity log pertama terhadap subtask `open` memajukannya ke `in_progress` dengan validasi scope `id_project`; `done` selalu eksplisit (ADR 0008).
- [x] 4.4 **✅ Diputuskan (sesi grill, 2026-10-21):** **YA** — meng-assign proyek otomatis men-seed checklist subtask default (mis. Requirement → BoQ → PropTek → HLD) dari template. Lead SA tetap bisa menambah/menghapus subtask secara manual. **Mendarat (T1):** keempat subtask default langsung ditugaskan ke SA proyek (`assigned_sa`), seeding idempoten pada re-assign.
- [x] 4.5 Frontend: tampilan to-do list subtask yang di-assign ke SA; UX mencatat aktivitas terhadap subtask; manajemen subtask untuk Lead SA. **Mendarat (T3):** section Subtask di `projects/[id]` (`frontend/src/components/SubtaskSection.tsx`) dengan kontrol per-role — SA melihat to-do list miliknya + tombol "Tandai selesai"; Lead_SA/Admin bisa tambah/hapus/assign-ulang; badge status per item + ringkasan "N/M selesai" di header.

**Kriteria selesai:** SA melihat to-do list subtask, mencatat aktivitas terhadap salah satunya, dan subtask berubah status.
