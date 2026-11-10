# Portal SA

Portal internal untuk tim Solution Architect (SA) di alur pre-sales sampai handover PMO. Glossary ini mendefinisikan istilah domain yang spesifik untuk portal ini — bukan konsep pemrograman umum. Ground truth perilaku produk ada di `SA Application/Spesifikasi_Teknis_Portal_SA.md`.

## Peran

**Sales**:
Orang yang membuat opportunity dan mengisi kualifikasi awal. Bukan bagian dari tim SA; mendapat akses baca ke folder/dokumen tertentu.
_Avoid_: Account Executive, AE

**SA** (Solution Architect):
Orang yang ditugaskan mengerjakan sisi teknis sebuah proyek pre-sales: dokumen, scoring, activity.
_Avoid_: Engineer, Presales Engineer

**Lead SA**:
SA yang mengambil keputusan assignment proyek ke SA dan mengelola subtask. Pengambil keputusan assignment; tidak ada step "qualify" manual terpisah di atas gate BANT otomatis.
_Avoid_: SA Manager

**Backup SA**:
SA yang diberi akses baca Project Story sebuah proyek untuk handover saat SA utama berhalangan (mis. cuti). Bukan peran atau entity tersendiri — dipetakan sebagai *collaborator* lewat fitur Project Collaboration.
_Avoid_: Pengganti SA, substitute SA

## Proyek & status

**Opportunity**:
Peluang pre-sales yang dibuat Sales. Begitu masuk sistem, direpresentasikan sebagai `Project`.
_Avoid_: Deal, lead

**Project**:
Entity inti yang melacak satu opportunity dari intake sampai handover. Punya `status`, BANT score, dokumen, dan activity log.
_Avoid_: Case, ticket

**Pending DQ**:
Status proyek saat menunggu DQ Number diisi; milik Flow 2 (Dokumen, DQ Number & Gating). Status spec yang wajib dipertahankan meski status operasional lain mengikuti kode.

## Kualifikasi

**BANT score**:
Skor kualifikasi 0–100 (Budget, Authority, Need, Timeline). Dihitung backend dari jawaban Kuesioner kualifikasi dan/atau hasil analisis dokumen, bukan angka kiriman klien. Gate otomatis: `≥ 60` → proyek lanjut ke assignment; `< 60` → `Need Clarification`. Threshold ditetapkan spec, bukan asumsi.
_Avoid_: Lead score, qualification score

**Kuesioner kualifikasi**:
Kumpulan pertanyaan faktual terstruktur yang diisi Sales saat membuat opportunity (set tetap, bertanda `schema_version`). Jawabannya menjadi evidence untuk BANT score dan bahan dokumen Requirement; Sales tidak menilai dirinya sendiri.
_Avoid_: Form BANT manual, form pertanyaan awal, skor manual Sales

**DQ Number**:
Nomor identifikasi proyek yang menjadi gate Flow 2: fungsi tertentu terkunci sampai DQ Number terisi.
_Avoid_: Deal number, project code

## Pekerjaan & aktivitas

**Subtask**:
Work item yang bisa ditugaskan dalam sebuah proyek, punya status open → in_progress → done (mis. "Create HLD", "Peer Review"). Saat SA di-assign ke proyek, checklist default (`Requirement, BoQ, PropTek, HLD`) di-seed dan langsung ditugaskan ke SA proyek itu; Lead SA boleh memindah sebagian ke SA lain. Mencatat activity log pertama terhadap subtask `open` memindahkannya ke `in_progress`; `done` selalu ditandai eksplisit, tidak pernah disimpulkan dari adanya log. Berbeda dari `ActivityCategory`.
_Avoid_: Task, to-do, activity

**ActivityCategory**:
Taksonomi untuk mengelompokkan entri activity log (mis. Internal Meeting, Customer Meeting, Document Review). Dimensi pengelompokan, bukan work item yang ditugaskan. Berbeda dari `Subtask`.
_Avoid_: Subtask (keduanya berbeda peran), activity type

**Project Story**:
Catatan naratif/kronologis aktivitas sebuah proyek, dapat diakses Backup SA untuk handover.
_Avoid_: Timeline, log narasi

## Dokumen

**Requirement** (dokumen):
Daftar butir kebutuhan customer terstruktur (`kategori` + `butir`) yang **di-generate AI** dari Kuesioner kualifikasi + Source document — konten turunan, bukan file upload customer. Disimpan sebagai `Document` dengan `doc_type="Requirement"`, menjadi baseline perbandingan BoQ. SA yang mengedit menandainya `is_overridden`.
_Avoid_: Spec customer, dokumen kebutuhan upload

**Source document**:
File MoM atau RFP yang di-upload Sales saat intake; teks hasil ekstraksinya disimpan sebagai bahan Requirement. Bukan dokumen deliverable proyek.
_Avoid_: Lampiran, attachment, dokumen referensi

**BoQ** (Bill of Quantity):
Dokumen daftar item/kuantitas yang dibandingkan terhadap dokumen Requirement untuk analisis gap coverage.
_Avoid_: Quote, penawaran

## Folder & provisioning

**Folder proyek** (Google Drive):
Struktur folder Drive yang dibuat otomatis saat SA di-assign: satu folder master `[Customer] - [Project]` berisi subfolder `Inventory` (Viewer Sales), `Diagram` (tanpa akses Sales), dan `Solutions` (tanpa akses Sales sampai DQ terisi). `Final_Deliverables` dibuat di dalam `Solutions` saat handover.
_Avoid_: Drive folder, workspace folder

**Solutions folder**:
Subfolder tempat deliverable teknis proyek disimpan. Satu-satunya folder yang akses Sales-nya berubah sepanjang lifecycle: dikunci (lock) oleh SLA saat DQ telat, dibuka (unlock) saat DQ terisi atau dokumen `Reviewed`. Operasi lock/unlock/handover SELALU menyasar id folder Solutions — bukan id folder master. Disimpan di `gdrive_solutions_folder_id`, terpisah dari `gdrive_folder_id` (master).
_Avoid_: Folder deliverable, folder solusi

**Provisioning status**:
Keadaan pembuatan folder proyek sebuah proyek: `pending` (sedang dibuat), `provisioned` (selesai, id tersimpan), atau `failed` (gagal setelah retry; bisa di-provision ulang oleh Lead_SA/Admin). Disimpan di kolom `folder_provisioning_status` dan menggerakkan badge di dashboard.
_Avoid_: Folder status, status folder
