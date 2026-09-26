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
    tenant_id: Optional[UUID] = None

@router.get("")
async def list_queues(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT q.id, q.name, q.queue_number, q.strategy, q.agent_timeout, q.wrap_up_time,
               q.max_wait_time, q.agents, q.enabled, q.created_at::text, t.name as tenant_name
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
        INSERT INTO queues (name, queue_number, strategy, agent_timeout, wrap_up_time, max_wait_time, agents, tenant_id)
        VALUES (:name, :queue_number, :strategy, :agent_timeout, :wrap_up_time, :max_wait_time, :agents, CAST(:tenant_id AS uuid))
        RETURNING id, name, queue_number, strategy, agent_timeout, wrap_up_time, max_wait_time, agents, enabled, created_at::text
    """
    data = payload.dict()
    data["tenant_id"] = target_tenant
    row = await execute_query_one(query, data)
    return dict(row)

@router.put("/{queue_id}")
async def update_queue(
    queue_id: UUID,
    payload: QueueCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    query = """
        UPDATE queues
        SET name = :name, queue_number = :queue_number, strategy = :strategy,
            agent_timeout = :agent_timeout, wrap_up_time = :wrap_up_time,
            max_wait_time = :max_wait_time, agents = :agents, updated_at = NOW()
        WHERE id = CAST(:id AS uuid)
        RETURNING id, name, queue_number, strategy, agents
    """
    data = payload.dict()
    data["id"] = queue_id
    row = await execute_query_one(query, data)
    if not row:
        raise HTTPException(status_code=404, detail="Queue not found")
    return dict(row)

@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queue(
    queue_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    await execute_query("UPDATE queues SET deleted_at = NOW(), enabled = false WHERE id = CAST(:id AS uuid)", {"id": queue_id})
    return None
