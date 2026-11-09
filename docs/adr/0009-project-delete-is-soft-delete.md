# Hapus proyek adalah soft delete, disaring global di level ORM

`DELETE /projects/{id}` (Lead_SA/Admin) semula melakukan hard delete dan **selalu gagal** (500) untuk proyek yang punya dokumen, activity log, atau SLA record, karena FK `documents`, `activity_logs`, dan `sla_tracking` → `projects` tidak memakai `ON DELETE`. Kami menggantinya dengan soft delete: kolom `projects.deleted_at` + `deleted_by` (migration 009). Proyek terhapus disembunyikan dari **semua** SELECT ORM atas `Project` lewat listener `do_orm_execute` + `with_loader_criteria` di `app/models/project.py` — bukan filter manual per query (ada ~45 query `select(Project)` yang tersebar, gampang terlewat). Spec tidak mengatur penghapusan proyek; keputusan ini diambil user (2026-11-09).

## Considered Options

- **Hard delete + `ON DELETE CASCADE`** — ditolak: activity log adalah data utilisasi SA (dashboard Lead SA); menghapusnya diam-diam merusak laporan jam kerja. Hilang permanen, tanpa jalan pulih.
- **Tolak hapus (409) bila ada data terkait** — ditolak: hampir semua proyek nyata punya data terkait, sehingga fitur hapus praktis tidak berguna.
- **Soft delete, filter manual per query** — ditolak: rawan bocor saat query baru ditambah.
- **Soft delete, filter global ORM** — dipilih.

## Consequences

- Data terkait tetap utuh. Utilisasi per SA (`/sa/utilization`, `/utilization/summary`) tetap menghitung jam dari proyek terhapus karena mengagregasi `activity_logs` langsung; tabel effort per proyek (`/utilization/projects`) tidak menampilkannya.
- Semua endpoint yang lookup proyek by ID otomatis 404 untuk proyek terhapus (termasuk DELETE ulang).
- SLA timer aktif dihentikan (`stopped_at`) saat proyek dihapus agar scheduler tidak lagi mengirim reminder/eskalasi. Folder Google Drive **tidak** disentuh (tetap ada, termasuk status lock-nya).
- Kode yang memang perlu melihat proyek terhapus (mis. fitur restore/audit kelak) harus opt-in dengan `.execution_options(include_deleted=True)` (konstanta `INCLUDE_DELETED`).
- Filter hanya berlaku untuk query ORM. Raw SQL (`text(...)`) atas tabel `projects` harus menambahkan `deleted_at IS NULL` sendiri — saat ADR ini ditulis tidak ada.
- Belum ada UI restore; pemulihan = set `deleted_at = NULL` langsung di DB.
