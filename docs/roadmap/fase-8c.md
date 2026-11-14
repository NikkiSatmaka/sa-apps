<!-- Bagian dari docs/ROADMAP.md (indeks). Checkbox fase ini di-update di sini. -->

## Fase 8C — Model Status (fitur 14)

**Tujuan:** menerapkan [ADR 0013](../adr/0013-model-status-dua-field.md): `status` siklus kerja + `qualification_state`. Dikerjakan setelah 8A dan 8B karena menyentuh `workflow.py` dan `_ATURAN` yang sama.

- [ ] 8C.1 Migration + model: enum `status` baru, `qualification_state`, `previous_status`, `lost_reason`; pemetaan data lama; test upgrade, downgrade, dan constraint.
- [ ] 8C.2 State machine dan hak per transisi sesuai tabel spec §2.0 (`Submitted` butuh PropTek/BOQ/Mandays ≥ `Reviewed`; `Handed Over` hanya lewat handover; `Closed`/`Lost` read-only; buka kembali hanya `is_admin`).
- [x] 8C.3 `In Progress` otomatis dari activity log atau subtask `in_progress` pertama.
- [x] 8C.4 `On Hold` dan lanjut; timer SLA berhenti selama `On Hold`.
- [ ] 8C.5 `scoring_engine.apply_threshold` dan notifikasi memakai `qualification_state`; `Won` memicu notifikasi HLD ke semua SA; `Closed` membuat subtask dan log read-only.
- [ ] 8C.6 Frontend: badge, filter, dan aksi status mengikuti nama dan hak baru.

**Kriteria selesai:** tidak ada nama status lama di kode atau UI; semua transisi di spec §2.0 punya test.
