# Matriks akses Drive dan gate DQ untuk Sales dan Product

Pernyataan awal "tidak ada role lain yang boleh mengakses Drive" dikoreksi pemilik produk pada 2026-11-13: **gate DQ tetap seperti di Flow 2**. Setelah `dq_number` terisi, Sales dan Product boleh mengakses folder `Solutions`.

| Folder | SA, Lead_SA (ditugaskan) | Sales, Product (ditugaskan) | PMO / Delivery Lead |
| :--- | :--- | :--- | :--- |
| `Inventory` | Editor | Viewer | tidak ada |
| `Diagram` | Editor | tidak ada | tidak ada |
| `Solutions` | Editor | tidak ada; Viewer setelah DQ terisi | tidak ada |
| `Final_Deliverables` | Editor | tidak ada | Viewer saat handover |

Keputusan:

- Akses mengikuti **orang yang sedang ditugaskan**; mengganti `sales_pic`/`product_pic`/SA mencabut akses lama dan memberi akses baru. Bila project tanpa Sales, gate DQ hanya berlaku untuk Product.
- PMO Lead dan Delivery Lead (tanpa akun portal) adalah **satu-satunya pengecualian**, hanya lewat aksi handover.
- DQ diisi oleh Sales, Product, atau Lead_SA. Reminder H+3 ke Sales dan Product; eskalasi H+5 ke `lead_sa` project itu dan semua `is_admin`; folder `Solutions` dikunci pada H+5 dan Sales/Product diberi tahu. Eskalasi sekali per project ([issue #77](https://github.com/NikkiSatmaka/sa-apps/issues/77)).
- Timer SLA berhenti selama `On Hold` ([ADR 0013](0013-model-status-dua-field.md)).
- Folder provisioning kini memberi Viewer `Inventory` kepada Sales **dan Product**.

## Konsekuensi

- Issue #27 (verifikasi Drive nyata) dikerjakan sebelum perubahan permission ini, dengan kriteria yang mengikuti tabel ini.
- Link dokumen Solutions bagi Sales/Product tetap mengikuti gate DQ dan izin Drive ([ADR 0011](0011-baca-proyek-terbuka-tulis-dibatasi.md)).
