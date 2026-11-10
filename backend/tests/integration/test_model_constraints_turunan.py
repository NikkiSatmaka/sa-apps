"""
Constraint model turunan di Postgres nyata: ActivityLog, NotificationLog, AuditLog,
ProjectCollaborator, SLATracking, Subtask, SourceDocument (tiket B10, spec #49).

Dua arah: valid (termasuk batas) diterima; tidak valid ditolak OLEH DATABASE.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models import (
    ActivityLog,
    Project,
    ProjectCollaborator,
    SourceDocument,
    Subtask,
    User,
)
from tests.integration.model_helpers import (
    bangun_audit,
    bangun_kolaborator,
    bangun_log,
    bangun_notifikasi,
    bangun_sla,
    bangun_source_doc,
    bangun_subtask,
    bangun_user,
    ditolak,
    siapkan_proyek,
    simpan,
)

PROJECT_KATEGORI = [
    "Assessment",
    "Internal Meeting",
    "Customer Meeting",
    "Principal Meeting",
    "Commercial Document",
    "Technical Document",
    "Document Review",
]
NON_PROJECT_KATEGORI = [
    "Training",
    "Self-Lab",
    "Self-Learning",
    "Exam",
    "Internal Meeting",
    "Internal Presentation",
    "External Presentation",
    "Principal Meeting",
]


async def _ditolak_null(db, kolom: str, objek) -> None:
    with pytest.raises(IntegrityError) as err:
        async with db.begin_nested():
            db.add(objek)
            await db.flush()
    assert kolom in str(err.value)


# ============================================================================== ActivityLog


class TestActivityLog:
    @pytest.mark.parametrize("kat", PROJECT_KATEGORI)
    async def test_kategori_project_diterima(self, db_session, kat):
        user, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_log(user.id, proyek.id_project, subtask_category=kat))

    @pytest.mark.parametrize("kat", NON_PROJECT_KATEGORI)
    async def test_kategori_non_project_diterima(self, db_session, kat):
        user, _ = await siapkan_proyek(db_session)
        log = bangun_log(
            user.id, None, work_type="Non-Project", project_phase=None, subtask_category=kat
        )
        await simpan(db_session, log)

    @pytest.mark.parametrize("kat", ["Ngopi", "assessment", "", "Meeting"])
    async def test_kategori_tidak_dikenal_ditolak(self, db_session, kat):
        user, proyek = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_activity_logs_subtask_category",
            bangun_log(user.id, proyek.id_project, subtask_category=kat),
        )

    async def test_work_type_tidak_valid_ditolak(self, db_session):
        user, proyek = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_activity_logs_work_type",
            bangun_log(user.id, proyek.id_project, work_type="Lain"),
        )

    @pytest.mark.parametrize(
        "fase", ["Pre-Implementation", "Implementation", "Post-Implementation"]
    )
    async def test_fase_valid(self, db_session, fase):
        user, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_log(user.id, proyek.id_project, project_phase=fase))

    async def test_fase_tidak_valid_ditolak(self, db_session):
        user, proyek = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_activity_logs_project_phase",
            bangun_log(user.id, proyek.id_project, project_phase="Selesai"),
        )

    async def test_project_tanpa_id_project_ditolak(self, db_session):
        user, _ = await siapkan_proyek(db_session)
        await ditolak(
            db_session, "chk_activity_logs_worktype_consistency", bangun_log(user.id, None)
        )

    async def test_project_tanpa_fase_ditolak(self, db_session):
        user, proyek = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_activity_logs_worktype_consistency",
            bangun_log(user.id, proyek.id_project, project_phase=None),
        )

    async def test_non_project_dengan_id_project_ditolak(self, db_session):
        user, proyek = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_activity_logs_worktype_consistency",
            bangun_log(
                user.id,
                proyek.id_project,
                work_type="Non-Project",
                project_phase=None,
                subtask_category="Training",
            ),
        )

    async def test_non_project_dengan_fase_ditolak(self, db_session):
        user, _ = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_activity_logs_worktype_consistency",
            bangun_log(
                user.id,
                None,
                work_type="Non-Project",
                project_phase="Implementation",
                subtask_category="Training",
            ),
        )

    @pytest.mark.parametrize("durasi", ["0.25", "0.50", "1", "12.5", "24", "24.00"])
    async def test_durasi_valid_termasuk_batas(self, db_session, durasi):
        user, proyek = await siapkan_proyek(db_session)
        log = bangun_log(user.id, proyek.id_project, duration_hours=Decimal(durasi))
        await simpan(db_session, log)
        await db_session.refresh(log)
        assert log.duration_hours == Decimal(durasi)

    @pytest.mark.parametrize("durasi", ["0", "0.24", "24.01", "-1", "100"])
    async def test_durasi_di_luar_rentang_ditolak(self, db_session, durasi):
        user, proyek = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_activity_logs_duration_hours",
            bangun_log(user.id, proyek.id_project, duration_hours=Decimal(durasi)),
        )

    async def test_database_tidak_menegakkan_kelipatan_025_itu_tugas_schema(self, db_session):
        """Kelipatan 0.25 dijaga skema Pydantic; CHECK DB hanya rentang (0.30 lolos di DB)."""
        user, proyek = await siapkan_proyek(db_session)
        await simpan(
            db_session, bangun_log(user.id, proyek.id_project, duration_hours=Decimal("0.30"))
        )

    async def test_gcal_event_id_unik_hanya_bila_tidak_null(self, db_session):
        user, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_log(user.id, proyek.id_project, gcal_event_id="evt-1"))
        await ditolak(
            db_session,
            "idx_unique_gcal_mapping",
            bangun_log(user.id, proyek.id_project, gcal_event_id="evt-1"),
        )
        # Banyak log tanpa event Calendar (NULL) sah; event lain sah.
        await simpan(
            db_session,
            bangun_log(user.id, proyek.id_project, gcal_event_id=None),
            bangun_log(user.id, proyek.id_project, gcal_event_id=None),
            bangun_log(user.id, proyek.id_project, gcal_event_id="evt-2"),
        )
        n = (
            (
                await db_session.execute(
                    select(ActivityLog).where(ActivityLog.id_project == proyek.id_project)
                )
            )
            .scalars()
            .all()
        )
        assert len(n) == 4

    async def test_fk_proyek_user_dan_subtask_tidak_ada_ditolak(self, db_session):
        user, proyek = await siapkan_proyek(db_session)
        await ditolak(db_session, "fk_activity_logs_project", bangun_log(user.id, "PRJ-TIDAK-ADA"))
        log = bangun_log(user.id, proyek.id_project)
        log.sa_id = uuid.uuid4()
        await ditolak(db_session, "fk_activity_logs_sa", log)
        await ditolak(
            db_session,
            "fk_activity_logs_id_subtask",
            bangun_log(user.id, proyek.id_project, id_subtask="ST-TIDAK-ADA"),
        )

    async def test_hapus_subtask_mengosongkan_tautan_log_tidak_menghapus_log(self, db_session):
        user, proyek = await siapkan_proyek(db_session)
        st = bangun_subtask(proyek.id_project)
        await simpan(db_session, st)
        log = bangun_log(user.id, proyek.id_project, id_subtask=st.id_subtask)
        await simpan(db_session, log)

        await db_session.execute(delete(Subtask).where(Subtask.id_subtask == st.id_subtask))
        db_session.expire(log)
        await db_session.refresh(log)
        assert log.id_subtask is None  # ON DELETE SET NULL
        assert log.raw_notes == "catatan"

    async def test_proyek_dengan_log_tidak_bisa_dihapus_fisik(self, db_session):
        user, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_log(user.id, proyek.id_project))
        with pytest.raises(IntegrityError) as err:
            async with db_session.begin_nested():
                await db_session.execute(
                    delete(Project).where(Project.id_project == proyek.id_project)
                )
        assert "fk_activity_logs_project" in str(err.value)

    @pytest.mark.parametrize("kolom", ["sa_id", "subtask_category", "duration_hours", "raw_notes"])
    async def test_kolom_wajib_tidak_boleh_null(self, db_session, kolom):
        user, proyek = await siapkan_proyek(db_session)
        log = bangun_log(user.id, proyek.id_project)
        setattr(log, kolom, None)
        await _ditolak_null(db_session, kolom, log)

    async def test_default_work_type_dan_timestamp_serta_jsonb(self, db_session):
        user, proyek = await siapkan_proyek(db_session)
        polish = {"discussion_points": ["a"], "action_items": [{"description": "x", "pic": None}]}
        log = ActivityLog(
            id_log=f"LOG-{uuid.uuid4().hex[:8]}",
            sa_id=user.id,
            id_project=proyek.id_project,
            project_phase="Implementation",
            subtask_category="Assessment",
            duration_hours=Decimal("1"),
            raw_notes="n",
            ai_polished_notes=polish,
        )
        await simpan(db_session, log)
        db_session.expire(log)
        await db_session.refresh(log)
        assert log.work_type == "Project"
        assert log.created_at.tzinfo is not None
        assert log.ai_polished_notes == polish


# ============================================================================== NotificationLog


EVENT_TYPE = [
    "assignment",
    "status_change",
    "sla_reminder",
    "sla_escalation",
    "handover",
    "doc_ready",
]


class TestNotificationLog:
    @pytest.mark.parametrize("event", EVENT_TYPE)
    async def test_event_type_valid(self, db_session, event):
        user = bangun_user()
        await simpan(db_session, user)
        await simpan(db_session, bangun_notifikasi(user.id, event_type=event))

    @pytest.mark.parametrize("event", ["requirement_ready", "Assignment", "", "closed_win"])
    async def test_event_type_tidak_valid_ditolak(self, db_session, event):
        user = bangun_user()
        await simpan(db_session, user)
        await ditolak(
            db_session,
            "chk_notification_logs_event_type",
            bangun_notifikasi(user.id, event_type=event),
        )

    @pytest.mark.parametrize("channel", ["in-app", "email"])
    async def test_channel_valid(self, db_session, channel):
        user = bangun_user()
        await simpan(db_session, user)
        await simpan(db_session, bangun_notifikasi(user.id, channel=channel))

    @pytest.mark.parametrize("channel", ["sms", "in_app", "Email", ""])
    async def test_channel_tidak_valid_ditolak(self, db_session, channel):
        user = bangun_user()
        await simpan(db_session, user)
        await ditolak(
            db_session, "chk_notification_logs_channel", bangun_notifikasi(user.id, channel=channel)
        )

    @pytest.mark.parametrize("status", ["pending", "sent", "failed", "read"])
    async def test_status_valid(self, db_session, status):
        user = bangun_user()
        await simpan(db_session, user)
        await simpan(db_session, bangun_notifikasi(user.id, status=status))

    @pytest.mark.parametrize("status", ["delivered", "unread", ""])
    async def test_status_tidak_valid_ditolak(self, db_session, status):
        user = bangun_user()
        await simpan(db_session, user)
        await ditolak(
            db_session, "chk_notification_logs_status", bangun_notifikasi(user.id, status=status)
        )

    async def test_fk_penerima_tidak_ada_ditolak(self, db_session):
        await ditolak(db_session, "fk_notification_logs_recipient", bangun_notifikasi(uuid.uuid4()))

    async def test_default_status_pending_dan_metadata_tersimpan_di_kolom_metadata(
        self, db_session
    ):
        user = bangun_user()
        await simpan(db_session, user)
        n = bangun_notifikasi(user.id, notification_metadata={"proyek": "PRJ-1", "n": [1, 2]})
        await simpan(db_session, n)
        await db_session.refresh(n)
        assert n.status == "pending" and n.read_at is None
        mentah = (
            await db_session.execute(
                text("SELECT metadata FROM notification_logs WHERE id = :i"), {"i": n.id}
            )
        ).scalar_one()
        assert mentah == {"proyek": "PRJ-1", "n": [1, 2]}

    async def test_read_at_bisa_diisi(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        waktu = datetime(2025, 5, 5, tzinfo=timezone.utc)
        n = bangun_notifikasi(user.id, status="read", read_at=waktu)
        await simpan(db_session, n)
        await db_session.refresh(n)
        assert n.read_at == waktu

    @pytest.mark.parametrize("kolom", ["event_type", "recipient_user_id", "channel"])
    async def test_kolom_wajib_tidak_boleh_null(self, db_session, kolom):
        user = bangun_user()
        await simpan(db_session, user)
        n = bangun_notifikasi(user.id)
        setattr(n, kolom, None)
        await _ditolak_null(db_session, kolom, n)


# ============================================================================== AuditLog


class TestAuditLog:
    async def test_create_dengan_old_value_null_dan_json_roundtrip(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        a = bangun_audit(user.id, old_value=None, new_value={"status": "Assigned", "n": [1]})
        await simpan(db_session, a)
        db_session.expire(a)
        await db_session.refresh(a)
        assert a.old_value is None
        assert a.new_value == {"status": "Assigned", "n": [1]}
        assert a.created_at.tzinfo is not None

    async def test_update_menyimpan_nilai_lama_dan_baru(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        a = bangun_audit(
            user.id, action="status_change", old_value={"s": "New"}, new_value={"s": "Ready"}
        )
        await simpan(db_session, a)
        assert (a.old_value, a.new_value) == ({"s": "New"}, {"s": "Ready"})

    @pytest.mark.parametrize("kolom", ["entity_type", "entity_id", "action", "performed_by"])
    async def test_kolom_wajib_tidak_boleh_null(self, db_session, kolom):
        user = bangun_user()
        await simpan(db_session, user)
        a = bangun_audit(user.id)
        setattr(a, kolom, None)
        with pytest.raises(IntegrityError) as err:
            async with db_session.begin_nested():
                db_session.add(a)
                await db_session.flush()
        assert kolom in str(err.value)

    async def test_new_value_json_null_sql_ditolak(self, db_session):
        """NULL SQL ditolak; hanya JSON 'null'/objek yang dihasilkan aplikasi yang tersimpan."""
        user = bangun_user()
        await simpan(db_session, user)
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await db_session.execute(
                    text(
                        "INSERT INTO audit_logs "
                        "(id, entity_type, entity_id, action, performed_by, new_value, created_at) "
                        "VALUES ('A-NULL', 'p', '1', 'create', :u, NULL, now())"
                    ),
                    {"u": user.id},
                )

    async def test_fk_performed_by_tidak_ada_ditolak(self, db_session):
        await ditolak(db_session, "fk_audit_logs_performed_by", bangun_audit(uuid.uuid4()))

    async def test_id_unik(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        await simpan(db_session, bangun_audit(user.id, id="AUD-DUP"))
        await ditolak(db_session, "audit_logs_pkey", bangun_audit(user.id, id="AUD-DUP"))

    async def test_entity_id_tidak_punya_fk_jejak_tetap_ada_walau_entitas_hilang(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        await simpan(db_session, bangun_audit(user.id, entity_id="PRJ-SUDAH-DIHAPUS"))


# ============================================================================== ProjectCollaborator


class TestProjectCollaborator:
    async def test_tambah_kolaborator_valid_dan_default_viewer(self, db_session):
        pemilik, proyek = await siapkan_proyek(db_session)
        rekan = bangun_user()
        await simpan(db_session, rekan)
        k = bangun_kolaborator(proyek.id_project, rekan.id, pemilik.id)
        await simpan(db_session, k)
        await db_session.refresh(k)
        assert k.role == "viewer" and isinstance(k.id, uuid.UUID)
        assert k.created_at.tzinfo is not None

    async def test_role_contributor_tersimpan(self, db_session):
        pemilik, proyek = await siapkan_proyek(db_session)
        rekan = bangun_user()
        await simpan(db_session, rekan)
        k = bangun_kolaborator(proyek.id_project, rekan.id, pemilik.id, role="contributor")
        await simpan(db_session, k)
        await db_session.refresh(k)
        assert k.role == "contributor"

    async def test_user_sama_dua_kali_di_proyek_sama_ditolak_tetapi_proyek_lain_boleh(
        self, db_session
    ):
        pemilik, proyek = await siapkan_proyek(db_session)
        _, proyek2 = await siapkan_proyek(db_session)
        rekan = bangun_user()
        await simpan(db_session, rekan)
        await simpan(db_session, bangun_kolaborator(proyek.id_project, rekan.id, pemilik.id))
        await ditolak(
            db_session,
            "uq_project_collaborator",
            bangun_kolaborator(proyek.id_project, rekan.id, pemilik.id, role="contributor"),
        )
        await simpan(db_session, bangun_kolaborator(proyek2.id_project, rekan.id, pemilik.id))

    async def test_fk_proyek_user_dan_penambah_tidak_ada_ditolak(self, db_session):
        pemilik, proyek = await siapkan_proyek(db_session)
        rekan = bangun_user()
        await simpan(db_session, rekan)
        await ditolak(
            db_session,
            "fk_project_collaborators_project",
            bangun_kolaborator("PRJ-TIDAK-ADA", rekan.id, pemilik.id),
        )
        await ditolak(
            db_session,
            "fk_project_collaborators_user",
            bangun_kolaborator(proyek.id_project, uuid.uuid4(), pemilik.id),
        )
        await ditolak(
            db_session,
            "fk_project_collaborators_added_by",
            bangun_kolaborator(proyek.id_project, rekan.id, uuid.uuid4()),
        )

    async def test_hapus_proyek_cascade_menghapus_kolaborator(self, db_session):
        pemilik, proyek = await siapkan_proyek(db_session)
        rekan = bangun_user()
        await simpan(db_session, rekan)
        await simpan(db_session, bangun_kolaborator(proyek.id_project, rekan.id, pemilik.id))
        # Hapus lewat SQL: hanya kolaborator yang CASCADE; proyek tak punya anak non-cascade lain.
        await db_session.execute(
            text("DELETE FROM projects WHERE id_project = :p"), {"p": proyek.id_project}
        )
        sisa = (
            await db_session.execute(
                text("SELECT count(*) FROM project_collaborators WHERE id_project = :p"),
                {"p": proyek.id_project},
            )
        ).scalar_one()
        assert sisa == 0

    async def test_hapus_user_kolaborator_cascade_tetapi_penambah_tidak_boleh_hilang(
        self, db_session
    ):
        pemilik, proyek = await siapkan_proyek(db_session)
        rekan = bangun_user()
        await simpan(db_session, rekan)
        await simpan(db_session, bangun_kolaborator(proyek.id_project, rekan.id, pemilik.id))
        # added_by tanpa ondelete → pemilik tidak bisa dihapus (juga sales_pic proyek).
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                await db_session.execute(delete(User).where(User.id == pemilik.id))
        # Rekan (user_id, ON DELETE CASCADE) bisa dihapus dan barisnya ikut hilang.
        await db_session.execute(delete(User).where(User.id == rekan.id))
        sisa = (
            (
                await db_session.execute(
                    select(ProjectCollaborator).where(
                        ProjectCollaborator.id_project == proyek.id_project
                    )
                )
            )
            .scalars()
            .all()
        )
        assert sisa == []


# ============================================================================== SLATracking


class TestSLATracking:
    @pytest.mark.parametrize("status", ["green", "yellow", "red"])
    async def test_status_valid(self, db_session, status):
        _, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_sla(proyek.id_project, current_status=status))

    @pytest.mark.parametrize("status", ["orange", "Green", ""])
    async def test_status_tidak_valid_ditolak(self, db_session, status):
        _, proyek = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_sla_tracking_current_status",
            bangun_sla(proyek.id_project, current_status=status),
        )

    async def test_satu_proyek_satu_tracker(self, db_session):
        _, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_sla(proyek.id_project))
        await ditolak(db_session, "uq_sla_tracking_project_id", bangun_sla(proyek.id_project))

    async def test_fk_proyek_tidak_ada_ditolak(self, db_session):
        await ditolak(db_session, "fk_sla_tracking_project", bangun_sla("PRJ-TIDAK-ADA"))

    async def test_default_hari_nol_hijau_tidak_terkunci(self, db_session):
        _, proyek = await siapkan_proyek(db_session)
        s = bangun_sla(proyek.id_project)
        await simpan(db_session, s)
        await db_session.refresh(s)
        assert (s.days_elapsed, s.current_status, s.is_locked) == (0, "green", False)
        assert s.stopped_at is None and s.locked_at is None and s.unlocked_at is None

    @pytest.mark.parametrize("kolom", ["project_id", "started_at"])
    async def test_kolom_wajib_tidak_boleh_null(self, db_session, kolom):
        _, proyek = await siapkan_proyek(db_session)
        s = bangun_sla(proyek.id_project)
        setattr(s, kolom, None)
        await _ditolak_null(db_session, kolom, s)

    async def test_siklus_lock_unlock_tersimpan(self, db_session):
        _, proyek = await siapkan_proyek(db_session)
        t0 = datetime(2025, 1, 6, tzinfo=timezone.utc)
        s = bangun_sla(
            proyek.id_project, is_locked=True, locked_at=t0, days_elapsed=5, current_status="red"
        )
        await simpan(db_session, s)
        s.is_locked, s.unlocked_at = False, t0
        await db_session.flush()
        await db_session.refresh(s)
        assert (s.is_locked, s.unlocked_at, s.days_elapsed) == (False, t0, 5)


# ============================================================================== Subtask


class TestSubtask:
    @pytest.mark.parametrize("status", ["open", "in_progress", "done"])
    async def test_status_valid(self, db_session, status):
        _, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_subtask(proyek.id_project, status=status))

    @pytest.mark.parametrize("status", ["closed", "Open", "in progress", ""])
    async def test_status_tidak_valid_ditolak(self, db_session, status):
        _, proyek = await siapkan_proyek(db_session)
        await ditolak(
            db_session, "chk_subtasks_status", bangun_subtask(proyek.id_project, status=status)
        )

    async def test_judul_unik_per_proyek_tetapi_boleh_sama_antar_proyek(self, db_session):
        _, p1 = await siapkan_proyek(db_session)
        _, p2 = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_subtask(p1.id_project, title="Buat HLD"))
        await ditolak(
            db_session, "uq_subtask_project_title", bangun_subtask(p1.id_project, title="Buat HLD")
        )
        await simpan(db_session, bangun_subtask(p2.id_project, title="Buat HLD"))

    async def test_judul_beda_kapitalisasi_dianggap_berbeda(self, db_session):
        _, p = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_subtask(p.id_project, title="Buat HLD"))
        await simpan(db_session, bangun_subtask(p.id_project, title="buat hld"))

    async def test_judul_150_karakter_diterima_151_ditolak(self, db_session):
        _, p = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_subtask(p.id_project, title="t" * 150))
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                db_session.add(bangun_subtask(p.id_project, title="t" * 151))
                await db_session.flush()

    async def test_fk_proyek_dan_sa_tidak_ada_ditolak(self, db_session):
        _, p = await siapkan_proyek(db_session)
        await ditolak(db_session, "subtasks_id_project_fkey", bangun_subtask("PRJ-TIDAK-ADA"))
        await ditolak(
            db_session,
            "subtasks_assigned_sa_fkey",
            bangun_subtask(p.id_project, assigned_sa=uuid.uuid4()),
        )

    async def test_assigned_sa_opsional_dan_default_open(self, db_session):
        user, p = await siapkan_proyek(db_session)
        a = bangun_subtask(p.id_project)
        b = bangun_subtask(p.id_project, assigned_sa=user.id)
        await simpan(db_session, a, b)
        await db_session.refresh(a)
        assert a.status == "open" and a.assigned_sa is None and b.assigned_sa == user.id

    async def test_hapus_proyek_cascade_menghapus_subtask(self, db_session):
        _, p = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_subtask(p.id_project))
        await db_session.execute(
            text("DELETE FROM projects WHERE id_project = :p"), {"p": p.id_project}
        )
        n = (await db_session.execute(text("SELECT count(*) FROM subtasks"))).scalar_one()
        assert n == 0

    async def test_updated_at_berubah_saat_update(self, db_session):
        _, p = await siapkan_proyek(db_session)
        s = bangun_subtask(p.id_project)
        await simpan(db_session, s)
        awal = s.updated_at
        s.status = "done"
        await db_session.flush()
        assert s.updated_at > awal


# ============================================================================== SourceDocument


class TestSourceDocument:
    @pytest.mark.parametrize("tipe", ["MoM", "RFP"])
    async def test_doc_type_valid(self, db_session, tipe):
        _, p = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_source_doc(p.id_project, doc_type=tipe))

    @pytest.mark.parametrize("tipe", ["BOQ", "mom", ""])
    async def test_doc_type_tidak_valid_ditolak(self, db_session, tipe):
        _, p = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_source_documents_doc_type",
            bangun_source_doc(p.id_project, doc_type=tipe),
        )

    @pytest.mark.parametrize("status", ["pending", "extracted", "empty", "failed"])
    async def test_extraction_status_valid(self, db_session, status):
        _, p = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_source_doc(p.id_project, extraction_status=status))

    @pytest.mark.parametrize("status", ["done", "Pending", ""])
    async def test_extraction_status_tidak_valid_ditolak(self, db_session, status):
        _, p = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_source_documents_status",
            bangun_source_doc(p.id_project, extraction_status=status),
        )

    async def test_fk_proyek_tidak_ada_ditolak(self, db_session):
        await ditolak(
            db_session, "source_documents_id_project_fkey", bangun_source_doc("PRJ-TIDAK-ADA")
        )

    async def test_default_dan_beberapa_dokumen_per_proyek(self, db_session):
        _, p = await siapkan_proyek(db_session)
        a, b = bangun_source_doc(p.id_project), bangun_source_doc(p.id_project)
        await simpan(db_session, a, b)  # tidak ada unique per proyek: MoM & RFP bisa banyak
        await db_session.refresh(a)
        assert a.extraction_status == "pending" and a.truncated is False
        assert a.extracted_text is None and isinstance(a.id, uuid.UUID)

    async def test_ukuran_file_bigint_menampung_nilai_besar(self, db_session):
        _, p = await siapkan_proyek(db_session)
        d = bangun_source_doc(p.id_project, size_bytes=5 * 1024**3)
        await simpan(db_session, d)
        await db_session.refresh(d)
        assert d.size_bytes == 5 * 1024**3

    async def test_hapus_proyek_cascade_menghapus_source_document(self, db_session):
        _, p = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_source_doc(p.id_project))
        await db_session.execute(
            text("DELETE FROM projects WHERE id_project = :p"), {"p": p.id_project}
        )
        n = (await db_session.execute(select(SourceDocument))).scalars().all()
        assert n == []

    async def test_index_proyek_ada(self, db_session):
        idx = (
            await db_session.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'idx_source_documents_project'"
                )
            )
        ).scalar_one()
        assert "id_project" in idx

    @pytest.mark.parametrize("kolom", ["filename", "doc_type", "size_bytes"])
    async def test_kolom_wajib_tidak_boleh_null(self, db_session, kolom):
        _, p = await siapkan_proyek(db_session)
        d = bangun_source_doc(p.id_project)
        setattr(d, kolom, None)
        await _ditolak_null(db_session, kolom, d)
