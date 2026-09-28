from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr, Field
from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, CurrentUser, require_roles, validate_tenant_access
from src.core.security import hash_password

router = APIRouter(prefix="/extensions", tags=["Extension Management"])


class ExtensionCreate(BaseModel):
    tenant_id: Optional[str] = Field(None, description="Tenant ID (derived from user context if omitted)")
    extension_number: str = Field(..., min_length=2, max_length=20, example="1001")
    display_name: str = Field(..., min_length=2, max_length=100, example="John Doe")
    email: Optional[str] = None
    sip_password: str = Field(..., min_length=8, description="SIP authentication password")
    voicemail_pin: Optional[str] = Field("1234", min_length=4, max_length=10)
    caller_id_name: Optional[str] = None
    caller_id_number: Optional[str] = None
    outbound_caller_id: Optional[str] = None
    emergency_caller_id: Optional[str] = None
    webrtc_enabled: Optional[bool] = True
    no_answer_timeout: Optional[int] = 20


class ExtensionUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    caller_id_name: Optional[str] = None
    caller_id_number: Optional[str] = None
    outbound_caller_id: Optional[str] = None
    emergency_caller_id: Optional[str] = None
    enabled: Optional[bool] = None
    webrtc_enabled: Optional[bool] = None
    no_answer_timeout: Optional[int] = None


