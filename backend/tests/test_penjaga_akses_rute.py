"""
Penjaga rute: setiap rute yang memuat id proyek WAJIB memanggil titik keputusan akses
(`app.core.dependencies.ensure_project_access`), kecuali tercantum di `PENGECUALIAN` (tiket #88,
spec #87).

Cara kerja (AST reachability, bukan substring):
1. Ratakan semua `APIRoute` (FastAPI 0.162: `app.routes` memuat `_IncludedRouter`, bukan rute
   anak — pola sama dengan `tests/test_route_shadowing.py`).
2. "Rute berisi id proyek" = path param `project_id`/`id_project`/`doc_id`/`id_log`/`id_subtask`,
   ATAU field body bernama `id_project`/`project_id`. Heuristik berdasarkan NAMA parameter,
   bukan awalan path, sehingga `/projects/users/search` dan sejenisnya tidak ikut.
3. Dari `route.endpoint` (dan semua `Depends`-nya) telusuri panggilan fungsi yang bisa
   di-resolve ke kode `app.*` sampai kedalaman `KEDALAMAN_MAKS`; lulus bila titik keputusan
   tercapai.

Keterbatasan (sengaja, ditutup oleh test lain): penjaga TIDAK membuktikan cek dijalankan di
semua jalur, SEBELUM efek samping, atau tidak tertelan `try/except Exception`; panggilan dinamis
(`getattr`, method pada instance yang tak bisa di-resolve statis) tidak terlihat. Itu tugas test
integrasi peran × aksi (403 tanpa efek samping) dan meta-verifikasi per tiket.

Daftar `PENGECUALIAN`: tiap entri = rute, alasan, dan nomor. Selama overhaul (#88–#91) nomor =
tiket pembersih `#N`; hasil akhir #92 hanya berisi pengecualian SAH bernomor `SAH-N`. Ratchet:
entri yang rutenya sudah memanggil titik keputusan, atau rutenya tak ada lagi, membuat test GAGAL. Satu entri per baris, urut, supaya diff antar-tiket tidak
beririsan.
"""

import ast
import inspect
import re
import textwrap
import types
from collections.abc import Callable, Iterable

from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from app.core.dependencies import ensure_project_access, get_current_user
from app.main import app

TITIK_KEPUTUSAN = ("app.core.dependencies", "ensure_project_access")
PARAM_ID_PROYEK = {"project_id", "id_project", "doc_id", "id_log", "id_subtask"}
FIELD_BODY_ID_PROYEK = {"id_project", "project_id"}
KEDALAMAN_MAKS = 5
POLA_NOMOR = re.compile(r"^(#\d+|SAH-\d+)$")

