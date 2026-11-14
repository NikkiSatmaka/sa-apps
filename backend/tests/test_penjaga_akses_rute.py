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

Daftar `PENGECUALIAN`: tiap entri = rute, alasan, dan nomor `SAH-N` (pengecualian sah). Ratchet:
entri yang rutenya sudah memanggil titik keputusan, atau rutenya tak ada lagi, membuat test GAGAL.
Satu entri per baris, urut, supaya diff antar-tiket tidak beririsan.

Penjaga kedua (`pelanggaran_try`): panggilan titik keputusan (langsung atau lewat fungsi `app.*`
yang memanggilnya) tidak boleh berada di badan `try` yang `except`-nya menangkap `Exception`/
`BaseException`/bare/`HTTPException` tanpa re-raise, karena 403 akan tertelan (jadi 500 atau 200).

Keterbatasan pemindai yang DIKUNCI test (`test_keterbatasan_*`), bukan kebetulan:
- fungsi bersarang yang tidak pernah dipanggil, dan cabang mati (`if False:`), tetap dihitung
  sebagai "memanggil titik keputusan" (analisis AST tidak mengeksekusi kode);
- panggilan dinamis (`getattr`, method pada instance yang tak bisa di-resolve) tidak terlihat;
- `pelanggaran_try` menganggap `raise` apa pun yang bare / me-raise nama `as` sebagai re-raise,
  tanpa memeriksa apakah jalur itu selalu tercapai.
