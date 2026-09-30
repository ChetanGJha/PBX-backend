import json
import zoneinfo
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/business-hours", tags=["Business Hours & Time Conditions"])


class BusinessHoursCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    timezone: str = Field("UTC", max_length=50)
    schedule: Dict[str, Any]
    open_destination_type: str = Field("extension", max_length=30)
    open_destination_target: str = Field("1001", max_length=100)
    closed_destination_type: str = Field("voicemail", max_length=30)
    closed_destination_target: str = Field("1001", max_length=100)
    holiday_destination_type: Optional[str] = Field("voicemail", max_length=30)
    holiday_destination_target: Optional[str] = Field("1001", max_length=100)
    tenant_id: Optional[UUID] = None


class BusinessHoursUpdate(BaseModel):
    name: Optional[str] = None
    timezone: Optional[str] = None
    schedule: Optional[Dict[str, Any]] = None
    open_destination_type: Optional[str] = None
    open_destination_target: Optional[str] = None
    closed_destination_type: Optional[str] = None
    closed_destination_target: Optional[str] = None
    holiday_destination_type: Optional[str] = None
    holiday_destination_target: Optional[str] = None


class HolidayCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    holiday_date: date


def evaluate_schedule_now(bh_row: Dict[str, Any], holidays: List[Dict[str, Any]]) -> Dict[str, Any]:
    tz_str = bh_row.get("timezone") or "UTC"
    try:
        tz = zoneinfo.ZoneInfo(tz_str)
    except Exception:
        tz = zoneinfo.ZoneInfo("UTC")

    now_tz = datetime.now(tz)
    today_date = now_tz.date()
    curr_time_str = now_tz.strftime("%H:%M")
    day_name = now_tz.strftime("%A").lower()

    # Check holidays
    matching_holiday = next((h for h in holidays if str(h.get("holiday_date")) == str(today_date)), None)
    if matching_holiday:
        return {
            "status": "HOLIDAY",
            "holiday_name": matching_holiday.get("name"),
            "current_time": curr_time_str,
            "current_date": str(today_date),
            "timezone": tz_str,
            "active_destination": {
                "type": bh_row.get("holiday_destination_type") or bh_row.get("closed_destination_type") or "voicemail",
                "target": bh_row.get("holiday_destination_target") or bh_row.get("closed_destination_target") or "1001",
            }
        }

    sched = bh_row.get("schedule") or {}
    if isinstance(sched, str):
        try:
            sched = json.loads(sched)
        except Exception:
            sched = {}
    day_conf = sched.get(day_name) or {}
    is_open = False
    if day_conf.get("enabled"):
        open_time = day_conf.get("open", "00:00")
        close_time = day_conf.get("close", "23:59")
        if open_time <= curr_time_str < close_time:
            is_open = True

    if is_open:
        return {
            "status": "OPEN",
            "current_time": curr_time_str,
            "current_date": str(today_date),
            "timezone": tz_str,
            "active_destination": {
                "type": bh_row.get("open_destination_type") or "extension",
                "target": bh_row.get("open_destination_target") or "1001",
            }
        }
    else:
        return {
            "status": "CLOSED",
            "current_time": curr_time_str,
            "current_date": str(today_date),
            "timezone": tz_str,
            "active_destination": {
                "type": bh_row.get("closed_destination_type") or "voicemail",
                "target": bh_row.get("closed_destination_target") or "1001",
            }
        }


