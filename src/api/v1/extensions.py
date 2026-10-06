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



class ExtensionVoicemailPayload(BaseModel):
    mailbox: Optional[str] = None
    password: Optional[str] = None
    email_notification: Optional[bool] = None
    email_attach_file: Optional[bool] = None
    email_address: Optional[str] = None
    delete_after_email: Optional[bool] = None
    greeting_path: Optional[str] = None

class ExtensionForwardingPayload(BaseModel):
    forward_always_enabled: Optional[bool] = None
    forward_always_destination: Optional[str] = None
    forward_busy_enabled: Optional[bool] = None
    forward_busy_destination: Optional[str] = None
    forward_no_answer_enabled: Optional[bool] = None
    forward_no_answer_destination: Optional[str] = None
    forward_no_answer_timeout: Optional[int] = None


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

    # Check active extension number uniqueness within tenant
    existing_active = await execute_query_one(
        "SELECT id FROM extensions WHERE tenant_id = :tenant_id AND extension_number = :num AND deleted_at IS NULL",
        {"tenant_id": target_tenant_id, "num": payload.extension_number}
    )
    if existing_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extension number '{payload.extension_number}' already exists in this tenant"
        )

    # Check for soft-deleted extension with the same extension_number (to free up constraint)
    existing_deleted = await execute_query_one(
        "SELECT id FROM extensions WHERE tenant_id = :tenant_id AND extension_number = :num AND deleted_at IS NOT NULL",
        {"tenant_id": target_tenant_id, "num": payload.extension_number}
    )
    if existing_deleted:
        await execute_query_one(
            "UPDATE extensions SET extension_number = extension_number || '_del_' || substr(md5(random()::text), 1, 6) WHERE id = :id",
            {"id": existing_deleted["id"]}
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
    try:
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
    except Exception as exc:
        err_str = str(exc)
        if "extensions_tenant_id_extension_number_key" in err_str or "unique constraint" in err_str.lower() or "duplicate key" in err_str.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Extension number '{payload.extension_number}' already exists in this tenant"
            )
        raise

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



@router.get("/call-forwarding/all")
async def list_all_call_forwarding(
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = None if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT e.id as extension_id, e.extension_number, e.display_name, e.tenant_id, t.name as tenant_name,
               cf.forward_always_enabled, cf.forward_always_destination,
               cf.forward_busy_enabled, cf.forward_busy_destination,
               cf.forward_no_answer_enabled, cf.forward_no_answer_destination,
               COALESCE(cf.forward_no_answer_timeout, e.no_answer_timeout, 20) as forward_no_answer_timeout,
               cf.updated_at::text
        FROM extensions e
        LEFT JOIN call_forwarding cf ON e.id = cf.extension_id
        LEFT JOIN tenants t ON e.tenant_id = t.id
        WHERE e.deleted_at IS NULL
    """
    params = {}
    if target_tenant:
        query += " AND e.tenant_id = :tenant_id"
        params["tenant_id"] = target_tenant
    query += " ORDER BY e.extension_number ASC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.get("/voicemail-boxes/all")
async def list_all_voicemail_boxes(
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = None if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT e.id as extension_id, e.extension_number, e.display_name, e.tenant_id, t.name as tenant_name,
               vb.id as voicemail_box_id,
               COALESCE(vb.mailbox, e.extension_number) as mailbox,
               COALESCE(vb.password, e.voicemail_pin, '1234') as password,
               COALESCE(vb.email_notification, e.voicemail_to_email, true) as email_notification,
               COALESCE(vb.email_attach_file, true) as email_attach_file,
               COALESCE(vb.email_address, e.voicemail_email, e.email) as email_address,
               COALESCE(vb.delete_after_email, false) as delete_after_email,
               vb.greeting_path,
               vb.created_at::text
        FROM extensions e
        LEFT JOIN voicemail_boxes vb ON e.id = vb.extension_id
        LEFT JOIN tenants t ON e.tenant_id = t.id
        WHERE e.deleted_at IS NULL
    """
    params = {}
    if target_tenant:
        query += " AND e.tenant_id = :tenant_id"
        params["tenant_id"] = target_tenant
    query += " ORDER BY e.extension_number ASC"
    rows = await execute_query(query, params)
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
        "UPDATE extensions SET deleted_at = NOW(), enabled = false, extension_number = extension_number || '_del_' || substr(md5(random()::text), 1, 6) WHERE id = :id",
        {"id": extension_id}
    )
    return None