# (METHOD, path absolut) -> (alasan, nomor "SAH-n")
#
# Hasil akhir #92: HANYA pengecualian yang SAH. Rute yang dulu punya pemeriksa buatan sendiri
# (workflow, handover, Requirement, collaborators, detail proyek, kuesioner, polish) sudah
# dimigrasikan ke titik keputusan bersama dan dikeluarkan dari daftar ini. Yang tersisa:
# (a) role gate murni Lead_SA/Admin dan (b) aturan kepemilikan subtask. Menambah entri baru
# memerlukan alasan spesifik + nomor SAH berikutnya + test integrasi yang mengunci aturannya.
PENGECUALIAN: dict[tuple[str, str], tuple[str, str]] = {
    ("DELETE", "/api/v1/projects/subtasks/{id_subtask}"): (
        "role gate Lead_SA/Admin saja (_require_lead_sa): tingkat tertinggi, tidak ada "
        "hubungan per-proyek yang bisa lebih longgar; 403 sebelum proyek dimuat. Dikunci "
        "test_akses_k5 (role gate)",
        "SAH-1",
    ),
    ("DELETE", "/api/v1/projects/{project_id}"): (
        "role gate Lead_SA/Admin saja (delete_project): tingkat tertinggi, tidak ada hubungan "
        "per-proyek yang bisa lebih longgar; 403 sebelum proyek dimuat. Dikunci test_akses_k5 "
        "(role gate)",
        "SAH-2",
    ),
    ("PATCH", "/api/v1/projects/subtasks/{id_subtask}/assign"): (
        "role gate Lead_SA/Admin saja (_require_lead_sa): tingkat tertinggi, tidak ada "
        "hubungan per-proyek yang bisa lebih longgar; 403 sebelum proyek dimuat. Dikunci "
        "test_akses_k5 (role gate)",
        "SAH-3",
    ),
    ("PATCH", "/api/v1/projects/subtasks/{id_subtask}/status"): (
        "aturan kepemilikan SUBTASK (Lead_SA/Admin atau SA pemilik subtask), sengaja berbeda "
        "dari akses proyek: subtask milik SA tertentu, bukan hak seluruh pihak proyek. "
        "Dikunci test_akses_k5",
        "SAH-4",
    ),
    ("POST", "/api/v1/projects/{project_id}/assign"): (
        "role gate Lead_SA/Admin saja (_require_lead_sa): tingkat tertinggi, tidak ada "
        "hubungan per-proyek yang bisa lebih longgar; 403 sebelum proyek dimuat. Dikunci "
        "test_akses_k5 (role gate)",
        "SAH-5",
    ),
    ("POST", "/api/v1/projects/{project_id}/handover-config"): (
        "role gate Lead_SA/Admin saja (configure_handover): tingkat tertinggi, tidak ada "
        "hubungan per-proyek yang bisa lebih longgar; 403 sebelum proyek dimuat. Dikunci "
        "test_akses_k5 (role gate)",
        "SAH-6",
    ),
    ("POST", "/api/v1/projects/{project_id}/provision-folder"): (
        "role gate Lead_SA/Admin saja (_require_lead_sa): tingkat tertinggi, tidak ada "
        "hubungan per-proyek yang bisa lebih longgar; 403 sebelum proyek dimuat. Dikunci "
        "test_akses_k5 (role gate)",
        "SAH-7",
    ),
    ("POST", "/api/v1/projects/{project_id}/reassign"): (
        "role gate Lead_SA/Admin saja (_require_lead_sa): tingkat tertinggi, tidak ada "
        "hubungan per-proyek yang bisa lebih longgar; 403 sebelum proyek dimuat. Dikunci "
        "test_akses_k5 (role gate)",
        "SAH-8",
    ),
    ("POST", "/api/v1/projects/{project_id}/score-manual"): (
        "role gate Lead_SA/Admin saja (require_role): tingkat tertinggi, tidak ada hubungan "
        "per-proyek yang bisa lebih longgar; 403 sebelum proyek dimuat. Dikunci test_akses_k5 "
        "(role gate)",
        "SAH-9",
    ),
    ("POST", "/api/v1/projects/{project_id}/subtasks"): (
        "role gate Lead_SA/Admin saja (_require_lead_sa): tingkat tertinggi, tidak ada "
        "hubungan per-proyek yang bisa lebih longgar; 403 sebelum proyek dimuat. Dikunci "
        "test_akses_k5 (role gate)",
        "SAH-10",
    ),
}


# --------------------------------------------------------------------------- pemindai


def _ratakan(router_atau_app) -> list[tuple[str, APIRoute]]:
    """(path absolut, APIRoute) dalam urutan registrasi; menangani `_IncludedRouter`."""
    hasil: list[tuple[str, APIRoute]] = []
    for rute in router_atau_app.routes:
        if isinstance(rute, APIRoute):
            hasil.append((rute.path, rute))
        elif type(rute).__name__ == "_IncludedRouter":
            awalan = rute.include_context.prefix or ""
            for anak in rute.original_router.routes:
                if isinstance(anak, APIRoute):
                    hasil.append((awalan + anak.path, anak))
    return hasil


