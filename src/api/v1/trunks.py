from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/trunks", tags=["SIP Trunks"])


class TrunkCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    host: str = Field(..., description="SIP Proxy or Host IP/Domain")
    port: int = 5060
    transport: str = "UDP"
    username: Optional[str] = None
    password: Optional[str] = None
    realm: Optional[str] = None
    priority: int = 1
    tenant_id: Optional[UUID] = None
    register: bool = True
    srtp: bool = False
    p_asserted_identity: bool = True


class TrunkUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    transport: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    realm: Optional[str] = None
    priority: Optional[int] = None
    tenant_id: Optional[UUID] = None
    register: Optional[bool] = None
    srtp: Optional[bool] = None
    p_asserted_identity: Optional[bool] = None
    enabled: Optional[bool] = None


@router.get("")
async def list_trunks(current_user: CurrentUser = Depends(get_current_user)):
    """
    List all SIP trunks. Superadmins see all; Tenant Admins see their assigned trunks and global shared trunks.
    """
    if current_user.is_super_admin:
        query = """
            SELECT t.id, t.name, t.host, t.port, t.transport, t.username, t.realm, t.priority,
                   t.tenant_id, t.register, t.srtp, t.enabled, t.created_at::text,
                   ten.name as tenant_name, ten.domain as tenant_domain
            FROM sip_trunks t
            LEFT JOIN tenants ten ON t.tenant_id = ten.id
            WHERE t.deleted_at IS NULL
            ORDER BY t.priority ASC, t.name ASC
        """
        rows = await execute_query(query)
    else:
        query = """
            SELECT t.id, t.name, t.host, t.port, t.transport, t.username, t.realm, t.priority,
                   t.tenant_id, t.register, t.srtp, t.enabled, t.created_at::text,
                   ten.name as tenant_name, ten.domain as tenant_domain
            FROM sip_trunks t
            LEFT JOIN tenants ten ON t.tenant_id = ten.id
            WHERE t.deleted_at IS NULL
              AND (t.tenant_id = CAST(:t_id AS uuid) OR t.tenant_id IS NULL)
            ORDER BY t.priority ASC, t.name ASC
        """
        rows = await execute_query(query, {"t_id": str(current_user.tenant_id)})
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_trunk(
    payload: TrunkCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
    Create a new SIP trunk provider connection.
    """
    query = """
        INSERT INTO sip_trunks (name, host, port, transport, username, password, realm, priority, tenant_id, register, srtp)
        VALUES (:name, :host, :port, :transport, :username, :password, :realm, :priority, :tenant_id, :register, :srtp)
        RETURNING id, name, host, port, transport, username, realm, priority, register, srtp, enabled, created_at::text
    """
    row = await execute_query_one(query, payload.dict())
    return dict(row)


@router.put("/{trunk_id}")
async def update_trunk(
    trunk_id: UUID,
    payload: TrunkUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
    Update SIP trunk settings and tenant assignment.
    """
    existing = await execute_query_one(
        "SELECT id FROM sip_trunks WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL",
        {"id": str(trunk_id)}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="SIP trunk not found")

    updates = []
    params = {"id": str(trunk_id)}

    data = payload.dict(exclude_unset=True)
    for field, val in data.items():
        if field == "tenant_id":
            if val is not None:
                updates.append("tenant_id = CAST(:tenant_id AS uuid)")
                params["tenant_id"] = str(val)
            else:
                updates.append("tenant_id = NULL")
        else:
            updates.append(f"{field} = :{field}")
            params[field] = val

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    query = f"""
        UPDATE sip_trunks
        SET {', '.join(updates)}, updated_at = NOW()
        WHERE id = CAST(:id AS uuid)
        RETURNING id, name, host, port, transport, username, realm, priority, tenant_id, register, srtp, enabled, created_at::text
    """
    row = await execute_query_one(query, params)
    return dict(row)


@router.delete("/{trunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trunk(
    trunk_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
    Delete a SIP trunk.
    """
    await execute_query("UPDATE sip_trunks SET deleted_at = NOW(), enabled = false WHERE id = CAST(:id AS uuid)", {"id": str(trunk_id)})
    return None
