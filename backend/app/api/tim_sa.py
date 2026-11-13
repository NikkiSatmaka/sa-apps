"""
API Tim SA per proyek: SA utama (`Project.assigned_sa`) + SA tambahan (`ProjectAssignments`).

Endpoints (ADR 0014, spec §2.5):
- GET    /projects/{project_id}/tim-sa                 — baca tim (semua pengguna terautentikasi)
- POST   /projects/{project_id}/tim-sa                 — tambah SA tambahan (Lead_SA/Admin)
- DELETE /projects/{project_id}/tim-sa/{user_id}       — lepas SA tambahan atau SA utama
- PUT    /projects/{project_id}/tim-sa/utama           — ganti SA utama

Aturan: hanya Lead_SA/Admin yang mengatur tim; SA utama tidak diulang di tabel
`project_assignments`; setelah `Assigned` project minimal punya satu SA, jadi SA utama hanya
bisa dilepas bila ada SA tambahan yang naik menggantikannya. Setiap perubahan masuk audit log.
Drive Editor, SLA, dan notifikasi mengikuti penugasan di tiket Orang-4 (#120).
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    PERAN_DAPAT_DITUGASKAN,
    TingkatAkses,
    ensure_project_access,
    get_current_user,
)
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.project_assignment import ProjectAssignment
from app.models.user import User
from app.schemas.response import success_response
from app.schemas.tim_sa import (
    AnggotaSA,
    AnggotaSATambahan,
    GantiSAUtamaRequest,
    TambahSATambahanRequest,
    TimSAResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Tim SA"])


def _ditolak(kode: int, pesan: str) -> HTTPException:
    return HTTPException(status_code=kode, detail=pesan)


async def _muat_proyek(db: AsyncSession, project_id: str) -> Project:
    proyek = (
        await db.execute(select(Project).where(Project.id_project == project_id))
    ).scalar_one_or_none()
    if proyek is None:
        raise _ditolak(
            status.HTTP_404_NOT_FOUND, f"Proyek dengan ID '{project_id}' tidak ditemukan."
        )
    return proyek


async def _muat_kandidat(db: AsyncSession, user_id: uuid.UUID) -> User:
    """User yang boleh ditugaskan sebagai SA: ada (404) dan berrole SA/Lead_SA (400)."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise _ditolak(status.HTTP_404_NOT_FOUND, f"User dengan ID '{user_id}' tidak ditemukan.")
    if user.role not in PERAN_DAPAT_DITUGASKAN:
        raise _ditolak(
            status.HTTP_400_BAD_REQUEST,
            f"User '{user.name}' memiliki role '{user.role}', bukan 'SA' atau 'Lead_SA'. "
            "Hanya SA atau Lead_SA yang bisa masuk tim SA.",
        )
    return user


async def _muat_penugasan(db: AsyncSession, project_id: str) -> list[ProjectAssignment]:
    hasil = await db.execute(
        select(ProjectAssignment)
        .where(ProjectAssignment.id_project == project_id)
        .order_by(ProjectAssignment.created_at, ProjectAssignment.id)
        .execution_options(populate_existing=True)
    )
    return list(hasil.scalars())


def _snapshot(proyek: Project, penugasan: list[ProjectAssignment]) -> dict:
    return {
        "sa_utama": str(proyek.assigned_sa) if proyek.assigned_sa else None,
        "sa_tambahan": [str(p.user_id) for p in penugasan],
    }


async def _bangun_tim(db: AsyncSession, proyek: Project) -> dict:
    penugasan = await _muat_penugasan(db, proyek.id_project)
    ids = {p.user_id for p in penugasan}
    if proyek.assigned_sa:
        ids.add(proyek.assigned_sa)
    orang: dict[uuid.UUID, User] = {}
    if ids:
        orang = {
            u.id: u for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars()
        }
    utama = orang.get(proyek.assigned_sa) if proyek.assigned_sa else None
    return TimSAResponse(
        sa_utama=AnggotaSA(id=utama.id, name=utama.name, email=utama.email) if utama else None,
        sa_tambahan=[
            AnggotaSATambahan(
                id=p.user_id,
                name=orang[p.user_id].name,
                email=orang[p.user_id].email,
                added_by=p.added_by,
                created_at=p.created_at,
            )
            for p in penugasan
        ],
    ).model_dump(mode="json")


