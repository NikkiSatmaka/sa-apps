"""
Unit pelengkap cabang kecil modul kualifikasi/scoring/proyek (tiket B8 #61): tanpa DB/jaringan.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api import projects as api_projects
from app.schemas.scoring import BANTSubScores
from app.services.scoring_engine import ScoringEngine


class _Upload:
    """UploadFile minimal."""

    def __init__(self, filename, content=b"x", content_type="application/pdf", gagal=False):
        self.filename, self.content_type = filename, content_type
        self._content, self._gagal = content, gagal

    async def read(self):
        if self._gagal:
            raise OSError("disk penuh")
        return self._content


# --------------------------------------------------------------------------- upload


@pytest.mark.parametrize(
    ("nama", "valid"),
    [
        ("", False),
        (None, False),
        ("a.pdf", True),
        ("A.DOCX", True),
        ("a.txt", False),
        ("pdf", False),
    ],
)
def test_validasi_ekstensi_file(nama, valid):
    assert api_projects._validate_file_extension(nama) is valid


async def test_upload_gagal_dibaca_dilaporkan_per_file_tanpa_konten():
    hasil, konten = await api_projects._process_file_upload(_Upload("a.pdf", gagal=True))

    assert hasil.success is False and konten is None
    assert "Gagal membaca file" in hasil.error


async def test_upload_melebihi_batas_ditolak_dengan_ukuran(monkeypatch):
    monkeypatch.setattr(api_projects, "MAX_FILE_SIZE_BYTES", 4)

    hasil, konten = await api_projects._process_file_upload(_Upload("a.pdf", b"12345"))

    assert (hasil.success, konten, hasil.size_bytes) == (False, None, 5)
    assert "melebihi batas 20MB" in hasil.error


async def test_upload_kosong_ditolak_dan_nama_hilang_dianggap_unknown():
    kosong, _ = await api_projects._process_file_upload(_Upload("a.pdf", b""))
    tanpa_nama, _ = await api_projects._process_file_upload(_Upload(None))

    assert kosong.error == "File kosong (0 bytes)." and kosong.size_bytes == 0
    assert tanpa_nama.filename == "unknown" and tanpa_nama.success is False


async def test_upload_ekstensi_valid_dengan_mime_asing_tetap_diterima():
    hasil, konten = await api_projects._process_file_upload(
        _Upload("a.pdf", b"abc", content_type="application/octet-stream")
    )

    assert hasil.success is True and konten == b"abc"


def test_id_proyek_berformat_dan_acak():
    a, b = api_projects._generate_project_id(), api_projects._generate_project_id()

    assert a.startswith("PRJ-") and len(a) == len("PRJ-20250101-A3X9K2")
    assert a != b


# --------------------------------------------------------------------------- scoring engine


def test_parse_respons_llm_dict_string_berpagar_dan_rusak():
    e = ScoringEngine()
    data = {"budget": {"score": 5}}

    assert e._parse_llm_response(data) is data
    assert e._parse_llm_response("```json\n" + json.dumps(data) + "\n```") == data
    assert e._parse_llm_response("bukan json") is None
    assert e._parse_llm_response(123) is None
    assert e._parse_llm_response(None) is None


@pytest.mark.parametrize(
    "mentah",
    [
        None,
        "teks",
        [],
        {},
        {"budget": 1},
        {"budget": 1, "authority": 1, "need": 1, "timeline": 99},
        {"budget": "a", "authority": 1, "need": 1, "timeline": 1},
    ],
)
def test_sub_skor_tersimpan_tidak_valid_diabaikan(mentah):
    assert ScoringEngine._as_sub_scores(mentah) is None


def test_sub_skor_tersimpan_valid_dan_stored_ai_override():
    e = ScoringEngine()
    proyek = MagicMock()
    proyek.ai_scoring_result = {
        "sub_scores": {"budget": 1, "authority": 2, "need": 3, "timeline": 4}
    }
    proyek.override_sub_scores = {"budget": 9, "authority": 9, "need": 9, "timeline": 9}

    assert e._stored_ai(proyek) == BANTSubScores(budget=1, authority=2, need=3, timeline=4)
    assert e._plain_override(proyek) == {"budget": 9, "authority": 9, "need": 9, "timeline": 9}
    proyek.ai_scoring_result = "rusak"
    proyek.override_sub_scores = None
    assert e._stored_ai(proyek) is None and e._plain_override(proyek) is None
    assert e._stored_ai(None) is None and e._stored_override(None) is None


def test_rubrik_tidak_dihitung_tanpa_jawaban_atau_proyek():
    e = ScoringEngine()
    proyek = MagicMock()
    proyek.qualification_answers = None

    assert e._rubric_scores(None) is None
    assert e._rubric_scores(proyek) is None


async def test_refresh_proyek_gagal_memakai_state_sebelumnya_dan_none_tetap_none():
    e = ScoringEngine()
    db = MagicMock()
    db.refresh = AsyncMock(side_effect=RuntimeError("koneksi putus"))
    proyek = MagicMock()

    assert await e._refresh_project(db, "PRJ-1", proyek) is proyek
    assert await e._refresh_project(db, "PRJ-1", None) is None
