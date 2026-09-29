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
    enabled: Optional[bool] = True


class HuntGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    extension_number: Optional[str] = None
    strategy: Optional[str] = None
    members: Optional[str] = None
    timeout: Optional[int] = None
    enabled: Optional[bool] = None


@router.get("")
async def list_hunt_groups(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT id, name, extension_number, strategy, members, timeout, enabled, created_at::text, tenant_id
        FROM hunt_groups
        WHERE deleted_at IS NULL
    """
    params = {}
    if target_tenant:
        query += " AND tenant_id = :t_id"
        params["t_id"] = target_tenant

    query += " ORDER BY extension_number ASC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_hunt_group(
    payload: HuntGroupCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    target_tenant = payload.tenant_id if current_user.is_super_admin and payload.tenant_id else current_user.tenant_id
    if not target_tenant and not current_user.is_super_admin:
        raise HTTPException(status_code=400, detail="Tenant ID is required")

    check_sql = "SELECT id FROM hunt_groups WHERE extension_number = :ext AND deleted_at IS NULL"
    check_params = {"ext": payload.extension_number}
    if target_tenant:
        check_sql += " AND tenant_id = :tid"
        check_params["tid"] = target_tenant
    existing = await execute_query_one(check_sql, check_params)
    if existing:
        raise HTTPException(status_code=400, detail=f"Extension {payload.extension_number} is already assigned to another hunt group")

    query = """
        INSERT INTO hunt_groups (name, extension_number, strategy, members, timeout, tenant_id, enabled)
        VALUES (:name, :extension_number, :strategy, :members, :timeout, :tenant_id, :enabled)
        RETURNING id, name, extension_number, strategy, members, timeout, enabled, created_at::text
    """
    data = {
        "name": payload.name,
        "extension_number": payload.extension_number,
        "strategy": payload.strategy or "sequential",
        "members": payload.members,
        "timeout": payload.timeout or 20,
        "tenant_id": target_tenant,
        "enabled": payload.enabled if payload.enabled is not None else True
    }
    row = await execute_query_one(query, data)
    return dict(row)


@router.put("/{hunt_group_id}")
async def update_hunt_group(
    hunt_group_id: UUID,
    payload: HuntGroupUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    existing = await execute_query_one("SELECT * FROM hunt_groups WHERE id = :id AND deleted_at IS NULL", {"id": hunt_group_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Hunt group not found")
    if not current_user.is_super_admin and str(existing.get("tenant_id")) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    updates = []
    params = {"id": hunt_group_id}

    if payload.name is not None:
        updates.append("name = :name")
        params["name"] = payload.name
    if payload.extension_number is not None:
        updates.append("extension_number = :extension_number")
        params["extension_number"] = payload.extension_number
    if payload.strategy is not None:
        updates.append("strategy = :strategy")
        params["strategy"] = payload.strategy
    if payload.members is not None:
        updates.append("members = :members")
        params["members"] = payload.members
    if payload.timeout is not None:
        updates.append("timeout = :timeout")
        params["timeout"] = payload.timeout
    if payload.enabled is not None:
        updates.append("enabled = :enabled")
        params["enabled"] = payload.enabled

    if not updates:
        return dict(existing)

    updates.append("updated_at = NOW()")
    sql = f"UPDATE hunt_groups SET {', '.join(updates)} WHERE id = :id RETURNING id, name, extension_number, strategy, members, timeout, enabled, created_at::text"
    row = await execute_query_one(sql, params)
    return dict(row)


@router.delete("/{hunt_group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hunt_group(
    hunt_group_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    existing = await execute_query_one("SELECT * FROM hunt_groups WHERE id = :id AND deleted_at IS NULL", {"id": hunt_group_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Hunt group not found")
    if not current_user.is_super_admin and str(existing.get("tenant_id")) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    await execute_query("UPDATE hunt_groups SET deleted_at = NOW() WHERE id = :id", {"id": hunt_group_id})
    return None
