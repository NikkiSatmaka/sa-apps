"""
Seed Demo Data — Script untuk mengisi database dengan dummy data.

Jalankan:
    docker compose exec backend python -m scripts.seed_demo_data

Script ini idempotent — bisa dijalankan berkali-kali tanpa duplikat.
Setiap insert dicek terlebih dahulu apakah data sudah ada.

Data yang dibuat:
- 6 users (2 Sales, 3 SA, 1 Lead_SA) — sesuai demo login credentials
- 8 proyek dengan berbagai status dan DQ Number
- 6 dokumen
- 15+ activity logs (tersebar di beberapa bulan untuk demo utilisasi)
"""

import asyncio
import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.document import Document
from app.models.project import Project
from app.models.user import User
from app.schemas.qualification_definition import QUESTIONNAIRE_SCHEMA_VERSION


def deterministic_uuid(seed_string: str) -> uuid.UUID:
    """Generate UUID deterministic berdasarkan string (selalu sama untuk input sama)."""
    return uuid.UUID(hashlib.md5(seed_string.encode()).hexdigest())


def qualification_answers_for_demo(
    mrr: int | None, pic_name: str, pic_position: str, pic_email: str, need: str
) -> dict:
    """Jawaban demo mengikuti nama field dan pilihan skema kualifikasi aktif."""
    return {
        "mrr": mrr,
        "budget_dialokasikan": "Ya",
        "pic_nama": pic_name,
        "pic_jabatan": pic_position,
        "pic_email": pic_email,
        "peran_pic": "Pengambil keputusan",
        "stakeholder_lain": None,
        "masalah_bisnis": need,
        "jenis_workload": "Data warehouse/analytics",
        "lingkungan": "Hybrid",
        "skala": "40 server, 20 TB",
        "persyaratan_khusus": None,
        "target_go_live": "≤ 6 bulan",
        "kompetitor": None,
    }


# ============================================================
# DATA DEMO — sesuai dengan konfigurasi DEMO_USERS di auth.py
# ============================================================

DEMO_USERS = [
    {
        "email": "demo-sales@portal-sa.local",
        "name": "Demo Sales",
        "role": "Sales",
        "google_id": "demo-google-id-sales",
    },
    {
        "email": "demo-sales2@portal-sa.local", "name": "Demo Sales 2",
        "role": "Sales", "google_id": "demo-google-id-sales-2",
    },
    {
        "email": "demo-product@portal-sa.local", "name": "Demo Product",
        "role": "Product", "google_id": "demo-google-id-product",
    },
    {
        "email": "demo-product2@portal-sa.local", "name": "Demo Product 2",
        "role": "Product", "google_id": "demo-google-id-product-2",
    },
    {
        "email": "demo-sa@portal-sa.local",
        "name": "Demo SA",
        "role": "SA",
        "google_id": "demo-google-id-sa",
    },
    {
        "email": "demo-sa2@portal-sa.local", "name": "Demo SA 2",
        "role": "SA", "google_id": "demo-google-id-sa-2",
    },
    {
        "email": "demo-lead@portal-sa.local",
        "name": "Demo Lead SA",
        "role": "Lead_SA",
        "google_id": "demo-google-id-lead-sa",
    },
    {
        "email": "demo-lead2@portal-sa.local", "name": "Demo Lead SA 2",
        "role": "Lead_SA", "google_id": "demo-google-id-lead-sa-2",
    },
    {
        "email": "demo-admin@portal-sa.local",
        "name": "Demo Admin",
        "role": "SA",
        "is_admin": True,
        "google_id": "demo-google-id-admin",
    },
    {
        "email": "demo-admin2@portal-sa.local", "name": "Demo Admin 2",
        "role": "SA", "is_admin": True, "google_id": "demo-google-id-admin-2",
    },
]