"""

import ast
import inspect
import re
import textwrap
import types
from collections.abc import Callable, Iterable

import pytest
from fastapi import APIRouter, Depends
from fastapi.routing import APIRoute

from app.core.dependencies import ensure_project_access, get_current_user
from app.main import app

TITIK_KEPUTUSAN = ("app.core.dependencies", "ensure_project_access")
PARAM_ID_PROYEK = {"project_id", "id_project", "doc_id", "id_log", "id_subtask"}
FIELD_BODY_ID_PROYEK = {"id_project", "project_id"}
KEDALAMAN_MAKS = 5
POLA_NOMOR = re.compile(r"^(#\d+|SAH-\d+)$")

# Alasan tunggal untuk semua role gate murni (satu konstanta agar tidak berulang di tiap entri).
ALASAN_ROLE_GATE = (
    "role gate Lead_SA/Admin saja: tingkat tertinggi, tidak ada hubungan per-proyek yang bisa "
    "lebih longgar; 403 sebelum proyek dimuat. Dikunci test_akses_k5 (role gate)"
)

# (METHOD, path absolut) -> (alasan, nomor "SAH-n")
# Hasil akhir #92: HANYA pengecualian yang SAH. Rute yang dulu punya pemeriksa buatan sendiri
# (workflow, handover, Requirement, collaborators, detail proyek, kuesioner, polish) sudah
# dimigrasikan ke titik keputusan bersama dan dikeluarkan dari daftar ini. Yang tersisa hanya
# role gate murni Lead_SA/Admin. `PATCH .../subtasks/{id}/status` (dulu SAH-4, kepemilikan
# subtask) kini memanggil titik keputusan (TULIS) sehingga keluar dari daftar; nomor SAH-4
# tidak dipakai ulang. `POST .../subtasks` (dulu SAH-10) keluar sejak #147 (SA ditugaskan boleh
# membuat subtask, spec §2.0/§2.5); nomor SAH-10 juga tidak dipakai ulang. Menambah entri baru
# memerlukan alasan spesifik + nomor SAH berikutnya +
# test integrasi yang mengunci aturannya.
PENGECUALIAN: dict[tuple[str, str], tuple[str, str]] = {
    ("DELETE", "/api/v1/projects/subtasks/{id_subtask}"): (
        ALASAN_ROLE_GATE,
        "SAH-1",
    ),
    ("DELETE", "/api/v1/projects/{project_id}"): (
        ALASAN_ROLE_GATE,
        "SAH-2",
    ),
    ("PATCH", "/api/v1/projects/subtasks/{id_subtask}/assign"): (
        ALASAN_ROLE_GATE,
        "SAH-3",
    ),
    ("PATCH", "/api/v1/projects/{project_id}/people"): (
        ALASAN_ROLE_GATE,
        "SAH-11",
    ),
    ("POST", "/api/v1/projects/{project_id}/assign"): (
        ALASAN_ROLE_GATE,
        "SAH-5",
    ),
    ("POST", "/api/v1/projects/{project_id}/handover-config"): (
        ALASAN_ROLE_GATE,
        "SAH-6",
    ),
    ("POST", "/api/v1/projects/{project_id}/provision-folder"): (
        ALASAN_ROLE_GATE,
        "SAH-7",
    ),
    ("POST", "/api/v1/projects/{project_id}/reassign"): (
        ALASAN_ROLE_GATE,
        "SAH-8",
    ),
    ("POST", "/api/v1/projects/{project_id}/score-manual"): (
        ALASAN_ROLE_GATE,
        "SAH-9",
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


def _pohon_dan_konteks(fn: Callable) -> tuple[ast.AST, dict, dict] | None:
    """AST sumber `fn` beserta globals dan closure-nya, atau None bila sumber tak tersedia."""
    try:
        sumber = textwrap.dedent(inspect.getsource(fn))
        pohon = ast.parse(sumber)
    except OSError, TypeError, SyntaxError:
        return None
    globals_ = getattr(fn, "__globals__", {})
    closure = {}
    if getattr(fn, "__closure__", None):
        closure = dict(
            zip(fn.__code__.co_freevars, (c.cell_contents for c in fn.__closure__), strict=False)
        )
    return pohon, globals_, closure


def _callee(fn: Callable) -> Iterable[object]:
    """Objek yang dipanggil di dalam `fn` dan bisa di-resolve secara statis."""
    konteks = _pohon_dan_konteks(fn)
    if konteks is None:
        return
    pohon, globals_, closure = konteks
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


# --------------------------------------------------------------------------- try yang menelan 403

TANGKAP_SEMUA = {"Exception", "BaseException"}
NAMA_HTTP_EXCEPTION = {"HTTPException"}


def _nama_tipe(node: ast.expr | None) -> set[str]:
    """Nama tipe pada `except <tipe>` (Name/Attribute/Tuple); bare except = {"*"}."""
    if node is None:
        return {"*"}
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    if isinstance(node, ast.Tuple):
        return set().union(*(_nama_tipe(e) for e in node.elts))
    return set()


def _melempar_ulang(handler: ast.ExceptHandler) -> bool:
    """`raise` polos, atau `raise <nama as>`, di badan handler (tidak masuk fungsi bersarang)."""
    antre = list(handler.body)
    while antre:
        node = antre.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        if isinstance(node, ast.Raise):
            if node.exc is None:
                return True
            if isinstance(node.exc, ast.Name) and node.exc.id == handler.name:
                return True
        antre.extend(ast.iter_child_nodes(node))
    return False


def _try_menelan_403(node: ast.Try | ast.TryStar) -> bool:
    """Apakah `HTTPException` 403 dari badan `try` ini tertelan oleh handler-nya?

    Handler pertama yang bisa menangkap `HTTPException` (bare, `Exception`, `BaseException`, atau
    `HTTPException` sendiri) menentukan: tanpa re-raise = tertelan; dengan re-raise = lolos.
    """
    for handler in node.handlers:
        nama = _nama_tipe(handler.type)
        if "*" in nama or nama & TANGKAP_SEMUA or nama & NAMA_HTTP_EXCEPTION:
            return not _melempar_ulang(handler)
    return False


def _simpul_badan(badan: list[ast.stmt]) -> Iterable[ast.AST]:
    """Semua simpul di `badan` tanpa masuk fungsi/lambda bersarang (tidak dieksekusi di sini)."""
    antre = list(badan)
    while antre:
        node = antre.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        yield node
        antre.extend(ast.iter_child_nodes(node))


def _membawa_titik_keputusan(target: object) -> bool:
    if _adalah_titik_keputusan(target):
        return True
    fungsi = _fungsi_app(target)
    return fungsi is not None and memanggil_titik_keputusan(fungsi)


def pelanggaran_try(fn: Callable) -> list[int]:
    """Nomor baris (relatif sumber `fn`) tiap `try` yang menelan 403 dari titik keputusan.

    Hanya BADAN `try` yang dilindungi handler-nya: panggilan di `else`/`finally`/badan handler
    tidak dihitung. Panggilan dihitung bila resolve ke titik keputusan atau ke fungsi `app.*`
    yang (sampai kedalaman pemindai) memanggilnya.
    """
    konteks = _pohon_dan_konteks(fn)
    if konteks is None:
        return []
    pohon, globals_, closure = konteks
    baris: list[int] = []
    for node in ast.walk(pohon):
        if not isinstance(node, ast.Try | ast.TryStar) or not _try_menelan_403(node):
            continue
        for sub in _simpul_badan(node.body):
            if isinstance(sub, ast.Call) and _membawa_titik_keputusan(
                _resolve(sub.func, globals_, closure)
            ):
                baris.append(node.lineno)
                break
    return sorted(baris)


def _fungsi_terjangkau(awal: Callable, kedalaman: int = KEDALAMAN_MAKS) -> list[Callable]:
    """`awal` beserta fungsi `app.*` yang terjangkau darinya (penelusuran sama dengan pemindai)."""
    terlihat: dict[int, Callable] = {}

    def _telusuri(f: Callable, sisa: int) -> None:
        if id(f) in terlihat:
            return
        terlihat[id(f)] = f
        if sisa <= 0:
            return
        for target in _callee(f):
            anak = _fungsi_app(target)
            if anak is not None:
                _telusuri(anak, sisa - 1)

    _telusuri(awal, kedalaman)
    return list(terlihat.values())


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
                f"{kunci[0]} {kunci[1]}: pengecualian wajib punya alasan dan nomor "
                "'#N' atau 'SAH-N'"
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


def test_pengecualian_sah_hanya_role_gate():
    """Cegah pengecualian baru diam-diam: satu-satunya alasan sah adalah role gate murni."""
    for kunci, (alasan, _tiket) in PENGECUALIAN.items():
        assert alasan == ALASAN_ROLE_GATE, kunci


# --------------------------------------------------------------------------- try yang menelan 403


def test_tidak_ada_titik_keputusan_di_dalam_try_yang_menelan_http_exception():
    """403 dari titik keputusan tidak boleh berubah jadi 500/200 oleh `try/except Exception`."""
    pelanggar = []
    for path, rute in _ratakan(app):
        for fn in _fungsi_terjangkau(rute.endpoint):
            for baris in pelanggaran_try(fn):
                pelanggar.append(f"{fn.__module__}.{fn.__qualname__} (baris {baris}) via {path}")
    assert sorted(set(pelanggar)) == []


def test_pemindai_try_menjangkau_fungsi_app_dalam_jumlah_wajar():
    """Mencegah penjaga 'hijau' karena penelusuran tidak menemukan fungsi apa pun."""
    fungsi = {f for _p, r in _ratakan(app) for f in _fungsi_terjangkau(r.endpoint)}
    assert len(fungsi) >= 100


async def _helper_app(db, project, user):
    await ensure_project_access(db, project, user)


# `_helper_app` berpura-pura milik paket app.* agar ditelusuri (modul test tidak ditelusuri).
_helper_app.__module__ = "app.pura_pura"


async def _handler_menelan(db, project, user):
    try:
        await ensure_project_access(db, project, user)
    except Exception:
        return "ditelan"


async def _handler_bare(db, project, user):
    try:
        await ensure_project_access(db, project, user)
    except:  # noqa: E722
        return "ditelan"


async def _handler_base_exception(db, project, user):
    try:
        await ensure_project_access(db, project, user)
    except BaseException:
        return "ditelan"


async def _handler_tuple(db, project, user):
    try:
        await ensure_project_access(db, project, user)
    except ValueError, Exception:
        return "ditelan"


async def _handler_http_exception_ditelan(db, project, user):
    from fastapi import HTTPException

    try:
        await ensure_project_access(db, project, user)
    except HTTPException:
        return "ditelan"


async def _handler_via_helper(db, project, user):
    try:
        await _helper_app(db, project, user)
    except Exception:
        return "ditelan"


async def _handler_raise_jadi_500(db, project, user):
    try:
        await ensure_project_access(db, project, user)
    except Exception as e:
        raise RuntimeError("gagal") from e


async def _handler_re_raise_polos(db, project, user):
    try:
        await ensure_project_access(db, project, user)
    except Exception:
        raise


async def _handler_re_raise_nama(db, project, user):
    try:
        await ensure_project_access(db, project, user)
    except Exception as e:
        raise e


async def _handler_http_exception_lolos_dulu(db, project, user):
    from fastapi import HTTPException

    try:
        await ensure_project_access(db, project, user)
    except HTTPException:
        raise
    except Exception:
        return "hanya galat lain yang ditelan"


async def _handler_tipe_sempit(db, project, user):
    try:
        await ensure_project_access(db, project, user)
    except ValueError:
        return "tidak menangkap HTTPException"


async def _handler_cek_di_luar_try(db, project, user):
    await ensure_project_access(db, project, user)
    try:
        return await _kerja()
    except Exception:
        return "gagal kerja"


async def _handler_cek_di_finally_else_dan_handler(db, project, user):
    try:
        await _kerja()
    except Exception:
        await ensure_project_access(db, project, user)
    else:
        await ensure_project_access(db, project, user)
    finally:
        await ensure_project_access(db, project, user)


async def _handler_fungsi_bersarang_di_try(db, project, user):
    try:

        async def _tidak_dipanggil():
            await ensure_project_access(db, project, user)

    except Exception:
        return "tidak dieksekusi di dalam try"


async def _kerja():
    return None


@pytest.mark.parametrize(
    "fn",
    [
        _handler_menelan,
        _handler_bare,
        _handler_base_exception,
        _handler_tuple,
        _handler_http_exception_ditelan,
        _handler_via_helper,
        _handler_raise_jadi_500,
    ],
)
def test_pelanggaran_try_mendeteksi_403_yang_tertelan(fn):
    assert len(pelanggaran_try(fn)) == 1


@pytest.mark.parametrize(
    "fn",
    [
        _handler_re_raise_polos,
        _handler_re_raise_nama,
        _handler_http_exception_lolos_dulu,
        _handler_tipe_sempit,
        _handler_cek_di_luar_try,
        _handler_cek_di_finally_else_dan_handler,
        _handler_fungsi_bersarang_di_try,
    ],
)
def test_pelanggaran_try_tidak_menandai_403_yang_lolos(fn):
    assert pelanggaran_try(fn) == []


def test_pelanggaran_try_via_fungsi_non_app_tidak_terlihat():
    """KETERBATASAN (dikunci): helper di luar paket `app.*` tidak ditelusuri, sehingga `try`
    yang membungkus helper itu tidak ditandai. Fungsi `app.*` ditelusuri (lihat
    `_handler_via_helper`)."""

    async def helper_luar(db, project, user):
        await ensure_project_access(db, project, user)

    async def handler(db, project, user):
        try:
            await helper_luar(db, project, user)
        except Exception:
            return "ditelan"

    assert pelanggaran_try(handler) == []


# --------------------------------------------------------------------------- keterbatasan pemindai


def test_keterbatasan_fungsi_bersarang_tak_dipanggil_dihitung_sebagai_cek():
    """KETERBATASAN (dikunci): pemindai menelusuri AST apa adanya, jadi fungsi bersarang yang
    memanggil titik keputusan tetapi TIDAK PERNAH dipanggil tetap membuat rute dianggap
    terlindungi (false negative). Ditangkap test integrasi peran × aksi, bukan pemindai ini."""
    router = APIRouter()

    @router.get("/projects/{project_id}/bersarang")
    async def bersarang(project_id: str, user=Depends(get_current_user)):
        async def _tak_pernah_dipanggil():
            await ensure_project_access(None, None, user)

        return {}

    assert pindai(_ratakan(router), {}) == []


def test_keterbatasan_cabang_mati_dihitung_sebagai_cek():
    """KETERBATASAN (dikunci): cek di cabang yang tak pernah tercapai (`if False:`) tetap dihitung
    karena pemindai tidak mengevaluasi kondisi."""
    router = APIRouter()

    @router.get("/projects/{project_id}/mati")
    async def mati(project_id: str, user=Depends(get_current_user)):
        if False:
            await ensure_project_access(None, None, user)
        return {}

    assert pindai(_ratakan(router), {}) == []


def test_keterbatasan_cek_hanya_di_sebagian_cabang_dianggap_terlindungi():
    """KETERBATASAN (dikunci): cek yang hanya ada di satu cabang `if` membuat rute dianggap
    terlindungi walau cabang lain lolos tanpa cek (pemindai tidak memeriksa semua jalur)."""
    router = APIRouter()

    @router.get("/projects/{project_id}/sebagian")
    async def sebagian(project_id: str, bendera: bool = False, user=Depends(get_current_user)):
        if bendera:
            await ensure_project_access(None, None, user)
        return {}

    assert pindai(_ratakan(router), {}) == []


def test_keterbatasan_panggilan_dinamis_tidak_terlihat():
    """KETERBATASAN (dikunci): `getattr(...)(...)` tidak bisa di-resolve statis, sehingga cek
    yang dipanggil secara dinamis TIDAK dikenali dan rute ditandai pelanggaran."""
    import app.core.dependencies as modul

    router = APIRouter()

    @router.get("/projects/{project_id}/dinamis")
    async def dinamis(project_id: str, user=Depends(get_current_user)):
        await getattr(modul, "ensure_project_access")(None, None, user)

    assert len(pindai(_ratakan(router), {})) == 1
