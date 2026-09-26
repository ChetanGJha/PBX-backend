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

@router.get("")
async def list_trunks(current_user: CurrentUser = Depends(get_current_user)):
    query = """
        SELECT id, name, host, port, transport, username, realm, priority,
               tenant_id, register, srtp, enabled, created_at::text
        FROM sip_trunks
        WHERE deleted_at IS NULL
        ORDER BY priority ASC, name ASC
    """
    rows = await execute_query(query)
    return [dict(r) for r in rows]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_trunk(
    payload: TrunkCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    query = """
        INSERT INTO sip_trunks (name, host, port, transport, username, password, realm, priority, tenant_id, register, srtp)
        VALUES (:name, :host, :port, :transport, :username, :password, :realm, :priority, :tenant_id, :register, :srtp)
        RETURNING id, name, host, port, transport, username, realm, priority, register, srtp, enabled, created_at::text
    """
    row = await execute_query_one(query, payload.dict())
    return dict(row)

@router.delete("/{trunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trunk(
    trunk_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    await execute_query("UPDATE sip_trunks SET deleted_at = NOW(), enabled = false WHERE id = :id", {"id": trunk_id})
    return None
