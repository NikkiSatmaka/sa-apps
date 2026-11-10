# Spesifikasi Teknis & Alur Kerja Portal Solutions Architect (SA)

Dokumen ini merangkum spesifikasi teknis, alur kerja (workflow), struktur basis data, serta integrasi layanan eksternal untuk Portal SA (pengganti Redmine) yang diakses dalam bentuk *Progressive Web App* (PWA).

> **Visualisasi alur bisnis:** lihat [`Alur_Bisnis_Portal_SA.md`](Alur_Bisnis_Portal_SA.md) untuk diagram Mermaid keempat alur kerja, aktor/peran, integrasi, dan ER entitas inti.

---

## 1. Konsep Utama Aplikasi
Portal ini menggabungkan manajemen proyek (request Sales ke SA) dan manajemen utilisasi/aktivitas harian (Time Tracking & Activity Log) ke dalam satu platform yang ditenagai oleh **Google Workspace (GDrive, Gmail, GCalendar)** dan **Google Gemini AI**.

---

## 2. Alur Kerja Aplikasi (Workflows)

### Flow 1: Pre-Sales Request & AI Scoring
1. **Input Sales:** Sales masuk ke portal, mengisi form data customer, estimasi awal, mengisi *Kuesioner kualifikasi*, dan mengunggah dokumen referensi (MoM / RFP).

   > **Catatan kuesioner (keputusan grill 2026-11-10):** *Kuesioner kualifikasi* adalah kumpulan pertanyaan faktual terstruktur (set tetap, bertanda `schema_version`) yang menjadi evidence skor BANT. Skor dihitung oleh backend (rubrik deterministik), bukan dinilai sendiri oleh Sales; jika ada dokumen, skor AI digabung per kriteria dengan nilai tertinggi. Lihat [`docs/adr/0010-bant-score-computed-in-backend.md`](../docs/adr/0010-bant-score-computed-in-backend.md).
2. **AI Processing:** File dianalisis oleh Gemini AI (Multimodal) untuk mengekstrak spesifikasi, memvalidasi matriks BANT (Budget, Authority, Need, Timeline), menentukan *Priority*, *Use Case Tagging*, serta menyusun *Pre-filled OLA/Mandays* internal untuk SA.

   > **Catatan scope (keputusan grill 2026-10-21):** penyusunan *Pre-filled OLA/Mandays* **ditunda keluar dari MVP** (backlog pasca-MVP). Deskripsi fitur ini sengaja dipertahankan di spec sebagai *intent*; implementasinya di luar scope MVP.
3. **Threshold Gatekeeper:**
   - Jika *BANT Score* < 60%: Sistem meminta Sales merevisi/melengkapi data (Status: `Need Clarification`).
   - Jika *BANT Score* >= 60%: Lolos. Notifikasi *New Opportunity* dikirim ke Lead SA untuk penugasan (*Assignment*).

### Flow 2: Dokumen, SLA DQ Number, dan Gating System
1. **Work Stream SA:** SA yang ditugaskan dapat langsung bekerja tanpa harus menunggu DQ Number. SA mengerjakan *Technical Proposal*, *BOQ (AWS Calc)*, dan *Mandays* di folder `Solutions`. (Dokumen HLD ditunda hingga *Closed-Win*).
2. **DQ Number Gating (SLA 5 Hari):**
   - **< 5 Hari:** Jika Sales sudah input DQ, saat dokumen SA berstatus `Reviewed`, link Google Drive akan **terbuka otomatis** untuk Sales beserta notifikasi email.
   - **> 5 Hari:** Jika DQ belum diinput, link dokumen akan **terkunci (Hidden/Locked)**. Sistem mengirimkan reminder (H+3) dan eskalasi ke Sales Manager (H+5).

### Flow 3: Activity Mapping & Project Story (Aplikasi 2)
1. **GCalendar Sync:** Sistem menarik data acara (*events*) dari Google Calendar SA secara *real-time*.
2. **Mapping oleh SA:** Melalui Portal, SA memetakan kalender ke dalam work item *Subtask* (misal: "Meeting Pre-Implementation", "Create HLD"). *Subtask* adalah work item yang bisa ditugaskan, berbeda dari `ActivityCategory` (taksonomi pengelompokan log) — lihat catatan pada struktur `ActivityLogs`.
3. **AI Activity Polish:** Saat SA mengetik catatan rapat (*notes*) secara kasual di Portal, Gemini AI merapikan teks tersebut menjadi **Poin Diskusi & Action Items** terstruktur.
4. **Project Story:** Log aktivitas ini dimasukkan ke dalam *Project Story* global yang dapat diakses oleh Manager dan *Backup SA* (untuk *handover* saat SA cuti).

   > **Catatan pemetaan (keputusan grill 2026-10-21):** *Backup SA* **bukan** peran atau entity baru — ia dipenuhi oleh fitur **Project Collaboration**, yaitu *collaborator* dengan akses baca *Project Story*. Lihat [`docs/adr/0002-backup-sa-via-project-collaboration.md`](../docs/adr/0002-backup-sa-via-project-collaboration.md).

