import logging
from uuid import uuid4
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, CurrentUser, require_roles
from src.core.email_service import get_smtp_settings, send_email_smtp

logger = logging.getLogger("pbx.api.smtp")

router = APIRouter(prefix="/settings/smtp", tags=["SMTP Settings"])


class SmtpSettingsResponse(BaseModel):
    configured: bool
    is_using_global_fallback: bool = False
    id: Optional[str] = None
    tenant_id: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    use_tls: Optional[bool] = True
    updated_at: Optional[datetime] = None


class SmtpSettingsUpdate(BaseModel):
    smtp_host: str = Field(..., min_length=2, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    from_email: str = Field(..., min_length=3, max_length=255)
    from_name: Optional[str] = "PBX Voicemail"
    use_tls: bool = True
    tenant_id: Optional[str] = None


class SmtpTestRequest(BaseModel):
    to_email: str = Field(..., min_length=5, max_length=255)
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = "PBX Voicemail"
    use_tls: Optional[bool] = True
    tenant_id: Optional[str] = None


@router.get("", response_model=SmtpSettingsResponse)
async def get_smtp_config(
    tenant_id: Optional[str] = Query(None, description="Tenant ID (Super Admin only)"),
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Get current SMTP settings.
    - Tenant Admins receive their tenant's settings, or fallback to global if not overridden.
    - Super Admins can query specific tenants or global settings (tenant_id=None).
    """
    target_tenant_id = current_user.tenant_id if not current_user.is_super_admin else tenant_id

    settings_row, is_global = await get_smtp_settings(target_tenant_id)
    if not settings_row:
        return SmtpSettingsResponse(
            configured=False,
            is_using_global_fallback=False,
            tenant_id=target_tenant_id
        )

    # Only treat as fallback if a specific tenant was requested and fell back to global
    is_fallback = is_global and (target_tenant_id is not None)

    return SmtpSettingsResponse(
        configured=True,
        is_using_global_fallback=is_fallback,
        id=str(settings_row["id"]) if settings_row.get("id") else None,
        tenant_id=str(settings_row["tenant_id"]) if settings_row.get("tenant_id") else None,
        smtp_host=settings_row.get("smtp_host"),
        smtp_port=settings_row.get("smtp_port"),
        smtp_username=settings_row.get("smtp_username"),
        smtp_password=settings_row.get("smtp_password"),
        from_email=settings_row.get("from_email"),
        from_name=settings_row.get("from_name"),
        use_tls=bool(settings_row.get("use_tls", True)),
        updated_at=settings_row.get("updated_at")
    )


@router.put("")
async def update_smtp_config(
    payload: SmtpSettingsUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Create or update SMTP settings.
    - Preserves existing password if empty or masked '••••••••' is submitted.
    - Tenant Admins can only update their own tenant settings.
    - Super Admins can update global (tenant_id=None) or any tenant settings.
    """
    target_tenant_id = current_user.tenant_id if not current_user.is_super_admin else payload.tenant_id

    # Check for existing record
    if target_tenant_id:
        existing = await execute_query_one(
            "SELECT id, smtp_password FROM email_settings WHERE tenant_id = CAST(:tid AS uuid)",
            {"tid": target_tenant_id}
        )
    else:
        existing = await execute_query_one(
            "SELECT id, smtp_password FROM email_settings WHERE tenant_id IS NULL LIMIT 1"
        )

    # Resolve password: if empty or masked, retain existing
    final_password = payload.smtp_password
    if final_password in (None, "", "••••••••"):
        final_password = existing.get("smtp_password") if existing else None

    if existing:
        # UPDATE
        await execute_query(
            """
            UPDATE email_settings
            SET smtp_host = :host,
                smtp_port = :port,
                smtp_username = :username,
                smtp_password = :password,
                from_email = :from_email,
                from_name = :from_name,
                use_tls = :use_tls,
                updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
            """,
            {
                "id": str(existing["id"]),
                "host": payload.smtp_host,
                "port": payload.smtp_port,
                "username": payload.smtp_username,
                "password": final_password,
                "from_email": payload.from_email,
                "from_name": payload.from_name,
                "use_tls": payload.use_tls
            }
        )
        logger.info(f"Updated SMTP settings for tenant={target_tenant_id or 'GLOBAL'}")
    else:
        # INSERT
        new_id = str(uuid4())
        if target_tenant_id:
            await execute_query(
                """
                INSERT INTO email_settings (
                    id, tenant_id, smtp_host, smtp_port, smtp_username,
                    smtp_password, from_email, from_name, use_tls, updated_at
                ) VALUES (
                    CAST(:id AS uuid), CAST(:tid AS uuid),
                    :host, :port, :username, :password, :from_email, :from_name, :use_tls, NOW()
                )
                """,
                {
                    "id": new_id,
                    "tid": target_tenant_id,
                    "host": payload.smtp_host,
                    "port": payload.smtp_port,
                    "username": payload.smtp_username,
                    "password": final_password,
                    "from_email": payload.from_email,
                    "from_name": payload.from_name,
                    "use_tls": payload.use_tls
                }
            )
        else:
            await execute_query(
                """
                INSERT INTO email_settings (
                    id, tenant_id, smtp_host, smtp_port, smtp_username,
                    smtp_password, from_email, from_name, use_tls, updated_at
                ) VALUES (
                    CAST(:id AS uuid), NULL,
                    :host, :port, :username, :password, :from_email, :from_name, :use_tls, NOW()
                )
                """,
                {
                    "id": new_id,
                    "host": payload.smtp_host,
                    "port": payload.smtp_port,
                    "username": payload.smtp_username,
                    "password": final_password,
                    "from_email": payload.from_email,
                    "from_name": payload.from_name,
                    "use_tls": payload.use_tls
                }
            )
        logger.info(f"Created new SMTP settings for tenant={target_tenant_id or 'GLOBAL'}")

    return {"status": "success", "message": "SMTP settings saved successfully"}


@router.delete("")
async def delete_smtp_config(
    tenant_id: Optional[str] = Query(None, description="Tenant ID (Super Admin only)"),
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Delete custom SMTP settings.
    - For a tenant: resets custom SMTP and reverts to global PBX fallback.
    - For Super Admin with no tenant_id: deletes global default SMTP settings.
    """
    target_tenant_id = current_user.tenant_id if not current_user.is_super_admin else tenant_id

    if target_tenant_id:
        await execute_query(
            "DELETE FROM email_settings WHERE tenant_id = CAST(:tid AS uuid)",
            {"tid": target_tenant_id}
        )
        logger.info(f"Deleted custom SMTP settings for tenant {target_tenant_id}; reverted to global fallback")
        return {"status": "success", "message": "Custom tenant SMTP settings deleted; reverted to global default."}
    else:
        await execute_query("DELETE FROM email_settings WHERE tenant_id IS NULL")
        logger.info("Deleted global default SMTP settings")
        return {"status": "success", "message": "Global default SMTP settings deleted."}


@router.post("/test")
async def test_smtp_connection(
    payload: SmtpTestRequest,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Send a test email to verify SMTP credentials and server connectivity.
    """
    target_tenant_id = current_user.tenant_id if not current_user.is_super_admin else payload.tenant_id

    if payload.smtp_host:
        # User is testing credentials entered in the form before saving
        final_password = payload.smtp_password
        if final_password in (None, "", "••••••••"):
            existing, _ = await get_smtp_settings(target_tenant_id)
            if existing:
                final_password = existing.get("smtp_password")

        smtp_cfg = {
            "smtp_host": payload.smtp_host,
            "smtp_port": payload.smtp_port or 587,
            "smtp_username": payload.smtp_username,
            "smtp_password": final_password,
            "from_email": payload.from_email or "voicemail@pbx.local",
            "from_name": payload.from_name or "PBX Voicemail",
            "use_tls": bool(payload.use_tls if payload.use_tls is not None else True)
        }
    else:
        # Test saved configuration
        existing, is_global = await get_smtp_settings(target_tenant_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No SMTP settings configured for this tenant or globally."
            )
        smtp_cfg = existing

    # Prepare Test Email Content
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    subject = "PBX SMTP Configuration Test Email"
    html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 24px;">
  <div style="max-width: 500px; margin: 0 auto; background-color: #1e293b; padding: 24px; border-radius: 8px; border: 1px solid #334155;">
    <h2 style="color: #38bdf8; margin-top: 0;">PBX SMTP Connection Test</h2>
    <p>Success! Your SMTP configuration is working correctly.</p>
    <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
      <tr><td style="color: #94a3b8; padding: 6px 0;">SMTP Host:</td><td><strong>{smtp_cfg.get('smtp_host')}:{smtp_cfg.get('smtp_port')}</strong></td></tr>
      <tr><td style="color: #94a3b8; padding: 6px 0;">Sender Email:</td><td>{smtp_cfg.get('from_email')}</td></tr>
      <tr><td style="color: #94a3b8; padding: 6px 0;">Test Timestamp:</td><td>{now_str} UTC</td></tr>
    </table>
    <p style="margin-top: 20px; font-size: 12px; color: #64748b;">This test email confirms your PBX can deliver voicemail recordings and notifications via SMTP.</p>
  </div>
</body>
</html>"""

    success, err_msg = await send_email_smtp(
        smtp_cfg=smtp_cfg,
        to_email=payload.to_email,
        subject=subject,
        html_body=html_body,
        attachment_path=None
    )

    if not success:
        return {"success": False, "error": err_msg}

    return {"success": True, "message": f"Test email successfully delivered to {payload.to_email}"}
