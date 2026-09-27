from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/hunt-groups", tags=["Hunt Groups"])

class HuntGroupCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    extension_number: str = Field(..., description="Extension e.g. 8001")
    strategy: str = "sequential"  # sequential, simultaneous, circular
    members: str = Field(..., description="Comma-separated member extension numbers e.g. 1001,1002")
    timeout: int = 20
    tenant_id: Optional[UUID] = None

@router.get("")
async def list_hunt_groups(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT id, name, extension_number, strategy, members, timeout, created_at::text
        FROM hunt_groups
        WHERE deleted_at IS NULL
    """
    params = {}
    if target_tenant:
        query += " AND tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = target_tenant

    query += " ORDER BY extension_number ASC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_hunt_group(
    payload: HuntGroupCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    target_tenant = payload.tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        INSERT INTO hunt_groups (name, extension_number, strategy, members, timeout, tenant_id)
        VALUES (:name, :extension_number, :strategy, :members, :timeout, CAST(:tenant_id AS uuid))
        RETURNING id, name, extension_number, strategy, members, timeout, created_at::text
    """
    data = payload.dict()
    data["tenant_id"] = target_tenant
    row = await execute_query_one(query, data)
    return dict(row)


class HuntGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    extension_number: Optional[str] = None
    strategy: Optional[str] = None
    members: Optional[str] = None
    timeout: Optional[int] = None

@router.put("/{hunt_group_id}")
async def update_hunt_group(
    hunt_group_id: UUID,
    payload: HuntGroupUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    existing = await execute_query_one("SELECT * FROM hunt_groups WHERE id = :id AND deleted_at IS NULL", {"id": hunt_group_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Hunt group not found")
    if not current_user.is_super_admin and str(existing.get("tenant_id")) != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    query = """
        UPDATE hunt_groups
        SET name = COALESCE(:name, name),
            extension_number = COALESCE(:extension_number, extension_number),
            strategy = COALESCE(:strategy, strategy),
            members = COALESCE(:members, members),
            timeout = COALESCE(:timeout, timeout),
            updated_at = NOW()
        WHERE id = :id
        RETURNING id, name, extension_number, strategy, members, timeout, created_at::text
    """
    data = payload.dict(exclude_unset=True)
    data["id"] = hunt_group_id
    for k in ["name", "extension_number", "strategy", "members", "timeout"]:
        if k not in data:
            data[k] = None
    row = await execute_query_one(query, data)
    return dict(row)

@router.delete("/{hunt_group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hunt_group(
    hunt_group_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    existing = await execute_query_one("SELECT * FROM hunt_groups WHERE id = :id AND deleted_at IS NULL", {"id": hunt_group_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Hunt group not found")
    if not current_user.is_super_admin and str(existing.get("tenant_id")) != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    await execute_query("UPDATE hunt_groups SET deleted_at = NOW() WHERE id = :id", {"id": hunt_group_id})
