"""Subtask kaya (#124), unit tanpa DB: validasi schema dan aturan penanda terlambat."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.subtask import SubtaskCreateRequest, SubtaskUpdateRequest
from app.services.subtask import subtask_terlambat

HARI_INI = date(2030, 6, 15)


@pytest.mark.parametrize(
    ("due", "status", "terlambat"),
    [
        (date(2030, 6, 14), "open", True),  # kemarin
        (date(2030, 6, 14), "in_progress", True),
        (date(2030, 6, 14), "done", False),  # sudah selesai tidak terlambat
        (date(2030, 6, 15), "open", False),  # jatuh tempo hari ini belum terlambat
        (date(2030, 6, 16), "open", False),
        (None, "open", False),  # tanpa due date tidak pernah terlambat
        (None, "done", False),
    ],
)
def test_subtask_terlambat_hanya_bila_lewat_due_date_dan_belum_done(due, status, terlambat):
    assert subtask_terlambat(due, status, HARI_INI) is terlambat


def test_subtask_terlambat_memakai_hari_ini_bawaan_bila_tidak_diberikan():
    assert subtask_terlambat(date(2000, 1, 1), "open") is True
    assert subtask_terlambat(date(2999, 1, 1), "open") is False


def test_create_request_field_baru_opsional():
    req = SubtaskCreateRequest(title="X")

    assert (req.description, req.due_date, req.estimate_hours) == (None, None, None)


def test_create_request_menerima_nilai_valid():
    req = SubtaskCreateRequest(
        title="X", description=" uraian ", due_date="2030-01-02", estimate_hours="1.5"
    )

    assert req.description == "uraian"
    assert req.due_date == date(2030, 1, 2)
    assert req.estimate_hours == Decimal("1.5")


@pytest.mark.parametrize("jam", ["-0.01", "-5", "100000", "1.001"])
def test_estimate_hours_di_luar_batas_ditolak(jam):
    with pytest.raises(ValidationError):
        SubtaskCreateRequest(title="X", estimate_hours=jam)
    with pytest.raises(ValidationError):
        SubtaskUpdateRequest(estimate_hours=jam)


def test_description_terlalu_panjang_ditolak_dan_spasi_jadi_none():
    with pytest.raises(ValidationError):
        SubtaskCreateRequest(title="X", description="x" * 2001)
    assert SubtaskCreateRequest(title="X", description="  ").description is None
    assert SubtaskCreateRequest(title="X", description="x" * 2000).description == "x" * 2000


def test_update_request_tanpa_field_ditolak():
    with pytest.raises(ValidationError):
        SubtaskUpdateRequest()


def test_update_request_membedakan_tidak_dikirim_dari_null_eksplisit():
    req = SubtaskUpdateRequest(due_date=None)

    assert req.model_fields_set == {"due_date"}
    assert req.due_date is None
