"""Test unit skrip gerbang cakupan (scripts/cakupan_gerbang.py): dua ambang terpisah."""

import json

import pytest

from scripts import cakupan_gerbang as g


def _ringkasan(cl, ns, cb, nb):
    return {
        "covered_lines": cl,
        "num_statements": ns,
        "covered_branches": cb,
        "num_branches": nb,
    }


def _data(total, **files):
    return {
        "totals": total,
        "files": {n: {"summary": s} for n, s in files.items()},
    }


def _jalankan(tmp_path, data, capsys):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(data))
    rc = g.main(["x", str(p)])
    return rc, capsys.readouterr()


def test_lolos_tepat_di_ambang(tmp_path, capsys):
    rc, out = _jalankan(
        tmp_path, _data(_ringkasan(90, 100, 80, 100), a=_ringkasan(9, 10, 8, 10)), capsys
    )
    assert rc == 0
    assert "GERBANG CAKUPAN LOLOS" in out.out


def test_gagal_bila_baris_di_bawah_ambang_padahal_cabang_baik(tmp_path, capsys):
    rc, out = _jalankan(tmp_path, _data(_ringkasan(89, 100, 100, 100)), capsys)
    assert rc == 1
    assert "BARIS 89.00% < 90%" in out.err
    assert "CABANG" not in out.err.split("Lihat kolom")[0]


def test_gagal_bila_cabang_di_bawah_ambang_padahal_baris_baik(tmp_path, capsys):
    rc, out = _jalankan(tmp_path, _data(_ringkasan(100, 100, 79, 100)), capsys)
    assert rc == 1
    assert "CABANG 79.00% < 80%" in out.err
    assert "BARIS" not in out.err.split("Lihat kolom")[0]


def test_gagal_dua_ambang_sekaligus_dilaporkan_keduanya(tmp_path, capsys):
    rc, out = _jalankan(tmp_path, _data(_ringkasan(50, 100, 10, 100)), capsys)
    assert rc == 1
    assert "BARIS" in out.err and "CABANG" in out.err


def test_modul_di_bawah_ambang_hanya_peringatan(tmp_path, capsys):
    data = _data(_ringkasan(95, 100, 90, 100), kecil=_ringkasan(1, 10, 1, 8))
    rc, out = _jalankan(tmp_path, data, capsys)
    assert rc == 0
    assert "::warning" in out.out and "kecil" in out.out


def test_tanpa_statement_atau_cabang_dianggap_lolos():
    assert g.Cakupan("k", 0, 0, 0, 0).baris == 100.0
    assert g.Cakupan("k", 0, 0, 0, 0).cabang == 100.0


def test_masukan_tidak_valid(tmp_path, capsys):
    rc, out = _jalankan(tmp_path, {"foo": 1}, capsys)
    assert rc == 2 and "tidak valid" in out.err
    rc, out = _jalankan(tmp_path, _data({"covered_lines": 1, "num_statements": 1}), capsys)
    assert rc == 2 and "branch" in out.err
    assert g.main(["x", str(tmp_path / "tidak-ada.json")]) == 2
    assert g.main(["x"]) == 2


@pytest.mark.parametrize("baris,cabang,lolos", [(90, 80, True), (89, 80, False), (90, 79, False)])
def test_periksa_ambang_terpisah(baris, cabang, lolos):
    t = g.Cakupan("TOTAL", baris, 100, cabang, 100)
    assert (g.periksa(t, []) == []) is lolos