def berisi_id_proyek(rute: APIRoute, path: str) -> bool:
    nama_path = {p for p in rute.param_convertors} if hasattr(rute, "param_convertors") else set()
    nama_path |= {n for n in PARAM_ID_PROYEK if "{" + n + "}" in path}
    if nama_path & PARAM_ID_PROYEK:
        return True
    for param in rute.dependant.body_params:
        model = getattr(param.field_info, "annotation", None)
        medan = set(getattr(model, "model_fields", {}) or {})
        if (medan | {param.name}) & FIELD_BODY_ID_PROYEK:
            return True
    return False


def _adalah_titik_keputusan(obj: object) -> bool:
    return (
        getattr(obj, "__module__", None) == TITIK_KEPUTUSAN[0]
        and getattr(obj, "__name__", None) == TITIK_KEPUTUSAN[1]
    )


def _resolve(node: ast.expr, globals_: dict, closure: dict) -> object | None:
    """Resolve `a`, `a.b`, `a.b.c` secara statis dari globals/closure fungsi."""
    if isinstance(node, ast.Name):
        return closure.get(node.id, globals_.get(node.id))
    if isinstance(node, ast.Attribute):
        dasar = _resolve(node.value, globals_, closure)
        if dasar is None:
            return None
        return getattr(dasar, node.attr, None)
    return None


def _callee(fn: Callable) -> Iterable[object]:
    """Objek yang dipanggil di dalam `fn` dan bisa di-resolve secara statis."""
    try:
        sumber = textwrap.dedent(inspect.getsource(fn))
        pohon = ast.parse(sumber)
    except OSError, TypeError, SyntaxError:
        return
    globals_ = getattr(fn, "__globals__", {})
    closure = {}
    if getattr(fn, "__closure__", None):
        closure = dict(
            zip(fn.__code__.co_freevars, (c.cell_contents for c in fn.__closure__), strict=False)
        )
    for node in ast.walk(pohon):
        if isinstance(node, ast.Call):
            target = _resolve(node.func, globals_, closure)
            if target is not None:
                yield target


def _fungsi_app(obj: object) -> Callable | None:
    """Fungsi/method milik paket `app.*` yang bisa ditelusuri, atau None."""
    if isinstance(obj, type):  # konstruktor kelas: telusuri __init__ saja tidak perlu
        return None
    if isinstance(obj, types.MethodType):
        obj = obj.__func__
    if not callable(obj) or not hasattr(obj, "__code__"):
        return None
    if not (getattr(obj, "__module__", "") or "").startswith("app."):
        return None
    return obj  # type: ignore[return-value]


def memanggil_titik_keputusan(fn: Callable, kedalaman: int = KEDALAMAN_MAKS) -> bool:
    terlihat: set[int] = set()

    def _telusuri(f: Callable, sisa: int) -> bool:
        if id(f) in terlihat:
            return False
        terlihat.add(id(f))
        for target in _callee(f):
            if _adalah_titik_keputusan(target):
                return True
            anak = _fungsi_app(target)
            if anak is not None and sisa > 0 and _telusuri(anak, sisa - 1):
                return True
        return False

    return _telusuri(fn, kedalaman)


def _dependency_calls(rute: APIRoute) -> Iterable[Callable]:
    antre = list(rute.dependant.dependencies)
    while antre:
        dep = antre.pop()
        if dep.call is not None:
            yield dep.call
        antre.extend(dep.dependencies)


def rute_terlindungi(rute: APIRoute) -> bool:
    if memanggil_titik_keputusan(rute.endpoint):
        return True
    return any(
        _adalah_titik_keputusan(c) or memanggil_titik_keputusan(c)
        for c in _dependency_calls(rute)
        if c is not get_current_user
    )


def _kunci(path: str, rute: APIRoute) -> list[tuple[str, str]]:
    return [(m, path) for m in sorted(rute.methods - {"HEAD", "OPTIONS"})]


