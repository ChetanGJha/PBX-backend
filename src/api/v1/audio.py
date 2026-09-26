import os
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel
from src.core.database import execute_query, execute_query_one
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/audio", tags=["Audio Prompts"])

AUDIO_DIR = "/var/lib/freeswitch/recordings"

@router.get("")
async def list_audio_files(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id
    query = """
        SELECT id, name as file_name, file_path, category, description, created_at::text
        FROM announcements
        WHERE 1=1
    """
    params = {}
    if target_tenant:
        query += " AND tenant_id = CAST(:t_id AS uuid)"
        params["t_id"] = target_tenant

    rows = await execute_query(query, params)
    return [dict(r) for r in rows]

@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_audio_file(
    file: UploadFile = File(...),
    category: str = "ivr_greeting",
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    target_tenant = tenant_id if current_user.is_super_admin else current_user.tenant_id
    filename = file.filename
    rel_path = f"prompts/{filename}"

    query = """
        INSERT INTO announcements (name, file_name, file_path, category, tenant_id)
        VALUES (:name, :file_name, :file_path, :category, CAST(:tenant_id AS uuid))
        RETURNING id, file_name, file_path, category, created_at::text
    """
    row = await execute_query_one(query, {
        "name": filename,
        "file_name": filename,
        "file_path": rel_path,
        "category": category,
        "tenant_id": target_tenant
    })
    return dict(row)
