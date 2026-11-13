# Backup SA dipetakan ke Project Collaboration, bukan entity baru

Spec Flow 3 meminta Project Story dapat diakses "Backup SA" saat SA utama berhalangan. Kami memutuskan requirement ini dipenuhi oleh fitur Project Collaboration yang sudah ada: "Backup SA" adalah *collaborator dengan akses baca Project Story*, bukan peran atau entity tersendiri. Alternatif (konsep Backup SA terpisah) ditolak karena menduplikasi mekanisme akses yang sudah ada tanpa menambah kemampuan. Dicatat sebagai ADR karena pembaca masa depan yang membaca spec akan mencari entity "Backup SA" di kode dan tidak menemukannya — pemetaan ke collaborator ini sengaja, bukan fitur yang terlewat.

## Consequences

- Keputusan pemilik produk 2026-11-10 ([ADR 0011](0011-baca-proyek-terbuka-tulis-dibatasi.md)): semua proyek, termasuk Project Story dan ringkasan AI, dapat dibaca semua pengguna terautentikasi. Akibatnya "akses baca Story" tidak lagi membedakan collaborator; yang bermakna dari Backup SA adalah peran *contributor* (boleh menulis activity log). Hak tulis Sales PIC (activity log, kalender) tidak berubah.
