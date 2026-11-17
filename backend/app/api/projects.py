"""Project API router composed from stable use-case modules."""

from fastapi import APIRouter

from app.api.project_intake_api import router as project_intake_router
from app.api.project_lifecycle_api import router as project_lifecycle_router
from app.api.project_list_api import router as project_list_router

router = APIRouter(prefix="/projects", tags=["Projects"])
router.include_router(project_list_router)
router.include_router(project_lifecycle_router)
router.include_router(project_intake_router)
