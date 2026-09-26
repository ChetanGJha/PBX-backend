from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/gateways", tags=["Sofia Gateways"])

class GatewayCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    proxy: str = Field(..., description="Proxy IP/Domain")
    username: Optional[str] = None
    password: Optional[str] = None
    realm: Optional[str] = None
    from_domain: Optional[str] = None
    codecs: str = "PCMU,PCMA,G722"
    tenant_id: Optional[UUID] = None
    register: bool = True
    caller_id_in_from: bool = False

class GatewayAssignmentCreate(BaseModel):
    tenant_id: UUID
    gateway_id: UUID
    direction: str = "inbound_outbound"
    priority: int = 1
    caller_id_policy: str = "tenant_default"
    allow_outbound: bool = True
    accept_inbound: bool = True
    allow_international: bool = False

@router.get("")
async def list_gateways(current_user: CurrentUser = Depends(get_current_user)):
    query = """
        SELECT g.id, g.name, g.proxy, g.username, g.realm, g.from_domain, g.codecs,
               g.register, g.enabled, g.created_at::text, t.name as tenant_name
        FROM gateways g
        LEFT JOIN tenants t ON g.tenant_id = t.id
        WHERE g.deleted_at IS NULL
        ORDER BY g.name ASC
    """
    rows = await execute_query(query)
    return [dict(r) for r in rows]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_gateway(
    payload: GatewayCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    query = """
        INSERT INTO gateways (name, proxy, username, password, realm, from_domain, codecs, tenant_id, register)
        VALUES (:name, :proxy, :username, :password, :realm, :from_domain, :codecs, :tenant_id, :register)
        RETURNING id, name, proxy, username, realm, from_domain, codecs, register, enabled, created_at::text
    """
    row = await execute_query_one(query, payload.dict())
    return dict(row)

@router.post("/assign", status_code=status.HTTP_201_CREATED)
async def assign_gateway_to_tenant(
    payload: GatewayAssignmentCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    query = """
        INSERT INTO tenant_gateways (tenant_id, gateway_id, direction, priority, caller_id_policy, allow_outbound, accept_inbound, allow_international)
        VALUES (:tenant_id, :gateway_id, :direction, :priority, :caller_id_policy, :allow_outbound, :accept_inbound, :allow_international)
        ON CONFLICT (tenant_id, gateway_id) DO UPDATE SET
            direction = EXCLUDED.direction,
            priority = EXCLUDED.priority,
            caller_id_policy = EXCLUDED.caller_id_policy,
            allow_outbound = EXCLUDED.allow_outbound,
            accept_inbound = EXCLUDED.accept_inbound,
            allow_international = EXCLUDED.allow_international
        RETURNING tenant_id, gateway_id, direction, priority, caller_id_policy
    """
    row = await execute_query_one(query, payload.dict())
    return dict(row)
