from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/contacts", tags=["Contacts Directory"])


class ContactCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: Optional[str] = None
    organization: Optional[str] = None
    phone_primary: str = Field(..., min_length=3, max_length=50)
    phone_mobile: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None
    tenant_id: Optional[UUID] = None


class ContactUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    organization: Optional[str] = None
    phone_primary: Optional[str] = None
    phone_mobile: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


@router.get("")
async def list_contacts(
    search: Optional[str] = None,
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id

    query = """
        SELECT c.id, c.tenant_id, c.first_name, c.last_name, c.organization,
               c.phone_primary, c.phone_mobile, c.email, c.notes,
               c.created_at::text, c.updated_at::text, t.name as tenant_name
        FROM contacts c
        LEFT JOIN tenants t ON c.tenant_id = t.id
    """
    where_clauses = []
    params = {}
    if target_tenant:
        where_clauses.append("c.tenant_id = :tenant_id")
        params["tenant_id"] = target_tenant
    if search:
        where_clauses.append("(c.first_name ILIKE :search OR c.last_name ILIKE :search OR c.phone_primary ILIKE :search OR c.organization ILIKE :search)")
        params["search"] = f"%{search}%"
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += " ORDER BY c.first_name ASC, c.last_name ASC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_contact(
    payload: ContactCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN", "SUPERVISOR", "AGENT"]))
):
    tid = payload.tenant_id if current_user.is_super_admin else current_user.tenant_id
    if not tid and not current_user.is_super_admin:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    query = """
        INSERT INTO contacts (tenant_id, first_name, last_name, organization, phone_primary, phone_mobile, email, notes)
        VALUES (:tenant_id, :first_name, :last_name, :organization, :phone_primary, :phone_mobile, :email, :notes)
        RETURNING id, tenant_id, first_name, last_name, organization, phone_primary, phone_mobile, email, notes, created_at::text, updated_at::text
    """
    data = payload.dict()
    data["tenant_id"] = tid
    row = await execute_query_one(query, data)
    return dict(row)


@router.put("/{contact_id}")
async def update_contact(
    contact_id: UUID,
    payload: ContactUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN", "SUPERVISOR", "AGENT"]))
):
    existing = await execute_query_one("SELECT id, tenant_id FROM contacts WHERE id = :id", {"id": contact_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Contact not found")
    if not current_user.is_super_admin and str(existing["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    data = payload.dict(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    fields = [f"{k} = :{k}" for k in data.keys()]
    data["id"] = contact_id
    query = f"""
        UPDATE contacts
        SET {', '.join(fields)}, updated_at = NOW()
        WHERE id = :id
        RETURNING id, tenant_id, first_name, last_name, organization, phone_primary, phone_mobile, email, notes, created_at::text, updated_at::text
    """
    row = await execute_query_one(query, data)
    return dict(row)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN", "SUPERVISOR", "AGENT"]))
):
    existing = await execute_query_one("SELECT id, tenant_id FROM contacts WHERE id = :id", {"id": contact_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Contact not found")
    if not current_user.is_super_admin and str(existing["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    await execute_query("DELETE FROM contacts WHERE id = :id", {"id": contact_id})
    return None
