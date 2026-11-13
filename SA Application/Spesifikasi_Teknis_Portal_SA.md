# Spesifikasi Teknis & Alur Kerja Portal Solutions Architect (SA)

Dokumen ini merangkum spesifikasi teknis, alur kerja (workflow), struktur basis data, serta integrasi layanan eksternal untuk Portal SA (pengganti Redmine) yang diakses dalam bentuk *Progressive Web App* (PWA).

> **Visualisasi alur bisnis:** lihat [`Alur_Bisnis_Portal_SA.md`](Alur_Bisnis_Portal_SA.md) untuk diagram Mermaid keempat alur kerja, aktor/peran, integrasi, dan ER entitas inti.

---

## 1. Konsep Utama Aplikasi
Portal ini pertama-tama adalah **aplikasi ticketing / project tracker khusus untuk SA** (mirip Jira, tetapi dikustomisasi untuk alur kerja SA): melacak project, beban kerja SA, dan output SA di Google Drive. Satu project diperlakukan seperti satu *ticket* yang memuat subtask, dokumen, komentar, dan log aktivitas. Portal ini hanya untuk tim SA dan pihak yang membuat atau memantau project SA; bukan CRM atau tool manajemen project umum.

Portal menggabungkan manajemen project (request ke SA) dan manajemen utilisasi/aktivitas harian (Time Tracking & Activity Log) ke dalam satu platform yang ditenagai oleh **Google Workspace (GDrive, Gmail, GCalendar)** dan **Google Gemini AI**.

---

## 2. Peran, Hak, dan Alur Kerja

### 2.0 Peran dan hak

> **Keputusan pemilik produk 2026-11-13.** Lihat [`docs/adr/0012-role-fungsional-tunggal-dan-flag-admin.md`](../docs/adr/0012-role-fungsional-tunggal-dan-flag-admin.md) dan [`docs/adr/0014-orang-per-project-dan-multi-sa.md`](../docs/adr/0014-orang-per-project-dan-multi-sa.md).

Setiap user punya **tepat satu role fungsional** dan boleh sekaligus memiliki flag **`is_admin`** (kemampuan, bukan pekerjaan).

| Role | Fungsi |
| :--- | :--- |
| `Sales` | Pembuat dan pemantau project. Opsional per project. |
| `Product` | Setara `Sales` dalam hak di portal (hanya beda tim). Selalu ada di setiap project. |
| `SA` | Mengerjakan project: dokumen, subtask, activity log. Boleh ditugaskan ke project. |
| `Lead_SA` | Memimpin SA: menugaskan dan mengganti orang di project, membuat subtask, memantau beban. Boleh juga ditugaskan sebagai SA. Boleh membuat project. |
| `is_admin` (flag) | Kelola user, jalankan `POST /sla/process`, membuka kembali `Closed` dan `Lost`, mengganti orang di project, hak penuh atas semua project. Selalu menempel pada satu role fungsional (tidak ada Admin murni). |

Ringkasan hak tulis (aturan baca: **semua proyek dapat dibaca semua pengguna terautentikasi**, lihat Flow 3):

| Aksi | Sales / Product | SA (ditugaskan) | Lead_SA | `is_admin` |
| :--- | :---: | :---: | :---: | :---: |
| Membuat project | ✓ | ✗ | ✓ | ✓ |
| Edit data intake dan Kuesioner kualifikasi | ✓ (`created_by` / `sales_pic` / `product_pic` project itu) | ✗ | ✓ | ✓ |
| Mengisi DQ Number | ✓ (`sales_pic` / `product_pic`) | ✗ | ✓ | ✓ |
| Menulis activity log, mengunggah dokumen, mengelola status dokumen dan Requirement | ✗ | ✓ | ✓ | ✓ |
| Membuat, mengubah, menyelesaikan subtask | ✗ | ✓ | ✓ | ✓ |
| Menulis komentar project | ✓ (yang ditugaskan di project) | ✓ | ✓ | ✓ |
| Menambah, melepas, mengganti orang di project | ✗ | ✗ | ✓ | ✓ |

Hak perpindahan status ada di bagian *Siklus status* di bawah.

