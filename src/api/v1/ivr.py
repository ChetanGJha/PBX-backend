"""
IVR Menu Management API
Handles CRUD for IVR menus (auto-attendants) and their DTMF key node configurations.
"""
import uuid
import logging
from typing import Optional
from sqlalchemy.sql import text
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one, execute_transaction
from src.core.permissions import get_current_user, CurrentUser

logger = logging.getLogger("pbx.ivr")

router = APIRouter(prefix="/ivr", tags=["IVR Menus"])


# ─── Pydantic Schemas ────────────────────────────────────────────────────────

class IvrCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    greeting_audio: Optional[str] = "welcome_prompt.wav"
    direct_extension_dial: Optional[bool] = True
    timeout: Optional[int] = 10
    tenant_id: Optional[str] = None


class IvrUpdate(BaseModel):
    name: Optional[str] = None
    greeting_audio: Optional[str] = None
    direct_extension_dial: Optional[bool] = None
    timeout: Optional[int] = None
    tenant_id: Optional[str] = None
    enabled: Optional[bool] = None


class IvrNodeUpsert(BaseModel):
    dtmf_key: str = Field(..., description="DTMF key: 0-9, *, #")
    action_type: str = Field(..., description="extension | queue | play_audio | voicemail | hangup")
    action_target: str = Field(default="", description="Target value for the action")


# ─── IVR Menu Endpoints ───────────────────────────────────────────────────────

