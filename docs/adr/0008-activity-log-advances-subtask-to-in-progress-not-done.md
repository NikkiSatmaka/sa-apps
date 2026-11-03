# Mencatat activity log memajukan subtask ke `in_progress`, tidak pernah ke `done`

Link `ActivityLog.id_subtask` semula murni informasional (mencatat aktivitas terhadap subtask tidak mengubah statusnya). Untuk Fase 4 kami memberinya efek: mencatat activity log pertama terhadap subtask ber-status `open` memindahkannya ke `in_progress`, dengan validasi bahwa `id_subtask` memang milik `id_project` yang sama. Transisi ke `done` **tidak** disimpulkan dari adanya log — hanya SA yang tahu kapan sebuah work item benar-benar tuntas, jadi penutupan selalu aksi eksplisit (tombol "Tandai selesai" di UI, atau `PATCH /status`).

## Considered Options

- **Tetap informasional, status selalu manual** — ditolak: tidak memenuhi kriteria selesai Fase 4 ("SA mencatat aktivitas terhadap salah satunya, dan subtask berubah status").
- **Penuh: aktivitas → `in_progress`, dan sediakan jalan auto/semi-auto ke `done`** — ditolak: "selesai" tidak bisa disimpulkan dari adanya aktivitas; menebak penutupan menimbulkan subtask yang keliru ditutup.
- **Hanya `open → in_progress` otomatis; `done` eksplisit** — dipilih: murah dan akurat (ada log ⇒ kerja sudah dimulai) tanpa menebak kapan kerja selesai.

## Consequences

- Perilaku link berubah dari yang di-assert test lama (`TestActivityLogSubtaskLink`: membuat log dengan `id_subtask` TIDAK mengubah status) — test itu harus diperbarui agar mencerminkan transisi `open → in_progress`.
- Jalur activity logging kini menyentuh dan memvalidasi subtask: menambah query untuk memastikan `id_subtask` ∈ `id_project` dan memajukan status bila masih `open`. Idempoten pada aktivitas berikutnya (sudah `in_progress`/`done` tidak diubah; `done` tidak pernah dimundurkan oleh aktivitas).
