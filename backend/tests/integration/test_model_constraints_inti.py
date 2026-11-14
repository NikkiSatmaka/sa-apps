"""
Constraint model inti di Postgres nyata: User, Project, Document (tiket B10, spec #49).

Setiap CHECK/FK/unique/index diuji dua arah: nilai valid (termasuk batas) diterima,
nilai tidak valid ditolak OLEH DATABASE (nama constraint ada di pesan error).
Constraint Document yang sudah dijaga test B2 (`test_migration.py`: gdrive_link/created_by/
unique Requirement) tidak diulang di sini.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.models import Project, User
from app.models.project import INCLUDE_DELETED
from tests.integration.model_helpers import (
    bangun_document,
    bangun_project,
    bangun_user,
    ditolak,
    siapkan_proyek,
    simpan,
)

# ============================================================================== User


class TestUser:
    @pytest.mark.parametrize("role", ["Sales", "Product", "SA", "Lead_SA"])
    async def test_role_valid_diterima(self, db_session, role):
        u = bangun_user(role=role)
        await simpan(db_session, u)
        assert (await db_session.get(User, u.id)).role == role

    @pytest.mark.parametrize("role", ["Admin", "admin", "Manager", "", "SA ", "PMO"])
    async def test_role_tidak_valid_ditolak(self, db_session, role):
        # `User(...)` langsung: `bangun_user("Admin")` adalah persona (SA + is_admin), bukan role.
        n = uuid.uuid4().hex
        user = User(id=uuid.uuid4(), email=f"{n}@x.local", name="N", role=role, google_id=f"g-{n}")
        await ditolak(db_session, "chk_users_role", user)

    async def test_email_unik(self, db_session):
        await simpan(db_session, bangun_user(email="sama@portal-sa.local"))
        await ditolak(db_session, "uq_users_email", bangun_user(email="sama@portal-sa.local"))

    async def test_google_id_unik(self, db_session):
        await simpan(db_session, bangun_user(google_id="g-sama"))
        await ditolak(db_session, "uq_users_google_id", bangun_user(google_id="g-sama"))

    async def test_email_berbeda_kapitalisasi_dianggap_berbeda_perilaku_nyata(self, db_session):
        """Unique bersifat case-sensitive di DB; normalisasi email adalah tugas layer aplikasi."""
        await simpan(db_session, bangun_user(email="Budi@portal-sa.local"))
        await simpan(db_session, bangun_user(email="budi@portal-sa.local"))

    @pytest.mark.parametrize("kolom", ["email", "name", "google_id"])
    async def test_kolom_wajib_tidak_boleh_null(self, db_session, kolom):
        from sqlalchemy.exc import IntegrityError

        u = bangun_user(**{kolom: None})
        with pytest.raises(IntegrityError) as err:
            async with db_session.begin_nested():
                db_session.add(u)
                await db_session.flush()
        assert kolom in str(err.value)

    async def test_is_admin_bawaan_false_dan_menempel_pada_role_fungsional(self, db_session):
        biasa = bangun_user()
        admin = bangun_user(role="Lead_SA", is_admin=True)
        await simpan(db_session, biasa)
        await simpan(db_session, admin)
        assert (await db_session.get(User, biasa.id)).is_admin is False
        assert (await db_session.get(User, admin.id)).is_admin is True

    async def test_default_role_sa_dan_timestamp_terisi(self, db_session):
        n = uuid.uuid4().hex
        u = User(id=uuid.uuid4(), email=f"{n}@x.local", name="N", google_id=f"g-{n}")
        await simpan(db_session, u)
        await db_session.refresh(u)
        assert u.role == "SA"
        assert u.avatar_url is None
        assert u.created_at.tzinfo is not None and u.updated_at.tzinfo is not None

    async def test_updated_at_berubah_saat_update(self, db_session):
        u = bangun_user()
        await simpan(db_session, u)
        awal = u.updated_at
        u.name = "Nama Baru"
        await db_session.flush()
        assert u.updated_at > awal
        assert u.created_at <= awal

    async def test_id_dibuat_otomatis_bila_tidak_diberikan(self, db_session):
        n = uuid.uuid4().hex
        u = User(email=f"{n}@x.local", name="N", google_id=f"g-{n}")
        await simpan(db_session, u)
        assert isinstance(u.id, uuid.UUID)

    async def test_panjang_email_lebih_dari_255_ditolak(self, db_session):
        from sqlalchemy.exc import DBAPIError

        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                db_session.add(bangun_user(email="a" * 250 + "@x.local"))
                await db_session.flush()


# ============================================================================== Project


STATUS_VALID = [
    "Intake",
    "Awaiting Assignment",
    "Assigned",
    "In Progress",
    "Submitted",
    "Won",
    "Handed Over",
    "Closed",
    "On Hold",
]

# Nama status lama (sebelum ADR 0013) tidak boleh lolos CHECK.
STATUS_LAMA = [
    "New",
    "Pending Assignment",
    "Ready",
    "Closed-Win",
    "Handover Complete",
    "Need Clarification",
    "Scoring Pending",
    "Manual Review Required",
]

QUALIFICATION_STATE_VALID = ["Scoring", "Need Clarification", "Manual Review", "Qualified"]


class TestProject:
    @pytest.mark.parametrize("status", STATUS_VALID)
    async def test_status_valid_diterima(self, db_session, status):
        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(user.id, status=status)
        await simpan(db_session, p)
        assert (await db_session.get(Project, p.id_project)).status == status

    @pytest.mark.parametrize("status", ["Draft", "intake", "", "Closed Won", *STATUS_LAMA])
    async def test_status_tidak_valid_ditolak(self, db_session, status):
        user = bangun_user()
        await simpan(db_session, user)
        await ditolak(db_session, "chk_projects_status", bangun_project(user.id, status=status))

    async def test_status_lost_valid_dengan_lost_reason(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(user.id, status="Lost", lost_reason="Customer batal")
        await simpan(db_session, p)
        assert (await db_session.get(Project, p.id_project)).lost_reason == "Customer batal"

    @pytest.mark.parametrize("alasan", [None, "", "   "])
    async def test_status_lost_tanpa_lost_reason_ditolak(self, db_session, alasan):
        user = bangun_user()
        await simpan(db_session, user)
        await ditolak(
            db_session,
            "chk_projects_lost_reason",
            bangun_project(user.id, status="Lost", lost_reason=alasan),
        )

    async def test_lost_reason_boleh_ada_pada_status_lain(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        await simpan(db_session, bangun_project(user.id, status="Assigned", lost_reason="sisa"))

    @pytest.mark.parametrize("nilai", QUALIFICATION_STATE_VALID)
    async def test_qualification_state_valid_diterima(self, db_session, nilai):
        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(user.id, qualification_state=nilai)
        await simpan(db_session, p)
        assert (await db_session.get(Project, p.id_project)).qualification_state == nilai

    @pytest.mark.parametrize("nilai", ["Manual Review Required", "scoring", "", "Intake"])
    async def test_qualification_state_tidak_valid_ditolak(self, db_session, nilai):
        user = bangun_user()
        await simpan(db_session, user)
        await ditolak(
            db_session,
            "chk_projects_qualification_state",
            bangun_project(user.id, qualification_state=nilai),
        )

    async def test_default_status_intake_dan_qualification_state_scoring(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(user.id)
        await simpan(db_session, p)
        baris = await db_session.get(Project, p.id_project)
        assert (baris.status, baris.qualification_state, baris.previous_status) == (
            "Intake",
            "Scoring",
            None,
        )

    @pytest.mark.parametrize("nilai", ["Awaiting Assignment", "In Progress", "Submitted", "Won"])
    async def test_previous_status_valid_diterima(self, db_session, nilai):
        user = bangun_user()
        await simpan(db_session, user)
        await simpan(db_session, bangun_project(user.id, status="On Hold", previous_status=nilai))

    @pytest.mark.parametrize("nilai", ["On Hold", "Lost", "Ready", "Pending Assignment", ""])
    async def test_previous_status_tidak_valid_ditolak(self, db_session, nilai):
        user = bangun_user()
        await simpan(db_session, user)
        await ditolak(
            db_session,
            "chk_projects_previous_status",
            bangun_project(user.id, previous_status=nilai),
        )

    async def test_status_pending_dq_ditolak_database(self, db_session):
        """
        `Pending DQ` bukan status proyek (diputuskan 2026-11-10, ADR 0001 / issue #79): DQ yang
        belum diisi cukup ditandai `dq_number` kosong, sehingga CHECK `chk_projects_status`
        menolaknya.
        """
        user = bangun_user()
        await simpan(db_session, user)
        await ditolak(
            db_session, "chk_projects_status", bangun_project(user.id, status="Pending DQ")
        )

    @pytest.mark.parametrize("skor", [0, 1, 59, 60, 99, 100])
    async def test_bant_score_valid_termasuk_batas(self, db_session, skor):
        user = bangun_user()
        await simpan(db_session, user)
        await simpan(db_session, bangun_project(user.id, bant_score=skor))

    @pytest.mark.parametrize("skor", [-1, 101, 1000])
    async def test_bant_score_di_luar_rentang_ditolak(self, db_session, skor):
        user = bangun_user()
        await simpan(db_session, user)
        await ditolak(
            db_session, "chk_projects_bant_score", bangun_project(user.id, bant_score=skor)
        )

    async def test_bant_score_null_diterima(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(user.id, bant_score=None)
        await simpan(db_session, p)

    @pytest.mark.parametrize(
        "dq", [None, "ABCDE", "12345", "abc-1", "-----", "DQ-2025-00123", "A" * 20]
    )
    async def test_dq_number_valid_termasuk_batas(self, db_session, dq):
        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(user.id, dq_number=dq)
        await simpan(db_session, p)
        assert (await db_session.get(Project, p.id_project)).dq_number == dq

    @pytest.mark.parametrize(
        "dq", ["ABCD", "ABC DE", "ABC_DE", "ABC.123", "DQ/2025", "ÅBCDE", "ABC-1\n"]
    )
    async def test_dq_number_format_tidak_valid_ditolak(self, db_session, dq):
        user = bangun_user()
        await simpan(db_session, user)
        await ditolak(db_session, "chk_dq_number_format", bangun_project(user.id, dq_number=dq))

    async def test_dq_number_21_karakter_ditolak_oleh_panjang_kolom(self, db_session):
        from sqlalchemy.exc import DBAPIError

        user = bangun_user()
        await simpan(db_session, user)
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                db_session.add(bangun_project(user.id, dq_number="A" * 21))
                await db_session.flush()

    @pytest.mark.parametrize("nilai", [None, "pending", "provisioned", "failed"])
    async def test_folder_provisioning_status_valid(self, db_session, nilai):
        user = bangun_user()
        await simpan(db_session, user)
        await simpan(db_session, bangun_project(user.id, folder_provisioning_status=nilai))

    @pytest.mark.parametrize("nilai", ["Provisioned", "ok", ""])
    async def test_folder_provisioning_status_tidak_valid(self, db_session, nilai):
        user = bangun_user()
        await simpan(db_session, user)
        await ditolak(
            db_session,
            "chk_projects_folder_provisioning_status",
            bangun_project(user.id, folder_provisioning_status=nilai),
        )

    @pytest.mark.parametrize("nilai", [None, "pending", "ready", "failed"])
    async def test_requirement_generation_status_valid(self, db_session, nilai):
        user = bangun_user()
        await simpan(db_session, user)
        await simpan(db_session, bangun_project(user.id, requirement_generation_status=nilai))

    @pytest.mark.parametrize("nilai", ["done", "Submitted", ""])
    async def test_requirement_generation_status_tidak_valid(self, db_session, nilai):
        user = bangun_user()
        await simpan(db_session, user)
        await ditolak(
            db_session,
            "chk_projects_requirement_generation_status",
            bangun_project(user.id, requirement_generation_status=nilai),
        )

    @pytest.mark.parametrize("kolom", ["created_by", "product_pic", "sales_pic", "lead_sa", "assigned_sa", "deleted_by"]
    )
    async def test_fk_user_tidak_ada_ditolak(self, db_session, kolom):
        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(user.id)
        setattr(p, kolom, uuid.uuid4())
        await ditolak(db_session, f"fk_projects_{kolom}", p)

    async def test_fk_user_ada_diterima(self, db_session):
        a, b = bangun_user(role="Sales"), bangun_user(role="SA")
        await simpan(db_session, a, b)
        p = bangun_project(a.id, assigned_sa=b.id)
        await simpan(db_session, p)

    async def test_user_tidak_bisa_dihapus_selama_masih_jadi_sales_pic(self, db_session):
        from sqlalchemy import delete
        from sqlalchemy.exc import IntegrityError

        user, _ = await siapkan_proyek(db_session)
        with pytest.raises(IntegrityError) as err:
            async with db_session.begin_nested():
                await db_session.execute(delete(User).where(User.id == user.id))
        assert "fk_projects_sales_pic" in str(err.value)

    @pytest.mark.parametrize(
        "kolom", ["project_name", "customer_name", "created_by", "product_pic", "target_submit"]
    )
    async def test_kolom_wajib_tidak_boleh_null(self, db_session, kolom):
        from sqlalchemy.exc import IntegrityError

        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(user.id)
        setattr(p, kolom, None)
        with pytest.raises(IntegrityError) as err:
            async with db_session.begin_nested():
                db_session.add(p)
                await db_session.flush()
        assert kolom in str(err.value)

    async def test_sales_pic_dan_lead_sa_boleh_null(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(None, product_pic=user.id, created_by=user.id)
        await simpan(db_session, p)
        await db_session.refresh(p)
        assert p.sales_pic is None
        assert p.lead_sa is None

    async def test_id_project_unik(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        await simpan(db_session, bangun_project(user.id, id_project="PRJ-DUP"))
        await ditolak(db_session, "projects_pkey", bangun_project(user.id, id_project="PRJ-DUP"))

    async def test_default_status_intake_dan_timestamp_dan_tag_kosong(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(user.id)
        await simpan(db_session, p)
        await db_session.refresh(p)
        assert p.status == "Intake"
        assert p.use_case_tags == []
        assert p.created_at.tzinfo is not None
        assert p.deleted_at is None and p.bant_score is None and p.estimasi_nilai is None

    async def test_estimasi_nilai_numeric_14_2_menyimpan_sampai_batas_maksimum(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(user.id, estimasi_nilai=Decimal("999999999999.99"))
        await simpan(db_session, p)
        await db_session.refresh(p)
        assert p.estimasi_nilai == Decimal("999999999999.99")

    async def test_estimasi_nilai_melebihi_presisi_ditolak_database(self, db_session):
        from sqlalchemy.exc import DBAPIError

        user = bangun_user()
        await simpan(db_session, user)
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                db_session.add(bangun_project(user.id, estimasi_nilai=Decimal("100000000000000")))
                await db_session.flush()

    async def test_estimasi_nilai_dibulatkan_ke_dua_desimal(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(user.id, estimasi_nilai=Decimal("10.126"))
        await simpan(db_session, p)
        await db_session.refresh(p)
        assert p.estimasi_nilai == Decimal("10.13")

    async def test_kolom_jsonb_mutabel_tersimpan_dan_perubahan_dalam_dilacak(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        p = bangun_project(user.id, bant_detail={"budget": 10}, use_case_tags=["DR", "Migrasi"])
        await simpan(db_session, p)
        p.bant_detail["authority"] = 20  # MutableDict harus menandai perubahan
        await db_session.flush()
        db_session.expire(p)
        await db_session.refresh(p)
        assert p.bant_detail == {"budget": 10, "authority": 20}
        assert p.use_case_tags == ["DR", "Migrasi"]

    async def test_partial_index_proyek_aktif_ada_dan_hanya_mencakup_belum_dihapus(
        self, db_session
    ):
        row = (
            await db_session.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_projects_active'")
            )
        ).scalar_one()
        assert "updated_at" in row and "deleted_at IS NULL" in row

    async def test_soft_delete_menyembunyikan_proyek_dari_select_orm(self, db_session):
        user = bangun_user()
        await simpan(db_session, user)
        aktif = bangun_project(user.id)
        terhapus = bangun_project(
            user.id, deleted_at=datetime(2025, 1, 1, tzinfo=timezone.utc), deleted_by=user.id
        )
        await simpan(db_session, aktif, terhapus)

        ids = (await db_session.execute(select(Project.id_project))).scalars().all()
        assert aktif.id_project in ids and terhapus.id_project not in ids

        semua = (
            (
                await db_session.execute(
                    select(Project.id_project).execution_options(**{INCLUDE_DELETED: True})
                )
            )
            .scalars()
            .all()
        )
        assert {aktif.id_project, terhapus.id_project} <= set(semua)

        # Baris tetap ada di tabel (soft delete, bukan hapus fisik).
        fisik = (
            await db_session.execute(
                text("SELECT count(*) FROM projects WHERE id_project = :i"),
                {"i": terhapus.id_project},
            )
        ).scalar_one()
        assert fisik == 1

    async def test_soft_delete_tidak_menyaring_proyek_di_count_dengan_opsi_include(
        self, db_session
    ):
        user = bangun_user()
        await simpan(db_session, user)
        await simpan(
            db_session,
            bangun_project(user.id, deleted_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
        )
        n = (await db_session.execute(select(func.count()).select_from(Project))).scalar_one()
        assert n == 0
        n_semua = (
            await db_session.execute(
                select(func.count())
                .select_from(Project)
                .execution_options(**{INCLUDE_DELETED: True})
            )
        ).scalar_one()
        assert n_semua == 1


# ============================================================================== Document


class TestDocument:
    @pytest.mark.parametrize("tipe", ["PropTek", "BOQ", "Mandays", "MoM", "RFP", "HLD"])
    async def test_doc_type_valid_non_requirement(self, db_session, tipe):
        user, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_document(proyek.id_project, user.id, doc_type=tipe))

    @pytest.mark.parametrize("tipe", ["Proposal", "boq", "", "SOW"])
    async def test_doc_type_tidak_valid_ditolak(self, db_session, tipe):
        user, proyek = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_documents_doc_type",
            bangun_document(proyek.id_project, user.id, doc_type=tipe),
        )

    @pytest.mark.parametrize("status", ["Draft", "Reviewed", "Final"])
    async def test_status_valid(self, db_session, status):
        user, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_document(proyek.id_project, user.id, status=status))

    @pytest.mark.parametrize("status", ["Approved", "draft", ""])
    async def test_status_tidak_valid_ditolak(self, db_session, status):
        user, proyek = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_documents_status",
            bangun_document(proyek.id_project, user.id, status=status),
        )

    @pytest.mark.parametrize("folder", ["Inventory", "Diagram", "Solutions"])
    async def test_folder_type_valid(self, db_session, folder):
        user, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_document(proyek.id_project, user.id, folder_type=folder))

    @pytest.mark.parametrize("folder", ["Final", "solutions", ""])
    async def test_folder_type_tidak_valid_ditolak(self, db_session, folder):
        user, proyek = await siapkan_proyek(db_session)
        await ditolak(
            db_session,
            "chk_documents_folder_type",
            bangun_document(proyek.id_project, user.id, folder_type=folder),
        )

    async def test_fk_proyek_tidak_ada_ditolak(self, db_session):
        user, _ = await siapkan_proyek(db_session)
        await ditolak(db_session, "fk_documents_project", bangun_document("PRJ-TIDAK-ADA", user.id))

    @pytest.mark.parametrize("kolom", ["created_by", "updated_by"])
    async def test_fk_user_tidak_ada_ditolak(self, db_session, kolom):
        user, proyek = await siapkan_proyek(db_session)
        d = bangun_document(proyek.id_project, user.id)
        setattr(d, kolom, uuid.uuid4())
        await ditolak(db_session, f"fk_documents_{kolom}", d)

    async def test_default_status_draft_dan_flag_requirement_false(self, db_session):
        user, proyek = await siapkan_proyek(db_session)
        d = bangun_document(proyek.id_project, user.id)
        await simpan(db_session, d)
        await db_session.refresh(d)
        assert d.status == "Draft"
        assert d.is_overridden is False and d.source_truncated is False
        assert d.content is None and d.source_hash is None and d.generated_at is None

    async def test_server_default_flag_berlaku_untuk_insert_tanpa_orm(self, db_session):
        """`is_overridden`/`source_truncated` punya server_default false (SQL mentah)."""
        user, proyek = await siapkan_proyek(db_session)
        await db_session.execute(
            text(
                "INSERT INTO documents "
                "(id_doc, id_project, doc_type, status, folder_type, gdrive_link, created_by) "
                "VALUES ('D-RAW', :p, 'HLD', 'Draft', 'Solutions', 'https://x', :u)"
            ),
            {"p": proyek.id_project, "u": user.id},
        )
        baris = (
            await db_session.execute(
                text("SELECT is_overridden, source_truncated FROM documents WHERE id_doc='D-RAW'")
            )
        ).one()
        assert (baris.is_overridden, baris.source_truncated) == (False, False)

    async def test_requirement_content_jsonb_roundtrip(self, db_session):
        user, proyek = await siapkan_proyek(db_session)
        butir = [{"id": "r1", "kategori": "Fungsional", "butir": "Harus bisa X"}]
        d = bangun_document(
            proyek.id_project,
            None,
            doc_type="Requirement",
            gdrive_link=None,
            folder_type="Inventory",
            content=butir,
            source_hash="a" * 64,
        )
        await simpan(db_session, d)
        db_session.expire(d)
        await db_session.refresh(d)
        assert d.content == butir and d.source_hash == "a" * 64

    async def test_notes_lebih_dari_500_karakter_ditolak(self, db_session):
        from sqlalchemy.exc import DBAPIError

        user, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_document(proyek.id_project, user.id, notes="n" * 500))
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                db_session.add(bangun_document(proyek.id_project, user.id, notes="n" * 501))
                await db_session.flush()

    async def test_proyek_tidak_bisa_dihapus_selama_punya_dokumen(self, db_session):
        from sqlalchemy import delete
        from sqlalchemy.exc import IntegrityError

        user, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_document(proyek.id_project, user.id))
        with pytest.raises(IntegrityError) as err:
            async with db_session.begin_nested():
                await db_session.execute(
                    delete(Project).where(Project.id_project == proyek.id_project)
                )
        assert "fk_documents_project" in str(err.value)

    async def test_id_doc_unik(self, db_session):
        user, proyek = await siapkan_proyek(db_session)
        await simpan(db_session, bangun_document(proyek.id_project, user.id, id_doc="DUP"))
        await ditolak(
            db_session, "documents_pkey", bangun_document(proyek.id_project, user.id, id_doc="DUP")
        )


# ================================================================ Kesesuaian model ↔ DB


async def test_constraint_dan_index_bernama_di_model_ada_di_database_hasil_migration(db_session):
    """
    Setiap CHECK/UNIQUE/Index BERNAMA yang dideklarasikan di model harus ada di schema hasil
    `alembic upgrade head`. Mencegah drift diam-diam (model menjanjikan jaminan yang
    tidak dimiliki DB).
    """
    from sqlalchemy import CheckConstraint, UniqueConstraint

    import app.models  # noqa: F401  - pastikan semua model terdaftar di metadata
    from app.core.database import Base

    di_db = {
        r[0]
        for r in (
            await db_session.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace "
                    "UNION SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
                )
            )
        ).all()
    }
    dijanjikan = set()
    for tabel in Base.metadata.tables.values():
        for c in tabel.constraints:
            if isinstance(c, (CheckConstraint, UniqueConstraint)) and c.name:
                dijanjikan.add(c.name)
        dijanjikan |= {i.name for i in tabel.indexes if i.name}
    assert len(dijanjikan) >= 25  # pagar: pastikan loop benar-benar menemukan constraint
    assert dijanjikan - di_db == set()


async def test_kolom_unique_dan_index_di_model_sama_dengan_database(db_session):
    """Kolom penyusun UNIQUE/Index bernama di model harus sama dengan yang ada di DB."""
    from sqlalchemy import UniqueConstraint

    import app.models  # noqa: F401
    from app.core.database import Base

    unik_db = {
        r.conname: set(r.kolom)
        for r in (
            await db_session.execute(
                text(
                    "SELECT c.conname, array_agg(a.attname::text) AS kolom FROM pg_constraint c "
                    "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
                    "WHERE c.contype = 'u' AND c.connamespace = 'public'::regnamespace "
                    "GROUP BY c.conname"
                )
            )
        ).all()
    }
    definisi_index = dict(
        (
            await db_session.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
            )
        ).all()
    )
    diperiksa = 0
    for tabel in Base.metadata.tables.values():
        for c in tabel.constraints:
            if isinstance(c, UniqueConstraint) and c.name:
                assert unik_db[c.name] == {col.name for col in c.columns}, c.name
                diperiksa += 1
        for idx in tabel.indexes:
            if idx.name:
                definisi = definisi_index[idx.name]
                kolom_db = definisi.split("(", 1)[1].split(")", 1)[0]
                assert [x.strip() for x in kolom_db.split(",")] == [c.name for c in idx.columns]
                assert ("UNIQUE" in definisi) is bool(idx.unique), idx.name
                parsial = idx.dialect_options["postgresql"]["where"]
                assert (" WHERE " in definisi) is (parsial is not None), idx.name
                diperiksa += 1
    assert diperiksa >= 5