def _catat(
    db: AsyncSession, proyek: Project, pelaku: User, aksi: str, lama: dict, baru: dict
) -> None:
    db.add(
        AuditLog(
            id=f"AUD-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:6]}",
            entity_type="project",
            entity_id=proyek.id_project,
            action=aksi,
            performed_by=pelaku.id,
            old_value=lama,
            new_value=baru,
            created_at=datetime.now(UTC),
        )
    )


async def _proyek_untuk_kelola(db: AsyncSession, project_id: str, pelaku: User) -> Project:
    """Muat proyek (404) lalu tegakkan hak atur tim: hanya Lead_SA/Admin (403)."""
    proyek = await _muat_proyek(db, project_id)
    await ensure_project_access(
        db,
        proyek,
        pelaku,
        TingkatAkses.KELOLA_TIM_SA,
        pesan="Hanya Lead_SA atau Admin yang dapat mengatur tim SA.",
    )
    return proyek


def _butuh_sa_utama(proyek: Project) -> None:
    if proyek.assigned_sa is None:
        raise _ditolak(
            status.HTTP_409_CONFLICT,
            "Proyek belum punya SA utama. Tugaskan SA utama lebih dulu lewat assign.",
        )


async def _naikkan_sa_utama(
    db: AsyncSession,
    proyek: Project,
    user_id: uuid.UUID,
    pelaku: User,
    *,
    pertahankan_lama: bool,
) -> None:
    """Jadikan `user_id` SA utama: keluarkan dari tabel (utama tidak diulang), lalu SA lama
    dilepas atau dijadikan SA tambahan."""
    sa_lama = proyek.assigned_sa
    await db.execute(
        delete(ProjectAssignment).where(
            ProjectAssignment.id_project == proyek.id_project,
            ProjectAssignment.user_id == user_id,
        )
    )
    proyek.assigned_sa = user_id
    proyek.updated_at = datetime.now(UTC)
    if pertahankan_lama and sa_lama is not None:
        db.add(ProjectAssignment(id_project=proyek.id_project, user_id=sa_lama, added_by=pelaku.id))