async def get_or_create_user(db: AsyncSession, user_data: dict) -> User:
    """Cek user berdasarkan email, buat jika belum ada. Jika sudah ada, pastikan data konsisten."""
    result = await db.execute(
        select(User).where(User.email == user_data["email"])
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update role dan flag admin jika berubah (untuk konsistensi seed)
        is_admin = user_data.get("is_admin", False)
        if existing.role != user_data["role"] or existing.is_admin != is_admin:
            existing.role = user_data["role"]
            existing.is_admin = is_admin
            await db.flush()
        print(f"  [ok] User sudah ada: {user_data['email']} (id: {existing.id})")
        return existing

    # Buat user baru dengan deterministic UUID (berdasarkan email)
    user_id = deterministic_uuid(user_data["email"])
    user = User(
        id=user_id,
        email=user_data["email"],
        name=user_data["name"],
        role=user_data["role"],
        is_admin=user_data.get("is_admin", False),
        google_id=user_data["google_id"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()
    print(f"  [+] User dibuat: {user_data['email']} ({user_data['role']}) id: {user_id}")
    return user


async def get_or_create_project(
    db: AsyncSession,
    project_data: dict,
    sales_id: uuid.UUID,
    sa_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
) -> Project:
    """Cek proyek berdasarkan id_project, buat jika belum ada."""
    result = await db.execute(
        select(Project).where(Project.id_project == project_data["id_project"])
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Hanya fixture demo bernama tetap yang ownership-nya disinkronkan saat rerun.
        if project_data["id_project"].startswith("PRJ-DEMO-"):
            ownership = {"sales_pic": sales_id, "assigned_sa": sa_id}
            if product_id is not None:
                ownership["product_pic"] = product_id
            changed = False
            for field, value in ownership.items():
                if getattr(existing, field, None) != value:
                    setattr(existing, field, value)
                    changed = True
            if changed:
                await db.flush()
        jawaban = project_data.get("qualification_answers")
        if jawaban is not None:
            versi = QUESTIONNAIRE_SCHEMA_VERSION
            berubah = (
                existing.qualification_answers != jawaban
                or existing.qualification_schema_version != versi
            )
            if berubah:
                existing.qualification_answers = jawaban
                existing.qualification_schema_version = versi
                await db.flush()
                print(
                    f"  [~] Kualifikasi proyek diperbarui: "
                    f"{project_data['project_name']}"
                )
            else:
                print(f"  [ok] Proyek sudah ada: {project_data['project_name']}")
        # Pembaruan legacy tetap berlaku hanya untuk payload tanpa jawaban kuesioner.
        elif project_data.get("bant_detail") and existing.bant_detail != project_data["bant_detail"]:
            existing.bant_detail = project_data["bant_detail"]
            await db.flush()
            print(f"  [~] Proyek diupdate: {project_data['project_name']}")
        else:
            print(f"  [ok] Proyek sudah ada: {project_data['project_name']}")
        return existing

    now = datetime.now(timezone.utc)
    project = Project(
        id_project=project_data["id_project"],
        project_name=project_data["project_name"],
        customer_name=project_data["customer_name"],
        created_by=sales_id,
        product_pic=product_id or sales_id,
        sales_pic=sales_id,
        assigned_sa=sa_id,
        status=project_data["status"],
        qualification_state=project_data.get(
            "qualification_state", "Scoring" if project_data["status"] == "Intake" else "Qualified"
        ),
        target_submit=project_data["target_submit"],
        bant_score=project_data.get("bant_score"),
        qualification_answers=project_data.get("qualification_answers"),
        qualification_schema_version=(
            QUESTIONNAIRE_SCHEMA_VERSION
            if project_data.get("qualification_answers") is not None
            else None
        ),
        bant_detail=None,
        use_case_tags=project_data.get("use_case_tags"),
        dq_number=project_data.get("dq_number"),
        assigned_at=now if sa_id else None,
        created_at=now,
        updated_at=now,
    )
    db.add(project)
    await db.flush()
    print(f"  [+] Proyek dibuat: {project_data['project_name']} ({project_data['status']})")
    return project


async def get_or_create_document(
    db: AsyncSession,
    doc_data: dict,
    created_by: uuid.UUID,
) -> Document:
    """Cek dokumen berdasarkan id_doc, buat jika belum ada."""
    result = await db.execute(
        select(Document).where(Document.id_doc == doc_data["id_doc"])
    )
    existing = result.scalar_one_or_none()

    if existing:
        print(f"  [ok] Dokumen sudah ada: {doc_data['id_doc']}")
        return existing

    now = datetime.now(timezone.utc)
    doc = Document(
        id_doc=doc_data["id_doc"],
        id_project=doc_data["id_project"],
        doc_type=doc_data["doc_type"],
        status=doc_data["status"],
        gdrive_link=doc_data["gdrive_link"],
        folder_type=doc_data["folder_type"],
        notes=doc_data.get("notes"),
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(doc)
    await db.flush()
    print(f"  [+] Dokumen dibuat: {doc_data['id_doc']} ({doc_data['doc_type']})")
    return doc


async def get_or_create_activity_log(
    db: AsyncSession,
    log_data: dict,
    sa_id: uuid.UUID,
) -> ActivityLog:
    """Cek activity log berdasarkan id_log, buat jika belum ada."""
    result = await db.execute(
        select(ActivityLog).where(ActivityLog.id_log == log_data["id_log"])
    )
    existing = result.scalar_one_or_none()

    if existing:
        print(f"  [ok] Activity log sudah ada: {log_data['id_log']}")
        return existing

    work_type = log_data.get("work_type", "Project")
    log = ActivityLog(
        id_log=log_data["id_log"],
        work_type=work_type,
        id_project=log_data.get("id_project"),
        project_phase=log_data.get("project_phase"),
        sa_id=sa_id,
        subtask_category=log_data["subtask_category"],
        duration_hours=Decimal(str(log_data["duration_hours"])),
        raw_notes=log_data["raw_notes"],
        created_at=log_data.get("created_at", datetime.now(timezone.utc)),
    )
    db.add(log)
    await db.flush()
    print(f"  [+] Log: [{work_type}] {log_data['subtask_category']} ({log_data['duration_hours']}h)")
    return log


async def seed_all():
    """Jalankan seluruh proses seeding."""
    print("=" * 60)
    print("SEED DEMO DATA - Portal SA MVP")
    print("=" * 60)

    async with AsyncSessionLocal() as db:
        try:
            # == 1. Buat Users ==
            print("\n[1/4] Membuat demo users...")
            users = {}
            for user_data in DEMO_USERS:
                user = await get_or_create_user(db, user_data)
                users[user_data["email"]] = user

            sales1 = users["demo-sales@portal-sa.local"]
            sales2 = users["demo-sales2@portal-sa.local"]
            sa1 = users["demo-sa@portal-sa.local"]
            sa2 = users["demo-sa2@portal-sa.local"]
            sa3 = users["demo-sa@portal-sa.local"]
            lead_sa = users["demo-lead@portal-sa.local"]
            product1 = users["demo-product@portal-sa.local"]
            product2 = users["demo-product2@portal-sa.local"]

            # == 2. Buat Projects ==
            print("\n[2/4] Membuat demo projects...")

            projects_data = [
                {
                    "id_project": "PRJ-DEMO-001",
                    "project_name": "Migrasi Data Warehouse ke AWS",
                    "customer_name": "PT Nusantara Digital",
                    "status": "Assigned",
                    "target_submit": date(2026, 9, 15),
                    "bant_score": 75,
                    "bant_detail": {"budget": 25, "authority": 20, "need": 15, "timeline": 15, "budget_mrr": 50000000, "pic_name": "Andi Wijaya", "pic_position": "CTO", "pic_email": "andi@nusantara.co.id", "need_description": "Migrasi data warehouse 10TB dari on-premise Oracle ke AWS Redshift Serverless", "timeline_target": "2026-09-15"},
                    "use_case_tags": ["data-warehouse", "redshift", "s3"],
                    "sales": sales1.id,
                    "sa": sa1.id,
                    "dq_number": None,
                },
                {
                    "id_project": "PRJ-DEMO-002",
                    "project_name": "Cloud Native App Modernization",
                    "customer_name": "PT Maju Bersama Tech",
                    "status": "Submitted",
                    "target_submit": date(2026, 8, 30),
                    "bant_score": 85,
                    "bant_detail": {"budget": 25, "authority": 25, "need": 20, "timeline": 15, "budget_mrr": 120000000, "pic_name": "Sari Dewi", "pic_position": "VP Engineering", "pic_email": "sari@majubersama.id", "need_description": "Migrasi dari on-prem Kubernetes ke EKS dengan zero downtime. 15 microservices.", "timeline_target": "2026-08-30"},
                    "use_case_tags": ["kubernetes", "eks", "app-mod"],
                    "sales": sales1.id,
                    "sa": sa2.id,
                    "dq_number": "DQ-2026-00234",
                },
                {
                    "id_project": "PRJ-DEMO-003",
                    "project_name": "AI Platform Development",
                    "customer_name": "PT Cerdas Teknologi",
                    "status": "Awaiting Assignment",
                    "target_submit": date(2026, 10, 1),
                    "bant_score": 62,
                    "bant_detail": {"budget": 20, "authority": 17, "need": 15, "timeline": 10, "budget_mrr": 30000000, "pic_name": "Rudi Hartono", "pic_position": "Head of Data", "pic_email": "rudi@cerdas.tech", "need_description": "Platform ML untuk prediksi churn dan recommendation engine", "timeline_target": "2026-10-01"},
                    "use_case_tags": ["machine-learning", "sagemaker", "bedrock"],
                    "sales": sales2.id,
                    "sa": None,
                    "dq_number": None,
                },
                {
                    "id_project": "PRJ-DEMO-004",
                    "project_name": "Disaster Recovery Setup",
                    "customer_name": "PT Aman Sentosa",
                    "status": "Intake",
                    "qualification_state": "Need Clarification",
                    "target_submit": date(2026, 11, 15),
                    "bant_score": 45,
                    "bant_detail": {"budget": 10, "authority": 15, "need": 10, "timeline": 10, "budget_mrr": None, "pic_name": "Bambang S.", "pic_position": "IT Manager", "pic_email": "bambang@aman.co.id", "need_description": "DR setup untuk critical systems", "timeline_target": "2026-11-15"},
                    "use_case_tags": ["dr", "backup"],
                    "sales": sales2.id,
                    "sa": None,
                    "dq_number": None,
                },
                {
                    "id_project": "PRJ-DEMO-005",
                    "project_name": "IoT Data Pipeline",
                    "customer_name": "PT Koneksi Pintar",
                    "status": "Won",
                    "target_submit": date(2026, 6, 1),
                    "bant_score": 90,
                    "bant_detail": {"budget": 25, "authority": 25, "need": 20, "timeline": 20, "budget_mrr": 80000000, "pic_name": "Dewi Kusuma", "pic_position": "CTO", "pic_email": "dewi@koneksi.io", "need_description": "IoT data pipeline untuk 10K+ sensor devices, real-time analytics", "timeline_target": "2026-06-01"},
                    "use_case_tags": ["iot", "kinesis", "data-pipeline"],
                    "sales": sales1.id,
                    "sa": sa1.id,
                    "dq_number": "DQ-2026-00189",
                },
                {
                    "id_project": "PRJ-DEMO-006",
                    "project_name": "Security Compliance Audit Platform",
                    "customer_name": "Bank Nusantara Sejahtera",
                    "status": "Assigned",
                    "target_submit": date(2026, 9, 20),
                    "bant_score": 80,
                    "bant_detail": {"budget": 20, "authority": 25, "need": 20, "timeline": 15, "budget_mrr": 95000000, "pic_name": "Herman Tanaka", "pic_position": "CISO", "pic_email": "herman@banknusantara.co.id", "need_description": "Compliance platform: PCI-DSS, ISO 27001 monitoring dan audit trail", "timeline_target": "2026-09-20"},
                    "use_case_tags": ["security", "compliance", "guardduty"],
                    "sales": sales2.id,
                    "sa": sa3.id,
                    "dq_number": None,
                },
                {
                    "id_project": "PRJ-DEMO-007",
                    "project_name": "Real-Time Analytics Dashboard",
                    "customer_name": "PT Media Interaktif",
                    "status": "Submitted",
                    "target_submit": date(2026, 8, 10),
                    "bant_score": 78,
                    "bant_detail": {"budget": 20, "authority": 20, "need": 20, "timeline": 18, "budget_mrr": 45000000, "pic_name": "Lisa Permata", "pic_position": "Head of Product", "pic_email": "lisa@mediainteraktif.id", "need_description": "Real-time analytics dashboard untuk monitoring user engagement 2M+ DAU", "timeline_target": "2026-08-10"},
                    "use_case_tags": ["analytics", "quicksight", "kinesis"],
                    "sales": sales1.id,
                    "sa": sa1.id,
                    "dq_number": "DQ-2026-00301",
                },
                {
                    "id_project": "PRJ-DEMO-008",
                    "project_name": "Multi-Region Database Migration",
                    "customer_name": "PT Global Logistics",
                    "status": "Assigned",
                    "target_submit": date(2026, 10, 30),
                    "bant_score": 70,
                    "bant_detail": {"budget": 20, "authority": 15, "need": 20, "timeline": 15, "budget_mrr": 65000000, "pic_name": "Agus Salim", "pic_position": "VP Technology", "pic_email": "agus@globallogistics.co.id", "need_description": "Multi-region Aurora PostgreSQL untuk high availability cross Asia Pacific", "timeline_target": "2026-10-30"},
                    "use_case_tags": ["aurora", "rds", "migration"],
                    "sales": sales2.id,
                    "sa": sa2.id,
                    "dq_number": None,
                },
            ]

            for index, proj_data in enumerate(projects_data):
                sa = proj_data.pop("sa")
                sales = proj_data.pop("sales")
                detail = proj_data.pop("bant_detail")
                proj_data["qualification_answers"] = qualification_answers_for_demo(
                    detail["budget_mrr"],
                    detail["pic_name"],
                    detail["pic_position"],
                    detail["pic_email"],
                    detail["need_description"],
                )
                await get_or_create_project(
                    db,
                    proj_data,
                    sales_id=sales,
                    sa_id=sa,
                    product_id=(product1 if index % 2 == 0 else product2).id,
                )

            # == 3. Buat Documents ==
            print("\n[3/4] Membuat demo documents...")

            documents_data = [
                {"id_doc": "DOC-001", "id_project": "PRJ-DEMO-001", "doc_type": "PropTek", "status": "Draft", "gdrive_link": "https://drive.google.com/file/d/demo-proptek-001", "folder_type": "Solutions", "notes": "Draft PropTek migrasi data warehouse"},
                {"id_doc": "DOC-002", "id_project": "PRJ-DEMO-001", "doc_type": "BOQ", "status": "Draft", "gdrive_link": "https://drive.google.com/file/d/demo-boq-001", "folder_type": "Solutions", "notes": "Estimasi BOQ Redshift + S3 + Glue"},
                {"id_doc": "DOC-003", "id_project": "PRJ-DEMO-002", "doc_type": "PropTek", "status": "Reviewed", "gdrive_link": "https://drive.google.com/file/d/demo-proptek-002", "folder_type": "Solutions", "notes": "PropTek sudah di-review lead SA"},
                {"id_doc": "DOC-004", "id_project": "PRJ-DEMO-002", "doc_type": "BOQ", "status": "Final", "gdrive_link": "https://drive.google.com/file/d/demo-boq-002", "folder_type": "Solutions", "notes": "BOQ final EKS cluster"},
                {"id_doc": "DOC-005", "id_project": "PRJ-DEMO-005", "doc_type": "HLD", "status": "Final", "gdrive_link": "https://drive.google.com/file/d/demo-hld-005", "folder_type": "Solutions", "notes": "HLD IoT pipeline (Won)"},
                {"id_doc": "DOC-006", "id_project": "PRJ-DEMO-006", "doc_type": "PropTek", "status": "Draft", "gdrive_link": "https://drive.google.com/file/d/demo-proptek-006", "folder_type": "Solutions", "notes": "Draft Security Compliance"},
                {"id_doc": "DOC-007", "id_project": "PRJ-DEMO-007", "doc_type": "PropTek", "status": "Reviewed", "gdrive_link": "https://drive.google.com/file/d/demo-proptek-007", "folder_type": "Solutions", "notes": "PropTek analytics dashboard"},
                {"id_doc": "DOC-008", "id_project": "PRJ-DEMO-008", "doc_type": "BOQ", "status": "Draft", "gdrive_link": "https://drive.google.com/file/d/demo-boq-008", "folder_type": "Solutions", "notes": "BOQ Aurora multi-region"},
            ]

            for doc_data in documents_data:
                await get_or_create_document(db, doc_data, created_by=sa1.id)

            # == 4. Buat Activity Logs — tersebar beberapa bulan untuk demo utilisasi ==
            print("\n[4/4] Membuat demo activity logs...")

            # Helper: buat datetime di bulan tertentu
            def make_date(year: int, month: int, day: int) -> datetime:
                return datetime(year, month, day, 10, 0, 0, tzinfo=timezone.utc)

            # Semua log Project default fase Pre-Implementation (mayoritas pre-sales).
            # Non-Project: id_project & project_phase None, subtask dari set Non-Project.
            PRE = "Pre-Implementation"
            activity_logs_data = [
                # === SA1 (Demo SA) — Juni 2026 ===
                {"id_log": "LOG-001", "work_type": "Project", "id_project": "PRJ-DEMO-005", "project_phase": PRE, "subtask_category": "Customer Meeting", "duration_hours": 2.0, "raw_notes": "Meeting IoT Data Pipeline dengan PT Koneksi Pintar. Diskusi arsitektur Kinesis + Lambda.", "created_at": make_date(2026, 6, 3)},
                {"id_log": "LOG-002", "work_type": "Project", "id_project": "PRJ-DEMO-005", "project_phase": PRE, "subtask_category": "Technical Document", "duration_hours": 6.0, "raw_notes": "Menyusun PropTek IoT pipeline: Kinesis Data Streams + Firehose + S3 + Athena.", "created_at": make_date(2026, 6, 5)},
                {"id_log": "LOG-003", "work_type": "Project", "id_project": "PRJ-DEMO-005", "project_phase": PRE, "subtask_category": "Customer Meeting", "duration_hours": 4.0, "raw_notes": "Workshop demo IoT data ingestion dengan customer. Hands-on Kinesis producer SDK.", "created_at": make_date(2026, 6, 10)},
                # === SA1 — Non-Project Juni 2026 ===
                {"id_log": "LOG-NP1", "work_type": "Non-Project", "subtask_category": "Training", "duration_hours": 8.0, "raw_notes": "AWS Analytics Specialty training (hari 1).", "created_at": make_date(2026, 6, 12)},
                {"id_log": "LOG-NP2", "work_type": "Non-Project", "subtask_category": "Self-Lab", "duration_hours": 3.0, "raw_notes": "Hands-on lab Kinesis Data Analytics di akun sandbox.", "created_at": make_date(2026, 6, 18)},
                # === SA1 — Juli 2026 ===
                {"id_log": "LOG-004", "work_type": "Project", "id_project": "PRJ-DEMO-001", "project_phase": PRE, "subtask_category": "Customer Meeting", "duration_hours": 2.0, "raw_notes": "Meeting awal dengan PT Nusantara Digital. Diskusi kebutuhan migrasi DWH on-premise ke Redshift.", "created_at": make_date(2026, 7, 2)},
                {"id_log": "LOG-005", "work_type": "Project", "id_project": "PRJ-DEMO-001", "project_phase": PRE, "subtask_category": "Technical Document", "duration_hours": 8.0, "raw_notes": "Menyusun draft PropTek Redshift Serverless + S3 data lake. Termasuk diagram arsitektur dan sizing.", "created_at": make_date(2026, 7, 7)},
                {"id_log": "LOG-006", "work_type": "Project", "id_project": "PRJ-DEMO-007", "project_phase": PRE, "subtask_category": "Internal Meeting", "duration_hours": 2.0, "raw_notes": "Diskusi internal tentang arsitektur Real-Time Analytics: Kinesis vs MSK untuk streaming.", "created_at": make_date(2026, 7, 12)},
                {"id_log": "LOG-007", "work_type": "Project", "id_project": "PRJ-DEMO-007", "project_phase": PRE, "subtask_category": "Technical Document", "duration_hours": 5.0, "raw_notes": "Buat PropTek real-time analytics: Kinesis + Lambda + QuickSight.", "created_at": make_date(2026, 7, 15)},
                # === SA1 — Agustus 2026 ===
                {"id_log": "LOG-008", "work_type": "Project", "id_project": "PRJ-DEMO-001", "project_phase": PRE, "subtask_category": "Document Review", "duration_hours": 2.0, "raw_notes": "Peer review PropTek DWH migration dengan Budi. Feedback: tambahkan cost comparison.", "created_at": make_date(2026, 8, 4)},
                {"id_log": "LOG-009", "work_type": "Project", "id_project": "PRJ-DEMO-001", "project_phase": PRE, "subtask_category": "Commercial Document", "duration_hours": 4.0, "raw_notes": "Menyusun BOQ Redshift RA3 nodes + S3 storage + Glue ETL jobs.", "created_at": make_date(2026, 8, 8)},
                {"id_log": "LOG-010", "work_type": "Project", "id_project": "PRJ-DEMO-007", "project_phase": PRE, "subtask_category": "Customer Meeting", "duration_hours": 3.0, "raw_notes": "Workshop QuickSight dashboard demo ke PT Media Interaktif.", "created_at": make_date(2026, 8, 15)},

                # === SA2 (Budi Prakoso) — Juli 2026 ===
                {"id_log": "LOG-011", "work_type": "Project", "id_project": "PRJ-DEMO-002", "project_phase": PRE, "subtask_category": "Customer Meeting", "duration_hours": 2.0, "raw_notes": "Meeting awal EKS migration. Customer ingin pindah dari on-prem K8s ke EKS.", "created_at": make_date(2026, 7, 3)},
                {"id_log": "LOG-012", "work_type": "Project", "id_project": "PRJ-DEMO-002", "project_phase": PRE, "subtask_category": "Technical Document", "duration_hours": 7.0, "raw_notes": "PropTek EKS: cluster design, networking (VPC CNI), observability (CloudWatch Container Insights).", "created_at": make_date(2026, 7, 8)},
                {"id_log": "LOG-013", "work_type": "Project", "id_project": "PRJ-DEMO-002", "project_phase": PRE, "subtask_category": "Document Review", "duration_hours": 1.5, "raw_notes": "Peer review PropTek dengan tim SA. Masukan: tambahkan migration runbook.", "created_at": make_date(2026, 7, 14)},
                {"id_log": "LOG-NP3", "work_type": "Non-Project", "subtask_category": "Exam", "duration_hours": 2.0, "raw_notes": "Ujian sertifikasi AWS Solutions Architect Professional.", "created_at": make_date(2026, 7, 20)},
                # === SA2 — Agustus 2026 ===
                {"id_log": "LOG-014", "work_type": "Project", "id_project": "PRJ-DEMO-002", "project_phase": PRE, "subtask_category": "Commercial Document", "duration_hours": 5.0, "raw_notes": "BOQ EKS: compute (m6i.xlarge x 6 nodes), networking, ALB, monitoring.", "created_at": make_date(2026, 8, 2)},
                {"id_log": "LOG-015", "work_type": "Project", "id_project": "PRJ-DEMO-002", "project_phase": PRE, "subtask_category": "Customer Meeting", "duration_hours": 4.0, "raw_notes": "Hands-on EKS deployment workshop. Demo CI/CD pipeline CodePipeline + ArgoCD.", "created_at": make_date(2026, 8, 10)},
                {"id_log": "LOG-016", "work_type": "Project", "id_project": "PRJ-DEMO-008", "project_phase": PRE, "subtask_category": "Customer Meeting", "duration_hours": 2.0, "raw_notes": "Meeting PT Global Logistics: Aurora PostgreSQL multi-region dengan Global Database.", "created_at": make_date(2026, 8, 18)},
                {"id_log": "LOG-017", "work_type": "Project", "id_project": "PRJ-DEMO-008", "project_phase": PRE, "subtask_category": "Commercial Document", "duration_hours": 3.0, "raw_notes": "BOQ Aurora: db.r6g.xlarge primary + 2 reader, cross-region replica.", "created_at": make_date(2026, 8, 22)},

                # === SA3 (Ayu Lestari) — Agustus 2026 ===
                {"id_log": "LOG-018", "work_type": "Project", "id_project": "PRJ-DEMO-006", "project_phase": PRE, "subtask_category": "Assessment", "duration_hours": 2.5, "raw_notes": "Assessment Bank Nusantara: compliance requirement (PCI-DSS, ISO 27001). Diskusi GuardDuty + Security Hub.", "created_at": make_date(2026, 8, 5)},
                {"id_log": "LOG-019", "work_type": "Project", "id_project": "PRJ-DEMO-006", "project_phase": PRE, "subtask_category": "Technical Document", "duration_hours": 6.0, "raw_notes": "PropTek Security Compliance: GuardDuty, Security Hub, Config Rules, CloudTrail.", "created_at": make_date(2026, 8, 9)},
                {"id_log": "LOG-020", "work_type": "Project", "id_project": "PRJ-DEMO-006", "project_phase": PRE, "subtask_category": "Internal Meeting", "duration_hours": 1.5, "raw_notes": "Diskusi internal: best practice landing zone untuk banking sector.", "created_at": make_date(2026, 8, 14)},
                {"id_log": "LOG-021", "work_type": "Project", "id_project": "PRJ-DEMO-006", "project_phase": PRE, "subtask_category": "Document Review", "duration_hours": 2.0, "raw_notes": "Peer review security architecture dengan Lead SA.", "created_at": make_date(2026, 8, 20)},
                {"id_log": "LOG-NP4", "work_type": "Non-Project", "subtask_category": "Self-Learning", "duration_hours": 4.0, "raw_notes": "Belajar AWS Security Hub + Config conformance packs.", "created_at": make_date(2026, 8, 25)},

                # === Lead SA (Demo Lead SA) juga mencatat aktivitasnya ===
                {"id_log": "LOG-022", "work_type": "Project", "id_project": "PRJ-DEMO-006", "project_phase": PRE, "subtask_category": "Principal Meeting", "duration_hours": 1.5, "raw_notes": "Alignment dengan Principal AWS terkait security reference architecture.", "created_at": make_date(2026, 8, 21)},
                {"id_log": "LOG-NP5", "work_type": "Non-Project", "subtask_category": "Internal Presentation", "duration_hours": 2.0, "raw_notes": "Presentasi internal: review utilisasi tim SA kuartal berjalan.", "created_at": make_date(2026, 8, 27)},
                {"id_log": "LOG-NP6", "work_type": "Non-Project", "subtask_category": "Principal Meeting", "duration_hours": 1.5, "raw_notes": "Quarterly sync dengan Principal AWS: roadmap enablement tim SA.", "created_at": make_date(2026, 8, 28)},
            ]

            # Assignment pembuat log per id_log (SA & Lead SA)
            sa_assignment = {
                "LOG-001": sa1.id, "LOG-002": sa1.id, "LOG-003": sa1.id,
                "LOG-NP1": sa1.id, "LOG-NP2": sa1.id,
                "LOG-004": sa1.id, "LOG-005": sa1.id, "LOG-006": sa1.id,
                "LOG-007": sa1.id, "LOG-008": sa1.id, "LOG-009": sa1.id,
                "LOG-010": sa1.id,
                "LOG-011": sa2.id, "LOG-012": sa2.id, "LOG-013": sa2.id,
                "LOG-NP3": sa2.id,
                "LOG-014": sa2.id, "LOG-015": sa2.id, "LOG-016": sa2.id,
                "LOG-017": sa2.id,
                "LOG-018": sa3.id, "LOG-019": sa3.id, "LOG-020": sa3.id,
                "LOG-021": sa3.id, "LOG-NP4": sa3.id,
                "LOG-022": lead_sa.id, "LOG-NP5": lead_sa.id, "LOG-NP6": lead_sa.id,
            }

            for log_data in activity_logs_data:
                sa_id = sa_assignment[log_data["id_log"]]
                await get_or_create_activity_log(db, log_data, sa_id=sa_id)

            # Commit semua perubahan
            await db.commit()

            print("\n" + "=" * 60)
            print("SEEDING SELESAI!")
            print("=" * 60)
            print(f"   Users     : {len(DEMO_USERS)}")
            print(f"   Projects  : {len(projects_data)}")
            print(f"   Documents : {len(documents_data)}")
            print(f"   Logs      : {len(activity_logs_data)}")
            print("=" * 60)
            print("\nLogin sebagai Lead SA untuk melihat utilisasi.")
            print("Login sebagai Sales untuk melihat proyek.")

        except Exception as e:
            await db.rollback()
            print(f"\nERROR: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(seed_all())
