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
