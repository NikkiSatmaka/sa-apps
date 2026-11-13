# Model status dua field: siklus kerja dan `qualification_state`

Enum `Projects.status` lama mencampur tiga hal: gate kualifikasi intake (`New`, `Scoring Pending`, `Need Clarification`, `Manual Review Required`), kerja SA (`Assigned`, `Ready`), dan hasil komersial (`Closed-Win`, `Lost`). Tidak ada status "SA sedang mengerjakan", tidak ada penutup setelah handover, tidak ada jeda, dan `Ready` tidak didefinisikan di spec, glossary, maupun ADR. Keputusan ini **menggantikan** [ADR 0001](0001-status-enum-code-is-ground-truth.md).

Kami memutuskan (pemilik produk, 2026-11-13):

- `status`: `Intake`, `Awaiting Assignment`, `Assigned`, `In Progress`, `Submitted`, `Won`, `Handed Over`, `Closed`, ditambah status samping `Lost` dan `On Hold`.
- `qualification_state`: `Scoring`, `Need Clarification`, `Manual Review`, `Qualified`. Hanya bermakna saat `status = Intake`; setelah lolos tetap `Qualified`.
- Pemetaan: `New`/`Scoring Pending` → `Intake`+`Scoring`; `Need Clarification` → `Intake`+`Need Clarification`; `Manual Review Required` → `Intake`+`Manual Review`; `Pending Assignment` → `Awaiting Assignment`; `Ready` → `Submitted`; `Closed-Win` → `Won`; `Handover Complete` → `Handed Over`.
- `In Progress` berpindah otomatis dari `Assigned` saat SA pertama mencatat activity log atau subtask `in_progress`.
- `Submitted` = paket proposal diserahkan ke Sales/Product; syarat PropTek, BOQ, Mandays minimal `Reviewed`. Boleh kembali ke `In Progress` bila customer meminta revisi.
- `Handed Over` tetap hanya lewat `POST /projects/{id}/handover` (spec issue #76).
- `Closed` read-only; selama belum `Closed`, subtask dan activity log tetap boleh ditambah. `Lost` juga read-only dan wajib punya `lost_reason`.
- `On Hold` menghentikan timer SLA DQ; lanjut mengembalikan ke `previous_status`. `Cancelled` tidak ada karena `Lost` sudah mencakupnya.
- Hak: `Submitted` oleh SA ditugaskan/Lead_SA/`is_admin`; `Won` oleh Sales/Product/Lead_SA/`is_admin`; `Lost` dan `Closed` oleh Lead_SA/`is_admin`; jeda dan lanjut oleh Lead_SA/`is_admin`/Sales/Product; membuka kembali `Closed`/`Lost` hanya `is_admin`, dengan alasan di audit log. Sales PIC tidak lagi boleh mengubah status selain `Won` dan jeda.

## Asumsi default (belum dikonfirmasi eksplisit, ubah bila keliru)

- `On Hold` hanya dari `Awaiting Assignment` sampai `Submitted` (sebelum `Won`).
- `Lost` boleh dari status mana pun sebelum `Handed Over` (termasuk `Won`, sama seperti `Closed-Win` → `Lost` sebelumnya).
- `lead_sa` boleh kosong saat `Intake` dan wajib sejak `Assigned`.

## Konsekuensi

- Menyentuh CheckConstraint, state machine `workflow.py`, `scoring_engine.apply_threshold`, notifikasi, dashboard, dan frontend. Migration memetakan data lama sesuai tabel (tidak ada data produksi; satu langkah, tetap dengan test upgrade, downgrade, dan constraint).
- Enum ini ditetapkan sengaja; jangan "dirapikan" kembali menjadi satu daftar campuran.
