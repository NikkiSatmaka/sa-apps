# Orang per project sebagai field yang bisa diganti, dan multi-SA

Satu project hanya punya `sales_pic` (wajib) dan `assigned_sa` (satu UUID). Padahal setiap project selalu punya Product dan boleh tanpa Sales, penugasan tiap peran bisa berubah, dan project kompleks butuh lebih dari satu SA. Subtask juga hanya punya satu assignee.

Kami memutuskan (pemilik produk, 2026-11-13):

- Field di `Projects`: `created_by` (tetap), `product_pic` (wajib), `sales_pic` (opsional), `lead_sa` (wajib sejak `Assigned`), `assigned_sa` (SA utama). Satu orang per peran; hanya Lead_SA atau `is_admin` yang mengganti, setiap penggantian masuk audit log.
- Bila Product membuat project, `product_pic` otomatis dirinya. Bila Sales membuat, Sales memilih Product.
- **Multi-SA:** tabel `ProjectAssignments` (`id_project`, `user_id`, `added_by`, `created_at`; unik pada `id_project`+`user_id`) untuk SA tambahan. SA utama tetap `assigned_sa`. SA tambahan punya hak **setara** SA utama (log, dokumen, status dokumen, Requirement, `Submitted`, handover, Drive Editor). Notifikasi "buat HLD" saat `Won` ke semua SA project. SA utama hanya berbeda sebagai penanggung jawab (tampil di dashboard, acuan eskalasi SLA).
- Setelah `Assigned`, project minimal punya satu SA. Bila SA utama dilepas dan masih ada SA tambahan, Lead_SA wajib memilih SA utama baru.
- **Subtask:** tetap **satu assignee**, yaitu salah satu SA project atau Lead_SA. Pekerjaan yang dikerjakan dua orang dipecah menjadi dua subtask. Hitungan beban kerja menghitung project dengan banyak SA untuk tiap SA-nya.
- Hanya Lead_SA atau `is_admin` yang menambah, melepas, atau mengganti SA. Drive Editor mengikuti penugasan; timer SLA tidak direset.
- **Collaborator tetap** untuk Backup SA dan pengamat dengan hak terbatas ([ADR 0002](0002-backup-sa-via-project-collaboration.md)); sengaja tidak dilebur dengan SA tambahan.

## Konsekuensi

- `_ATURAN` di `backend/app/core/dependencies.py` perlu dihitung per hubungan (id) pada tiap field orang dan pada `ProjectAssignments`, bukan lagi `sales_pic`/`assigned_sa` tunggal; "SA ditugaskan" berarti SA utama atau tambahan.
- Filter "proyek saya" menjadi `involved=me`: cocok bila user adalah `created_by`, `sales_pic`, `product_pic`, `lead_sa`, SA utama/tambahan, atau collaborator.
- Belum diverifikasi: apakah contributor saat ini mendapat Drive Editor; dicek saat fase ini dikerjakan.
