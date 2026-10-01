import os
import logging
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse
from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

logger = logging.getLogger("pbx.api.reports")

router = APIRouter(prefix="/reports", tags=["Reports & Analytics"])


@router.get("/cdr")
async def get_cdr_report(
    tenant_id: Optional[UUID] = None,
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    call_type: Optional[str] = "all",  # all, internal, inbound, outbound
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Fetch historical Call Detail Records (CDR) with optional date, tenant, and direction filters.
    """
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id

    query = """
        SELECT c.id, c.call_uuid,
               COALESCE(c.caller_number, c.source_extension, 'Unknown') as caller_id_number,
               COALESCE(c.caller_name, 'N/A') as caller_id_name,
               COALESCE(c.destination, c.destination_extension, 'Unknown') as destination_number,
               COALESCE(c.source_extension, c.caller_number, 'Unknown') as source_extension,
               COALESCE(c.destination_extension, c.destination, 'Unknown') as destination_extension,
               c.start_time::text as start_stamp, 
               c.start_time::text as start_time,
               c.created_at::text as created_at,
               c.answer_time::text as answer_stamp, 
               c.end_time::text as end_stamp,
               COALESCE(c.duration, 0) as duration, 
               COALESCE(c.billsec, 0) as billsec, 
               COALESCE(c.hangup_cause, 'NORMAL_CLEARING') as hangup_cause, 
               COALESCE(c.direction, 'internal') as direction, 
               c.recording_id,
               r.file_path as recording_file_path, 
               r.file_size as recording_file_size,
               COALESCE(t.name, 'Global') as tenant_name, 
               t.domain as tenant_domain
        FROM cdr c
        LEFT JOIN tenants t ON c.tenant_id = t.id
        LEFT JOIN recordings r ON c.recording_id = r.id
        WHERE 1=1
    """
    params = {}

    if target_tenant:
        query += " AND c.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = str(target_tenant)

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


@router.get("/recordings")
async def list_call_recordings(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    List recorded call sessions.
    """
    target_tenant = tenant_id if current_user.is_super_admin and tenant_id else current_user.tenant_id

    query = """
        SELECT r.id, r.call_uuid, 
               COALESCE(r.source_extension, r.caller_number, 'Unknown') as source_extension,
               COALESCE(r.caller_number, r.source_extension, 'Unknown') as caller_number,
               COALESCE(r.destination_number, 'Unknown') as destination_number,
               COALESCE(r.direction, 'call') as direction,
               r.start_time::text as start_time,
               COALESCE(r.created_at, r.start_time)::text as created_at,
               COALESCE(r.duration, 0) as duration, 
               r.file_path,
               COALESCE(substring(r.file_path from '[^/\\\\]+$'), 'recording.wav') as file_name,
               COALESCE(r.file_size, 0) as file_size,
               COALESCE(t.name, 'Global') as tenant_name
        FROM recordings r
        LEFT JOIN tenants t ON r.tenant_id = t.id
        WHERE 1=1
    """
    params = {}
    if target_tenant:
        query += " AND r.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = str(target_tenant)

    query += " ORDER BY r.start_time DESC LIMIT 500"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.get("/recordings/{recording_id}/stream")
async def stream_call_recording(
    recording_id: UUID,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Stream call recording audio file.
    """
    row = await execute_query_one(
        "SELECT file_path, tenant_id FROM recordings WHERE id = CAST(:id AS uuid)",
        {"id": str(recording_id)}
    )
    if not row:
        raise HTTPException(status_code=404, detail="Recording not found")

    if not current_user.is_super_admin and row.get("tenant_id") and str(row["tenant_id"]) != str(current_user.tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    file_path = row.get("file_path")
    resolved_path = None
    if file_path and os.path.exists(file_path):
        resolved_path = file_path
    else:
        # Fallback candidates inside docker volume
        base_name = os.path.basename(file_path) if file_path else f"{recording_id}.wav"
        candidates = [
            f"/var/lib/freeswitch/recordings/{row['tenant_id']}/{base_name}",
            f"/var/lib/freeswitch/recordings/{base_name}",
            f"/var/lib/freeswitch/recordings/archive/{base_name}",
        ]
        for cand in candidates:
            if os.path.exists(cand):
                resolved_path = cand
                break

    if not resolved_path:
        raise HTTPException(status_code=404, detail="Recording audio file not found on disk")

    return FileResponse(
        resolved_path,
        media_type="audio/wav",
        filename=os.path.basename(resolved_path),
        headers={"Accept-Ranges": "bytes"}
    )


@router.get("/outbound")
async def get_outbound_report(
    tenant_id: Optional[UUID] = None,
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Outbound calls analytics.
    """
    target_tenant = tenant_id if current_user.is_super_admin and tenant_id else current_user.tenant_id
    query = """
        SELECT c.id, c.call_uuid,
               COALESCE(c.source_extension, c.caller_number, 'Unknown') as caller_id_number,
               COALESCE(c.source_extension, c.caller_number, 'Unknown') as source_extension,
               COALESCE(c.destination, c.destination_extension, 'Unknown') as destination_number,
               COALESCE(c.destination, c.destination_extension, 'Unknown') as destination,
               c.start_time::text as start_stamp,
               c.start_time::text as start_time,
               COALESCE(c.created_at, c.start_time)::text as created_at,
               COALESCE(c.duration, 0) as duration,
               COALESCE(c.billsec, 0) as billsec,
               COALESCE(c.hangup_cause, 'NORMAL_CLEARING') as hangup_cause,
               COALESCE(t.name, 'Global') as tenant_name
        FROM cdr c
        LEFT JOIN tenants t ON c.tenant_id = t.id
        WHERE (c.direction = 'outbound' OR c.direction = 'Outbound' OR LENGTH(c.destination) > 6)
    """
    params = {}
    if target_tenant:
        query += " AND c.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = str(target_tenant)
    if start_date:
        query += " AND c.start_time >= CAST(:start_date AS timestamptz)"
        params["start_date"] = f"{start_date} 00:00:00"
    if end_date:
        query += " AND c.start_time <= CAST(:end_date AS timestamptz)"
        params["end_date"] = f"{end_date} 23:59:59"

    query += " ORDER BY c.start_time DESC LIMIT 500"
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.get("/internal")
async def get_internal_summary(
    tenant_id: Optional[UUID] = None,
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Extension-to-extension internal calls summary.
    Excludes non-extension numbers, feature codes (*xx), and automated prefixes.
    """
    target_tenant = tenant_id if current_user.is_super_admin and tenant_id else current_user.tenant_id
    query = """
        SELECT 
            COALESCE(c.source_extension, c.caller_number, 'Unknown') as caller_id_number,
            COALESCE(c.destination_extension, c.destination, 'Unknown') as destination_number,
            COUNT(*) as total_calls,
            COALESCE(SUM(c.duration), 0) as total_duration_sec,
            ROUND(COALESCE(AVG(c.duration), 0)) as avg_duration_sec
        FROM cdr c
        WHERE c.direction = 'internal'
          AND c.destination NOT LIKE '*%'
          AND c.destination NOT LIKE 'fwd_%'
          AND c.destination NOT LIKE 'voicemail_%'
          AND LENGTH(COALESCE(c.destination_extension, c.destination, '')) <= 6
          AND LENGTH(COALESCE(c.source_extension, c.caller_number, '')) <= 6
          AND COALESCE(c.source_extension, c.caller_number, '') ~ '^[0-9]+$'
          AND COALESCE(c.destination_extension, c.destination, '') ~ '^[0-9]+$'
          AND COALESCE(c.source_extension, c.caller_number, '') != COALESCE(c.destination_extension, c.destination, '')
    """
    params = {}
    if target_tenant:
        query += " AND c.tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = str(target_tenant)
    if start_date:
        query += " AND c.start_time >= CAST(:start_date AS timestamptz)"
        params["start_date"] = f"{start_date} 00:00:00"
    if end_date:
        query += " AND c.start_time <= CAST(:end_date AS timestamptz)"
        params["end_date"] = f"{end_date} 23:59:59"

    query += """
        GROUP BY COALESCE(c.source_extension, c.caller_number, 'Unknown'),
                 COALESCE(c.destination_extension, c.destination, 'Unknown')
        ORDER BY total_calls DESC
        LIMIT 500
    """
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.get("/summary")
async def get_call_analytics_summary(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Summary stats: total calls, total minutes, answered calls, failed calls.
    """
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id

    query = """
        SELECT 
            COUNT(*) as total_calls,
            COALESCE(SUM(billsec), 0) / 60 as total_minutes,
            COUNT(*) FILTER (WHERE billsec > 0) as answered_calls,
            COUNT(*) FILTER (WHERE billsec = 0) as missed_or_failed_calls
        FROM cdr
        WHERE 1=1
    """
    params = {}
    if target_tenant:
        query += " AND tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = str(target_tenant)

    row = await execute_query_one(query, params)
    return dict(row) if row else {
        "total_calls": 0,
        "total_minutes": 0,
        "answered_calls": 0,
        "missed_or_failed_calls": 0
    }


@router.get("/voicemail")
async def get_voicemail_report(
    tenant_id: Optional[UUID] = None,
    extension_number: Optional[str] = Query(None, description="Filter by extension number"),
    is_read: Optional[bool] = Query(None, description="Filter by read status"),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Fetch extension-wise voicemail analytics summary and itemized voicemail messages.
    """
    target_tenant = tenant_id if current_user.is_super_admin and tenant_id else current_user.tenant_id

    # 1. Extension-wise summary
    summary_query = """
        SELECT 
            e.extension_number,
            e.display_name,
            e.email,
            COUNT(vm.id) as total_messages,
            COUNT(vm.id) FILTER (WHERE vm.read = false) as unread_messages,
            COALESCE(SUM(vm.duration), 0) as total_duration_seconds,
            MAX(vm.created_at::text) as latest_message_at
        FROM extensions e
        LEFT JOIN voicemail_boxes vb ON e.id = vb.extension_id AND vb.tenant_id = e.tenant_id
        LEFT JOIN voicemail_messages vm ON vb.id = vm.voicemail_box_id
        WHERE e.deleted_at IS NULL
    """
    summary_params = {}
    if target_tenant:
        summary_query += " AND e.tenant_id = CAST(:t_id AS uuid)"
        summary_params["t_id"] = str(target_tenant)
    if extension_number:
        summary_query += " AND e.extension_number = :ext_num"
        summary_params["ext_num"] = extension_number

    summary_query += " GROUP BY e.extension_number, e.display_name, e.email ORDER BY e.extension_number ASC"
    summary_rows = await execute_query(summary_query, summary_params)

    # 2. Itemized messages list
    msg_query = """
        SELECT 
            vm.id,
            e.extension_number,
            e.display_name,
            vb.mailbox,
            vm.caller_id_number,
            vm.caller_id_name,
            vm.file_path,
            vm.duration,
            vm.read,
            vm.created_at::text as created_at
        FROM voicemail_messages vm
        JOIN voicemail_boxes vb ON vm.voicemail_box_id = vb.id
        JOIN extensions e ON vb.extension_id = e.id
        WHERE e.deleted_at IS NULL
    """
    msg_params = {}
    if target_tenant:
        msg_query += " AND vb.tenant_id = CAST(:t_id AS uuid)"
        msg_params["t_id"] = str(target_tenant)
    if extension_number:
        msg_query += " AND e.extension_number = :ext_num"
        msg_params["ext_num"] = extension_number
    if is_read is not None:
        msg_query += " AND vm.read = :is_read"
        msg_params["is_read"] = is_read
    if start_date:
        msg_query += " AND vm.created_at >= CAST(:start_date AS timestamptz)"
        msg_params["start_date"] = f"{start_date} 00:00:00"
    if end_date:
        msg_query += " AND vm.created_at <= CAST(:end_date AS timestamptz)"
        msg_params["end_date"] = f"{end_date} 23:59:59"

    msg_query += " ORDER BY vm.created_at DESC LIMIT 500"
    msg_rows = await execute_query(msg_query, msg_params)

    total_messages = sum(r["total_messages"] for r in summary_rows) if summary_rows else 0
    unread_messages = sum(r["unread_messages"] for r in summary_rows) if summary_rows else 0
    total_duration = sum(r["total_duration_seconds"] for r in summary_rows) if summary_rows else 0

    return {
        "summary": [dict(r) for r in summary_rows],
        "messages": [dict(r) for r in msg_rows],
        "total_messages": total_messages,
        "unread_messages": unread_messages,
        "total_duration_seconds": total_duration
    }


@router.patch("/voicemail/{message_id}/read")
async def toggle_voicemail_read(
    message_id: UUID,
    read: bool = Query(True),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Mark a voicemail message as read or unread.
    """
    await execute_query(
        "UPDATE voicemail_messages SET read = :read WHERE id = CAST(:id AS uuid)",
        {"id": str(message_id), "read": read}
    )
    return {"status": "success", "message_id": str(message_id), "read": read}


@router.delete("/voicemail/{message_id}")
async def delete_voicemail(
    message_id: UUID,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Delete a voicemail message and clean up audio file.
    """
    row = await execute_query_one(
        "SELECT file_path FROM voicemail_messages WHERE id = CAST(:id AS uuid)",
        {"id": str(message_id)}
    )
    if not row:
        raise HTTPException(status_code=404, detail="Voicemail message not found")

    file_path = row.get("file_path")
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning(f"Could not delete voicemail file {file_path}: {e}")

    await execute_query(
        "DELETE FROM voicemail_messages WHERE id = CAST(:id AS uuid)",
        {"id": str(message_id)}
    )
    return {"status": "success", "message_id": str(message_id)}


@router.get("/voicemail/{message_id}/audio")
async def stream_voicemail_audio(
    message_id: UUID,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Stream audio file for a voicemail message.
    """
    row = await execute_query_one(
        "SELECT file_path FROM voicemail_messages WHERE id = CAST(:id AS uuid)",
        {"id": str(message_id)}
    )
    if not row:
        raise HTTPException(status_code=404, detail="Voicemail message not found")

    file_path = row.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Voicemail audio file not found on disk")

    return FileResponse(
        file_path,
        media_type="audio/wav",
        filename=os.path.basename(file_path),
        headers={"Accept-Ranges": "bytes"}
    )
