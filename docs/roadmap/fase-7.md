<!-- Bagian dari docs/ROADMAP.md (indeks). Checkbox fase ini di-update di sini. -->

## Fase 7 — Guardrails LLM (fitur 11, sisanya)

**Tujuan:** lapisan keamanan di sekitar semua pemanggilan Gemini. (Hardening auth sudah dikerjakan di Fase 0.) Sebaiknya mendarat sebelum/bersama Fase 6 karena fitur itu mengirim dokumen utuh ke LLM.

- [x] 7.1 Input safety: batas ukuran/konten dan mitigasi prompt-injection sebelum pemanggilan di `scoring_engine.py` / `activity_logger.py` / `activity_logs.py` (size/byte clamp + delimiter-wrap + neutralize).
- [x] 7.2 Output validation: paksa schema JSON yang diharapkan pada response terstruktur; tolak/retry pada output malformed atau di luar kontrak (`validate_llm_json` + Pydantic contracts).
- [x] 7.3 **Keputusan diambil:** handling PII memakai flag-and-log untuk MVP (regex Indonesia-centric, tanpa redaction, tanpa nilai mentah di log); redaction ditunda.
- [x] 7.4 Sentralisasi guardrails dalam satu module `backend/app/utils/guardrails.py` yang dilewati setiap Call_Site LLM.

**Kriteria selesai:** tidak ada konten user yang sampai ke Gemini tanpa melewati guardrail input; semua output terstruktur tervalidasi schema.
