from typing import Any
from uuid import UUID

from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.user import User


def _brief_person(user: User | None, user_id: UUID | None) -> dict[str, Any] | None:
    if user_id is None:
        return None
    return {
        "id": str(user_id),
        "name": user.name if user else None,
        "email": user.email if user else None,
    }


def _sort_order(sort: str | None):
    if sort:
        descending = sort.startswith("-")
        field_name = sort[1:] if descending else sort
        sort_column = getattr(Project, field_name, None)
        if sort_column is None:
            return desc(Project.updated_at)
        return desc(sort_column) if descending else asc(sort_column)
    return desc(Project.updated_at)


async def build_project_list_page(
    db: AsyncSession,
    filters: list[Any],
    sort: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """Query and serialize one deterministic page for the project-list endpoint."""
    total_result = await db.execute(
        select(func.count()).select_from(Project).where(*filters)
    )
    total = total_result.scalar_one()

    result = await db.execute(
        select(Project)
        .where(*filters)
        .order_by(_sort_order(sort), asc(Project.id_project))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    projects = result.scalars().all()

    person_ids = {
        person_id
        for project in projects
        for person_id in (project.created_by, project.product_pic, project.sales_pic)
        if person_id is not None
    }
    if person_ids:
        people_result = await db.execute(select(User).where(User.id.in_(person_ids)))
        people = {person.id: person for person in people_result.scalars().all()}
    else:
        people = {}

    items = [
        {
            "id_project": project.id_project,
            "project_name": project.project_name,
            "customer_name": project.customer_name,
            "status": project.status,
            "qualification_state": project.qualification_state,
            "dq_number": project.dq_number,
            "bant_score": project.bant_score,
            "use_case_tags": project.use_case_tags or [],
            "estimasi_nilai": (
                str(project.estimasi_nilai) if project.estimasi_nilai is not None else None
            ),
            "target_submit": project.target_submit.isoformat() if project.target_submit else None,
            "assigned_sa": str(project.assigned_sa) if project.assigned_sa else None,
            "created_by": _brief_person(people.get(project.created_by), project.created_by),
            "product_pic": _brief_person(people.get(project.product_pic), project.product_pic),
            "sales_pic": _brief_person(people.get(project.sales_pic), project.sales_pic),
            "gdrive_folder_id": project.gdrive_folder_id,
            "folder_provisioning_status": project.folder_provisioning_status,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        }
        for project in projects
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }
