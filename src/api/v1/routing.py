from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/routing", tags=["Call Routing"])


class RouteCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    did_number: Optional[str] = Field(None, description="DID Number for Inbound routes")
    route_type: str = "inbound_did"  # inbound_did, outbound
    destination_type: str = "queue"  # queue, extension, ivr, voicemail, external
    destination: str = Field(..., description="Target destination ID or number")
    priority: int = 1
    regex_pattern: Optional[str] = None
    gateway_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None


class RouteUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    did_number: Optional[str] = None
    route_type: Optional[str] = None
    destination_type: Optional[str] = None
    destination: Optional[str] = None
    priority: Optional[int] = None
    regex_pattern: Optional[str] = None
    gateway_id: Optional[UUID] = None
    enabled: Optional[bool] = None


@router.get("")
async def list_routes(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    List inbound DIDs and outbound dial-plan routes.
    """
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id

    query = """
        SELECT r.id, r.name, r.did_number, r.route_type, r.destination_type,
               r.destination, r.priority, r.regex_pattern, r.enabled, r.created_at::text,
               r.gateway_id, t.name as tenant_name
        FROM call_routes r
        LEFT JOIN tenants t ON r.tenant_id = t.id
        WHERE r.deleted_at IS NULL
    """
    params = {}
    if target_tenant:
        query += " AND r.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = target_tenant

    query += " ORDER BY r.priority ASC, r.name ASC"

    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_route(
    payload: RouteCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Create an inbound DID route or outbound dial-plan route.
    """
    target_tenant = payload.tenant_id if current_user.is_super_admin else current_user.tenant_id

    query = """
        INSERT INTO call_routes (name, did_number, route_type, destination_type, destination, priority, regex_pattern, gateway_id, tenant_id)
        VALUES (:name, :did_number, :route_type, :destination_type, :destination, :priority, :regex_pattern, :gateway_id, :tenant_id)
        RETURNING id, name, did_number, route_type, destination_type, destination, priority, regex_pattern, enabled, created_at::text
    """
    data = payload.dict()
    data["tenant_id"] = target_tenant
    row = await execute_query_one(query, data)
    return dict(row)


@router.put("/{route_id}")
async def update_route(
    route_id: UUID,
    payload: RouteUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Update an existing call routing rule.
    """
    check_query = "SELECT id, tenant_id FROM call_routes WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
    existing = await execute_query_one(check_query, {"id": str(route_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Route not found")

    if not current_user.is_super_admin and str(existing["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    data = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clauses = []
    params = {"id": str(route_id)}
    for k, v in data.items():
        set_clauses.append(f"{k} = :{k}")
        params[k] = str(v) if isinstance(v, UUID) else v

    query = f"""
        UPDATE call_routes
        SET {", ".join(set_clauses)}
        WHERE id = CAST(:id AS uuid)
        RETURNING id, name, did_number, route_type, destination_type, destination, priority, regex_pattern, enabled, created_at::text
    """
    row = await execute_query_one(query, params)
    return dict(row)


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(
    route_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Soft-delete a routing rule.
    """
    check_query = "SELECT id, tenant_id FROM call_routes WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
    existing = await execute_query_one(check_query, {"id": str(route_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Route not found")

    if not current_user.is_super_admin and str(existing["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    await execute_query_one(
        "UPDATE call_routes SET deleted_at = NOW() WHERE id = CAST(:id AS uuid) RETURNING id",
        {"id": str(route_id)}
    )
    return None

