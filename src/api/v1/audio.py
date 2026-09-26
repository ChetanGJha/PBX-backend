"""
Audio File Management API
Handles upload, listing, and deletion of IVR prompt / greeting audio files.
"""
import os
import uuid
import logging
from typing import Optional
from sqlalchemy.sql import text
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from fastapi.responses import FileResponse

from src.core.database import execute_query, execute_query_one, execute_transaction, AsyncSessionLocal
from src.core.permissions import get_current_user, CurrentUser

logger = logging.getLogger("pbx.audio")

router = APIRouter(prefix="/audio", tags=["Audio Files"])

# Directory inside the container where audio files are stored
AUDIO_DIR = "/app/media/audio"


def _ensure_audio_dir():
    """Ensure the audio storage directory exists."""
    os.makedirs(AUDIO_DIR, exist_ok=True)


@router.get("", summary="List audio files")
async def list_audio_files(
    tenant_id: Optional[str] = Query(None, description="Filter by tenant"),
    category: Optional[str] = Query(None, description="Filter by category"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Return all audio files accessible to the authenticated user.
    Super Admins see all; tenant users see only their own tenant files.
    """
    conditions = ["1=1"]
    params: dict = {}

    # Tenant scoping
    if current_user.is_super_admin:
        if tenant_id:
            conditions.append("(af.tenant_id = :tenant_id OR af.tenant_id IS NULL)")
            params["tenant_id"] = tenant_id
    else:
        conditions.append("(af.tenant_id = :tenant_id OR af.tenant_id IS NULL)")
        params["tenant_id"] = current_user.tenant_id

    if category:
        conditions.append("af.category = :category")
        params["category"] = category

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT af.id, af.tenant_id, af.name, af.file_name, af.category,
               af.file_size, af.duration_seconds, af.created_at,
               t.name as tenant_name
        FROM audio_files af
        LEFT JOIN tenants t ON af.tenant_id = t.id
        WHERE {where_clause}
        ORDER BY af.created_at DESC
    """
    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.post("/upload", summary="Upload an audio file")
async def upload_audio_file(
    file: UploadFile = File(..., description="Audio file (.wav or .mp3)"),
    category: str = Form("ivr_greeting", description="Category: ivr_greeting, ivr_prompt, moh"),
    tenant_id: Optional[str] = Form(None, description="Associate with a tenant (optional)"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Upload an audio file for use as an IVR greeting or prompt.
    Files are stored in the FreeSWITCH sounds/custom directory.
    """
    _ensure_audio_dir()

    # Validate content type
    ALLOWED_TYPES = {"audio/wav", "audio/wave", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/ogg"}
    ALLOWED_EXTS = {".wav", ".mp3", ".ogg"}

    original_name = file.filename or "upload"
    _, ext = os.path.splitext(original_name.lower())

    if ext not in ALLOWED_EXTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported audio format '{ext}'. Allowed: .wav, .mp3, .ogg"
        )

    # Generate unique file name to avoid collisions
    unique_name = f"{uuid.uuid4().hex[:8]}_{original_name}"
    file_path = os.path.join(AUDIO_DIR, unique_name)

    # Enforce tenant scoping for non super-admins
    effective_tenant_id = tenant_id
    if not current_user.is_super_admin:
        effective_tenant_id = current_user.tenant_id

    # Stream write the file
    file_bytes = await file.read()
    file_size = len(file_bytes)

    try:
        with open(file_path, "wb") as f:
            f.write(file_bytes)
    except Exception as e:
        logger.error(f"Failed to write audio file to disk: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store audio file on server"
        )

    # Persist metadata in DB
    display_name = os.path.splitext(original_name)[0].replace("_", " ").replace("-", " ").title()
    file_id = str(uuid.uuid4())

    insert_params = {
        "id": file_id,
        "tenant_id": effective_tenant_id,
        "name": display_name,
        "file_name": unique_name,
        "category": category,
        "file_path": file_path,
        "file_size": file_size,
        "created_by": current_user.user_id,
    }

    async def _insert(session):
        await session.execute(
            text("""
                INSERT INTO audio_files (id, tenant_id, name, file_name, category, file_path, file_size, created_by)
                VALUES (:id, :tenant_id, :name, :file_name, :category, :file_path, :file_size, :created_by)
            """),
            insert_params
        )

    try:
        await execute_transaction(_insert)
    except Exception as e:
        # Clean up file if DB insert fails
        try:
            os.remove(file_path)
        except Exception:
            pass
        logger.error(f"DB insert for audio file failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save audio file metadata"
        )

    logger.info(f"Audio file uploaded: {unique_name} by user {current_user.username}")

    return {
        "id": file_id,
        "name": display_name,
        "file_name": unique_name,
        "category": category,
        "file_size": file_size,
        "tenant_id": effective_tenant_id,
        "message": "Audio file uploaded successfully"
    }


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete audio file")
async def delete_audio_file(
    file_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Delete an audio file by ID. Super Admin or owning tenant only.
    """
    row = await execute_query_one(
        "SELECT * FROM audio_files WHERE id = :id", {"id": file_id}
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found")

    if not current_user.is_super_admin and str(row["tenant_id"]) != current_user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Remove physical file
    file_path = row.get("file_path")
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning(f"Could not delete physical file {file_path}: {e}")

    async def _delete(session):
        await session.execute(text("DELETE FROM audio_files WHERE id = :id"), {"id": file_id})

    await execute_transaction(_delete)
    logger.info(f"Audio file {file_id} deleted by {current_user.username}")


@router.get("/{file_id}/stream", summary="Stream / play audio file")
async def stream_audio_file(file_id: str):
    """
    Stream audio file for in-browser playback.
    Accepts audio file UUID or unique file_name.
    """
    row = await execute_query_one(
        "SELECT * FROM audio_files WHERE CAST(id AS text) = :id OR file_name = :id",
        {"id": file_id}
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found")

    file_path = row.get("file_path")
    if not file_path or not os.path.exists(file_path):
        file_name = row.get("file_name", "")
        alt_path = os.path.join(AUDIO_DIR, file_name)
        if os.path.exists(alt_path):
            file_path = alt_path
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file missing from server disk")

    ext = os.path.splitext(file_path)[1].lower()
    media_type = "audio/mpeg" if ext == ".mp3" else ("audio/wav" if ext == ".wav" else "audio/ogg")

    return FileResponse(
        file_path,
        media_type=media_type,
        filename=row.get("file_name", "audio" + ext),
        headers={"Accept-Ranges": "bytes"}
    )
