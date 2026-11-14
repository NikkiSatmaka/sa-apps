# Worktree dan delegasi ke sub-agent

Dipointer dari `AGENTS.md`. Berlaku untuk **agen utama** (orchestrator). Sub-agent implementasi menerima brief dan tidak perlu membaca dokumen ini.

## Worktree (wajib untuk agen)

Checkout utama di root repo milik manusia, dan beberapa agen bisa berjalan paralel di repo yang sama. Kalau semua berbagi satu working tree, satu `git checkout` dari pihak lain diam-diam memindahkan commit Anda ke branch yang salah. Karena itu, setiap agen mengerjakan setiap branch di **git worktree** sendiri. Di checkout utama, agen hanya membaca. Edit, `checkout`, dan commit dilakukan di worktree.

- Buat worktree dari `main` terbaru di `.worktrees/<slug>` (folder ini di-ignore git), lalu jalankan semua perintah dengan cwd di worktree itu:
  ```bash
  git fetch origin
  git worktree add --no-track -b <type>/<slug> .worktrees/<slug> origin/main
  ```
  `--no-track` wajib. Tanpa itu, upstream branch baru menjadi `origin/main`, sehingga `git push` mengarah ke `main` dan ditolak pre-push hook. Push pertama: `git push -u origin <type>/<slug>`.
  Untuk melanjutkan branch yang sudah ada (mis. revisi review PR): `git worktree add .worktrees/<slug> <type>/<slug>`.
- File untracked tidak ikut ke worktree. Jalankan `uv sync` di `backend/` dan `pnpm install` di `frontend/`. Bila perlu, salin `.env`, `backend/.env`, dan `frontend/.env.local` dari checkout utama, tapi jangan di-commit.
- Stack Docker Compose lokal dan DB-nya dipakai bersama oleh semua branch. Verifikasi backend dari worktree lewat pytest, atau panggil app in-process (`httpx.ASGITransport`) ke DB yang sedang jalan. Minta persetujuan user sebelum rebuild atau restart stack: DB mungkin sudah di-migrate oleh branch lain, sehingga `alembic upgrade head` di branch Anda gagal.
- Setelah PR dibuat dan pekerjaan selesai, hapus worktree-nya dengan `git worktree remove .worktrees/<slug>`. Branch-nya tetap ada untuk PR.

---

## Delegasi implementasi ke sub-agent (wajib)

Konteks agen utama terbatas dan cepat penuh bila ia sendiri membaca kode, menulis test, dan menjalankan suite. Karena itu **setiap tiket implementasi dikerjakan oleh satu sub-agent** (agen terdelegasi dengan context window baru), sedangkan agen utama mengurus alur dan verifikasi. Aturan ini berlaku untuk semua sesi dan harness.

**Agen utama:**

1. Membaca tiket, ADR, dan spec yang relevan secukupnya untuk menulis brief (bukan untuk mengerjakan tiketnya).
2. Membuat worktree dan branch dari `origin/main` (bagian Worktree di atas), lalu mengirim **satu brief lengkap** ke sub-agent.
3. Setelah sub-agent selesai: memeriksa diff dan ringkasannya, menjalankan sendiri verification gate yang relevan bila ringkasan tidak meyakinkan, membuka PR (deskripsi sesuai template, termasuk tabel perilaku → test), memantau CI, lalu menghapus worktree.
4. Menandai dengan jelas keputusan desain yang diambil sub-agent di luar tiket di deskripsi PR, dan menanyakan ke user bila keputusan itu berdampak luas.

**Brief ke sub-agent harus memuat** (sub-agent tidak melihat percakapan sebelumnya dan tidak bisa bertanya ke user di tengah jalan):

- Nomor dan isi tiket (`gh issue view`), tiket induk, dan blocking-nya; path ADR dan bagian spec yang menjadi ground truth.
- Path worktree dan nama branch; semua perintah dijalankan dengan cwd di worktree itu, dan sub-agent tidak boleh menyentuh checkout utama.
- Aturan `AGENTS.md` yang wajib: test-first dengan **commit merah terpisah** sebelum implementasi, test migration untuk perubahan schema, Conventional Commits, stage file spesifik, tidak ada commit ke `main`, tanpa `--no-verify`.
- Cara menjalankan verifikasi: Postgres 18 sementara (`backend/README.md`, jangan menyentuh stack Docker Compose bersama), `uv run pytest` dan `-m integration`, `pnpm test` / `tsc --noEmit` / `pnpm build`, serta gerbang cakupan. Container sementara harus dihentikan di akhir.
- Batas lingkup: apa yang termasuk tiket dan apa yang bukan (tiket lain yang menyentuh area sama), serta larangan menurunkan ambang cakupan, menambah `skip`/`xfail`, atau melemahkan assertion.
- Bila ada keputusan yang tidak ditentukan tiket, ADR, atau spec: pilih opsi paling konservatif dan **catat** di laporan akhir, jangan mengarang perilaku produk.
- Format laporan akhir: ringkasan perubahan, daftar test baru beserta perilaku yang dilindungi, test lama yang diubah dan alasannya, hasil verifikasi (angka), hal yang belum terverifikasi, dan keputusan di luar tiket.

**Sub-agent tidak boleh:** push, membuka PR, mengubah issue, menyentuh stack Compose atau database bersama, atau mengubah `main`. Itu tugas agen utama setelah laporan diterima.

**Pengecualian (boleh dikerjakan agen utama sendiri):** perubahan dokumentasi atau konfigurasi tanpa perilaku, koreksi satu-dua baris yang sudah jelas, dan pekerjaan yang inti kesulitannya adalah **keputusan desain bersama user** (grill, penentuan ADR/spec). Bila ragu apakah tiket butuh keputusan di tengah jalan, tanyakan ke user sebelum mendelegasikan, bukan sesudahnya.

**Beberapa tiket:** tiket yang saling bergantung (lihat `blocked by`) dikerjakan berurutan dan berbasis `main` setelah PR sebelumnya digabung. Tiket yang independen boleh dikerjakan paralel, masing-masing dengan worktree, branch, dan sub-agent sendiri.
