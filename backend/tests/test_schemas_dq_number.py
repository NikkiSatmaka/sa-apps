"""
DQ Number (SA Spec Flow 2): alfanumerik + tanda hubung, panjang 5–20. Validator murni,
diuji dengan contoh batas dan properti (Hypothesis).
"""

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.dq_number import (
    DQ_NUMBER_PATTERN,
    DQNumberInput,
    DQNumberResponse,
    SolutionsDocumentResponse,
)

ALFABET_VALID = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-"


def _valid(v: str) -> bool:
    try:
        DQNumberInput(dq_number=v)
    except ValidationError:
        return False
    return True


class TestDQNumberInput:
    @pytest.mark.parametrize(
        "nilai",
        ["ABCDE", "12345", "abc-1", "-----", "DQ-2025-00123", "A" * 20, "a1-B2-c3-D4-e5-F6-g7"],
    )
    def test_format_valid_diterima(self, nilai):
        assert DQNumberInput(dq_number=nilai).dq_number == nilai

    @pytest.mark.parametrize(
        "nilai",
        [
            "",  # kosong
            "ABCD",  # 4 karakter: tepat di bawah batas
            "A" * 21,  # 21 karakter: tepat di atas batas
            "ABC DE",  # spasi
            "ABC_DE",  # underscore
            "ABC/DE",
            "ABCDÉ",  # non-ASCII
            "ABC.12",
            " ABCDE",
            "ABCDE ",
            "ABC-1\n",  # newline akhir: dulu lolos karena `$` pada re.match
            "\nABC-1",
            "ABC\n-1",
        ],
    )
    def test_format_tidak_valid_ditolak(self, nilai):
        with pytest.raises(ValidationError):
            DQNumberInput(dq_number=nilai)

    def test_batas_panjang_tepat_5_dan_20(self):
        assert _valid("A" * 5)
        assert _valid("A" * 20)
        assert not _valid("A" * 4)
        assert not _valid("A" * 21)

    def test_field_wajib(self):
        with pytest.raises(ValidationError):
            DQNumberInput()

    def test_bukan_string_ditolak(self):
        with pytest.raises(ValidationError):
            DQNumberInput(dq_number=12345)

    @given(st.text(alphabet=ALFABET_VALID, min_size=5, max_size=20))
    def test_properti_semua_string_alfanumerik_hyphen_5_20_diterima(self, nilai):
        assert DQNumberInput(dq_number=nilai).dq_number == nilai

    @given(st.text(alphabet=ALFABET_VALID, min_size=0, max_size=4))
    def test_properti_terlalu_pendek_ditolak(self, nilai):
        assert not _valid(nilai)

    @given(st.text(alphabet=ALFABET_VALID, min_size=21, max_size=60))
    def test_properti_terlalu_panjang_ditolak(self, nilai):
        assert not _valid(nilai)

    @settings(max_examples=300)
    @given(st.text(max_size=30))
    def test_properti_diterima_jika_dan_hanya_jika_cocok_pola_penuh(self, nilai):
        """Keputusan skema identik dengan pola yang juga dijaga CHECK database (`~ '^..$'`)."""
        diharapkan = re.fullmatch(r"[A-Za-z0-9\-]{5,20}", nilai) is not None
        assert _valid(nilai) is diharapkan

    @given(
        st.text(alphabet=ALFABET_VALID, min_size=5, max_size=19),
        st.sampled_from(["\n", "\r", " ", "\t", "!", "_"]),
    )
    def test_properti_karakter_asing_di_akhir_ditolak(self, dasar, sufiks):
        assert not _valid(dasar + sufiks)

    def test_pola_konstanta_selaras_dengan_check_database(self):
        # Pola yang sama dipakai CHECK `chk_dq_number_format` (diuji di Postgres pada tes model).
        assert DQ_NUMBER_PATTERN == r"^[A-Za-z0-9\-]{5,20}$"


class TestDQNumberResponse:
    def test_message_opsional(self):
        r = DQNumberResponse(
            id_project="P1",
            project_name="N",
            customer_name="C",
            dq_number="DQ-12345",
            status="Submitted",
        )
        assert r.message is None

    def test_field_wajib(self):
        with pytest.raises(ValidationError) as exc:
            DQNumberResponse(id_project="P1")
        assert {e["loc"][0] for e in exc.value.errors()} == {
            "project_name",
            "customer_name",
            "dq_number",
            "status",
        }


class TestSolutionsDocumentResponse:
    def test_valid_dan_notes_opsional(self):
        d = SolutionsDocumentResponse(
            id_doc="DOC-1", doc_type="BOQ", status="Draft", gdrive_link="https://drive/x"
        )
        assert d.notes is None

    def test_link_wajib(self):
        with pytest.raises(ValidationError):
            SolutionsDocumentResponse(id_doc="DOC-1", doc_type="BOQ", status="Draft")
