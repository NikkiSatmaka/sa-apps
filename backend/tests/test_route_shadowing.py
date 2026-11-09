"""
Regresi: route literal tidak boleh tertangkap route berparameter yang
terdaftar lebih dulu.

Starlette mencocokkan route sesuai urutan registrasi. Sebelumnya
`GET /projects/pending-assignment` (router assignment) selalu 404 karena
`GET /projects/{project_id}` (router projects) di-include lebih dulu dan
menangkap "pending-assignment" sebagai project_id.
"""

from fastapi.routing import APIRoute
from starlette.routing import Match

from app.main import app


def _flatten_api_routes() -> list[APIRoute]:
    """Kumpulkan seluruh APIRoute dalam urutan registrasi, lengkap dengan prefix.

    Sejak FastAPI 0.162 `app.include_router(...)` tidak lagi meratakan route
    anak ke `app.routes` sebagai APIRoute top-level; sebagai gantinya muncul
    wrapper `_IncludedRouter` yang menyimpan router asli di `original_router`
    dan prefix include (mis. `/api/v1`) di `include_context.prefix`. Path pada
    route anak relatif terhadap prefix itu, jadi kita gabungkan ulang menjadi
    path absolut agar pencocokan via `Route.matches()` tetap sahih.

    Tetap kompatibel dengan FastAPI lama: APIRoute top-level ikut dikumpulkan
    apa adanya.
    """

    flattened: list[APIRoute] = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            flattened.append(route)
        elif type(route).__name__ == "_IncludedRouter":
            prefix = route.include_context.prefix or ""
            for sub in route.original_router.routes:
                if isinstance(sub, APIRoute):
                    flattened.append(_prefixed_route(sub, prefix))
    return flattened


def _prefixed_route(route: APIRoute, prefix: str) -> APIRoute:
    """APIRoute salinan-dangkal dengan path diberi prefix include.

    Kita hanya butuh `path`/`path_regex`/`methods`/`endpoint` untuk uji
    shadowing, jadi cukup bangun ulang APIRoute dengan path absolut daripada
    memutasi objek milik router asli.
    """

    if not prefix:
        return route
    return APIRoute(
        prefix + route.path,
        route.endpoint,
        methods=list(route.methods or []),
        include_in_schema=False,
    )


def _shadowed_routes() -> list[str]:
    routes = _flatten_api_routes()
    problems = []
    for i, route in enumerate(routes):
        if "{" in route.path:
            continue
        for method in route.methods:
            scope = {"type": "http", "path": route.path, "method": method}
            for earlier in routes[:i]:
                match, _ = earlier.matches(scope)
                if match == Match.FULL:
                    problems.append(
                        f"{method} {route.path} tertangkap oleh {earlier.path}"
                    )
                    break
    return problems


def test_tidak_ada_route_literal_yang_tertangkap_route_lain():
    assert _shadowed_routes() == []


def test_pending_assignment_sampai_ke_handler_assignment():
    scope = {
        "type": "http",
        "path": "/api/v1/projects/pending-assignment",
        "method": "GET",
    }
    handler = next(
        r.endpoint
        for r in _flatten_api_routes()
        if r.matches(scope)[0] == Match.FULL
    )
    assert handler.__name__ == "get_pending_projects"
