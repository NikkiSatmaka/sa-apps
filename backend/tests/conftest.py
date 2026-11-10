"""
Konfigurasi pytest untuk backend Portal SA.

Men-set environment variable aman SEBELUM `app` di-import. Ini penting karena
`Settings()` dibuat saat import (mis. oleh `TestClient(app)`), dan sejak Fase 0
hardening `JWT_SECRET_KEY` tidak lagi punya default — tanpa secret valid,
`Settings()` akan fail-fast (ValidationError) dan merusak collection test.

Pakai `setdefault` agar tidak menimpa env nyata yang mungkin sudah di-set
operator saat menjalankan test di lingkungan lain.
"""

import os

# DATABASE_URL DIPAKSA (bukan setdefault) ke target yang langsung gagal.
# Alasan keamanan: test unit tidak boleh menyentuh database nyata mana pun (dev
# maupun Compose), walau operator punya DATABASE_URL di environment/.env.
# Alasan kecepatan: default `@db:5432` memicu resolusi DNS ±3,8 detik per
# percobaan pada jalur `AsyncSessionLocal()` yang tidak di-mock; 127.0.0.1:1
# ditolak seketika (connection refused).
# Test integrasi (tiket B2) wajib memakai jalur eksplisit sendiri lewat
# `TEST_DATABASE_URL` dan tidak boleh memakai DATABASE_URL ini.
os.environ["DATABASE_URL"] = "postgresql+asyncpg://test:test@127.0.0.1:1/test_unit_tanpa_db"
# Secret dummy khusus test (min 32 char) — bukan secret produksi.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-untuk-pytest-min-32-chars")
# Pastikan test berjalan sebagai development (demo mode boleh aktif, tak diblok).
os.environ.setdefault("ENVIRONMENT", "development")
# Suite memakai satu TestClient/IP bersama; limiter in-memory (100 req/menit) akan memicu 429
# palsu bila jumlah request test melebihinya. Longgarkan hanya untuk test.
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")
