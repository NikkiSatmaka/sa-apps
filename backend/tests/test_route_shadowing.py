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


def _shadowed_routes() -> list[str]:
    routes = [r for r in app.routes if isinstance(r, APIRoute)]
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
        for r in app.routes
        if isinstance(r, APIRoute) and r.matches(scope)[0] == Match.FULL
    )
    assert handler.__name__ == "get_pending_projects"
