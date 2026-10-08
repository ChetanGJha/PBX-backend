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
    tenant_ids: Optional[List[UUID]] = None  # Zero, one, or multiple tenants
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
    tenant_ids: Optional[List[UUID]] = None  # Zero, one, or multiple tenants
    register: Optional[bool] = None
    srtp: Optional[bool] = None
    p_asserted_identity: Optional[bool] = None
    enabled: Optional[bool] = None


@router.get("")
async def list_trunks(current_user: CurrentUser = Depends(get_current_user)):
    """
    List all SIP trunks.
    Superadmins see all trunks along with their assigned tenants (zero or more).
    Tenant Admins see trunks specifically assigned to their tenant, plus global shared trunks (assigned to zero tenants).
    """
    if current_user.is_super_admin:
        query = """
            SELECT t.id, t.name, t.host, t.port, t.transport, t.username, t.realm, t.priority,
                   t.tenant_id, t.register, t.srtp, t.enabled, t.created_at::text,
                   COALESCE(
                     json_agg(
                       json_build_object('id', ten.id, 'name', ten.name, 'domain', ten.domain)
                     ) FILTER (WHERE ten.id IS NOT NULL), '[]'::json
                   ) as assigned_tenants,
                   COALESCE(
                     array_agg(ten.id::text) FILTER (WHERE ten.id IS NOT NULL), '{}'
                   ) as tenant_ids,
                   CASE 
                     WHEN COUNT(ten.id) = 0 THEN 'Shared (All Tenants)'
                     WHEN COUNT(ten.id) = 1 THEN MAX(ten.name)
                     ELSE CONCAT(MAX(ten.name), ' +', COUNT(ten.id) - 1, ' more')
                   END as tenant_name,
                   MAX(ten.domain) as tenant_domain
            FROM sip_trunks t
            LEFT JOIN tenant_sip_trunks tst ON t.id = tst.trunk_id
            LEFT JOIN tenants ten ON tst.tenant_id = ten.id
            WHERE t.deleted_at IS NULL
            GROUP BY t.id
            ORDER BY t.priority ASC, t.name ASC
        """
        rows = await execute_query(query)
    else:
        query = """
            SELECT t.id, t.name, t.host, t.port, t.transport, t.username, t.realm, t.priority,
                   t.tenant_id, t.register, t.srtp, t.enabled, t.created_at::text,
                   COALESCE(
                     json_agg(
                       json_build_object('id', ten.id, 'name', ten.name, 'domain', ten.domain)
                     ) FILTER (WHERE ten.id IS NOT NULL), '[]'::json
                   ) as assigned_tenants,
                   COALESCE(
                     array_agg(ten.id::text) FILTER (WHERE ten.id IS NOT NULL), '{}'
                   ) as tenant_ids,
                   CASE 
                     WHEN COUNT(ten.id) = 0 THEN 'Shared (All Tenants)'
                     ELSE MAX(ten.name)
                   END as tenant_name,
                   MAX(ten.domain) as tenant_domain
            FROM sip_trunks t
            LEFT JOIN tenant_sip_trunks tst ON t.id = tst.trunk_id
            LEFT JOIN tenants ten ON tst.tenant_id = ten.id
            WHERE t.deleted_at IS NULL
              AND (
                tst.tenant_id = CAST(:t_id AS uuid)
                OR t.tenant_id = CAST(:t_id AS uuid)
                OR (
                  NOT EXISTS (SELECT 1 FROM tenant_sip_trunks WHERE trunk_id = t.id)
                  AND t.tenant_id IS NULL
                )
              )
            GROUP BY t.id
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
    Create a new SIP trunk provider connection and assign to zero, one, or multiple tenants.
    """
    assigned_tenants: List[UUID] = []
    if payload.tenant_ids is not None:
        assigned_tenants = payload.tenant_ids
    elif payload.tenant_id:
        assigned_tenants = [payload.tenant_id]

    legacy_tenant_id = assigned_tenants[0] if len(assigned_tenants) == 1 else None

    insert_params = payload.dict(exclude={"tenant_ids"})
    insert_params["tenant_id"] = legacy_tenant_id

    query = """
        INSERT INTO sip_trunks (name, host, port, transport, username, password, realm, priority, tenant_id, register, srtp)
        VALUES (:name, :host, :port, :transport, :username, :password, :realm, :priority, :tenant_id, :register, :srtp)
        RETURNING id, name, host, port, transport, username, realm, priority, register, srtp, enabled, created_at::text
    """
    row = await execute_query_one(query, insert_params)
    trunk_id = row["id"]

    # Insert into tenant_sip_trunks junction table
    for tid in assigned_tenants:
        await execute_query(
            "INSERT INTO tenant_sip_trunks (tenant_id, trunk_id) VALUES (CAST(:tid AS uuid), CAST(:trid AS uuid)) ON CONFLICT DO NOTHING",
            {"tid": str(tid), "trid": str(trunk_id)}
        )

    res = dict(row)
    res["tenant_ids"] = [str(t) for t in assigned_tenants]
    return res