@router.delete("/{extension_id}/voicemail", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voicemail_box(
    extension_id: str,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Delete voicemail box configuration for an extension.
    """
    ext = await execute_query_one("SELECT tenant_id FROM extensions WHERE id = :id AND deleted_at IS NULL", {"id": extension_id})
    if not ext:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Extension not found")

    validate_tenant_access(current_user, str(ext["tenant_id"]))

    await execute_query_one(
        "DELETE FROM voicemail_boxes WHERE extension_id = CAST(:id AS uuid) RETURNING id",
        {"id": extension_id}
    )
    await execute_query_one(
        "UPDATE extensions SET voicemail_pin = NULL, voicemail_email = NULL WHERE id = CAST(:id AS uuid) RETURNING id",
        {"id": extension_id}
    )
    return None

@router.get("/{extension_id}/forwarding")
async def get_extension_forwarding(
    extension_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    ext = await execute_query_one("SELECT id, tenant_id, extension_number FROM extensions WHERE id = :id AND deleted_at IS NULL", {"id": extension_id})
    if not ext:
        raise HTTPException(status_code=404, detail="Extension not found")
    validate_tenant_access(current_user, str(ext["tenant_id"]))
    row = await execute_query_one("SELECT * FROM call_forwarding WHERE extension_id = :id", {"id": extension_id})
    if not row:
        return {
            "extension_id": extension_id,
            "forward_always_enabled": False,
            "forward_always_destination": None,
            "forward_busy_enabled": False,
            "forward_busy_destination": None,
            "forward_no_answer_enabled": False,
            "forward_no_answer_destination": None,
            "forward_no_answer_timeout": 20
        }
    return dict(row)


@router.put("/{extension_id}/forwarding")
async def update_extension_forwarding(
    extension_id: str,
    payload: ExtensionForwardingPayload,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN", "AGENT"]))
):
    ext = await execute_query_one("SELECT id, tenant_id, extension_number FROM extensions WHERE id = :id AND deleted_at IS NULL", {"id": extension_id})
    if not ext:
        raise HTTPException(status_code=404, detail="Extension not found")
    validate_tenant_access(current_user, str(ext["tenant_id"]))

    # Clean boolean flags and destinations
    fae = bool(payload.forward_always_enabled) if payload.forward_always_enabled is not None else False
    fad = (payload.forward_always_destination or "").strip() or None if fae else None

    fbe = bool(payload.forward_busy_enabled) if payload.forward_busy_enabled is not None else False
    fbd = (payload.forward_busy_destination or "").strip() or None if fbe else None

    fne = bool(payload.forward_no_answer_enabled) if payload.forward_no_answer_enabled is not None else False
    fnd = (payload.forward_no_answer_destination or "").strip() or None if fne else None
    fnt = int(payload.forward_no_answer_timeout or 20)

    upsert_sql = """
        INSERT INTO call_forwarding (
            extension_id, forward_always_enabled, forward_always_destination,
            forward_busy_enabled, forward_busy_destination,
            forward_no_answer_enabled, forward_no_answer_destination,
            forward_no_answer_timeout, updated_at
        ) VALUES (
            CAST(:id AS uuid), :fae, :fad, :fbe, :fbd, :fne, :fnd, :fnt, NOW()
        )
        ON CONFLICT (extension_id) DO UPDATE SET
            forward_always_enabled = EXCLUDED.forward_always_enabled,
            forward_always_destination = EXCLUDED.forward_always_destination,
            forward_busy_enabled = EXCLUDED.forward_busy_enabled,
            forward_busy_destination = EXCLUDED.forward_busy_destination,
            forward_no_answer_enabled = EXCLUDED.forward_no_answer_enabled,
            forward_no_answer_destination = EXCLUDED.forward_no_answer_destination,
            forward_no_answer_timeout = EXCLUDED.forward_no_answer_timeout,
            updated_at = NOW()
        RETURNING *
    """
    row = await execute_query_one(upsert_sql, {
        "id": extension_id,
        "fae": fae,
        "fad": fad,
        "fbe": fbe,
        "fbd": fbd,
        "fne": fne,
        "fnd": fnd,
        "fnt": fnt
    })

    # Always keep extensions table in strict sync
    await execute_query_one(
        """
        UPDATE extensions
        SET call_forward_enabled = :en,
            call_forward_destination = :dest,
            call_forward_type = :ftype,
            updated_at = NOW()
        WHERE id = CAST(:id AS uuid)
        RETURNING id
        """,
        {
            "en": fae,
            "dest": fad,
            "ftype": "always" if fae else None,
            "id": extension_id
        }
    )

    return dict(row)


@router.delete("/{extension_id}/forwarding")
async def delete_extension_forwarding(
    extension_id: str,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN", "AGENT"]))
):
    """
    Completely reset and remove all call forwarding rules for this extension.
    """
    ext = await execute_query_one("SELECT id, tenant_id FROM extensions WHERE id = :id AND deleted_at IS NULL", {"id": extension_id})
    if not ext:
        raise HTTPException(status_code=404, detail="Extension not found")
    validate_tenant_access(current_user, str(ext["tenant_id"]))

    await execute_query("DELETE FROM call_forwarding WHERE extension_id = CAST(:id AS uuid)", {"id": extension_id})
    await execute_query(
        """
        UPDATE extensions
        SET call_forward_enabled = false,
            call_forward_destination = NULL,
            call_forward_type = NULL,
            updated_at = NOW()
        WHERE id = CAST(:id AS uuid)
        """,
        {"id": extension_id}
    )
    return {"status": "success", "message": "Call forwarding rule deleted successfully"}


@router.get("/{extension_id}/voicemail")
async def get_extension_voicemail(
    extension_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    ext = await execute_query_one("SELECT id, tenant_id, extension_number, voicemail_pin, voicemail_email, voicemail_to_email FROM extensions WHERE id = :id AND deleted_at IS NULL", {"id": extension_id})
    if not ext:
        raise HTTPException(status_code=404, detail="Extension not found")
    validate_tenant_access(current_user, str(ext["tenant_id"]))
    row = await execute_query_one("SELECT * FROM voicemail_boxes WHERE extension_id = :id", {"id": extension_id})
    if not row:
        return {
            "extension_id": extension_id,
            "mailbox": ext["extension_number"],
            "password": ext.get("voicemail_pin") or "1234",
            "email_notification": ext.get("voicemail_to_email") if ext.get("voicemail_to_email") is not None else True,
            "email_attach_file": True,
            "email_address": ext.get("voicemail_email") or "",
            "delete_after_email": False,
            "greeting_path": None
        }
    return dict(row)


@router.put("/{extension_id}/voicemail")
async def update_extension_voicemail(
    extension_id: str,
    payload: ExtensionVoicemailPayload,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN", "AGENT"]))
):
    ext = await execute_query_one("SELECT id, tenant_id, extension_number, voicemail_pin, voicemail_email, voicemail_to_email FROM extensions WHERE id = :id AND deleted_at IS NULL", {"id": extension_id})
    if not ext:
        raise HTTPException(status_code=404, detail="Extension not found")
    validate_tenant_access(current_user, str(ext["tenant_id"]))

    mailbox = payload.mailbox or ext["extension_number"]
    password = payload.password or ext.get("voicemail_pin") or "1234"
    email_notification = payload.email_notification if payload.email_notification is not None else True
    email_attach = payload.email_attach_file if payload.email_attach_file is not None else True
    email_addr = payload.email_address
    del_after = payload.delete_after_email if payload.delete_after_email is not None else False

    upsert_sql = """
        INSERT INTO voicemail_boxes (
            tenant_id, extension_id, mailbox, password,
            email_notification, email_attach_file, email_address,
            delete_after_email, greeting_path
        ) VALUES (
            :tid, :eid, :mbox, :pwd, :enotif, :eatt, :eaddr, :dae, :greet
        )
        ON CONFLICT (tenant_id, mailbox) DO UPDATE SET
            password = EXCLUDED.password,
            email_notification = EXCLUDED.email_notification,
            email_attach_file = EXCLUDED.email_attach_file,
            email_address = EXCLUDED.email_address,
            delete_after_email = EXCLUDED.delete_after_email,
            greeting_path = COALESCE(EXCLUDED.greeting_path, voicemail_boxes.greeting_path)
        RETURNING *
    """
    row = await execute_query_one(upsert_sql, {
        "tid": ext["tenant_id"],
        "eid": extension_id,
        "mbox": mailbox,
        "pwd": password,
        "enotif": email_notification,
        "eatt": email_attach,
        "eaddr": email_addr,
        "dae": del_after,
        "greet": payload.greeting_path
    })

    # Sync with extensions table
    await execute_query_one(
        "UPDATE extensions SET voicemail_pin = :pwd, voicemail_email = :eaddr, voicemail_to_email = :enotif WHERE id = :id RETURNING id",
        {"pwd": password, "eaddr": email_addr, "enotif": email_notification, "id": extension_id}
    )

    return dict(row)
