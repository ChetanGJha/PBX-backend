from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser
<<<<<<< HEAD
from src.services.gateway_sync import sync_gateway_file, remove_gateway_file, reload_freeswitch_gateways
=======
from src.services.gateway_sync import sync_gateways_to_freeswitch, execute_esl_command
>>>>>>> 642b5a2a01afc3a19796c4f49f1737db7fe86dc0

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
    profile: Optional[str] = Field("external", description="SIP Profile: 'external' (ITS SBC) or 'external-crossconnect' (Fixed Line SBC)")


class GatewayUpdate(BaseModel):
    name: Optional[str] = None
    proxy: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    realm: Optional[str] = None
    from_domain: Optional[str] = None
    codecs: Optional[str] = None
    tenant_id: Optional[UUID] = None
    register: Optional[bool] = None
    caller_id_in_from: Optional[bool] = None
    profile: Optional[str] = None
    enabled: Optional[bool] = None


class GatewayAssignmentCreate(BaseModel):
    tenant_id: UUID
    gateway_id: UUID
    direction: str = "inbound_outbound"  # inbound_outbound, inbound_only, outbound_only
    priority: int = 1
    caller_id_policy: str = "tenant_default"
    allow_outbound: bool = True
    accept_inbound: bool = True
    allow_international: bool = False


