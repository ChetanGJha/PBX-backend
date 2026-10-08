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
    strategy: str = "round_robin"  # round_robin, longest_idle, ring_all, top_down
    agent_timeout: int = 30
    wrap_up_time: int = 10
    max_wait_time: int = 300
    agents: Optional[str] = None  # Comma separated extension numbers
    announce_position: bool = True
    announce_wait_time: bool = True
    tenant_id: Optional[UUID] = None


class QueueUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    queue_number: Optional[str] = None
    strategy: Optional[str] = None
    agent_timeout: Optional[int] = None
    wrap_up_time: Optional[int] = None
    max_wait_time: Optional[int] = None
    agents: Optional[str] = None
    announce_position: Optional[bool] = None
    announce_wait_time: Optional[bool] = None
    tenant_id: Optional[UUID] = None
    enabled: Optional[bool] = None


@router.get("")
async def list_queues(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    List FreeSWITCH mod_callcenter call queues.
    """
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id

    query = """
        SELECT q.id, q.name, q.queue_number, q.strategy, q.agent_timeout, q.wrap_up_time,
               q.max_wait_time, q.agents, q.announce_position, q.announce_wait_time, q.enabled,
               q.created_at::text, q.tenant_id::text as tenant_id, t.name as tenant_name
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
    """
    Create a call queue.
    """
    target_tenant = payload.tenant_id if current_user.is_super_admin else current_user.tenant_id

    query = """
        INSERT INTO queues (name, queue_number, strategy, agent_timeout, wrap_up_time, max_wait_time, agents, announce_position, announce_wait_time, tenant_id)
        VALUES (:name, :queue_number, :strategy, :agent_timeout, :wrap_up_time, :max_wait_time, :agents, :announce_position, :announce_wait_time, :tenant_id)
        RETURNING id, name, queue_number, strategy, agent_timeout, wrap_up_time, max_wait_time, agents, enabled, created_at::text, tenant_id::text as tenant_id
    """
    data = payload.dict()
    data["tenant_id"] = target_tenant
    row = await execute_query_one(query, data)
    return dict(row)


@router.put("/{queue_id}")
async def update_queue(
    queue_id: UUID,
    payload: QueueUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Update an existing call queue and assigned agents.
    """
    check_query = "SELECT id, tenant_id FROM queues WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
    existing = await execute_query_one(check_query, {"id": str(queue_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Queue not found")

    if not current_user.is_super_admin and str(existing["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    data = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clauses = []
    params = {"id": str(queue_id)}
    for k, v in data.items():
        set_clauses.append(f"{k} = :{k}")
        params[k] = str(v) if isinstance(v, UUID) else v

    query = f"""
        UPDATE queues
        SET {", ".join(set_clauses)}
        WHERE id = CAST(:id AS uuid)
        RETURNING id, name, queue_number, strategy, agent_timeout, wrap_up_time, max_wait_time, agents, enabled, created_at::text, tenant_id::text as tenant_id
    """
    row = await execute_query_one(query, params)
    return dict(row)


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queue(
    queue_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Soft-delete a call queue.
    """
    check_query = "SELECT id, tenant_id FROM queues WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL"
    existing = await execute_query_one(check_query, {"id": str(queue_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Queue not found")

    if not current_user.is_super_admin and str(existing["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Access denied")

    await execute_query_one(
        "UPDATE queues SET deleted_at = NOW() WHERE id = CAST(:id AS uuid) RETURNING id",
        {"id": str(queue_id)}
    )
    return None
