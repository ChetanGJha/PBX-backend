from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/reports", tags=["Reports & Analytics"])

@router.get("/cdr")
async def get_cdr_report(
    tenant_id: Optional[UUID] = None,
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    call_type: Optional[str] = "all", # all, internal, inbound, outbound
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id

    query = """
        SELECT c.id, c.caller_number, c.caller_name, c.destination as destination_number,
               c.start_time::text as start_stamp, c.answer_time::text as answer_stamp, c.end_time::text as end_stamp,
               c.duration, c.billsec, c.hangup_cause, c.direction,
               t.name as tenant_name, t.domain as tenant_domain
        FROM cdr c
        LEFT JOIN tenants t ON c.tenant_id = t.id
        WHERE 1=1
    """
    params = {}

    if target_tenant:
        query += " AND c.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = target_tenant

    if start_date:
        query += " AND c.start_time >= CAST(:start_date AS timestamptz)"
        params["start_date"] = f"{start_date} 00:00:00"

    if end_date:
        query += " AND c.start_time <= CAST(:end_date AS timestamptz)"
        params["end_date"] = f"{end_date} 23:59:59"

    if call_type and call_type != "all":
        query += " AND c.direction = :call_type"
        params["call_type"] = call_type

    query += " ORDER BY c.start_time DESC LIMIT 500"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]

@router.get("/internal")
async def get_internal_call_report(
    tenant_id: Optional[UUID] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT c.caller_number, c.destination as destination_number,
               COUNT(*) as total_calls,
               SUM(c.duration) as total_duration_sec,
               AVG(c.duration)::int as avg_duration_sec
        FROM cdr c
        WHERE c.direction = 'internal'
    """
    params = {}
    if target_tenant:
        query += " AND c.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = target_tenant

    if start_date:
        query += " AND c.start_time >= CAST(:start_date AS timestamptz)"
        params["start_date"] = f"{start_date} 00:00:00"

    if end_date:
        query += " AND c.start_time <= CAST(:end_date AS timestamptz)"
        params["end_date"] = f"{end_date} 23:59:59"

    query += " GROUP BY c.caller_number, c.destination ORDER BY total_calls DESC"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]

@router.get("/outbound")
async def get_outbound_call_report(
    tenant_id: Optional[UUID] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT c.caller_number, c.destination as destination_number, c.billsec,
               c.hangup_cause, c.start_time::text as start_stamp, t.name as tenant_name
        FROM cdr c
        LEFT JOIN tenants t ON c.tenant_id = t.id
        WHERE c.direction = 'outbound'
    """
    params = {}
    if target_tenant:
        query += " AND c.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = target_tenant

    if start_date:
        query += " AND c.start_time >= CAST(:start_date AS timestamptz)"
        params["start_date"] = f"{start_date} 00:00:00"

    if end_date:
        query += " AND c.start_time <= CAST(:end_date AS timestamptz)"
        params["end_date"] = f"{end_date} 23:59:59"

    query += " ORDER BY c.start_time DESC LIMIT 300"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]

@router.get("/recordings")
async def get_recordings_report(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT r.id, r.call_uuid as call_id, r.file_path as file_name, r.file_path, r.file_size,
               r.duration, r.created_at::text, t.name as tenant_name
        FROM recordings r
        LEFT JOIN tenants t ON r.tenant_id = t.id
        WHERE 1=1
    """
    params = {}
    if target_tenant:
        query += " AND r.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = target_tenant

    query += " ORDER BY r.created_at DESC LIMIT 100"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]
