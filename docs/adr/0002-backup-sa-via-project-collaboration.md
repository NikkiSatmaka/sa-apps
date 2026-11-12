# Backup SA dipetakan ke Project Collaboration, bukan entity baru

Spec Flow 3 meminta Project Story dapat diakses "Backup SA" saat SA utama berhalangan. Kami memutuskan requirement ini dipenuhi oleh fitur Project Collaboration yang sudah ada: "Backup SA" adalah *collaborator dengan akses baca Project Story*, bukan peran atau entity tersendiri. Alternatif (konsep Backup SA terpisah) ditolak karena menduplikasi mekanisme akses yang sudah ada tanpa menambah kemampuan. Dicatat sebagai ADR karena pembaca masa depan yang membaca spec akan mencari entity "Backup SA" di kode dan tidak menemukannya — pemetaan ke collaborator ini sengaja, bukan fitur yang terlewat.

## Consequences

- Keputusan pemilik produk 2026-11-10: Sales PIC proyek itu juga boleh membaca Project Story dan meminta ringkasan AI (membalik spec #87 / issue #74). Ini di luar pemetaan Backup SA dan menyimpang dari teks spec Flow 3 yang menyebut "Manager dan Backup SA"; Story memuat catatan rapat mentah dan versi polish AI, jadi pembukaan ini disengaja. Hak tulis Sales PIC (activity log, kalender) tidak berubah.
