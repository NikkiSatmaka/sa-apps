# Portal SA

Portal internal untuk tim Solution Architect (SA): aplikasi ticketing / project tracker khusus SA (project diperlakukan seperti ticket) untuk melacak project, beban kerja, dan output SA di alur pre-sales sampai handover PMO. Glossary ini mendefinisikan istilah domain yang spesifik untuk portal ini — bukan konsep pemrograman umum. Ground truth perilaku produk ada di `SA Application/Spesifikasi_Teknis_Portal_SA.md`.

## Peran

**Sales**:
Dapat membuat dan memantau project; keterlibatannya opsional per project. Mengisi kuesioner kualifikasi dan DQ Number, boleh menulis komentar dan menetapkan `Won`. Bukan bagian dari tim SA; dapat melihat semua proyek. Akses Drive: Viewer `Inventory`, dan Viewer `Solutions` setelah DQ terisi.
_Avoid_: Account Executive, AE

**Sales PIC**:
Kontak dari tim Sales yang bertanggung jawab atas tindak lanjut komersial sebuah Opportunity atau Project. Sales PIC dapat berbeda dari orang yang mencatat project (misalnya Product Manager atau Lead SA yang memasukkannya atas nama Sales); relasi Sales PIC, bukan pembuat record semata, menjadi acuan kepemilikan Sales pada tampilan Portal SA.
_Avoid_: Menganggap pembuat project selalu Sales PIC

**Product Manager** (role `Product`; short form **PM**):
Penghubung tim ke principal cloud dan negosiator harga; bukan pembentuk produk atau solusi. Dalam Portal SA, haknya setara Sales meski berasal dari tim berbeda; PM dapat membuat dan memantau project, mengisi DQ Number, dan selalu menjadi kontak Product di setiap project.
_Avoid_: Product (sebagai sebutan untuk orang)

**SA** (Solution Architect):
Orang yang ditugaskan mengerjakan sisi teknis sebuah proyek: dokumen, subtask, activity log. Satu project boleh punya satu **SA utama** dan nol atau lebih **SA tambahan**.
_Avoid_: Engineer, Presales Engineer

**Lead SA**:
SA yang memimpin: menugaskan dan mengganti orang di project, membuat subtask, memantau beban SA, menutup project. Boleh juga ditugaskan sebagai SA dan membuat project. Tidak ada step "qualify" manual terpisah di atas gate BANT otomatis.
_Avoid_: SA Manager

**Admin** (`is_admin`):
Flag kemampuan, bukan role fungsional: kelola user, `POST /sla/process`, membuka kembali `Closed`/`Lost`, hak penuh atas semua project. Selalu menempel pada satu role fungsional (`Sales`, `Product Manager`, `SA`, atau `Lead_SA`); tidak ada Admin murni.
_Avoid_: Role Admin, superuser

**SA utama / SA tambahan**:
SA utama (`assigned_sa`) adalah penanggung jawab project. SA tambahan (tabel `ProjectAssignments`) punya hak setara SA utama; dipakai untuk project kompleks. Berbeda dari *collaborator*.
_Avoid_: Co-owner, secondary SA

**Backup SA**:
SA yang menggantikan SA utama sebuah proyek saat berhalangan (mis. cuti), supaya bisa meneruskan dan menulis activity log. Bukan peran atau entity tersendiri — dipetakan sebagai *collaborator* (*contributor*) lewat fitur Project Collaboration, dengan hak terbatas (tidak setara SA tambahan).
_Avoid_: Pengganti SA, substitute SA

## Proyek & status

**Customer**:
A persistent identity for an organization associated with one or more projects. Names that differ only by letter case or leading/trailing whitespace identify the same Customer; projects linked to it share its Drive folder even when its name changes.
_Avoid_: Treating each project’s `customer_name` text as a separate identity

**Customer link correction**:
Changing the Customer associated with an existing Project when its current association is wrong; it is distinct from assigning a Customer during initial project intake.
_Avoid_: Treating it as a Drive folder or permission repair

**Opportunity**:
Peluang pre-sales. Begitu dicatat di Portal SA, peluang tersebut dilacak sebagai `Project` yang sama dari intake melalui kualifikasi dan pekerjaan SA hingga ditutup; tidak ada catatan Lead/Opportunity terpisah sebelum Project.
_Avoid_: Deal, lead

**Project**:
Entity inti yang melacak satu Opportunity dari intake sampai penutupan. Memuat siklus kerja dan kualifikasi, BANT score, pemilik dan kontak dari Product, Sales, dan SA, subtask, dokumen, komentar, serta activity log. Orang yang mencatat Opportunity dapat berbeda dari Sales PIC. Diperlakukan seperti *ticket* di tracker, tetapi nama entity tetap `Project`.
_Avoid_: Case


**Status** (`Projects.status`):
Siklus kerja: `Intake` → `Awaiting Assignment` → `Assigned` → `In Progress` → `Submitted` → `Won` → `Handed Over` → `Closed`; status samping `Lost` dan `On Hold`. `In Progress` berpindah otomatis saat SA pertama mencatat aktivitas. `Submitted` = paket proposal diserahkan ke Sales/Product Manager untuk diajukan ke customer (bisa kembali ke `In Progress` untuk revisi). `Won` = PO rilis (hasil komersial). `Handed Over` hanya lewat aksi handover. `Closed` = project tuntas, read-only. Lihat spec §2.0.
_Avoid_: Stage, phase, `Ready`, `Closed-Win`, `Handover Complete`, `Pending Assignment` (nama lama)