@router.get("", summary="List all IVR menus")
async def list_ivrs(
    tenant_id: Optional[str] = Query(None, description="Filter by tenant ID"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """Return all IVR menus. Super Admin sees all; tenant users see only their tenant's menus."""
    conditions = ["im.deleted_at IS NULL"]
    params: dict = {}

    if current_user.is_super_admin:
        if tenant_id:
            conditions.append("im.tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
    else:
        conditions.append("im.tenant_id = :tenant_id")
        params["tenant_id"] = current_user.tenant_id

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT im.id, im.tenant_id, im.name, im.greeting_audio,
               im.direct_extension_dial, im.timeout, im.enabled,
               im.created_at, im.updated_at,
               t.name as tenant_name
        FROM ivr_menus im
        LEFT JOIN tenants t ON im.tenant_id = t.id
        WHERE {where_clause}
        ORDER BY im.created_at DESC
    """
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.get("/{ivr_id}", summary="Get IVR menu details")
async def get_ivr(
    ivr_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """Fetch a single IVR menu by ID."""
    row = await execute_query_one(
        """
        SELECT im.*, t.name as tenant_name
        FROM ivr_menus im
        LEFT JOIN tenants t ON im.tenant_id = t.id
        WHERE im.id = :id AND im.deleted_at IS NULL
        """,
        {"id": ivr_id}
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IVR menu not found")

    if not current_user.is_super_admin:
        if str(row.get("tenant_id", "")) != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return dict(row)


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create IVR menu")
async def create_ivr(
    payload: IvrCreate,
    current_user: CurrentUser = Depends(get_current_user)
):
    """Create a new IVR auto-attendant menu."""
    effective_tenant_id = payload.tenant_id
    if not current_user.is_super_admin:
        effective_tenant_id = current_user.tenant_id

    if effective_tenant_id:
        tenant = await execute_query_one(
            "SELECT id FROM tenants WHERE id = :id AND deleted_at IS NULL",
            {"id": effective_tenant_id}
        )
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Specified tenant does not exist"
            )

    ivr_id = str(uuid.uuid4())
    insert_params = {
        "id": ivr_id,
        "tenant_id": effective_tenant_id,
        "name": payload.name,
        "greeting_audio": payload.greeting_audio or "welcome_prompt.wav",
        "direct_ext": payload.direct_extension_dial if payload.direct_extension_dial is not None else True,
        "timeout": payload.timeout or 10,
    }

    async def _create(session):
        await session.execute(
            text("""
                INSERT INTO ivr_menus (id, tenant_id, name, greeting_audio, direct_extension_dial, timeout, enabled)
                VALUES (:id, :tenant_id, :name, :greeting_audio, :direct_ext, :timeout, true)
            """),
            insert_params
        )

    try:
        await execute_transaction(_create)
    except Exception as e:
        logger.error(f"Failed to create IVR menu: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create IVR menu: {str(e)}"
        )

    created = await execute_query_one("SELECT * FROM ivr_menus WHERE id = :id", {"id": ivr_id})
    logger.info(f"IVR menu '{payload.name}' created by {current_user.username}")
    return dict(created)


@router.put("/{ivr_id}", summary="Update IVR menu")
async def update_ivr(
    ivr_id: str,
    payload: IvrUpdate,
    current_user: CurrentUser = Depends(get_current_user)
):
    """Update an existing IVR menu's settings."""
    existing = await execute_query_one(
        "SELECT * FROM ivr_menus WHERE id = :id AND deleted_at IS NULL", {"id": ivr_id}
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IVR menu not found")

    if not current_user.is_super_admin:
        if str(existing.get("tenant_id", "")) != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    fields = []
    params: dict = {"id": ivr_id}

    if payload.name is not None:
        fields.append("name = :name")
        params["name"] = payload.name
    if payload.greeting_audio is not None:
        fields.append("greeting_audio = :greeting_audio")
        params["greeting_audio"] = payload.greeting_audio
    if payload.direct_extension_dial is not None:
        fields.append("direct_extension_dial = :direct_extension_dial")
        params["direct_extension_dial"] = payload.direct_extension_dial
    if payload.timeout is not None:
        fields.append("timeout = :timeout")
        params["timeout"] = payload.timeout
    if payload.enabled is not None:
        fields.append("enabled = :enabled")
        params["enabled"] = payload.enabled
    if "tenant_id" in payload.model_fields_set:
        fields.append("tenant_id = :tenant_id")
        params["tenant_id"] = payload.tenant_id if payload.tenant_id else None

    if not fields:
        return dict(existing)

    fields.append("updated_at = now()")
    set_clause = ", ".join(fields)
    update_params = params

    async def _update(session):
        await session.execute(
            text(f"UPDATE ivr_menus SET {set_clause} WHERE id = :id"),
            update_params
        )

    await execute_transaction(_update)

    updated = await execute_query_one("SELECT * FROM ivr_menus WHERE id = :id", {"id": ivr_id})
    logger.info(f"IVR menu {ivr_id} updated by {current_user.username}")
    return dict(updated)


@router.delete("/{ivr_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete IVR menu")
async def delete_ivr(
    ivr_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """Soft-delete an IVR menu."""
    existing = await execute_query_one(
        "SELECT * FROM ivr_menus WHERE id = :id AND deleted_at IS NULL", {"id": ivr_id}
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IVR menu not found")

    if not current_user.is_super_admin:
        if str(existing.get("tenant_id", "")) != current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    async def _soft_delete(session):
        await session.execute(
            text("UPDATE ivr_menus SET deleted_at = now() WHERE id = :id"),
            {"id": ivr_id}
        )

    await execute_transaction(_soft_delete)
    logger.info(f"IVR menu {ivr_id} deleted by {current_user.username}")


# ─── IVR Node (DTMF Key) Endpoints ────────────────────────────────────────────

@router.get("/{ivr_id}/nodes", summary="List DTMF key actions for an IVR menu")
async def list_ivr_nodes(
    ivr_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """Return all DTMF key action nodes for the specified IVR menu."""
    menu = await execute_query_one(
        "SELECT id, tenant_id FROM ivr_menus WHERE id = :id AND deleted_at IS NULL",
        {"id": ivr_id}
    )
    if not menu:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IVR menu not found")

    rows = await execute_query(
        """
        SELECT id, ivr_menu_id, dtmf_key, action_type, action_target, created_at
        FROM ivr_nodes
        WHERE ivr_menu_id = :ivr_id
        ORDER BY dtmf_key
        """,
        {"ivr_id": ivr_id}
    )
    return [dict(r) for r in rows]


@router.post("/{ivr_id}/nodes", summary="Upsert a DTMF key action node")
async def upsert_ivr_node(
    ivr_id: str,
    payload: IvrNodeUpsert,
    current_user: CurrentUser = Depends(get_current_user)
):
    """Create or update the action for a specific DTMF key in an IVR menu."""
    menu = await execute_query_one(
        "SELECT id, tenant_id FROM ivr_menus WHERE id = :id AND deleted_at IS NULL",
        {"id": ivr_id}
    )
    if not menu:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IVR menu not found")

    node_id = str(uuid.uuid4())
    upsert_params = {
        "id": node_id,
        "ivr_menu_id": ivr_id,
        "dtmf_key": payload.dtmf_key,
        "action_type": payload.action_type,
        "action_target": payload.action_target,
    }

    async def _upsert(session):
        await session.execute(
            text("""
                INSERT INTO ivr_nodes (id, ivr_menu_id, dtmf_key, action_type, action_target)
                VALUES (:id, :ivr_menu_id, :dtmf_key, :action_type, :action_target)
                ON CONFLICT (ivr_menu_id, dtmf_key)
                DO UPDATE SET
                    action_type = EXCLUDED.action_type,
                    action_target = EXCLUDED.action_target
            """),
            upsert_params
        )

    try:
        await execute_transaction(_upsert)
    except Exception as e:
        logger.error(f"Failed to upsert IVR node: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save DTMF key action: {str(e)}"
        )

    saved = await execute_query_one(
        "SELECT * FROM ivr_nodes WHERE ivr_menu_id = :ivr_id AND dtmf_key = :dtmf_key",
        {"ivr_id": ivr_id, "dtmf_key": payload.dtmf_key}
    )
    return dict(saved)


@router.delete("/{ivr_id}/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete DTMF key node")
async def delete_ivr_node(
    ivr_id: str,
    node_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """Delete a DTMF key action node from an IVR menu."""
    node = await execute_query_one(
        "SELECT id FROM ivr_nodes WHERE id = :id AND ivr_menu_id = :ivr_id",
        {"id": node_id, "ivr_id": ivr_id}
    )
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="IVR node not found")

    async def _delete(session):
        await session.execute(text("DELETE FROM ivr_nodes WHERE id = :id"), {"id": node_id})

    await execute_transaction(_delete)
    logger.info(f"IVR node {node_id} deleted by {current_user.username}")