### Flow 4: Post-Sales & PMO Handover
1. **Closed-Win Trigger:** Saat proyek berstatus *PO Rilis / Win*, SA menerima notifikasi wajib membuat **HLD (High Level Document)**.
2. **RAG Template Recommendation:** Fitur AI (RAG) merekomendasikan *template* / referensi dokumen dari proyek serupa sebelumnya.
3. **Automated Handover:** Setelah HLD disubmit, sistem otomatis membagikan hak akses folder `03_Final_Deliverables` beserta notifikasi *handover* kepada **PMO Lead** dan **Delivery Lead** untuk penyusunan *Project Charter* dan LLD.

---

## 3. Struktur Database & Field

### A. Tabel `Projects` (Opportunity Data)
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `id_project` | String | PK, Generate dari sistem |
| `project_name` | String | Nama proyek dari input Sales |
| `customer_name` | String | Nama perusahaan client |
| `dq_number` | String | Input belakangan, syarat rilis dokumen |
| `sales_pic` | UUID | Relasi ke tabel `Users` |
| `assigned_sa` | UUID | Relasi ke tabel `Users` |
| `status` | Enum | New, Pending Assignment, Assigned, Pending DQ, Ready, Closed-Win, Handover Complete, Lost, Need Clarification, Scoring Pending, Manual Review Required |
| `target_submit` | Date | Tanggal batas pengajuan proposal |
| `bant_score` | Integer | 0-100% didapat dari Gemini API |
| `use_case_tags` | JSON | Misal: ["App Mod", "DB Migration"] |
| `gdrive_folder_id` | String | ID Master Folder proyek di GDrive |

> **Catatan enum `status` (keputusan grill 2026-10-21):** set status operasional di atas mengikuti **kode sebagai ground truth** untuk status operasional — `Pending Assignment, Scoring Pending, Need Clarification, Manual Review Required, Handover Complete` lahir dari Flow 1 (AI scoring) dan Flow 4 (handover) yang sudah berjalan. `Pending DQ` **dipertahankan** karena milik Flow 2 (SLA DQ gating). Lihat [`docs/adr/0001-status-enum-code-is-ground-truth-keep-pending-dq.md`](../docs/adr/0001-status-enum-code-is-ground-truth-keep-pending-dq.md).

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
* **Fungsi:** Auto-provisioning struktur folder saat proyek dibuat (Format: `[Nama Customer] > [Nama Proyek] > Inventory / Diagram / Solutions`).
* **Permission Logic:**
  * *Sales* disembunyikan (*No Access*) dari folder `Solutions` sampai field `dq_number` terisi.
  * *SA/Lead SA* mendapatkan hak akses *Editor*.
  * *PMO/Delivery Lead* ditambahkan akses *Viewer* otomatis saat status berubah menjadi *Closed-Win*.

### B. Google Calendar API
* **Fungsi:** Webhook / API Fetch untuk menarik blok jadwal per hari tiap SA.
* **Flow:** Data event di-render pada UI Portal SA, lalu SA mengeklik event tersebut untuk di-assign ke `id_project` tertentu beserta estimasi *spent time*.

### C. Gmail API / Email Gateway
* **Fungsi:** Notifikasi *trigger-based* otomatis menggunakan format template HTML tepercaya.
* **Trigger Utama:**
  * Penugasan Lead SA (Internal SA).
  * Update Parsial Dokumen ke Sales.
  * Peringatan / Eskalasi SLA DQ Number (5 hari).
  * *Handover Email* pasca-Win ke tim PMO & Delivery.

### D. Google Gemini AI (Vertex AI / AI Studio)
* **Multimodal Parsing (Document to JSON):** Mengekstrak MoM/RFP (PDF/Doc) ke parameter BANT (Budget, Authority, Need, Timeline).
* **Text Structuring (Activity Log):** Membersihkan *raw_notes* menjadi `Action Items` dan `Discussion Points`.
* **RAG (Retrieval-Augmented Generation):** Melakukan *semantic search* pada metadata `use_case_tags` dan histori dari folder *Closed-Win* untuk merekomendasikan berkas (PropTek/HLD) masa lalu kepada SA sebagai referensi.
