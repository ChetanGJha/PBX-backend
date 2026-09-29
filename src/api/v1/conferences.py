from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/conferences", tags=["Audio & Video Conferences"])


class ConferenceCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    extension_number: str = Field(..., min_length=2, max_length=20)
    pin: Optional[str] = None
    moderator_pin: Optional[str] = None
    max_members: int = 50
    record_conference: bool = False
    wait_for_moderator: bool = False
    announce_join_leave: bool = True
    enabled: bool = True
    tenant_id: Optional[UUID] = None


class ConferenceUpdate(BaseModel):
    name: Optional[str] = None
    extension_number: Optional[str] = None
    pin: Optional[str] = None
    moderator_pin: Optional[str] = None
    max_members: Optional[int] = None
    record_conference: Optional[bool] = None
    wait_for_moderator: Optional[bool] = None
    announce_join_leave: Optional[bool] = None
    enabled: Optional[bool] = None


@router.get("")
async def list_conferences(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id

    query = """
        SELECT c.id, c.tenant_id, c.name, c.extension_number, c.pin, c.moderator_pin,
               c.max_members, c.record_conference, c.wait_for_moderator, c.announce_join_leave,
               c.enabled, c.created_at::text, t.name as tenant_name
        FROM conferences c
        LEFT JOIN tenants t ON c.tenant_id = t.id
    """
    params = {}
    if target_tenant:
        query += " WHERE c.tenant_id = :tenant_id"
        params["tenant_id"] = target_tenant
    query += " ORDER BY c.extension_number ASC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conference(
    payload: ConferenceCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    tid = payload.tenant_id if current_user.is_super_admin else current_user.tenant_id
    if not tid and not current_user.is_super_admin:
        raise HTTPException(status_code=400, detail="tenant_id is required")

    existing = await execute_query_one(
        "SELECT id FROM conferences WHERE tenant_id = :tid AND extension_number = :ext",
        {"tid": tid, "ext": payload.extension_number}
    )
    if existing:
        raise HTTPException(status_code=400, detail="Conference room extension already exists for this tenant")

    query = """
        INSERT INTO conferences (tenant_id, name, extension_number, pin, moderator_pin,
                                max_members, record_conference, wait_for_moderator, announce_join_leave, enabled)
        VALUES (:tenant_id, :name, :extension_number, :pin, :moderator_pin,
                :max_members, :record_conference, :wait_for_moderator, :announce_join_leave, :enabled)
        RETURNING id, tenant_id, name, extension_number, pin, moderator_pin, max_members,
                  record_conference, wait_for_moderator, announce_join_leave, enabled, created_at::text
    """
    data = payload.dict()
    data["tenant_id"] = tid
    row = await execute_query_one(query, data)
    return dict(row)


@router.put("/{conf_id}")
async def update_conference(
    conf_id: UUID,
    payload: ConferenceUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    existing = await execute_query_one(
        "SELECT id, tenant_id FROM conferences WHERE id = :id",
        {"id": conf_id}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Conference not found")
    if not current_user.is_super_admin and str(existing["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    data = payload.dict(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    fields = [f"{k} = :{k}" for k in data.keys()]
    data["id"] = conf_id
    query = f"""
        UPDATE conferences
        SET {', '.join(fields)}
        WHERE id = :id
        RETURNING id, tenant_id, name, extension_number, pin, moderator_pin, max_members,
                  record_conference, wait_for_moderator, announce_join_leave, enabled, created_at::text
    """
    row = await execute_query_one(query, data)
    return dict(row)


@router.delete("/{conf_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conference(
    conf_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    existing = await execute_query_one(
        "SELECT id, tenant_id FROM conferences WHERE id = :id",
        {"id": conf_id}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Conference not found")
    if not current_user.is_super_admin and str(existing["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    await execute_query("DELETE FROM conferences WHERE id = :id", {"id": conf_id})
    return None
