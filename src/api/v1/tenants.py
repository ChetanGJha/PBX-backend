from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/tenants", tags=["Tenants"])

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    domain: str = Field(..., min_length=3, max_length=100)
    sip_domain: Optional[str] = None
    timezone: str = "UTC"
    max_extensions: int = 100
    max_concurrent_calls: int = 20

class TenantStatusUpdate(BaseModel):
    enabled: bool

@router.get("")
async def list_tenants(current_user: CurrentUser = Depends(get_current_user)):
    query = """
        SELECT id, name, domain, sip_domain, timezone, enabled,
               max_extensions, max_concurrent_calls, created_at::text
        FROM tenants
        WHERE deleted_at IS NULL
        ORDER BY name ASC
    """
    rows = await execute_query(query)
    return [dict(r) for r in rows]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    clean_domain = payload.domain.strip().lower()
    sip_dom = payload.sip_domain.strip().lower() if payload.sip_domain else clean_domain

    # Recycler soft-deleted
    await execute_query("DELETE FROM tenants WHERE domain = :domain AND deleted_at IS NOT NULL", {"domain": clean_domain})

    existing = await execute_query_one("SELECT id FROM tenants WHERE domain = :domain AND deleted_at IS NULL", {"domain": clean_domain})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tenant domain '{clean_domain}' is already active."
        )

    query = """
        INSERT INTO tenants (name, domain, sip_domain, timezone, max_extensions, max_concurrent_calls)
        VALUES (:name, :domain, :sip_domain, :timezone, :max_extensions, :max_concurrent_calls)
        RETURNING id, name, domain, sip_domain, timezone, enabled, max_extensions, max_concurrent_calls, created_at::text
    """
    data = payload.dict()
    data["domain"] = clean_domain
    data["sip_domain"] = sip_dom
    row = await execute_query_one(query, data)
    return dict(row)

@router.put("/{tenant_id}/status")
async def toggle_tenant_status(
    tenant_id: UUID,
    payload: TenantStatusUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    query = "UPDATE tenants SET enabled = :enabled, updated_at = NOW() WHERE id = CAST(:id AS uuid) RETURNING id, name, enabled"
    row = await execute_query_one(query, {"id": tenant_id, "enabled": payload.enabled})
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return dict(row)

@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    # Requirement 2 Safeguard: Check allocated gateways, numbers/DIDs, extensions, IVRs
    ext_count = await execute_query_one("SELECT COUNT(*) as cnt FROM extensions WHERE tenant_id = CAST(:id AS uuid) AND deleted_at IS NULL", {"id": tenant_id})
    did_count = await execute_query_one("SELECT COUNT(*) as cnt FROM dids WHERE tenant_id = CAST(:id AS uuid) AND deleted_at IS NULL", {"id": tenant_id})
    gw_count = await execute_query_one("SELECT COUNT(*) as cnt FROM tenant_gateways WHERE tenant_id = CAST(:id AS uuid)", {"id": tenant_id})
    ivr_count = await execute_query_one("SELECT COUNT(*) as cnt FROM ivr_menus WHERE tenant_id = CAST(:id AS uuid)", {"id": tenant_id})

    allocated = []
    if ext_count and ext_count["cnt"] > 0: allocated.append(f"{ext_count['cnt']} Extension(s)")
    if did_count and did_count["cnt"] > 0: allocated.append(f"{did_count['cnt']} DID Number(s)")
    if gw_count and gw_count["cnt"] > 0: allocated.append(f"{gw_count['cnt']} Gateway/Trunk Assignment(s)")
    if ivr_count and ivr_count["cnt"] > 0: allocated.append(f"{ivr_count['cnt']} IVR Menu(s)")

    if allocated:
        details_str = ", ".join(allocated)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete tenant because it has allocated resources: {details_str}. Please unassign or delete allocated resources first."
        )

    await execute_query("UPDATE tenants SET deleted_at = NOW(), enabled = false WHERE id = CAST(:id AS uuid)", {"id": tenant_id})
    return None