### Alur umum satu project
1. Project dibuat oleh `Sales`, `Product`, `Lead_SA`, atau `is_admin`. Gate BANT berlaku untuk **siapa pun** pembuatnya.
2. `Lead_SA` menugaskan SA dan membuat subtask yang dibutuhkan; SA juga boleh membuat subtask.
3. SA mengerjakan project; output disimpan di Google Drive dan ditautkan pada project (Documents).
4. Setelah deliverable diserahkan, SA tetap memantau project dan subtask baru boleh muncul sampai `Lead_SA`/Admin menutup project (`Closed`).

### Siklus status

> **Keputusan 2026-11-13** (menggantikan enum status lama; lihat [`docs/adr/0013-model-status-dua-field.md`](../docs/adr/0013-model-status-dua-field.md)). Status lama dipetakan: `New`/`Scoring Pending`/`Need Clarification`/`Manual Review Required` → `Intake` + `qualification_state`; `Pending Assignment` → `Awaiting Assignment`; `Ready` → `Submitted`; `Closed-Win` → `Won`; `Handover Complete` → `Handed Over`.

`status` (siklus kerja):

```
Intake → Awaiting Assignment → Assigned → In Progress → Submitted → Won → Handed Over → Closed
                                                 ↑___________|            (Submitted → In Progress: revisi customer)
Status samping: Lost (dari status mana pun sebelum Handed Over) dan On Hold (jeda)
```

`qualification_state` (hanya bermakna saat `status = Intake`; berikutnya tetap `Qualified`): `Scoring`, `Need Clarification`, `Manual Review`, `Qualified`.

| Transisi | Pemicu | Siapa |
| :--- | :--- | :--- |
| `Intake` → `Awaiting Assignment` | `qualification_state` menjadi `Qualified` (BANT ≥ 60%, atau override Lead_SA) | sistem |
| `Awaiting Assignment` → `Assigned` | Penugasan SA | `Lead_SA` / `is_admin` |
| `Assigned` → `In Progress` | Activity log atau subtask `in_progress` pertama oleh SA | sistem (otomatis) |
| `Assigned` / `In Progress` → `Submitted` | Paket proposal diserahkan ke Sales/Product; syarat: PropTek, BOQ, Mandays minimal `Reviewed` | SA ditugaskan / `Lead_SA` / `is_admin` |
| `Submitted` → `In Progress` | Customer meminta revisi | SA ditugaskan / `Lead_SA` / `is_admin` |
| `Submitted` → `Won` | PO rilis / menang | `Sales`, `Product`, `Lead_SA`, `is_admin` |
| `Won` → `Handed Over` | **Hanya** lewat `POST /projects/{id}/handover` (Flow 4) | SA ditugaskan / `Lead_SA` / `is_admin` |
| `Handed Over` → `Closed` | Project ditutup; setelah ini read-only | `Lead_SA` / `is_admin` |
| (sebelum `Handed Over`) → `Lost` | Alasan (`lost_reason`) wajib | `Lead_SA` / `is_admin` |
| `Awaiting Assignment`..`Submitted` ↔ `On Hold` | Jeda dan lanjut; SLA DQ ikut berhenti selama `On Hold`; lanjut mengembalikan ke status sebelumnya (`previous_status`) | `Lead_SA`, `is_admin`, `Sales`, `Product` |
| `Closed` / `Lost` → status sebelumnya | Buka kembali; alasan tercatat di audit log | `is_admin` saja |

Selama belum `Closed`, subtask dan activity log tetap boleh ditambah (termasuk setelah `Handed Over`). `Closed`, dan `Lost`, bersifat read-only.

### Flow 1: Pre-Sales Request & AI Scoring
1. **Input pembuat:** Sales, Product, atau Lead_SA masuk ke portal, mengisi form data customer, estimasi awal, mengisi *Kuesioner kualifikasi*, dan mengunggah dokumen referensi (MoM / RFP). Pembuat mengisi kuesioner, apa pun perannya.

   > **Catatan kuesioner (keputusan grill 2026-11-10):** *Kuesioner kualifikasi* adalah kumpulan pertanyaan faktual terstruktur (set tetap, bertanda `schema_version`) yang menjadi evidence skor BANT. Skor dihitung oleh backend (rubrik deterministik), bukan dinilai sendiri oleh pembuat; jika ada dokumen, skor AI digabung per kriteria dengan nilai tertinggi. Lihat [`docs/adr/0010-bant-score-computed-in-backend.md`](../docs/adr/0010-bant-score-computed-in-backend.md).
