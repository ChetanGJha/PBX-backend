from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/call-block", tags=["Call Block / Blacklist"])


class CallBlockCreate(BaseModel):
    number: str = Field(..., min_length=2, max_length=50, description="Caller ID number to block")
    description: Optional[str] = None
    action: str = Field("reject", description="Action: reject, busy, or voicemail")
    enabled: bool = True
    tenant_id: Optional[UUID] = None


class CallBlockUpdate(BaseModel):
    number: Optional[str] = None
    description: Optional[str] = None
    action: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("")
async def list_blocked_numbers(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id

    query = """
        SELECT b.id, b.tenant_id, b.number, b.description, b.action, b.enabled,
               b.created_at::text, b.updated_at::text, t.name as tenant_name
        FROM call_block b
        LEFT JOIN tenants t ON b.tenant_id = t.id
    """
    params = {}
    if target_tenant:
        query += " WHERE b.tenant_id = :tenant_id"
        params["tenant_id"] = target_tenant
    query += " ORDER BY b.created_at DESC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_call_block(
    payload: CallBlockCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    tid = payload.tenant_id if current_user.is_super_admin else current_user.tenant_id
    if not tid and not current_user.is_super_admin:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    existing = await execute_query_one(
        "SELECT id FROM call_block WHERE tenant_id = :tid AND number = :num",
        {"tid": tid, "num": payload.number}
    )
    if existing:
        raise HTTPException(status_code=400, detail="Number already in blacklist for this tenant")

    query = """
        INSERT INTO call_block (tenant_id, number, description, action, enabled)
        VALUES (:tenant_id, :number, :description, :action, :enabled)
        RETURNING id, tenant_id, number, description, action, enabled, created_at::text, updated_at::text
    """
    data = payload.dict()
    data["tenant_id"] = tid
    row = await execute_query_one(query, data)
    return dict(row)


@router.put("/{block_id}")
async def update_call_block(
    block_id: UUID,
    payload: CallBlockUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    existing = await execute_query_one("SELECT id, tenant_id FROM call_block WHERE id = :id", {"id": block_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Block entry not found")
    if not current_user.is_super_admin and str(existing["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    data = payload.dict(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    fields = [f"{k} = :{k}" for k in data.keys()]
    data["id"] = block_id
    query = f"""
        UPDATE call_block
        SET {', '.join(fields)}, updated_at = NOW()
        WHERE id = :id
        RETURNING id, tenant_id, number, description, action, enabled, created_at::text, updated_at::text
    """
    row = await execute_query_one(query, data)
    return dict(row)


@router.delete("/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_call_block(
    block_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    existing = await execute_query_one("SELECT id, tenant_id FROM call_block WHERE id = :id", {"id": block_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Block entry not found")
    if not current_user.is_super_admin and str(existing["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    await execute_query("DELETE FROM call_block WHERE id = :id", {"id": block_id})
    return None
