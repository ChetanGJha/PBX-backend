from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/extensions", tags=["Extensions"])

class ExtensionCreate(BaseModel):
    extension_number: str = Field(..., min_length=2, max_length=20)
    display_name: str = Field(..., min_length=2, max_length=100)
    email: Optional[str] = None
    sip_password: str = Field(..., min_length=6)
    voicemail_pin: Optional[str] = Field("1234", min_length=4)
    tenant_id: Optional[UUID] = None

class PasswordResetPayload(BaseModel):
    new_sip_password: Optional[str] = Field(None, min_length=6)
    new_voicemail_pin: Optional[str] = Field(None, min_length=4)

class ExtensionSettingsPayload(BaseModel):
    voicemail_email: Optional[str] = None
    voicemail_to_email: bool = False
    follow_me_enabled: bool = False
    follow_me_destination: Optional[str] = None
    follow_me_timeout: int = 20
    call_forward_enabled: bool = False
    call_forward_type: str = "always"  # always, busy, no_answer
    call_forward_destination: Optional[str] = None

@router.get("")
async def list_extensions(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT e.id, e.extension_number, e.display_name, e.email, e.enabled,
               e.voicemail_email, e.voicemail_to_email, e.follow_me_enabled,
               e.follow_me_destination, e.follow_me_timeout, e.call_forward_enabled,
               e.call_forward_type, e.call_forward_destination, e.created_at::text,
               t.name as tenant_name, t.domain as tenant_domain
        FROM extensions e
        LEFT JOIN tenants t ON e.tenant_id = t.id
        WHERE e.deleted_at IS NULL
    """
    params = {}
    if target_tenant:
        query += " AND e.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = target_tenant

    query += " ORDER BY e.extension_number ASC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_extension(
    payload: ExtensionCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    target_tenant = payload.tenant_id if current_user.is_super_admin else current_user.tenant_id
    if not target_tenant:
        raise HTTPException(status_code=400, detail="Tenant ID is required to create extension.")

    query = """
        INSERT INTO extensions (extension_number, display_name, email, sip_password, voicemail_pin, tenant_id)
        VALUES (:extension_number, :display_name, :email, :sip_password, :voicemail_pin, CAST(:tenant_id AS uuid))
        RETURNING id, extension_number, display_name, email, enabled, created_at::text
    """
    data = payload.dict()
    data["tenant_id"] = target_tenant
    row = await execute_query_one(query, data)
    return dict(row)

@router.post("/{extension_id}/reset-password")
async def reset_extension_password(
    extension_id: UUID,
    payload: PasswordResetPayload,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):

    updates = []
    params = {"id": extension_id}
    if payload.new_sip_password:
        updates.append("sip_password = :sip_password")
        params["sip_password"] = payload.new_sip_password
    if payload.new_voicemail_pin:
        updates.append("voicemail_pin = :voicemail_pin")
        params["voicemail_pin"] = payload.new_voicemail_pin

    if not updates:
        raise HTTPException(status_code=400, detail="No new credentials provided.")

    query = f"UPDATE extensions SET {', '.join(updates)}, updated_at = NOW() WHERE id = CAST(:id AS uuid) RETURNING id, extension_number"
    row = await execute_query_one(query, params)
    if not row:
        raise HTTPException(status_code=404, detail="Extension not found")
    return {"status": "success", "message": "Credentials updated successfully"}

@router.put("/{extension_id}/settings")
async def update_extension_settings(
    extension_id: UUID,
    payload: ExtensionSettingsPayload,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    query = """
        UPDATE extensions
        SET voicemail_email = :voicemail_email,
            voicemail_to_email = :voicemail_to_email,
            follow_me_enabled = :follow_me_enabled,
            follow_me_destination = :follow_me_destination,
            follow_me_timeout = :follow_me_timeout,
            call_forward_enabled = :call_forward_enabled,
            call_forward_type = :call_forward_type,
            call_forward_destination = :call_forward_destination,
            updated_at = NOW()
        WHERE id = CAST(:id AS uuid)
        RETURNING id, extension_number, voicemail_email, voicemail_to_email, follow_me_enabled, call_forward_enabled
    """
    data = payload.dict()
    data["id"] = extension_id
    row = await execute_query_one(query, data)
    if not row:
        raise HTTPException(status_code=404, detail="Extension not found")
    return dict(row)