def pindai(
    rute_rata: list[tuple[str, APIRoute]],
    pengecualian: dict[tuple[str, str], tuple[str, str]],
) -> list[str]:
    """Daftar pelanggaran (kosong = bersih). Fungsi murni agar bisa diuji dengan router uji."""
    masalah: list[str] = []
    ada: set[tuple[str, str]] = set()
    for path, rute in rute_rata:
        if not berisi_id_proyek(rute, path):
            continue
        terlindungi = rute_terlindungi(rute)
        for kunci in _kunci(path, rute):
            ada.add(kunci)
            if kunci in pengecualian:
                if terlindungi:
                    masalah.append(
                        f"STALE: {kunci[0]} {kunci[1]} sudah memanggil titik keputusan; "
                        f"hapus dari PENGECUALIAN ({pengecualian[kunci][1]})"
                    )
            elif not terlindungi:
                masalah.append(
                    f"{kunci[0]} {kunci[1]} memuat id proyek tapi tidak memanggil "
                    f"ensure_project_access dan tidak ada di PENGECUALIAN"
                )
    for kunci, (alasan, tiket) in pengecualian.items():
        if kunci not in ada:
            masalah.append(f"STALE: {kunci[0]} {kunci[1]} di PENGECUALIAN tapi rutenya tidak ada")
        if not alasan.strip() or not POLA_NOMOR.match(tiket):
            masalah.append(
                f"{kunci[0]} {kunci[1]}: pengecualian wajib punya alasan dan nomor '#N' atau 'SAH-N'"
            )
    return masalah


# --------------------------------------------------------------------------- test


def test_semua_rute_berisi_id_proyek_memanggil_titik_keputusan_atau_dikecualikan():
    assert pindai(_ratakan(app), PENGECUALIAN) == []


def test_pemindai_menemukan_rute_berisi_id_proyek_dalam_jumlah_wajar():
    """Mencegah penjaga 'hijau' karena tidak menemukan apa-apa (mis. perataan rusak)."""
    ditemukan = [p for p, r in _ratakan(app) if berisi_id_proyek(r, p)]
    assert len(ditemukan) >= 30
    assert "/api/v1/projects/users/search" not in ditemukan
    assert "/api/v1/projects/pending-assignment" not in ditemukan


def test_pemindai_mengenali_rute_terlindungi_yang_ada():
    peta = {(m, p): rute_terlindungi(r) for p, r in _ratakan(app) for m in r.methods}
    for kunci in (
        ("GET", "/api/v1/projects/{project_id}/sla-status"),
        ("GET", "/api/v1/projects/{project_id}/bant-result"),
        ("GET", "/api/v1/projects/{project_id}/recommendations"),
        ("GET", "/api/v1/projects/{project_id}/documents"),
        ("GET", "/api/v1/projects/{project_id}/subtasks"),
        ("PATCH", "/api/v1/projects/{project_id}"),
        # dimigrasikan dari pemeriksa buatan sendiri di #92
        ("GET", "/api/v1/projects/{project_id}"),
        ("GET", "/api/v1/projects/{project_id}/collaborators"),
        ("DELETE", "/api/v1/projects/{project_id}/collaborators/{user_id}"),
        ("PATCH", "/api/v1/projects/{project_id}/status"),
        ("GET", "/api/v1/projects/{project_id}/handover-status"),
        ("POST", "/api/v1/projects/{project_id}/handover"),
        ("POST", "/api/v1/projects/{project_id}/requirement/regenerate"),
        ("POST", "/api/v1/projects/{project_id}/requirement/keep-version"),
        ("POST", "/api/v1/projects/{project_id}/requirement/items"),
        ("PUT", "/api/v1/projects/{project_id}/requirement/items/{item_id}"),
        ("DELETE", "/api/v1/projects/{project_id}/requirement/items/{item_id}"),
        ("PUT", "/api/v1/projects/{project_id}/qualification-answers"),
        ("POST", "/api/v1/activity-logs/{id_log}/polish"),
    ):
        assert peta[kunci] is True, kunci