@router.get("")
async def list_gateways(current_user: CurrentUser = Depends(get_current_user)):
    """
    List FreeSWITCH Sofia gateways. Superadmins see all; Tenant Admins see their assigned and shared gateways.
    """
    if current_user.is_super_admin:
        query = """
            SELECT g.id, g.name, g.proxy, g.username, g.realm, g.from_domain, g.codecs,
<<<<<<< HEAD
                   g.register, g.caller_id_in_from, g.enabled, g.tenant_id, g.created_at::text,
=======
                   g.register, g.caller_id_in_from, g.profile, g.enabled, g.tenant_id, g.created_at::text,
>>>>>>> 642b5a2a01afc3a19796c4f49f1737db7fe86dc0
                   t.name as tenant_name, t.domain as tenant_domain
            FROM gateways g
            LEFT JOIN tenants t ON g.tenant_id = t.id
            WHERE g.deleted_at IS NULL
            ORDER BY g.name ASC
        """
        rows = await execute_query(query)
    else:
        query = """
            SELECT g.id, g.name, g.proxy, g.username, g.realm, g.from_domain, g.codecs,
<<<<<<< HEAD
                   g.register, g.caller_id_in_from, g.enabled, g.tenant_id, g.created_at::text,
=======
                   g.register, g.caller_id_in_from, g.profile, g.enabled, g.tenant_id, g.created_at::text,
>>>>>>> 642b5a2a01afc3a19796c4f49f1737db7fe86dc0
                   t.name as tenant_name, t.domain as tenant_domain
            FROM gateways g
            LEFT JOIN tenants t ON g.tenant_id = t.id
            WHERE g.deleted_at IS NULL
              AND (g.tenant_id = CAST(:t_id AS uuid) OR g.tenant_id IS NULL)
            ORDER BY g.name ASC
        """
        rows = await execute_query(query, {"t_id": str(current_user.tenant_id)})
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_gateway(
    payload: GatewayCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
<<<<<<< HEAD
    Create a new Sofia Gateway and sync it to FreeSWITCH external profile.
=======
    Create a new Sofia Gateway, generate XML config and trigger FreeSWITCH Sofia rescan.
>>>>>>> 642b5a2a01afc3a19796c4f49f1737db7fe86dc0
    """
    data = payload.dict()
    if not data.get("profile"):
        data["profile"] = "external-crossconnect" if "10.50.185." in (data.get("proxy") or "") else "external"

    query = """
<<<<<<< HEAD
        INSERT INTO gateways (name, proxy, username, password, realm, from_domain, codecs, tenant_id, register, caller_id_in_from)
        VALUES (:name, :proxy, :username, :password, :realm, :from_domain, :codecs, :tenant_id, :register, :caller_id_in_from)
        RETURNING id, name, proxy, username, realm, from_domain, codecs, tenant_id, register, caller_id_in_from, enabled, created_at::text
    """
    row = await execute_query_one(query, payload.dict())
    gw_dict = dict(row)
    
    # Sync gateway to FreeSWITCH external profile and rescan
    sync_gateway_file(gw_dict)
    reload_freeswitch_gateways()
    
    return gw_dict
=======
        INSERT INTO gateways (name, proxy, username, password, realm, from_domain, codecs, tenant_id, register, caller_id_in_from, profile)
        VALUES (:name, :proxy, :username, :password, :realm, :from_domain, :codecs, :tenant_id, :register, :caller_id_in_from, :profile)
        RETURNING id, name, proxy, username, realm, from_domain, codecs, register, caller_id_in_from, profile, enabled, created_at::text
    """
    row = await execute_query_one(query, data)

    # Sync to FreeSWITCH XML and rescan profile
    try:
        await sync_gateways_to_freeswitch()
    except Exception as e:
        # Don't fail the API call if FreeSWITCH is reloading
        pass

    return dict(row)
>>>>>>> 642b5a2a01afc3a19796c4f49f1737db7fe86dc0


@router.put("/{gateway_id}")
async def update_gateway(
    gateway_id: UUID,
    payload: GatewayUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
<<<<<<< HEAD
    Update Sofia Gateway configuration, sync with FreeSWITCH external profile, and update tenant assignment.
=======
    Update Sofia Gateway configuration, regenerate XML and trigger FreeSWITCH rescan.
>>>>>>> 642b5a2a01afc3a19796c4f49f1737db7fe86dc0
    """
    existing = await execute_query_one(
        "SELECT id, name FROM gateways WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL",
        {"id": str(gateway_id)}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Gateway not found")

    updates = []
    params = {"id": str(gateway_id)}

    data = payload.dict(exclude_unset=True)
    for field, val in data.items():
        if field == "tenant_id":
            if val is not None:
                updates.append("tenant_id = CAST(:tenant_id AS uuid)")
                params["tenant_id"] = str(val)
            else:
                updates.append("tenant_id = NULL")
        else:
            updates.append(f"{field} = :{field}")
            params[field] = val

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    query = f"""
        UPDATE gateways
        SET {', '.join(updates)}, updated_at = NOW()
        WHERE id = CAST(:id AS uuid)
<<<<<<< HEAD
        RETURNING id, name, proxy, username, realm, from_domain, codecs, tenant_id, register, caller_id_in_from, enabled, created_at::text
    """
    row = await execute_query_one(query, params)
    gw_dict = dict(row)
    
    # If gateway name changed, remove old file
    if existing.get("name") and existing["name"] != gw_dict.get("name"):
        remove_gateway_file(existing["name"])
        
    if gw_dict.get("enabled", True):
        sync_gateway_file(gw_dict)
    else:
        remove_gateway_file(gw_dict["name"])
        
    reload_freeswitch_gateways()
    return gw_dict
=======
        RETURNING id, name, proxy, username, realm, from_domain, codecs, tenant_id, register, caller_id_in_from, profile, enabled, created_at::text
    """
    row = await execute_query_one(query, params)

    # Sync to FreeSWITCH XML and rescan profile
    try:
        await sync_gateways_to_freeswitch()
    except Exception:
        pass

    return dict(row)
>>>>>>> 642b5a2a01afc3a19796c4f49f1737db7fe86dc0


@router.delete("/{gateway_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_gateway(
    gateway_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
<<<<<<< HEAD
    Soft-delete a Sofia Gateway and remove from FreeSWITCH external profile.
    """
    existing = await execute_query_one(
        "SELECT id, name FROM gateways WHERE id = CAST(:id AS uuid) AND deleted_at IS NULL",
        {"id": str(gateway_id)}
    )
    if existing:
        await execute_query("UPDATE gateways SET deleted_at = NOW(), enabled = false WHERE id = CAST(:id AS uuid)", {"id": str(gateway_id)})
        remove_gateway_file(existing["name"])
        reload_freeswitch_gateways()
=======
    Soft-delete a Sofia Gateway, delete XML file and remove gateway from FreeSWITCH.
    """
    await execute_query("UPDATE gateways SET deleted_at = NOW(), enabled = false WHERE id = CAST(:id AS uuid)", {"id": str(gateway_id)})
    
    try:
        await sync_gateways_to_freeswitch()
    except Exception:
        pass
        
>>>>>>> 642b5a2a01afc3a19796c4f49f1737db7fe86dc0
    return None


@router.post("/assign", status_code=status.HTTP_201_CREATED)
async def assign_gateway_to_tenant(
    payload: GatewayAssignmentCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
    Assign a gateway to a tenant domain with route priorities.
    """
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
    reload_freeswitch_gateways()
    return dict(row)


@router.post("/sync")
async def trigger_gateway_sync(
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
    Forces an immediate synchronization of all database gateways into FreeSWITCH XML and rescans profiles.
    """
    result = await sync_gateways_to_freeswitch()
    return result


@router.get("/sofia-status")
async def get_sofia_status(
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN"]))
):
    """
    Fetches live sofia status from FreeSWITCH ESL.
    """
    output = execute_esl_command("sofia status")
    return {"sofia_status": output or "FreeSWITCH ESL unreachable"}
