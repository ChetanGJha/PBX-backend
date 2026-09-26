import json
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from src.core.database import execute_query, execute_query_one, execute_transaction
from src.core.security import hash_password
from src.core.permissions import get_current_user, require_roles, CurrentUser

router = APIRouter(prefix="/users", tags=["Users Management"])


class UserCreate(BaseModel):
    tenant_id: Optional[UUID] = Field(None, description="Target tenant UUID (Required for TENANT_ADMIN, SUPERVISOR, AGENT)")
    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str = Field("AGENT", description="Role: TENANT_ADMIN, SUB_ADMIN, SUPERVISOR, AGENT")
    allowed_modules: Optional[List[str]] = Field(default_factory=list)


class UserResponse(BaseModel):
    id: UUID
    tenant_id: Optional[UUID]
    tenant_name: Optional[str]
    tenant_domain: Optional[str]
    username: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    role: str
    allowed_modules: Optional[List[str]] = []
    is_active: bool
    created_at: str


@router.get("", response_model=List[UserResponse])
async def list_users(
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    List users. Super Admins can list all or filter by tenant.
    Tenant Admins only see users within their own tenant.
    """
    target_tenant = tenant_id

    if current_user.role != "SUPER_ADMIN":
        target_tenant = current_user.tenant_id
        if not target_tenant:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: User is not assigned to a tenant."
            )

    query = """
        SELECT u.id, u.tenant_id, t.name as tenant_name, t.domain as tenant_domain,
               u.username, u.email, u.first_name, u.last_name, u.is_active,
               COALESCE(u.allowed_modules, '[]'::jsonb) as allowed_modules,
               COALESCE(r.name, 'AGENT') as role,
               u.created_at::text as created_at
        FROM users u
        LEFT JOIN tenants t ON u.tenant_id = t.id
        LEFT JOIN user_roles ur ON u.id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.id
        WHERE u.deleted_at IS NULL
    """
    params = {}

    if target_tenant:
        query += " AND u.tenant_id = :tenant_id"
        params["tenant_id"] = target_tenant

    query += " ORDER BY u.created_at DESC"

    rows = await execute_query(query, params)
    return [dict(r) for r in rows]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Create a new user account (Tenant Admin, Supervisor, or Agent).
    """
    target_tenant = payload.tenant_id

    if current_user.role != "SUPER_ADMIN":
        target_tenant = current_user.tenant_id
        if payload.role == "SUPER_ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant Admins cannot create Super Admin users."
            )

    if payload.role != "SUPER_ADMIN" and not target_tenant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="tenant_id is required for non-SuperAdmin users."
        )

    # Check if username or email exists
    existing = await execute_query_one(
        "SELECT id FROM users WHERE (username = :u OR email = :e) AND deleted_at IS NULL",
        {"u": payload.username, "e": payload.email}
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email is already registered."
        )

    pwd_hash = hash_password(payload.password)
    target_role = payload.role.upper()

    async def create_tx(session):
        from sqlalchemy.sql import text
        # Fetch role id
        role_res = await session.execute(text("SELECT id FROM roles WHERE name = :r"), {"r": target_role})
        role_row = role_res.fetchone()
        if not role_row:
            raise Exception(f"Role '{target_role}' not found in database schema.")
        role_id = role_row[0]

        # Insert user
        user_res = await session.execute(
            text("""
            INSERT INTO users (tenant_id, username, email, password_hash, first_name, last_name, allowed_modules)
            VALUES (:t_id, :username, :email, :pwd_hash, :fn, :ln, CAST(:allowed_modules AS jsonb))
            RETURNING id, created_at::text
            """),
            {
                "t_id": target_tenant,
                "username": payload.username,
                "email": payload.email,
                "pwd_hash": pwd_hash,
                "fn": payload.first_name,
                "ln": payload.last_name,
                "allowed_modules": json.dumps(payload.allowed_modules or [])
            }
        )
        user_row = user_res.fetchone()
        user_id = user_row[0]
        created_at_str = user_row[1]

        # Assign user role
        await session.execute(
            text("INSERT INTO user_roles (user_id, role_id) VALUES (:u_id, :r_id)"),
            {"u_id": user_id, "r_id": role_id}
        )

        return user_id, created_at_str

    user_id, created_at_str = await execute_transaction(create_tx)

    # Fetch tenant details
    tenant_info = None
    if target_tenant:
        tenant_info = await execute_query_one(
            "SELECT name, domain FROM tenants WHERE id = :t_id",
            {"t_id": target_tenant}
        )

    return {
        "id": user_id,
        "tenant_id": target_tenant,
        "tenant_name": tenant_info["name"] if tenant_info else None,
        "tenant_domain": tenant_info["domain"] if tenant_info else None,
        "username": payload.username,
        "email": payload.email,
        "first_name": payload.first_name,
        "last_name": payload.last_name,
        "role": target_role,
        "allowed_modules": payload.allowed_modules or [],
        "is_active": True,
        "created_at": created_at_str
    }


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Soft-delete a user account.
    """
    user = await execute_query_one(
        "SELECT id, tenant_id FROM users WHERE id = :u_id AND deleted_at IS NULL",
        {"u_id": user_id}
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    target_tenant_str = str(user["tenant_id"]) if user.get("tenant_id") else None
    current_tenant_str = str(current_user.tenant_id) if current_user.tenant_id else None
    if current_user.role != "SUPER_ADMIN" and target_tenant_str != current_tenant_str:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot delete user from another tenant.")

    await execute_query(
        "UPDATE users SET deleted_at = NOW(), is_active = false WHERE id = :u_id",
        {"u_id": user_id}
    )
    return None


class UserPermissionsUpdate(BaseModel):
    allowed_modules: List[str] = Field(default_factory=list)

@router.put("/{user_id}/permissions")
async def update_user_permissions(
    user_id: UUID,
    payload: UserPermissionsUpdate,
    current_user: CurrentUser = Depends(require_roles(["SUPER_ADMIN", "TENANT_ADMIN"]))
):
    """
    Update module permissions for a sub-administrator.
    """
    user = await execute_query_one(
        "SELECT id, tenant_id FROM users WHERE id = CAST(:u_id AS uuid) AND deleted_at IS NULL",
        {"u_id": user_id}
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    target_tenant_str = str(user["tenant_id"]) if user.get("tenant_id") else None
    current_tenant_str = str(current_user.tenant_id) if current_user.tenant_id else None
    if current_user.role != "SUPER_ADMIN" and target_tenant_str != current_tenant_str:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot edit user from another tenant.")

    await execute_query(
        "UPDATE users SET allowed_modules = CAST(:modules AS jsonb), updated_at = NOW() WHERE id = CAST(:u_id AS uuid)",
        {"u_id": user_id, "modules": json.dumps(payload.allowed_modules)}
    )
    return {"status": "success", "user_id": str(user_id), "allowed_modules": payload.allowed_modules}
