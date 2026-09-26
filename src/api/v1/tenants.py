from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, CurrentUser, require_roles, validate_tenant_access

router = APIRouter(prefix="/tenants", tags=["Tenants"])


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    domain: str = Field(..., min_length=3, max_length=255, description="Tenant web domain (e.g., tenant-a.pbx.com)")
    sip_domain: str = Field(..., min_length=3, max_length=255, description="SIP domain (e.g., tenant-a.example.com)")
    branding: Optional[dict] = Field(default_factory=dict)
    timezone: Optional[str] = "UTC"
    max_extensions: Optional[int] = 100
    max_concurrent_calls: Optional[int] = 20


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    branding: Optional[dict] = None
    timezone: Optional[str] = None
    enabled: Optional[bool] = None
    max_extensions: Optional[int] = None
    max_concurrent_calls: Optional[int] = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
    Create a new tenant entity (Super Admin only).
    """
    # Check domain uniqueness among active tenants
    existing_domain = await execute_query_one(
        "SELECT id FROM tenants WHERE (domain = :domain OR sip_domain = :sip_domain) AND deleted_at IS NULL",
        {"domain": payload.domain, "sip_domain": payload.sip_domain}
    )
    if existing_domain:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant domain or SIP domain already registered."
        )

    # Purge any soft-deleted tenant using the same domain to prevent UNIQUE constraint violation
    await execute_query(
        "DELETE FROM tenants WHERE (domain = :domain OR sip_domain = :sip_domain) AND deleted_at IS NOT NULL",
        {"domain": payload.domain, "sip_domain": payload.sip_domain}
    )

    import json
    query = """
        INSERT INTO tenants (name, domain, sip_domain, branding, timezone, max_extensions, max_concurrent_calls)
        VALUES (:name, :domain, :sip_domain, CAST(:branding AS jsonb), :timezone, :max_extensions, :max_concurrent_calls)

        RETURNING id, name, domain, sip_domain, timezone, enabled, max_extensions, max_concurrent_calls, created_at
    """
    row = await execute_query_one(query, {
        "name": payload.name,
        "domain": payload.domain,
        "sip_domain": payload.sip_domain,
        "branding": json.dumps(payload.branding or {}),
        "timezone": payload.timezone or "UTC",
        "max_extensions": payload.max_extensions or 100,
        "max_concurrent_calls": payload.max_concurrent_calls or 20
    })

    return dict(row)


@router.get("")
async def list_tenants(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    List tenants. Super Admin sees all active tenants; Tenant Admin sees their own tenant context.
    """
    if current_user.is_super_admin:
        query = """
            SELECT id, name, domain, sip_domain, timezone, enabled, max_extensions, 
                   max_concurrent_calls, created_at
            FROM tenants
            WHERE deleted_at IS NULL
            ORDER BY name ASC
            OFFSET :skip LIMIT :limit
        """
        rows = await execute_query(query, {"skip": skip, "limit": limit})
    else:
        if not current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenant context found")
        query = """
            SELECT id, name, domain, sip_domain, timezone, enabled, max_extensions, 
                   max_concurrent_calls, created_at
            FROM tenants
            WHERE id = CAST(:tenant_id AS uuid) AND deleted_at IS NULL
        """
        rows = await execute_query(query, {"tenant_id": current_user.tenant_id})

    return [dict(r) for r in rows]


@router.get("/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Get detailed tenant information. Enforces multi-tenant authorization boundaries.
    """
    validate_tenant_access(current_user, tenant_id)

    query = """
        SELECT id, name, domain, sip_domain, branding, timezone, enabled, 
               max_extensions, max_concurrent_calls, created_at, updated_at
        FROM tenants
        WHERE id = CAST(:tenant_id AS uuid) AND deleted_at IS NULL
    """
    row = await execute_query_one(query, {"tenant_id": tenant_id})
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    return dict(row)


@router.put("/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    payload: TenantUpdate,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Update tenant settings. Non-superadmins cannot modify system resource limits or toggle status.
    """
    validate_tenant_access(current_user, tenant_id)

    if not current_user.is_super_admin and (payload.enabled is not None or payload.max_extensions is not None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Super Admin can update tenant resource limits or status"
        )

    import json
    query = """
        UPDATE tenants
        SET name = COALESCE(:name, name),
            branding = CASE WHEN :branding IS NOT NULL THEN CAST(:branding AS jsonb) ELSE branding END,

            timezone = COALESCE(:timezone, timezone),
            enabled = COALESCE(:enabled, enabled),
            max_extensions = COALESCE(:max_extensions, max_extensions),
            max_concurrent_calls = COALESCE(:max_concurrent_calls, max_concurrent_calls),
            updated_at = NOW()
        WHERE id = CAST(:tenant_id AS uuid) AND deleted_at IS NULL
        RETURNING id, name, domain, sip_domain, branding, timezone, enabled, max_extensions, max_concurrent_calls, updated_at
    """
    row = await execute_query_one(query, {
        "tenant_id": tenant_id,
        "name": payload.name,
        "branding": json.dumps(payload.branding) if payload.branding is not None else None,
        "timezone": payload.timezone,
        "enabled": payload.enabled,
        "max_extensions": payload.max_extensions,
        "max_concurrent_calls": payload.max_concurrent_calls
    })

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    return dict(row)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: str,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
    Soft delete tenant (Super Admin only).
    """
    query = "UPDATE tenants SET deleted_at = NOW(), enabled = false WHERE id = CAST(:tenant_id AS uuid) AND deleted_at IS NULL"
    row = await execute_query_one(query, {"tenant_id": tenant_id})
    return None