@router.get("")
async def list_business_hours(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id

    if target_tenant:
        where_clause = "WHERE b.tenant_id = CAST(:tenant_id AS uuid)"
        params = {"tenant_id": str(target_tenant)}
    else:
        where_clause = ""
        params = {}

    query = f"""
        SELECT b.id, b.tenant_id, b.name, b.timezone, b.schedule,
               b.open_destination_type, b.open_destination_target,
               b.closed_destination_type, b.closed_destination_target,
               b.holiday_destination_type, b.holiday_destination_target,
               b.created_at::text, b.updated_at::text, t.name as tenant_name,
               (SELECT COUNT(*) FROM holidays h WHERE h.business_hours_id = b.id) as holiday_count
        FROM business_hours b
        LEFT JOIN tenants t ON b.tenant_id = t.id
        {where_clause}
        ORDER BY b.created_at DESC
    """
    rows = await execute_query(query, params)
    
    # Enrich with live status
    enriched = []
    for r in rows:
        holidays = await execute_query(
            "SELECT id, name, holiday_date::text FROM holidays WHERE business_hours_id = CAST(:bh_id AS uuid)",
            {"bh_id": str(r["id"])}
        )
        status_info = evaluate_schedule_now(r, holidays)
        r_copy = dict(r)
        r_copy["live_status"] = status_info
        enriched.append(r_copy)

    return {"items": enriched, "total": len(enriched)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_business_hours(
    data: BusinessHoursCreate,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = data.tenant_id if current_user.is_super_admin and data.tenant_id else current_user.tenant_id
    if not target_tenant and current_user.is_super_admin:
        default_tenant = await execute_query_one("SELECT id FROM tenants WHERE enabled = true ORDER BY created_at ASC LIMIT 1")
        if default_tenant:
            target_tenant = default_tenant["id"]

    if not target_tenant:
        raise HTTPException(status_code=400, detail="Tenant ID is required")

    insert_q = """
        INSERT INTO business_hours (
            tenant_id, name, timezone, schedule,
            open_destination_type, open_destination_target,
            closed_destination_type, closed_destination_target,
            holiday_destination_type, holiday_destination_target
        ) VALUES (
            CAST(:tenant_id AS uuid), :name, :timezone, CAST(:schedule AS jsonb),
            :open_destination_type, :open_destination_target,
            :closed_destination_type, :closed_destination_target,
            :holiday_destination_type, :holiday_destination_target
        ) RETURNING id, tenant_id, name, timezone, schedule,
                    open_destination_type, open_destination_target,
                    closed_destination_type, closed_destination_target,
                    holiday_destination_type, holiday_destination_target,
                    created_at::text, updated_at::text
    """
    res = await execute_query_one(insert_q, {
        "tenant_id": str(target_tenant),
        "name": data.name,
        "timezone": data.timezone,
        "schedule": json.dumps(data.schedule),
        "open_destination_type": data.open_destination_type,
        "open_destination_target": data.open_destination_target,
        "closed_destination_type": data.closed_destination_type,
        "closed_destination_target": data.closed_destination_target,
        "holiday_destination_type": data.holiday_destination_type,
        "holiday_destination_target": data.holiday_destination_target,
    })
    return res


@router.get("/{bh_id}")
async def get_business_hours_details(
    bh_id: UUID,
    current_user: CurrentUser = Depends(get_current_user)
):
    query = """
        SELECT b.id, b.tenant_id, b.name, b.timezone, b.schedule,
               b.open_destination_type, b.open_destination_target,
               b.closed_destination_type, b.closed_destination_target,
               b.holiday_destination_type, b.holiday_destination_target,
               b.created_at::text, b.updated_at::text, t.name as tenant_name
        FROM business_hours b
        LEFT JOIN tenants t ON b.tenant_id = t.id
        WHERE b.id = CAST(:bh_id AS uuid)
    """
    row = await execute_query_one(query, {"bh_id": str(bh_id)})
    if not row:
        raise HTTPException(status_code=404, detail="Business hours schedule not found")

    if not current_user.is_super_admin and row["tenant_id"] != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    holidays = await execute_query(
        "SELECT id, name, holiday_date::text, created_at::text FROM holidays WHERE business_hours_id = CAST(:bh_id AS uuid) ORDER BY holiday_date ASC",
        {"bh_id": str(bh_id)}
    )
    status_info = evaluate_schedule_now(row, holidays)

    result = dict(row)
    result["holidays"] = holidays
    result["live_status"] = status_info
    return result


@router.put("/{bh_id}")
async def update_business_hours(
    bh_id: UUID,
    data: BusinessHoursUpdate,
    current_user: CurrentUser = Depends(get_current_user)
):
    existing = await execute_query_one(
        "SELECT id, tenant_id FROM business_hours WHERE id = CAST(:bh_id AS uuid)",
        {"bh_id": str(bh_id)}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Business hours schedule not found")

    if not current_user.is_super_admin and existing["tenant_id"] != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    updates = []
    params: Dict[str, Any] = {"bh_id": str(bh_id)}

    if data.name is not None:
        updates.append("name = :name")
        params["name"] = data.name
    if data.timezone is not None:
        updates.append("timezone = :timezone")
        params["timezone"] = data.timezone
    if data.schedule is not None:
        updates.append("schedule = CAST(:schedule AS jsonb)")
        params["schedule"] = json.dumps(data.schedule)
    if data.open_destination_type is not None:
        updates.append("open_destination_type = :open_destination_type")
        params["open_destination_type"] = data.open_destination_type
    if data.open_destination_target is not None:
        updates.append("open_destination_target = :open_destination_target")
        params["open_destination_target"] = data.open_destination_target
    if data.closed_destination_type is not None:
        updates.append("closed_destination_type = :closed_destination_type")
        params["closed_destination_type"] = data.closed_destination_type
    if data.closed_destination_target is not None:
        updates.append("closed_destination_target = :closed_destination_target")
        params["closed_destination_target"] = data.closed_destination_target
    if data.holiday_destination_type is not None:
        updates.append("holiday_destination_type = :holiday_destination_type")
        params["holiday_destination_type"] = data.holiday_destination_type
    if data.holiday_destination_target is not None:
        updates.append("holiday_destination_target = :holiday_destination_target")
        params["holiday_destination_target"] = data.holiday_destination_target

    if not updates:
        return existing

    updates.append("updated_at = NOW()")
    sql = f"UPDATE business_hours SET {', '.join(updates)} WHERE id = CAST(:bh_id AS uuid) RETURNING *"
    updated = await execute_query_one(sql, params)
    return updated


@router.delete("/{bh_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_business_hours(
    bh_id: UUID,
    current_user: CurrentUser = Depends(get_current_user)
):
    existing = await execute_query_one(
        "SELECT id, tenant_id FROM business_hours WHERE id = CAST(:bh_id AS uuid)",
        {"bh_id": str(bh_id)}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Business hours schedule not found")

    if not current_user.is_super_admin and existing["tenant_id"] != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    await execute_query_one(
        "DELETE FROM business_hours WHERE id = CAST(:bh_id AS uuid) RETURNING id",
        {"bh_id": str(bh_id)}
    )
    return None


@router.get("/{bh_id}/status")
async def get_live_status(
    bh_id: UUID,
    current_user: CurrentUser = Depends(get_current_user)
):
    row = await execute_query_one(
        "SELECT * FROM business_hours WHERE id = CAST(:bh_id AS uuid)",
        {"bh_id": str(bh_id)}
    )
    if not row:
        raise HTTPException(status_code=404, detail="Schedule not found")

    holidays = await execute_query(
        "SELECT id, name, holiday_date::text FROM holidays WHERE business_hours_id = CAST(:bh_id AS uuid)",
        {"bh_id": str(bh_id)}
    )
    return evaluate_schedule_now(row, holidays)


@router.get("/{bh_id}/holidays")
async def list_holidays(
    bh_id: UUID,
    current_user: CurrentUser = Depends(get_current_user)
):
    holidays = await execute_query(
        "SELECT id, business_hours_id, name, holiday_date::text, created_at::text FROM holidays WHERE business_hours_id = CAST(:bh_id AS uuid) ORDER BY holiday_date ASC",
        {"bh_id": str(bh_id)}
    )
    return holidays


@router.post("/{bh_id}/holidays", status_code=status.HTTP_201_CREATED)
async def add_holiday(
    bh_id: UUID,
    data: HolidayCreate,
    current_user: CurrentUser = Depends(get_current_user)
):
    bh = await execute_query_one(
        "SELECT id, tenant_id FROM business_hours WHERE id = CAST(:bh_id AS uuid)",
        {"bh_id": str(bh_id)}
    )
    if not bh:
        raise HTTPException(status_code=404, detail="Business hours schedule not found")

    if not current_user.is_super_admin and bh["tenant_id"] != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    created = await execute_query_one(
        """
        INSERT INTO holidays (business_hours_id, name, holiday_date)
        VALUES (CAST(:bh_id AS uuid), :name, :holiday_date)
        RETURNING id, business_hours_id, name, holiday_date::text, created_at::text
        """,
        {
            "bh_id": str(bh_id),
            "name": data.name,
            "holiday_date": data.holiday_date
        }
    )
    return created


@router.delete("/{bh_id}/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holiday(
    bh_id: UUID,
    holiday_id: UUID,
    current_user: CurrentUser = Depends(get_current_user)
):
    h = await execute_query_one(
        """
        SELECT h.id, b.tenant_id
        FROM holidays h
        JOIN business_hours b ON h.business_hours_id = b.id
        WHERE h.id = CAST(:holiday_id AS uuid) AND h.business_hours_id = CAST(:bh_id AS uuid)
        """,
        {"holiday_id": str(holiday_id), "bh_id": str(bh_id)}
    )
    if not h:
        raise HTTPException(status_code=404, detail="Holiday entry not found")

    if not current_user.is_super_admin and h["tenant_id"] != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    await execute_query_one(
        "DELETE FROM holidays WHERE id = CAST(:holiday_id AS uuid) RETURNING id",
        {"holiday_id": str(holiday_id)}
    )
    return None