def test_rute_uji_dengan_id_proyek_tanpa_cek_ditandai_pelanggaran():
    """Meta-verifikasi AC: rute baru berisi id proyek tanpa cek HARUS membuat pemindai gagal."""
    router = APIRouter()

    @router.get("/projects/{project_id}/baru")
    async def tanpa_cek(project_id: str, user=Depends(get_current_user)):
        return {"id": project_id}

    masalah = pindai(_ratakan(router), {})
    assert len(masalah) == 1 and "/projects/{project_id}/baru" in masalah[0]


def test_rute_uji_id_proyek_di_body_tanpa_cek_ditandai_pelanggaran():
    from pydantic import BaseModel

    class Muatan(BaseModel):
        id_project: str

    router = APIRouter()

    @router.post("/log-baru")
    async def tanpa_cek(payload: Muatan, user=Depends(get_current_user)):
        return {}

    assert len(pindai(_ratakan(router), {})) == 1


def test_rute_uji_dengan_cek_langsung_atau_lewat_helper_dianggap_aman():
    async def _helper(db, project, user):
        await ensure_project_access(db, project, user)

    router = APIRouter()

    @router.get("/projects/{project_id}/langsung")
    async def langsung(project_id: str, user=Depends(get_current_user)):
        await ensure_project_access(None, None, user)

    @router.get("/projects/{project_id}/via-helper")
    async def via_helper(project_id: str, user=Depends(get_current_user)):
        await _helper(None, None, user)

    # _helper di modul test (bukan app.*) tidak ditelusuri -> via-helper tetap pelanggaran
    masalah = pindai(_ratakan(router), {})
    assert [m for m in masalah if "langsung" in m] == []
    assert any("via-helper" in m for m in masalah)


def test_cek_hanya_di_komentar_atau_string_tidak_dihitung():
    router = APIRouter()

    @router.get("/projects/{project_id}/komentar")
    async def hanya_komentar(project_id: str, user=Depends(get_current_user)):
        # await ensure_project_access(db, project, user)
        return "ensure_project_access(db, project, user)"

    assert len(pindai(_ratakan(router), {})) == 1


def test_rute_tanpa_id_proyek_diabaikan():
    router = APIRouter()

    @router.get("/projects/users/search")
    async def cari(q: str, user=Depends(get_current_user)):
        return []

    assert pindai(_ratakan(router), {}) == []


def test_entri_pengecualian_stale_atau_tanpa_alasan_ditandai():
    router = APIRouter()

    @router.get("/projects/{project_id}/x")
    async def x(project_id: str, user=Depends(get_current_user)):
        await ensure_project_access(None, None, user)

    stale = pindai(_ratakan(router), {("GET", "/projects/{project_id}/x"): ("alasan", "#99")})
    hilang = pindai(_ratakan(router), {("GET", "/tidak/ada/{project_id}"): ("alasan", "#99")})
    tanpa_alasan = pindai(
        _ratakan(APIRouter()), {("GET", "/a"): ("", "#99"), ("GET", "/b"): ("alasan", "tiket")}
    )
    assert any("STALE" in m for m in stale)
    assert any("STALE" in m for m in hilang)
    assert sum("wajib punya alasan" in m for m in tanpa_alasan) == 2


def test_setiap_entri_pengecualian_adalah_pengecualian_sah_bernomor_unik():
    """Hasil akhir #92: tidak ada lagi entri 'tiket pembersih'; semuanya SAH-n, unik, beralasan."""
    nomor = [tiket for _alasan, tiket in PENGECUALIAN.values()]
    assert all(re.fullmatch(r"SAH-\d+", n) for n in nomor), nomor
    assert len(set(nomor)) == len(nomor)
    for kunci, (alasan, _tiket) in PENGECUALIAN.items():
        assert len(alasan.split()) >= 8, f"alasan terlalu pendek untuk {kunci}"


def test_pengecualian_sah_hanya_role_gate_atau_kepemilikan_subtask():
    """Cegah pengecualian baru diam-diam: tiap alasan harus menyebut role gate atau subtask."""
    for kunci, (alasan, _tiket) in PENGECUALIAN.items():
        assert "role gate" in alasan or "SUBTASK" in alasan, kunci
