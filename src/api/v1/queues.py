from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/queues", tags=["Call Queues"])

class QueueCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    queue_number: str = Field(..., description="Extension number for queue e.g. 7001")
    strategy: str = "round_robin"
    agent_timeout: int = 30
    wrap_up_time: int = 10
    max_wait_time: int = 300
    agents: Optional[str] = None
    announce_position: bool = True
    announce_wait_time: bool = True
    tenant_id: Optional[UUID] = None

@router.get("")
async def list_queues(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT q.id, q.name, q.queue_number, q.strategy, q.agent_timeout, q.wrap_up_time,
               q.max_wait_time, q.agents, q.announce_position, q.announce_wait_time, q.enabled,
               q.created_at::text, t.name as tenant_name
        FROM queues q
        LEFT JOIN tenants t ON q.tenant_id = t.id
        WHERE q.deleted_at IS NULL
    """
    params = {}
    if target_tenant:
        query += " AND q.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = target_tenant

    query += " ORDER BY q.queue_number ASC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_queue(
    payload: QueueCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    target_tenant = payload.tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        INSERT INTO queues (name, queue_number, strategy, agent_timeout, wrap_up_time, max_wait_time, agents, announce_position, announce_wait_time, tenant_id)
        VALUES (:name, :queue_number, :strategy, :agent_timeout, :wrap_up_time, :max_wait_time, :agents, :announce_position, :announce_wait_time, :tenant_id)
        RETURNING id, name, queue_number, strategy, agent_timeout, wrap_up_time, max_wait_time, agents, enabled, created_at::text
    """
    data = payload.dict()
    data["tenant_id"] = target_tenant
    row = await execute_query_one(query, data)
    return dict(row)
