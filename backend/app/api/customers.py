"""Customer identity selection, creation, and authorized rename."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.customer import Customer, normalize_customer_name
from app.models.project import Project
from app.models.user import User

router = APIRouter(prefix="/customers", tags=["Customers"])


class CustomerInput(BaseModel):
    name: str = Field(min_length=1, max_length=150)



@router.get("")
async def list_customers(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role not in {"Sales", "Product", "Lead_SA"} and user.is_admin is not True:
        raise HTTPException(status_code=403, detail="Tidak memiliki akses ke Customer.")
    rows = (await db.execute(select(Customer).order_by(Customer.name))).scalars().all()
    return [{"id": str(customer.id), "name": customer.name} for customer in rows]


@router.post("", status_code=201)
async def create_customer(body: CustomerInput, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "Lead_SA" and user.is_admin is not True:
        raise HTTPException(status_code=403, detail="Hanya Lead SA atau Admin yang dapat membuat Customer.")
    name = body.name.strip()
    normalized = normalize_customer_name(name)
    if not normalized:
        raise HTTPException(status_code=422, detail="Nama Customer wajib diisi.")
    existing = await db.scalar(select(Customer).where(Customer.normalized_name == normalized))
    if existing:
        return {"id": str(existing.id), "name": existing.name}
    customer = Customer(name=name, normalized_name=normalized)
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return {"id": str(customer.id), "name": customer.name}


@router.patch("/{customer_id}")
async def rename_customer(customer_id: uuid.UUID, body: CustomerInput, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "Lead_SA" and user.is_admin is not True:
        raise HTTPException(status_code=403, detail="Hanya Lead SA atau Admin yang dapat mengganti nama Customer.")
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer tidak ditemukan.")
    name = body.name.strip()
    normalized = normalize_customer_name(name)
    if not normalized:
        raise HTTPException(status_code=422, detail="Nama Customer wajib diisi.")
    duplicate = await db.scalar(select(Customer).where(Customer.normalized_name == normalized, Customer.id != customer.id))
    if duplicate:
        raise HTTPException(status_code=409, detail="Customer dengan nama tersebut sudah ada.")
    customer.name = name
    customer.normalized_name = normalized
    await db.execute(update(Project).where(Project.customer_id == customer.id).values(customer_name=name))
    await db.commit()
    return {"id": str(customer.id), "name": customer.name}
