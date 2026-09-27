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
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    host: Optional[str] = None
    port: Optional[int] = 5060
    transport: Optional[str] = "UDP"
    username: Optional[str] = None
    password: Optional[str] = None
    realm: Optional[str] = None
    priority: Optional[int] = 1
    tenant_id: Optional[UUID] = None
    register: Optional[bool] = True
    srtp: Optional[bool] = False

@router.get("")
async def list_trunks(current_user: CurrentUser = Depends(get_current_user)):
    query = """
        SELECT st.id, st.name, st.host, st.port, st.transport, st.username, st.realm, st.priority,
               st.tenant_id, st.register, st.srtp, st.enabled, st.created_at::text,
               t.name as tenant_name, t.domain as tenant_domain
        FROM sip_trunks st
        LEFT JOIN tenants t ON st.tenant_id = t.id
        WHERE st.deleted_at IS NULL
    """
    params = {}
    if not current_user.is_super_admin:
        query += " AND st.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = current_user.tenant_id

    query += " ORDER BY st.priority ASC, st.name ASC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_trunk(
    payload: TrunkCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    query = """
        INSERT INTO sip_trunks (name, host, port, transport, username, password, realm, priority, tenant_id, register, srtp)
        VALUES (:name, :host, :port, :transport, :username, :password, :realm, :priority, :tenant_id, :register, :srtp)
        RETURNING id, name, host, port, transport, username, realm, priority, tenant_id, register, srtp, enabled, created_at::text
    """
    row = await execute_query_one(query, payload.dict())
    return dict(row)

@router.put("/{trunk_id}")
async def update_trunk(
    trunk_id: UUID,
    payload: TrunkUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    existing = await execute_query_one(
        "SELECT id FROM sip_trunks WHERE id = :id AND deleted_at IS NULL",
        {"id": trunk_id}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="SIP Trunk not found")

    data = payload.dict(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields provided for update")

    data["id"] = trunk_id
    set_clauses = []
    for k in data.keys():
        if k == "id":
            continue
        if k == "tenant_id":
            set_clauses.append("tenant_id = CAST(:tenant_id AS uuid)")
        else:
            set_clauses.append(f"{k} = :{k}")
    set_clauses.append("updated_at = NOW()")

    query = f"""
        UPDATE sip_trunks
        SET {', '.join(set_clauses)}
        WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL
        RETURNING id, name, host, port, transport, username, realm, priority, tenant_id, register, srtp, enabled, created_at::text
    """
    row = await execute_query_one(query, data)
    return dict(row)

@router.delete("/{trunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trunk(
    trunk_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    await execute_query("UPDATE sip_trunks SET deleted_at = NOW(), enabled = false WHERE id = :id", {"id": trunk_id})
    return None
