"""
Fake boundary eksternal untuk test integrasi (tiket B3, spec #49): Gemini, Drive, Gmail, Calendar.

Setiap fake dapat diprogram (sukses / gagal terprogram), merekam panggilan untuk ditegaskan, dan
dipasang lewat fixture (`fake_llm`, `fake_drive`, `fake_gmail`, `fake_calendar`) yang otomatis
dipulihkan setelah test (monkeypatch). Lihat `backend/README.md`, bagian Fake boundary.
"""