@router.put("/{trunk_id}")
async def update_trunk(
    trunk_id: UUID,
    payload: TrunkUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
    Update SIP trunk settings and multi-tenant assignment (zero or more tenants).
    """
    existing = await execute_query_one(
        "SELECT id FROM sip_trunks WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL",
        {"id": str(trunk_id)}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="SIP trunk not found")

    updates = []
    params = {"id": str(trunk_id)}

    data = payload.dict(exclude_unset=True, exclude={"tenant_ids", "tenant_id"})
    for field, val in data.items():
        updates.append(f"{field} = :{field}")
        params[field] = val

    # Determine tenant assignment updates
    assigned_tenants: Optional[List[UUID]] = None
    if payload.tenant_ids is not None:
        assigned_tenants = payload.tenant_ids
    elif "tenant_id" in payload.dict(exclude_unset=True):
        if payload.tenant_id is not None:
            assigned_tenants = [payload.tenant_id]
        else:
            assigned_tenants = []

    if assigned_tenants is not None:
        # Clear existing assignments
        await execute_query(
            "DELETE FROM tenant_sip_trunks WHERE trunk_id = CAST(:trid AS uuid)",
            {"trid": str(trunk_id)}
        )
        for tid in assigned_tenants:
            await execute_query(
                "INSERT INTO tenant_sip_trunks (tenant_id, trunk_id) VALUES (CAST(:tid AS uuid), CAST(:trid AS uuid)) ON CONFLICT DO NOTHING",
                {"tid": str(tid), "trid": str(trunk_id)}
            )
        # Update legacy tenant_id field
        if len(assigned_tenants) == 1:
            updates.append("tenant_id = CAST(:legacy_tid AS uuid)")
            params["legacy_tid"] = str(assigned_tenants[0])
        else:
            updates.append("tenant_id = NULL")

    if not updates and assigned_tenants is None:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    if updates:
        query = f"""
            UPDATE sip_trunks
            SET {', '.join(updates)}, updated_at = NOW()
            WHERE id = CAST(:id AS uuid)
            RETURNING id, name, host, port, transport, username, realm, priority, tenant_id, register, srtp, enabled, created_at::text
        """
        row = await execute_query_one(query, params)
    else:
        row = await execute_query_one(
            "SELECT id, name, host, port, transport, username, realm, priority, tenant_id, register, srtp, enabled, created_at::text FROM sip_trunks WHERE id = CAST(:id AS uuid)",
            {"id": str(trunk_id)}
        )

    # Fetch updated assigned tenant ids
    t_rows = await execute_query(
        "SELECT tenant_id::text FROM tenant_sip_trunks WHERE trunk_id = CAST(:trid AS uuid)",
        {"trid": str(trunk_id)}
    )
    res = dict(row)
    res["tenant_ids"] = [r["tenant_id"] for r in t_rows]
    return res


@router.delete("/{trunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trunk(
    trunk_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
    Delete a SIP trunk and clean up tenant associations.
    """
    await execute_query("UPDATE sip_trunks SET deleted_at = NOW(), enabled = false WHERE id = CAST(:id AS uuid)", {"id": str(trunk_id)})
    await execute_query("DELETE FROM tenant_sip_trunks WHERE trunk_id = CAST(:id AS uuid)", {"id": str(trunk_id)})
    return None