class ResetPasswordPayload(BaseModel):
    new_sip_password: Optional[str] = Field(None, min_length=8)
    new_voicemail_pin: Optional[str] = Field(None, min_length=4, max_length=10)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_extension(
    payload: ExtensionCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Create a new extension within the caller's tenant context.
    """
    target_tenant_id = payload.tenant_id if current_user.is_super_admin and payload.tenant_id else current_user.tenant_id
    if not target_tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant ID context missing")

    validate_tenant_access(current_user, target_tenant_id)

    # Check extension quota limit
    tenant = await execute_query_one(
        "SELECT max_extensions FROM tenants WHERE id = :id AND deleted_at IS NULL",
        {"id": target_tenant_id}
    )
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    ext_count = await execute_query_one(
        "SELECT COUNT(*) as cnt FROM extensions WHERE tenant_id = :id AND deleted_at IS NULL",
        {"id": target_tenant_id}
    )
    if ext_count and ext_count["cnt"] >= tenant["max_extensions"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extension limit reached ({tenant['max_extensions']} max extensions allowed for this tenant)"
        )

    # Check extension number uniqueness within tenant
    existing = await execute_query_one(
        "SELECT id FROM extensions WHERE tenant_id = :tenant_id AND extension_number = :num AND deleted_at IS NULL",
        {"tenant_id": target_tenant_id, "num": payload.extension_number}
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extension number '{payload.extension_number}' already exists in this tenant"
        )

    query = """
        INSERT INTO extensions (
            tenant_id, extension_number, display_name, email, sip_password, voicemail_pin,
            caller_id_name, caller_id_number, outbound_caller_id, emergency_caller_id,
            webrtc_enabled, no_answer_timeout
        )
        VALUES (
            :tenant_id, :extension_number, :display_name, :email, :sip_password, :voicemail_pin,
            :caller_id_name, :caller_id_number, :outbound_caller_id, :emergency_caller_id,
            :webrtc_enabled, :no_answer_timeout
        )
        RETURNING id, tenant_id, extension_number, display_name, email, caller_id_name,
                  caller_id_number, outbound_caller_id, enabled, webrtc_enabled, no_answer_timeout, created_at
    """
    row = await execute_query_one(query, {
        "tenant_id": target_tenant_id,
        "extension_number": payload.extension_number,
        "display_name": payload.display_name,
        "email": payload.email.strip() if payload.email and payload.email.strip() else None,
        "sip_password": payload.sip_password,
        "voicemail_pin": payload.voicemail_pin or "1234",
        "caller_id_name": payload.caller_id_name or payload.display_name,
        "caller_id_number": payload.caller_id_number or payload.extension_number,
        "outbound_caller_id": payload.outbound_caller_id,
        "emergency_caller_id": payload.emergency_caller_id,
        "webrtc_enabled": payload.webrtc_enabled if payload.webrtc_enabled is not None else True,
        "no_answer_timeout": payload.no_answer_timeout or 20
    })

    return dict(row)


@router.get("")
async def list_extensions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    List all extensions for authenticated user's tenant.
    """
    target_tenant_id = current_user.tenant_id
    if current_user.is_super_admin:
        query = """
            SELECT e.id, e.tenant_id, t.name as tenant_name, e.extension_number, e.display_name,
                   e.email, e.caller_id_name, e.caller_id_number, e.outbound_caller_id,
                   e.enabled, e.webrtc_enabled, e.no_answer_timeout, e.created_at
            FROM extensions e
            JOIN tenants t ON e.tenant_id = t.id
            WHERE e.deleted_at IS NULL
            ORDER BY t.name ASC, e.extension_number ASC
            OFFSET :skip LIMIT :limit
        """
        rows = await execute_query(query, {"skip": skip, "limit": limit})
    else:
        if not target_tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenant context found")
        query = """
            SELECT id, tenant_id, extension_number, display_name, email, caller_id_name,
                   caller_id_number, outbound_caller_id, enabled, webrtc_enabled, no_answer_timeout, created_at
            FROM extensions
            WHERE tenant_id = :tenant_id AND deleted_at IS NULL
            ORDER BY extension_number ASC
            OFFSET :skip LIMIT :limit
        """
        rows = await execute_query(query, {"tenant_id": target_tenant_id, "skip": skip, "limit": limit})

    return [dict(r) for r in rows]


@router.get("/{extension_id}")
async def get_extension(
    extension_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Get extension detailed configuration.
    """
    query = """
        SELECT id, tenant_id, user_id, extension_number, display_name, email,
               caller_id_name, caller_id_number, outbound_caller_id, emergency_caller_id,
               timezone, enabled, webrtc_enabled, no_answer_timeout, created_at, updated_at
        FROM extensions
        WHERE id = :id AND deleted_at IS NULL
    """
    row = await execute_query_one(query, {"id": extension_id})
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extension not found")

    validate_tenant_access(current_user, str(row["tenant_id"]))
    return dict(row)


@router.put("/{extension_id}")
async def update_extension(
    extension_id: str,
    payload: ExtensionUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Update extension configuration.
    """
    ext = await execute_query_one("SELECT tenant_id FROM extensions WHERE id = :id AND deleted_at IS NULL", {"id": extension_id})
    if not ext:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extension not found")

    validate_tenant_access(current_user, str(ext["tenant_id"]))

    query = """
        UPDATE extensions
        SET display_name = COALESCE(:display_name, display_name),
            email = COALESCE(:email, email),
            caller_id_name = COALESCE(:caller_id_name, caller_id_name),
            caller_id_number = COALESCE(:caller_id_number, caller_id_number),
            outbound_caller_id = COALESCE(:outbound_caller_id, outbound_caller_id),
            emergency_caller_id = COALESCE(:emergency_caller_id, emergency_caller_id),
            enabled = COALESCE(:enabled, enabled),
            webrtc_enabled = COALESCE(:webrtc_enabled, webrtc_enabled),
            no_answer_timeout = COALESCE(:no_answer_timeout, no_answer_timeout),
            updated_at = NOW()
        WHERE id = :id AND deleted_at IS NULL
        RETURNING id, tenant_id, extension_number, display_name, email, caller_id_name,
                  caller_id_number, outbound_caller_id, enabled, webrtc_enabled, no_answer_timeout, updated_at
    """
    row = await execute_query_one(query, {
        "id": extension_id,
        "display_name": payload.display_name,
        "email": payload.email,
        "caller_id_name": payload.caller_id_name,
        "caller_id_number": payload.caller_id_number,
        "outbound_caller_id": payload.outbound_caller_id,
        "emergency_caller_id": payload.emergency_caller_id,
        "enabled": payload.enabled,
        "webrtc_enabled": payload.webrtc_enabled,
        "no_answer_timeout": payload.no_answer_timeout
    })

    return dict(row)


@router.post("/{extension_id}/reset-password")
async def reset_extension_credentials(
    extension_id: str,
    payload: ResetPasswordPayload,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Reset SIP authentication password or Voicemail PIN for an extension.
    """
    ext = await execute_query_one("SELECT tenant_id FROM extensions WHERE id = :id AND deleted_at IS NULL", {"id": extension_id})
    if not ext:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extension not found")

    validate_tenant_access(current_user, str(ext["tenant_id"]))

    if not payload.new_sip_password and not payload.new_voicemail_pin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Must provide new SIP password or Voicemail PIN")

    query = """
        UPDATE extensions
        SET sip_password = COALESCE(:sip_password, sip_password),
            voicemail_pin = COALESCE(:voicemail_pin, voicemail_pin),
            updated_at = NOW()
        WHERE id = :id AND deleted_at IS NULL
        RETURNING id, extension_number, updated_at
    """
    row = await execute_query_one(query, {
        "id": extension_id,
        "sip_password": payload.new_sip_password,
        "voicemail_pin": payload.new_voicemail_pin
    })

    return {
        "message": "Extension credentials updated successfully",
        "extension_id": str(row["id"]),
        "extension_number": row["extension_number"]
    }


@router.delete("/{extension_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_extension(
    extension_id: str,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Soft delete extension.
    """
    ext = await execute_query_one("SELECT tenant_id FROM extensions WHERE id = :id AND deleted_at IS NULL", {"id": extension_id})
    if not ext:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extension not found")

    validate_tenant_access(current_user, str(ext["tenant_id"]))

    await execute_query_one(
        "UPDATE extensions SET deleted_at = NOW(), enabled = false WHERE id = :id",
        {"id": extension_id}
    )
    return None
