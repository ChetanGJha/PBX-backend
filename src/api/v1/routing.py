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
    route_type: str = "inbound_did"
    destination_type: str = "queue"
    destination: str = Field(..., description="Target destination ID or number")
    priority: int = 1
    regex_pattern: Optional[str] = None
    gateway_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None

@router.get("")
async def list_routes(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT r.id, r.name, r.did_number, r.route_type, r.destination_type,
               r.destination, r.priority, r.regex_pattern, r.enabled, r.created_at::text,
               t.name as tenant_name
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