2. **AI Processing:** File dianalisis oleh Gemini AI (Multimodal) untuk mengekstrak spesifikasi, memvalidasi matriks BANT (Budget, Authority, Need, Timeline), menentukan *Priority*, *Use Case Tagging*, serta menyusun *Pre-filled OLA/Mandays* internal untuk SA.

   > **Catatan scope (keputusan grill 2026-10-21):** penyusunan *Pre-filled OLA/Mandays* **ditunda keluar dari MVP** (backlog pasca-MVP). Deskripsi fitur ini sengaja dipertahankan di spec sebagai *intent*; implementasinya di luar scope MVP.
3. **Threshold Gatekeeper (berlaku untuk semua pembuat):**
   - Jika *BANT Score* < 60%: `qualification_state = Need Clarification`. Notifikasi ke `created_by`, `product_pic`, dan `sales_pic` (bila ada); salah satu dari mereka atau Lead_SA boleh memperbaiki kuesioner untuk dinilai ulang.
   - Jika *BANT Score* >= 60%: Lolos (`Qualified`, `status = Awaiting Assignment`). Notifikasi *New Opportunity* dikirim ke Lead SA untuk penugasan (*Assignment*).

### Flow 2: Dokumen, SLA DQ Number, dan Gating System
1. **Work Stream SA:** Normalnya SA mulai bekerja setelah DQ Number diisi, sama seperti informasi lain yang diisi Sales atau Product. Pada kasus urgent yang jarang terjadi, SA yang ditugaskan boleh bekerja sebelum DQ terisi (prerogatif); portal tidak memblokirnya. SA mengerjakan *Technical Proposal*, *BOQ (AWS Calc)*, dan *Mandays* di folder `Solutions`. (Dokumen HLD ditunda hingga `Won`.)
2. **DQ Number Gating (SLA 5 Hari):** DQ Number diisi oleh Sales, Product, atau Lead_SA project itu.
   - **< 5 Hari:** Jika DQ sudah diinput, saat dokumen SA berstatus `Reviewed`, folder `Solutions` **terbuka otomatis** (Viewer) untuk Sales dan Product project itu beserta notifikasi email.
   - **> 5 Hari:** Jika DQ belum diinput, folder `Solutions` **terkunci (Hidden/Locked)** bagi Sales dan Product. Sistem mengirim reminder H+3 ke Sales dan Product project itu (Product saja bila tidak ada Sales) dan eskalasi H+5 ke `lead_sa` project itu dan semua user dengan `is_admin`.
   - Selama `status = On Hold`, timer SLA berhenti.

   > **Catatan divergensi (keputusan 2026-11-10, issue #77):** (1) Peran "Sales Manager" **tidak ada** di portal; penerima eskalasi H+5 adalah `lead_sa` project itu dan Admin, plus pemberitahuan ke Sales dan Product bahwa folder Solutions dikunci. (2) Eskalasi dikirim **sekali** per proyek. Bila penguncian folder di Drive gagal, hanya penguncian yang dicoba lagi pada siklus berikutnya (tiap jam). (3) Penguncian/pembukaan otomatis dicatat di audit log dengan pelaku kosong (aksi sistem; tidak ada user sistem). (4) Bila pembukaan kunci gagal saat DQ diinput, timer tetap berhenti dan pembukaan dicoba lagi pada siklus berikutnya sampai berhasil. (5) **Reassign SA:** timer SLA **berlanjut** (tidak direset); akses Editor folder Drive SA lama dicabut dan SA baru diberi; subtask tidak otomatis dipindahkan; reassign dari `Awaiting Assignment` menjalankan alur assign penuh (timer SLA + provisioning folder).
   >
   > **Pembaruan 2026-11-13:** peran Product ditambahkan dan akses Drive mengikuti orang yang sedang ditugaskan (lihat §4.A). Mengganti `sales_pic` / `product_pic` mencabut akses lama dan memberi akses baru. Aturan reassign SA di (5) berlaku juga untuk SA tambahan.

### Flow 3: Activity Mapping & Project Story (Aplikasi 2)
1. **GCalendar Sync:** Sistem menarik data acara (*events*) dari Google Calendar SA secara *real-time*.
2. **Mapping oleh SA:** Melalui Portal, SA memetakan kalender ke dalam work item *Subtask* (misal: "Meeting Pre-Implementation", "Create HLD"). *Subtask* adalah work item yang bisa ditugaskan, berbeda dari `ActivityCategory` (taksonomi pengelompokan log) — lihat catatan pada struktur `ActivityLogs`.
3. **AI Activity Polish:** Saat SA mengetik catatan rapat (*notes*) secara kasual di Portal, Gemini AI merapikan teks tersebut menjadi **Poin Diskusi & Action Items** terstruktur.
4. **Project Story:** Log aktivitas ini dimasukkan ke dalam *Project Story* global yang dapat dibaca **semua pengguna** (keputusan 2026-11-10, lihat catatan hak akses di bawah), termasuk *Backup SA* untuk *handover* saat SA cuti.

   > **Hak akses proyek (keputusan pemilik produk 2026-11-10):** **semua proyek dapat dilihat oleh semua pengguna terautentikasi**, tanpa batas (detail, daftar, dokumen, Project Story beserta ringkasan AI, kolaborator, subtask, hasil BANT, SLA). Hak **tulis** saja yang dibatasi menurut tabel hak di §2.0 dan aturan tiap aksi. Link dokumen folder `Solutions` bagi Sales dan Product tetap mengikuti gating DQ Flow 2 dan izin Drive. Story memuat catatan rapat mentah dan versi polish AI; keterbukaannya disengaja. Lihat [`docs/adr/0011-baca-proyek-terbuka-tulis-dibatasi.md`](../docs/adr/0011-baca-proyek-terbuka-tulis-dibatasi.md).

   > **Catatan pemetaan (keputusan grill 2026-10-21):** *Backup SA* **bukan** peran atau entity baru — ia dipenuhi oleh fitur **Project Collaboration**: *collaborator* (terutama *contributor*, yang boleh menulis activity log) menggantikan SA utama saat berhalangan. Karena membaca kini terbuka untuk semua, yang dibedakan collaborator hanyalah hak tulis. Lihat [`docs/adr/0002-backup-sa-via-project-collaboration.md`](../docs/adr/0002-backup-sa-via-project-collaboration.md). **Co-SA** (SA tambahan, hak setara SA utama) berbeda dari collaborator; lihat §2.5.

### Flow 4: Post-Sales & PMO Handover
1. **Won Trigger:** Saat proyek berstatus `Won` (PO Rilis), semua SA project itu menerima notifikasi wajib membuat **HLD (High Level Document)**.
2. **RAG Template Recommendation:** Fitur AI (RAG) merekomendasikan *template* / referensi dokumen dari proyek serupa sebelumnya.
3. **Handover (dipicu manual):** Setelah HLD berstatus *Final*, SA yang ditugaskan (utama atau tambahan), Lead SA, atau Admin memicu *handover* dari portal. Sistem membuat folder `Final_Deliverables` (di dalam `Solutions`), membagikan aksesnya sebagai *Viewer* kepada **PMO Lead** dan **Delivery Lead** beserta notifikasi *handover* untuk penyusunan *Project Charter* dan LLD, lalu mengubah status proyek menjadi `Handed Over`.
4. **Penutupan:** SA tetap memantau project setelah `Handed Over`; subtask baru boleh muncul. `Lead_SA` atau Admin menutup project (`Closed`) saat sudah benar-benar selesai.

   > **Catatan divergensi (keputusan 2026-11-10, issue #76):** (1) Handover **tidak otomatis** setelah HLD disubmit; ia dipicu manual dan selalu memeriksa prasyarat (status `Won`, HLD `Final`, email PMO/Delivery terisi, folder Drive ada). (2) `Handed Over` **hanya** dapat dicapai lewat aksi handover itu, tidak lewat perubahan status biasa. (3) Nama folder di Drive adalah `Final_Deliverables` (bukan `03_Final_Deliverables`). (4) PMO/Delivery Lead tidak wajib punya akun portal: yang punya akun menerima notifikasi in-app dan email, yang tidak punya menerima **email langsung**. (5) Bila Drive gagal setelah 3 kali retry, status proyek tidak berubah, SA dan Lead SA diberi notifikasi, dan handover dapat dicoba ulang; tidak ada status "Handover Failed".

### 2.5 Pelacakan project dan workload (lintas flow)

> **Keputusan 2026-11-13.** Lihat [`docs/adr/0014-orang-per-project-dan-multi-sa.md`](../docs/adr/0014-orang-per-project-dan-multi-sa.md).

- **Multi-SA.** Satu project boleh ditugaskan ke beberapa SA: satu **SA utama** (`assigned_sa`, penanggung jawab) dan nol atau lebih **SA tambahan** (tabel `ProjectAssignments`). SA tambahan punya hak setara SA utama (log, dokumen, status dokumen, Requirement, `Submitted`, handover, Drive Editor). Setelah `Assigned`, project harus punya minimal satu SA; bila SA utama dilepas dan masih ada SA tambahan, Lead_SA memilih SA utama baru. Hanya Lead_SA atau Admin yang mengatur penugasan. Lead_SA boleh ditugaskan sebagai SA.
- **Subtask** tetap **satu assignee**, yaitu salah satu SA project atau Lead_SA. Pekerjaan yang dikerjakan dua orang dipecah menjadi dua subtask. Subtask punya `description`, `due_date`, dan estimasi jam (opsional).
- **Komentar.** Setiap project punya thread komentar (`ProjectComments`) yang ditulis orang yang ditugaskan di project (Sales, Product, Lead_SA, SA utama/tambahan, collaborator) dan Admin, dan dibaca semua pengguna. Terpisah dari Project Story (log aktivitas SA). Orang yang ditugaskan diberi notifikasi komentar baru.
- **Tampilan manajemen untuk Lead_SA:** (1) beban tiap SA (subtask aktif, project aktif, jam terlog minggu ini), (2) subtask dan project yang lewat atau mendekati due date, (3) project yang terlalu lama di satu status, (4) project yang butuh aksi (belum di-assign, DQ kosong, `Need Clarification`). Project dengan banyak SA dihitung untuk tiap SA. Perencanaan kapasitas berbasis kalender ditunda pasca-MVP.
- **Untuk semua peran:** daftar "tugas saya" lintas project, dashboard *requester* bersama untuk Sales dan Product, dan filter "Hanya proyek saya" yang cocok bila user adalah `created_by`, `sales_pic`, `product_pic`, `lead_sa`, SA utama/tambahan, atau collaborator.

---

## 3. Struktur Database & Field

### A. Tabel `Projects` (Opportunity Data)
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `id_project` | String | PK, Generate dari sistem |
| `project_name` | String | Nama proyek dari input pembuat |
| `customer_name` | String | Nama perusahaan client |
| `dq_number` | String | Input belakangan oleh Sales, Product, atau Lead_SA; syarat rilis dokumen ke Sales/Product |
| `created_by` | UUID | Relasi ke `Users`: pembuat project (tidak berubah) |
| `product_pic` | UUID | Relasi ke `Users`: wajib; Product yang bertanggung jawab; bisa diganti Lead_SA/Admin |
| `sales_pic` | UUID | Relasi ke `Users`: **opsional** (project boleh tanpa Sales); bisa diganti Lead_SA/Admin |
| `lead_sa` | UUID | Relasi ke `Users`: Lead_SA yang memimpin project; wajib sejak `Assigned`; bisa diganti Lead_SA/Admin |
| `assigned_sa` | UUID | Relasi ke `Users`: SA utama (penanggung jawab); SA tambahan di `ProjectAssignments` |
| `status` | Enum | Intake, Awaiting Assignment, Assigned, In Progress, Submitted, Won, Handed Over, Closed, Lost, On Hold |
| `qualification_state` | Enum | Scoring, Need Clarification, Manual Review, Qualified (selain `Intake`: `Qualified`) |
| `previous_status` | Enum | Status sebelum `On Hold` atau `Lost`; dipakai saat lanjut atau dibuka kembali |
| `lost_reason` | Text | Wajib saat `Lost` |
| `target_submit` | Date | Tanggal batas pengajuan proposal |
| `bant_score` | Integer | 0-100% dihitung backend (rubrik + AI) |
| `use_case_tags` | JSON | Misal: ["App Mod", "DB Migration"] |
| `gdrive_folder_id` | String | ID Master Folder proyek di GDrive |

> **Catatan enum `status` (keputusan grill 2026-11-13, menggantikan catatan 2026-10-21/2026-11-10):** set status memakai model dua field di atas (siklus kerja + `qualification_state`). Status `Pending DQ` tetap **tidak ada**: DQ yang belum diisi cukup ditandai `dq_number` kosong. Lihat [`docs/adr/0013-model-status-dua-field.md`](../docs/adr/0013-model-status-dua-field.md); ADR 0001 digantikan.

### A2. Tabel `Users`
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `id` | UUID | PK |
| `email`, `name`, `google_id` | String | Identitas Google OAuth |
| `role` | Enum | `Sales`, `Product`, `SA`, `Lead_SA` (wajib) |
| `is_admin` | Boolean | Kemampuan administrasi; default `false` |

### A3. Tabel `ProjectAssignments` (SA tambahan)
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `id_project` | String | FK ke `Projects` |
| `user_id` | UUID | FK ke `Users` (role `SA` atau `Lead_SA`) |
| `added_by` | UUID | FK ke `Users` (Lead_SA/Admin) |
| `created_at` | Timestamp | |

Unik pada (`id_project`, `user_id`). SA utama tetap `Projects.assigned_sa` dan tidak diulang di tabel ini.

### A4. Tabel `Subtasks`
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `id_subtask` | String | PK |
| `id_project` | String | FK ke `Projects` |
| `title` | String | Judul work item |
| `description` | Text | Opsional |
| `assigned_sa` | UUID | Satu assignee: SA project (utama atau tambahan) atau Lead_SA |
| `status` | Enum | open, in_progress, done |
| `due_date` | Date | Opsional |
| `estimate_hours` | Decimal | Opsional |

### A5. Tabel `ProjectComments`
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `id_comment` | String | PK |
| `id_project` | String | FK ke `Projects` |
| `author_id` | UUID | FK ke `Users` |
| `body` | Text | Isi komentar |
| `created_at` | Timestamp | |

### B. Tabel `Documents` (Deliverables Tracker)
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `id_doc` | String | PK |
| `id_project` | String | FK ke tabel `Projects` |
| `doc_type` | Enum | MoM, RFP, PropTek, BOQ, Mandays, HLD, Requirement |
| `status` | Enum | Draft, Reviewed, Final |
| `gdrive_link` | String | URL Google Drive / File ID |
| `folder_type` | Enum | Inventory, Diagram, Solutions |

> **Catatan `Requirement` (keputusan grill 2026-11-10):** dokumen `Requirement` adalah konten turunan AI (daftar butir terstruktur dari kuesioner + teks MoM/RFP), bukan file Drive. Hanya tipe ini yang boleh memiliki `gdrive_link` kosong, dan `folder_type`-nya `Inventory`. Lihat [`docs/adr/0004-requirement-override-blocks-silent-resummarize.md`](../docs/adr/0004-requirement-override-blocks-silent-resummarize.md).

### C. Tabel `ActivityLogs` (Project Story & Mapping)
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `id_log` | String | PK |
| `id_project` | String | FK ke tabel `Projects` |
| `sa_id` | UUID | Relasi ke tabel `Users` (Pembuat log) |
| `activity_category`| Enum | `ActivityCategory` — taksonomi untuk mengelompokkan log aktivitas (lihat catatan di bawah). **Bukan** referensi ke work item `Subtask`. |
| `id_subtask` | String | FK opsional ke work item `Subtask` yang dituju log ini (mis. "Create HLD", "Peer Review") |
| `gcal_event_id` | String | ID event dari Google Calendar |
| `duration_hours` | Decimal | Durasi aktivitas dalam jam |
| `raw_notes` | Text | Catatan mentah dari SA |
| `ai_polished_notes`| JSON | Hasil AI (Summary & Action Items) |
| `created_at` | Timestamp| Waktu log dibuat |

> **Catatan `Subtask` vs `ActivityCategory` (keputusan grill 2026-10-21):** dua konsep yang sebelumnya tercampur dipisahkan eksplisit. Lihat [`GLOSSARY.md`](../GLOSSARY.md).
> - **`Subtask`** = *work item* yang bisa ditugaskan dalam sebuah proyek, punya status `open → in_progress → done` (contoh: "Create HLD", "Peer Review"). Ini yang dimaksud "Subtask Permanen" di Flow 3. Sebuah `ActivityLog` boleh menunjuk ke satu `Subtask` lewat FK opsional `id_subtask`.
> - **`ActivityCategory`** = *taksonomi* untuk mengelompokkan `ActivityLog`, bukan work item yang ditugaskan. Enum kode (ground truth): `Assessment, Internal Meeting, Customer Meeting, Principal Meeting, Commercial Document, Technical Document, Document Review, Training, Self-Lab, Self-Learning, Exam, Internal Presentation, External Presentation`.

---

## 4. Integrasi Layanan (Google Workspace & AI)

### A. Google Drive API
* **Fungsi:** Auto-provisioning struktur folder saat proyek ditugaskan (Format: `[Nama Customer] > [Nama Proyek] > Inventory / Diagram / Solutions`).
* **Permission Logic** (keputusan 2026-11-13, lihat [`docs/adr/0015-matriks-akses-drive-dan-gate-dq.md`](../docs/adr/0015-matriks-akses-drive-dan-gate-dq.md)). Akses mengikuti **orang yang sedang ditugaskan** di project; saat orang diganti, akses lama dicabut dan akses baru diberikan.

| Folder | SA, Lead_SA (ditugaskan) | Sales, Product (ditugaskan) | PMO / Delivery Lead |
| :--- | :--- | :--- | :--- |
| `Inventory` | Editor | Viewer | tidak ada |
| `Diagram` | Editor | tidak ada | tidak ada |
| `Solutions` | Editor | tidak ada; **Viewer setelah `dq_number` terisi** | tidak ada |
| `Final_Deliverables` | Editor | tidak ada | Viewer saat handover |

  Role selain itu tidak punya akses Drive. PMO/Delivery Lead (tanpa akun portal) adalah satu-satunya pengecualian, hanya lewat aksi handover (bukan saat status menjadi `Won`; lihat catatan Flow 4).

### B. Google Calendar API
* **Fungsi:** Webhook / API Fetch untuk menarik blok jadwal per hari tiap SA.
* **Flow:** Data event di-render pada UI Portal SA, lalu SA mengeklik event tersebut untuk di-assign ke `id_project` tertentu beserta estimasi *spent time*.

### C. Gmail API / Email Gateway
* **Fungsi:** Notifikasi *trigger-based* otomatis menggunakan format template HTML tepercaya.
* **Trigger Utama:**
  * Penugasan Lead SA (Internal SA).
  * Update Parsial Dokumen ke Sales dan Product.
  * Peringatan / Eskalasi SLA DQ Number (5 hari).
  * *Handover Email* pasca-Win ke tim PMO & Delivery.

### D. Google Gemini AI (Vertex AI / AI Studio)
* **Multimodal Parsing (Document to JSON):** Mengekstrak MoM/RFP (PDF/Doc) ke parameter BANT (Budget, Authority, Need, Timeline).
* **Text Structuring (Activity Log):** Membersihkan *raw_notes* menjadi `Action Items` dan `Discussion Points`.
* **RAG (Retrieval-Augmented Generation):** Melakukan *semantic search* pada metadata `use_case_tags` dan histori dari folder *Won* untuk merekomendasikan berkas (PropTek/HLD) masa lalu kepada SA sebagai referensi.
