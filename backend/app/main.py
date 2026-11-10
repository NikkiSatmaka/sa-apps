"""
Portal SA MVP — Backend FastAPI Application
Entry point utama untuk API backend.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.activity_logs import router as activity_logs_router
from app.api.admin import router as admin_router
from app.api.assignment import router as assignment_router
from app.api.auth import router as auth_router
from app.api.calendar import router as calendar_router
from app.api.collaborators import router as collaborators_router
from app.api.documents import router as documents_router
from app.api.dq_number import router as dq_number_router
from app.api.handover import router as handover_router
from app.api.notifications import router as notifications_router
from app.api.projects import router as projects_router
from app.api.qualification import router as qualification_router
from app.api.scoring import router as scoring_router
from app.api.requirement import router as requirement_router
from app.api.sla import router as sla_router
from app.api.subtasks import router as subtasks_router
from app.api.workflow import router as workflow_router
from app.core.config import settings
from app.core.database import check_database_health
from app.core.exceptions import register_exception_handlers
from app.core.rate_limiter import RateLimiterMiddleware
from app.schemas.response import error_response, success_response
from app.services.gemini_adapter import GeminiAdapter
from app.services.llm_provider import llm_factory
from app.services.sla_scheduler import SLAScheduler

logger = logging.getLogger(__name__)

# Background scheduler internal untuk Flow 2 (SLA DQ Number & gating).
# Memanggil process_sla_actions() secara periodik (reminder H+3, eskalasi H+5,
# auto-lock folder Solutions). Lihat ADR 0003.
#
# CATATAN MULTI-INSTANCE: scheduler ini hanya aman untuk MVP single-instance.
# Saat backend di-scale ke banyak instance, setiap instance akan menjalankan
# scheduler-nya sendiri dan menduplikasi aksi SLA. Saat scale-out, pindah ke
# cron eksternal (panggil POST /sla/process) atau tambahkan leader-election.
# Endpoint manual POST /sla/process tetap tersedia berdampingan.
sla_scheduler = SLAScheduler(interval_seconds=settings.SLA_SCHEDULER_INTERVAL_SECONDS)

app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API untuk Portal SA MVP — Manajemen Proyek Pre-Sales & Activity Log",
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Konfigurasi CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiter middleware (100 req/min/user, sliding window)
app.add_middleware(RateLimiterMiddleware)

# Daftarkan custom exception handlers agar semua response pakai format standar
register_exception_handlers(app)

# Register API routers
# Urutan penting: Starlette mencocokkan route sesuai urutan registrasi.
# assignment_router harus sebelum projects_router karena punya route literal
# `GET /projects/pending-assignment` yang sebaliknya tertangkap oleh
# `GET /projects/{project_id}`. Dijaga oleh tests/test_route_shadowing.py.
app.include_router(auth_router, prefix="/api/v1")
app.include_router(scoring_router, prefix="/api/v1")
app.include_router(requirement_router, prefix="/api/v1")
app.include_router(assignment_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(dq_number_router, prefix="/api/v1")
app.include_router(activity_logs_router, prefix="/api/v1")
app.include_router(calendar_router, prefix="/api/v1")
app.include_router(sla_router, prefix="/api/v1")
app.include_router(qualification_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(handover_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(collaborators_router, prefix="/api/v1")
app.include_router(subtasks_router, prefix="/api/v1")


@app.on_event("startup")
async def startup_register_adapters():
    """
    Daftarkan dependency yang dibutuhkan saat startup.
    Pembuatan skema tabel ditangani sepenuhnya oleh Alembic migration,
    bukan oleh aplikasi saat startup.
    """
    # Hard guard: refuse-to-start jika demo mode diaktifkan di produksi.
    # Guard ditaruh di startup (bukan Pydantic validator) agar Settings() tetap
    # bisa di-import — mis. untuk tooling/test — tanpa gagal; blokir hanya saat
    # app benar-benar naik.
    if settings.ENVIRONMENT == "production" and settings.DEMO_MODE:
        raise RuntimeError(
            "DEMO_MODE tidak boleh aktif saat ENVIRONMENT=production. "
            "Matikan DEMO_MODE (set false) sebelum menjalankan app di produksi."
        )

    # Register LLM adapter agar scoring engine dan summarize bisa berfungsi
    try:
        llm_factory.register_adapter("gemini", GeminiAdapter)
        logger.info("GeminiAdapter registered in LLM factory.")
    except Exception as e:
        logger.error(f"Failed to register GeminiAdapter: {e}", exc_info=True)

    # Jalankan background scheduler SLA (Flow 2). Toggle lewat SLA_SCHEDULER_ENABLED
    # agar bisa dimatikan di tooling/test. Lihat ADR 0003 + catatan multi-instance
    # pada definisi sla_scheduler di atas.
    if settings.SLA_SCHEDULER_ENABLED:
        sla_scheduler.start()
    else:
        logger.info("SLA scheduler dinonaktifkan (SLA_SCHEDULER_ENABLED=false).")


@app.on_event("shutdown")
async def shutdown_stop_scheduler():
    """Hentikan background scheduler SLA dengan rapi saat backend dimatikan."""
    await sla_scheduler.stop()


@app.get("/health")
async def health_check():
    """
    Health check endpoint untuk Docker dan monitoring.
    Tidak memerlukan autentikasi.
    Mencerminkan status koneksi database sebenarnya; jika database
    tidak bisa diakses, response mengembalikan HTTP 503.
    """
    db_healthy = await check_database_health()

    if not db_healthy:
        return JSONResponse(
            status_code=503,
            content=error_response(
                data={"api": "healthy", "database": "unhealthy"},
                message="Database tidak dapat diakses.",
            ),
        )

    return success_response(
        data={"api": "healthy", "database": "healthy"},
        message="Service berjalan normal.",
    )