@router.get(
    "/{project_id}/tim-sa",
    summary="Baca tim SA project",
    description="SA utama dan SA tambahan. Terbuka untuk semua pengguna terautentikasi.",
)
async def baca_tim_sa(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proyek = await _muat_proyek(db, project_id)
    await ensure_project_access(db, proyek, current_user, TingkatAkses.BACA)
    return success_response(data=await _bangun_tim(db, proyek), message="Tim SA berhasil diambil.")


@router.post(
    "/{project_id}/tim-sa",
    status_code=status.HTTP_201_CREATED,
    summary="Tambah SA tambahan",
    description="Menambah SA tambahan (hak setara SA utama). Hanya Lead_SA atau Admin.",
)
async def tambah_sa_tambahan(
    project_id: str,
    body: TambahSATambahanRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proyek = await _proyek_untuk_kelola(db, project_id, current_user)
    _butuh_sa_utama(proyek)
    kandidat = await _muat_kandidat(db, body.user_id)
    penugasan = await _muat_penugasan(db, project_id)
    if kandidat.id == proyek.assigned_sa or kandidat.id in {p.user_id for p in penugasan}:
        raise _ditolak(
            status.HTTP_409_CONFLICT, f"'{kandidat.name}' sudah menjadi anggota tim SA proyek ini."
        )

    lama = _snapshot(proyek, penugasan)
    db.add(ProjectAssignment(id_project=project_id, user_id=kandidat.id, added_by=current_user.id))
    await db.flush()
    baru = _snapshot(proyek, await _muat_penugasan(db, project_id))
    _catat(db, proyek, current_user, "sa_tambahan_ditambah", lama, baru)
    await db.commit()
    logger.info(
        "SA tambahan %s ditambah ke %s oleh %s", kandidat.email, project_id, current_user.email
    )
    return success_response(
        data=await _bangun_tim(db, proyek), message=f"{kandidat.name} ditambahkan ke tim SA."
    )


@router.put(
    "/{project_id}/tim-sa/utama",
    summary="Ganti SA utama",
    description=(
        "Mengganti SA utama (penanggung jawab). SA utama lama dilepas, atau tetap sebagai SA "
        "tambahan bila `pertahankan_sebagai_tambahan`. Hanya Lead_SA atau Admin."
    ),
)
async def ganti_sa_utama(
    project_id: str,
    body: GantiSAUtamaRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proyek = await _proyek_untuk_kelola(db, project_id, current_user)
    _butuh_sa_utama(proyek)
    baru_utama = await _muat_kandidat(db, body.user_id)
    if baru_utama.id == proyek.assigned_sa:
        raise _ditolak(
            status.HTTP_409_CONFLICT, f"'{baru_utama.name}' sudah menjadi SA utama proyek ini."
        )

    lama = _snapshot(proyek, await _muat_penugasan(db, project_id))
    await _naikkan_sa_utama(
        db, proyek, baru_utama.id, current_user, pertahankan_lama=body.pertahankan_sebagai_tambahan
    )
    await db.flush()
    baru = _snapshot(proyek, await _muat_penugasan(db, project_id))
    _catat(db, proyek, current_user, "sa_utama_diganti", lama, baru)
    await db.commit()
    logger.info(
        "SA utama %s diganti ke %s oleh %s", project_id, baru_utama.email, current_user.email
    )
    return success_response(
        data=await _bangun_tim(db, proyek), message=f"SA utama diganti ke {baru_utama.name}."
    )


@router.delete(
    "/{project_id}/tim-sa/{user_id}",
    summary="Lepas SA dari tim",
    description=(
        "Melepas SA tambahan. Melepas SA utama menuntut `sa_utama_baru` dari SA tambahan; tanpa "
        "SA tambahan, SA utama tidak bisa dilepas (minimal satu SA). Hanya Lead_SA atau Admin."
    ),
)
async def lepas_sa(
    project_id: str,
    user_id: uuid.UUID,
    sa_utama_baru: uuid.UUID | None = Query(
        default=None, description="Wajib saat melepas SA utama yang masih punya SA tambahan"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proyek = await _proyek_untuk_kelola(db, project_id, current_user)
    penugasan = await _muat_penugasan(db, project_id)
    anggota = {p.user_id for p in penugasan}
    lama = _snapshot(proyek, penugasan)

    if user_id == proyek.assigned_sa:
        if not anggota:
            raise _ditolak(
                status.HTTP_409_CONFLICT,
                "Project minimal punya satu SA: tambahkan SA tambahan atau ganti SA utama "
                "sebelum melepas SA utama.",
            )
        if sa_utama_baru is None:
            raise _ditolak(
                status.HTTP_409_CONFLICT,
                "SA utama masih punya SA tambahan: pilih SA utama baru (`sa_utama_baru`) dari "
                "SA tambahan.",
            )
        if sa_utama_baru not in anggota:
            raise _ditolak(
                status.HTTP_400_BAD_REQUEST,
                "SA utama baru harus salah satu SA tambahan project ini.",
            )
        await _naikkan_sa_utama(db, proyek, sa_utama_baru, current_user, pertahankan_lama=False)
        aksi = "sa_utama_diganti"
    elif user_id in anggota:
        await db.execute(
            delete(ProjectAssignment).where(
                ProjectAssignment.id_project == project_id, ProjectAssignment.user_id == user_id
            )
        )
        aksi = "sa_tambahan_dilepas"
    else:
        raise _ditolak(status.HTTP_404_NOT_FOUND, "User bukan anggota tim SA proyek ini.")

    await db.flush()
    baru = _snapshot(proyek, await _muat_penugasan(db, project_id))
    _catat(db, proyek, current_user, aksi, lama, baru)
    await db.commit()
    logger.info("SA %s dilepas dari %s oleh %s", user_id, project_id, current_user.email)
    return success_response(data=await _bangun_tim(db, proyek), message="SA dilepas dari tim.")