**Qualification state** (`Projects.qualification_state`):
Keadaan gate kualifikasi saat `status = Intake`: `Scoring`, `Need Clarification`, `Manual Review`, atau `Qualified`. Terpisah dari status siklus kerja karena gate intake bersifat sementara.
_Avoid_: Status intake, sub-status

**On Hold**:
Status samping untuk project yang dijeda; menghentikan timer SLA DQ. Lanjut mengembalikan ke `previous_status`.
_Avoid_: Paused, Suspended

## Kualifikasi

**BANT score**:
Skor kualifikasi 0–100 (Budget, Authority, Need, Timeline). Dihitung backend dari jawaban Kuesioner kualifikasi dan/atau hasil analisis dokumen, bukan angka kiriman klien. Gate otomatis: `≥ 60` → proyek lanjut ke assignment; `< 60` → `Need Clarification`. Threshold ditetapkan spec, bukan asumsi.
_Avoid_: Lead score, qualification score

**Kuesioner kualifikasi**:
Kumpulan pertanyaan faktual terstruktur yang diisi pembuat project (Sales, Product Manager, atau Lead SA) saat membuat opportunity (set tetap, bertanda `schema_version`). Jawabannya menjadi evidence untuk BANT score dan bahan dokumen Requirement; pembuat tidak menilai dirinya sendiri.
_Avoid_: Form BANT manual, form pertanyaan awal, skor manual pembuat

**DQ Number**:
Nomor identifikasi proyek yang menjadi gate Flow 2: folder Solutions terkunci bagi Sales dan Product Manager sampai DQ Number terisi. Diisi oleh Sales, Product Manager, atau Lead SA.
_Avoid_: Deal number, project code

## Pekerjaan & aktivitas

**Subtask**:
Work item yang bisa ditugaskan dalam sebuah proyek (satu assignee: SA project atau Lead SA), punya `description`, `due_date`, estimasi jam opsional, dan status open → in_progress → done (mis. "Create HLD", "Peer Review"). Saat SA di-assign ke proyek, checklist default (`Requirement, BoQ, PropTek, HLD`) di-seed dan langsung ditugaskan ke SA proyek itu; Lead SA boleh memindah sebagian ke SA lain. Mencatat activity log pertama terhadap subtask `open` memindahkannya ke `in_progress`; `done` selalu ditandai eksplisit, tidak pernah disimpulkan dari adanya log. Berbeda dari `ActivityCategory`.
_Avoid_: Task, to-do, activity

**ActivityCategory**:
Taksonomi untuk mengelompokkan entri activity log (mis. Internal Meeting, Customer Meeting, Document Review). Dimensi pengelompokan, bukan work item yang ditugaskan. Berbeda dari `Subtask`.
_Avoid_: Subtask (keduanya berbeda peran), activity type

**Project Story**:
Catatan naratif/kronologis aktivitas sebuah proyek. Dapat dibaca semua pengguna terautentikasi (keputusan 2026-11-10); menulisnya dibatasi SA ditugaskan (utama/tambahan) dan contributor. Memuat catatan rapat mentah dan versi polish AI.
_Avoid_: Timeline, log narasi

**Komentar project**:
Thread diskusi per project yang ditulis orang yang ditugaskan di project dan dibaca semua pengguna. Terpisah dari Project Story (log aktivitas SA). Dipakai Sales dan Product Manager untuk bertanya ke SA.
_Avoid_: Chat, catatan

## Dokumen

**Requirement** (dokumen):
Daftar butir kebutuhan customer terstruktur (`kategori` + `butir`) yang **di-generate AI** dari Kuesioner kualifikasi + Source document — konten turunan, bukan file upload customer. Disimpan sebagai `Document` dengan `doc_type="Requirement"`, menjadi baseline perbandingan BoQ. SA yang mengedit menandainya `is_overridden`.
_Avoid_: Spec customer, dokumen kebutuhan upload

**Source document**:
File MoM atau RFP yang di-upload pembuat project saat intake; teks hasil ekstraksinya disimpan sebagai bahan Requirement. Bukan dokumen deliverable proyek.
_Avoid_: Lampiran, attachment, dokumen referensi

**BoQ** (Bill of Quantity):
Dokumen daftar item/kuantitas yang dibandingkan terhadap dokumen Requirement untuk analisis gap coverage.
_Avoid_: Quote, penawaran

## Folder & provisioning

**Folder proyek** (Google Drive):
Folder proyek yang dibuat otomatis saat SA di-assign, di dalam folder **Customer** dan diberi nomor berurutan per Customer (`01-<Project>`, `02-<Project>`, …). Berisi subfolder `Inventory`, `Diagram`, dan `Solutions`; folder lama tidak otomatis dipindah atau diganti nama.
_Avoid_: Drive folder, workspace folder

**Solutions folder**:
Subfolder tempat deliverable teknis proyek disimpan. Satu-satunya folder yang akses Sales dan Product Manager-nya berubah sepanjang lifecycle: dikunci (lock) oleh SLA saat DQ telat, dibuka (unlock) saat DQ terisi atau dokumen `Reviewed`. Operasi lock/unlock/handover SELALU menyasar id folder Solutions — bukan id folder master. Disimpan di `gdrive_solutions_folder_id`, terpisah dari `gdrive_folder_id` (master).
_Avoid_: Folder deliverable, folder solusi

**Provisioning status**:
Keadaan pembuatan folder proyek sebuah proyek: `pending` (sedang dibuat), `provisioned` (selesai, id tersimpan), atau `failed` (gagal setelah retry; bisa di-provision ulang oleh Lead_SA/Admin). Disimpan di kolom `folder_provisioning_status` dan menggerakkan badge di dashboard.
_Avoid_: Folder status, status folder
