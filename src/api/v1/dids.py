from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/dids", tags=["DID Inventory"])

class DidCreate(BaseModel):
    did_number: str = Field(..., description="Phone number e.g. +18005550199")
    trunk_id: Optional[str] = None
    destination_type: str = "extension"
    destination: Optional[str] = None

class DidAssign(BaseModel):
    tenant_id: UUID

@router.get("")
async def list_dids(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    query = """
        SELECT d.id, d.did_number, d.trunk_id, d.tenant_id, d.destination_type,
               d.destination, d.enabled, d.created_at::text,
               t.name as tenant_name, t.domain as tenant_domain,
               s.name as trunk_name, s.host as trunk_host
        FROM dids d
        LEFT JOIN tenants t ON d.tenant_id = t.id
        LEFT JOIN sip_trunks s ON d.trunk_id = s.id
        WHERE d.deleted_at IS NULL
    """
    params = {}
    if not current_user.is_super_admin:
        query += " AND d.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = current_user.tenant_id

    query += " ORDER BY d.did_number ASC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_did(
    payload: DidCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    t_id = payload.trunk_id if payload.trunk_id and payload.trunk_id.strip() != "" else None
    num = payload.did_number.strip()
    dest = payload.destination.strip() if payload.destination and payload.destination.strip() else ""

    # Check if number already exists
    existing = await execute_query_one(
        "SELECT id, deleted_at FROM dids WHERE did_number = :num",
        {"num": num}
    )
    if existing:
        if existing.get("deleted_at"):
            query = """
                UPDATE dids
                SET deleted_at = NULL, trunk_id = CAST(:trunk_id AS uuid),
                    destination_type = :destination_type, destination = :destination,
                    destination_target = :destination_target, tenant_id = NULL, updated_at = NOW()
                WHERE id = CAST(:id AS uuid)
                RETURNING id, did_number, trunk_id, destination_type, destination, enabled, created_at::text
            """
            row = await execute_query_one(query, {
                "id": existing["id"],
                "trunk_id": t_id,
                "destination_type": payload.destination_type or "extension",
                "destination": payload.destination,
                "destination_target": dest
            })
            return dict(row)
        else:
            raise HTTPException(status_code=400, detail=f"DID {num} already exists in inventory")

    query = """
        INSERT INTO dids (did_number, trunk_id, destination_type, destination, destination_target)
        VALUES (:did_number, CAST(:trunk_id AS uuid), :destination_type, :destination, :destination_target)
        RETURNING id, did_number, trunk_id, destination_type, destination, enabled, created_at::text
    """
    row = await execute_query_one(query, {
        "did_number": num,
        "trunk_id": t_id,
        "destination_type": payload.destination_type or "extension",
        "destination": payload.destination,
        "destination_target": dest
    })
    return dict(row)

@router.post("/{did_id}/assign")
async def assign_did_to_tenant(
    did_id: UUID,
    payload: DidAssign,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    query = """
        UPDATE dids
        SET tenant_id = CAST(:tenant_id AS uuid), updated_at = NOW()
        WHERE id = CAST(:id AS uuid)
        RETURNING id, did_number, tenant_id
    """
    row = await execute_query_one(query, {"id": did_id, "tenant_id": payload.tenant_id})
    if not row:
        raise HTTPException(status_code=404, detail="DID not found")
    return dict(row)

@router.post("/{did_id}/unassign")
async def unassign_did(
    did_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    query = "UPDATE dids SET tenant_id = NULL, updated_at = NOW() WHERE id = CAST(:id AS uuid) RETURNING id, did_number"
    row = await execute_query_one(query, {"id": did_id})
    return dict(row)

@router.delete("/{did_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_did(
    did_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    query = "UPDATE dids SET deleted_at = NOW() WHERE id = CAST(:id AS uuid)"
    await execute_query_one(query, {"id": did_id})
    return None
