"""`generate_doc_id`: format DOC-{YYYYMMDD}-{6 alfanumerik}, tanggal UTC, muat di kolom id_doc."""

import re
from datetime import datetime, timezone
from unittest.mock import patch

from hypothesis import given, settings
from hypothesis import strategies as st

from app.utils.identifiers import generate_doc_id

POLA = re.compile(r"^DOC-\d{8}-[A-Z0-9]{6}$")


def test_format_sesuai_kontrak():
    assert POLA.fullmatch(generate_doc_id())


def test_muat_di_kolom_id_doc_string_50():
    assert len(generate_doc_id()) == len("DOC-20250101-ABC123") <= 50


def test_bagian_tanggal_memakai_tanggal_utc_hari_ini():
    class _Jam(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc  # harus UTC, bukan waktu lokal server
            return datetime(2031, 12, 9, 23, 59, tzinfo=timezone.utc)

    with patch("app.utils.identifiers.datetime", _Jam):
        assert generate_doc_id().startswith("DOC-20311209-")


@settings(max_examples=200)
@given(st.integers(min_value=0, max_value=10))
def test_properti_selalu_cocok_format_dan_hampir_selalu_unik(_):
    ids = {generate_doc_id() for _ in range(50)}
    assert all(POLA.fullmatch(i) for i in ids)
    # 36^6 ruang acak: 50 sampel bertabrakan secara praktis mustahil.
    assert len(ids) == 50
