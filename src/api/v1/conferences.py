from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser
from src.services.conference_service import (
    get_conference_live_status,
    terminate_conference,
    kick_conference_member
)

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
    tenant_id: Optional[UUID] = None


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
        query += " WHERE c.tenant_id = CAST(:tenant_id AS uuid)"
        params["tenant_id"] = str(target_tenant)
    query += " ORDER BY c.extension_number ASC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.get("/live")
async def list_live_conferences(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Returns real-time status of all conferences (active calls, participants, moderator presence).
    """
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id

    query = """
        SELECT c.id, c.tenant_id, c.name, c.extension_number, c.pin, c.moderator_pin,
               c.max_members, c.record_conference, c.enabled, t.name as tenant_name
        FROM conferences c
        LEFT JOIN tenants t ON c.tenant_id = t.id
        WHERE c.enabled = true
    """
    params = {}
    if target_tenant:
        query += " AND c.tenant_id = CAST(:tenant_id AS uuid)"
        params["tenant_id"] = str(target_tenant)
    query += " ORDER BY c.extension_number ASC"

    rows = await execute_query(query, params)
    result = []
    for r in rows:
        conf_dict = dict(r)
        conf_name = conf_dict.get("name") or f"conf_{conf_dict.get('extension_number')}"
        live_status = get_conference_live_status(conf_name)
        conf_dict["live"] = live_status
        result.append(conf_dict)
    return result



@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conference(
    payload: ConferenceCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    tid = payload.tenant_id if current_user.is_super_admin and payload.tenant_id else current_user.tenant_id
    if not tid:
        # fallback to first active tenant if superadmin
        first_t = await execute_query_one("SELECT id FROM tenants WHERE deleted_at IS NULL ORDER BY created_at ASC LIMIT 1")
        if first_t:
            tid = first_t["id"]
        else:
            raise HTTPException(status_code=400, detail="tenant_id is required")

    existing = await execute_query_one(
        "SELECT id FROM conferences WHERE tenant_id = CAST(:tid AS uuid) AND extension_number = :ext",
        {"tid": str(tid), "ext": payload.extension_number}
    )
    if existing:
        raise HTTPException(status_code=400, detail="Conference room extension already exists for this tenant")

    query = """
        INSERT INTO conferences (tenant_id, name, extension_number, pin, moderator_pin,
                                max_members, record_conference, wait_for_moderator, announce_join_leave, enabled)
        VALUES (CAST(:tenant_id AS uuid), :name, :extension_number, :pin, :moderator_pin,
                :max_members, :record_conference, :wait_for_moderator, :announce_join_leave, :enabled)
        RETURNING id, tenant_id, name, extension_number, pin, moderator_pin, max_members,
                  record_conference, wait_for_moderator, announce_join_leave, enabled, created_at::text
    """
    data = payload.dict()
    data["tenant_id"] = str(tid)
    row = await execute_query_one(query, data)
    return dict(row)


@router.put("/{conf_id}")
async def update_conference(
    conf_id: UUID,
    payload: ConferenceUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    existing = await execute_query_one(
        "SELECT id, tenant_id FROM conferences WHERE id = CAST(:id AS uuid)",
        {"id": str(conf_id)}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Conference not found")
    if not current_user.is_super_admin and str(existing["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    data = payload.dict(exclude_unset=True)
    if not current_user.is_super_admin:
        data.pop("tenant_id", None)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    fields = []
    params = {}
    for k, v in data.items():
        if k == "tenant_id":
            fields.append("tenant_id = CAST(:tenant_id AS uuid)")
            params["tenant_id"] = str(v)
        else:
            fields.append(f"{k} = :{k}")
            params[k] = v
    params["id"] = str(conf_id)
    query = f"""
        UPDATE conferences
        SET {', '.join(fields)}
        WHERE id = CAST(:id AS uuid)
        RETURNING id, tenant_id, name, extension_number, pin, moderator_pin, max_members,
                  record_conference, wait_for_moderator, announce_join_leave, enabled, created_at::text
    """
    row = await execute_query_one(query, params)
    return dict(row)


@router.delete("/{conf_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conference(
    conf_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    existing = await execute_query_one(
        "SELECT id, tenant_id FROM conferences WHERE id = CAST(:id AS uuid)",
        {"id": str(conf_id)}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Conference not found")
    if not current_user.is_super_admin and str(existing["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    await execute_query("DELETE FROM conferences WHERE id = CAST(:id AS uuid)", {"id": str(conf_id)})
    return None


@router.get("/{conf_id}/live")
async def get_conference_live(
    conf_id: UUID,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Returns real-time status of a specific conference room.
    """
    conf = await execute_query_one(
        "SELECT id, tenant_id, name, extension_number, pin, moderator_pin FROM conferences WHERE id = CAST(:id AS uuid)",
        {"id": str(conf_id)}
    )
    if not conf:
        raise HTTPException(status_code=404, detail="Conference room not found")
    if not current_user.is_super_admin and str(conf["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    conf_name = conf.get("name") or f"conf_{conf.get('extension_number')}"
    live_status = get_conference_live_status(conf_name)
    return {
        "id": conf["id"],
        "name": conf["name"],
        "extension_number": conf["extension_number"],
        "live": live_status
    }


@router.post("/{conf_id}/terminate")
@router.post("/{conf_id}/cancel")
async def terminate_conference_endpoint(
    conf_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Immediately drops/cancels all active calls in the conference room.
    Only tenant admins and super admins can execute this.
    """
    conf = await execute_query_one(
        "SELECT id, tenant_id, name, extension_number FROM conferences WHERE id = CAST(:id AS uuid)",
        {"id": str(conf_id)}
    )
    if not conf:
        raise HTTPException(status_code=404, detail="Conference room not found")
    if not current_user.is_super_admin and str(conf["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied: Only tenant admin can cancel conference calls")

    conf_name = conf.get("name") or f"conf_{conf.get('extension_number')}"
    success = terminate_conference(conf_name)
    return {
        "status": "terminated" if success else "failed",
        "conference_id": str(conf_id),
        "message": f"Conference '{conf_name}' disconnected successfully."
    }


@router.post("/{conf_id}/kick/{member_id}")
async def kick_conference_member_endpoint(
    conf_id: UUID,
    member_id: str,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Hangs up and drops a specific participant from the active conference call.
    Only tenant admins and super admins can execute this.
    """
    conf = await execute_query_one(
        "SELECT id, tenant_id, name, extension_number FROM conferences WHERE id = CAST(:id AS uuid)",
        {"id": str(conf_id)}
    )
    if not conf:
        raise HTTPException(status_code=404, detail="Conference room not found")
    if not current_user.is_super_admin and str(conf["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied: Only tenant admin can drop conference participants")

    conf_name = conf.get("name") or f"conf_{conf.get('extension_number')}"
    kick_conference_member(conf_name, member_id)
    return {
        "status": "kicked",
        "conference_id": str(conf_id),
        "member_id": member_id,
        "message": f"Member {member_id} dropped from conference '{conf_name}'."
    }

