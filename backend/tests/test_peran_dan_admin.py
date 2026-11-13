"""
Role fungsional tunggal + flag `is_admin` (issue #114, ADR 0012).

Seam: antarmuka publik `app.core.dependencies` (`hubungan_proyek`, `require_privileged`,
`require_admin`, `PeranUser`) dan kontrak role di `app.core.config`.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import VALID_ROLES
from app.core.database import get_db
from app.core.dependencies import (
    PeranUser,
    get_current_user,
    hubungan_proyek,
    require_admin,
    require_privileged,
)
from app.core.exceptions import register_exception_handlers
from tests._auth_support import SesiPalsu, buat_token, user_palsu


def _proyek() -> SimpleNamespace:
    return SimpleNamespace(id_project="PRJ-1", sales_pic=uuid.uuid4(), assigned_sa=None)


def test_role_valid_adalah_empat_role_fungsional_tanpa_admin():
    assert VALID_ROLES == ("Sales", "Product", "SA", "Lead_SA")
    assert {p.value for p in PeranUser} == set(VALID_ROLES)


@pytest.mark.parametrize(
    ("role", "is_admin", "privileged"),
    [
        ("Lead_SA", False, True),  # Lead_SA privileged tanpa flag
        ("SA", True, True),  # SA + is_admin privileged
        ("Sales", True, True),
        ("Product", True, True),
        ("SA", False, False),
        ("Sales", False, False),
        ("Product", False, False),
    ],
)
async def test_privileged_adalah_lead_sa_atau_is_admin(role, is_admin, privileged):
    user = user_palsu(role, is_admin=is_admin)
    h = await hubungan_proyek(SesiPalsu(None), _proyek(), user)
    assert h.privileged is privileged


def _app(user) -> tuple[TestClient, dict[str, str]]:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/privileged", dependencies=[Depends(require_privileged)])
    async def privileged():
        return {"ok": True}

    @app.get("/admin", dependencies=[Depends(require_admin)])
    async def admin():
        return {"ok": True}

    async def _db():
        yield SesiPalsu(user)

    app.dependency_overrides[get_db] = _db
    return TestClient(app), {"Authorization": f"Bearer {buat_token(user.id)}"}


@pytest.mark.parametrize(
    ("role", "is_admin", "jalur", "status"),
    [
        ("Lead_SA", False, "/privileged", 200),
        ("SA", True, "/privileged", 200),
        ("SA", False, "/privileged", 403),
        ("Product", False, "/privileged", 403),
        ("SA", True, "/admin", 200),
        ("Lead_SA", True, "/admin", 200),
        ("Lead_SA", False, "/admin", 403),  # Lead_SA bukan admin
        ("Sales", False, "/admin", 403),
    ],
)
def test_gerbang_privileged_dan_admin(role, is_admin, jalur, status):
    user = user_palsu(role, is_admin=is_admin)
    klien, header = _app(user)
    assert klien.get(jalur, headers=header).status_code == status
