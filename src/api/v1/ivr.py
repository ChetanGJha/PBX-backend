from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/ivr", tags=["IVR Menus"])

class IvrCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    greeting_audio: Optional[str] = "welcome_prompt.wav"
    direct_extension_dial: bool = True
    timeout: int = 10
    tenant_id: Optional[UUID] = None

class IvrActionCreate(BaseModel):
    digit: str = Field(..., description="DTMF digit 0-9, *, #")
    action_type: str = "extension"  # extension, queue, voicemail, external, hangup
    destination: str

@router.get("")
async def list_ivrs(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT id, name, greeting_audio, direct_extension_dial, timeout, created_at::text
        FROM ivr_menus
        WHERE deleted_at IS NULL
    """
    params = {}
    if target_tenant:
        query += " AND tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = target_tenant

    query += " ORDER BY name ASC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_ivr(
    payload: IvrCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    target_tenant = payload.tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        INSERT INTO ivr_menus (name, greeting_audio, direct_extension_dial, timeout, tenant_id)
        VALUES (:name, :greeting_audio, :direct_extension_dial, :timeout, CAST(:tenant_id AS uuid))
        RETURNING id, name, greeting_audio, direct_extension_dial, timeout, created_at::text
    """
    data = payload.dict()
    data["tenant_id"] = target_tenant
    row = await execute_query_one(query, data)
    return dict(row)
