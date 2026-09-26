from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from src.core.database import execute_query_one, execute_query, execute_transaction
from src.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from src.core.permissions import get_current_user, CurrentUser

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username_or_email: str = Field(..., description="Username or Email address")
    password: str = Field(..., description="User password")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class SeedSuperAdminRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: Optional[str] = "Platform"
    last_name: Optional[str] = "Admin"


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    """
    Authenticate user by username or email and return JWT access and refresh tokens.
    """
    query = """
        SELECT u.id, u.tenant_id, u.username, u.email, u.password_hash, u.is_active, 
               u.first_name, u.last_name, COALESCE(u.allowed_modules, '[]'::jsonb) as allowed_modules, r.name as role_name, t.domain as tenant_domain,
               t.sip_domain
        FROM users u
        LEFT JOIN tenants t ON u.tenant_id = t.id
        LEFT JOIN user_roles ur ON u.id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.id
        WHERE (u.username = :login OR u.email = :login) AND u.deleted_at IS NULL
    """
    user = await execute_query_one(query, {"login": payload.username_or_email})

    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username/email or password"
        )

    if not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated"
        )

    role_name = user.get("role_name") or "AGENT"
    tenant_id_str = str(user["tenant_id"]) if user["tenant_id"] else None

    token_data = {
        "sub": str(user["id"]),
        "username": user["username"],
        "email": user["email"],
        "role": role_name,
        "tenant_id": tenant_id_str,
        "sip_domain": user.get("sip_domain"),
            "allowed_modules": user.get("allowed_modules") or []
    }

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token({"sub": str(user["id"]), "type": "refresh"})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 1800,  # 30 minutes
        "user": {
            "id": str(user["id"]),
            "username": user["username"],
            "email": user["email"],
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
            "role": role_name,
            "tenant_id": tenant_id_str,
            "tenant_domain": user.get("tenant_domain"),
            "sip_domain": user.get("sip_domain"),
            "allowed_modules": user.get("allowed_modules") or []
        }
    }


@router.post("/refresh")
async def refresh_token_endpoint(payload: RefreshTokenRequest):
    """
    Issue new access token using a valid refresh token.
    """
    decoded = decode_token(payload.refresh_token)
    if not decoded or decoded.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    user_id = decoded.get("sub")
    query = """
        SELECT u.id, u.tenant_id, u.username, u.email, u.is_active, r.name as role_name,
               t.sip_domain
        FROM users u
        LEFT JOIN tenants t ON u.tenant_id = t.id
        LEFT JOIN user_roles ur ON u.id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.id
        WHERE u.id = :user_id AND u.deleted_at IS NULL
    """
    user = await execute_query_one(query, {"user_id": user_id})

    if not user or not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account inactive or not found"
        )

    token_data = {
        "sub": str(user["id"]),
        "username": user["username"],
        "email": user["email"],
        "role": user.get("role_name") or "AGENT",
        "tenant_id": str(user["tenant_id"]) if user["tenant_id"] else None,
        "sip_domain": user.get("sip_domain"),
            "allowed_modules": user.get("allowed_modules") or []
    }

    new_access_token = create_access_token(token_data)
    return {
        "access_token": new_access_token,
        "token_type": "bearer",
        "expires_in": 1800
    }


@router.get("/me")
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    """
    Get authenticated user profile and active tenant details.
    """
    query = """
        SELECT u.id, u.tenant_id, u.username, u.email, u.first_name, u.last_name, u.is_active,
               COALESCE(u.allowed_modules, '[]'::jsonb) as allowed_modules, u.created_at, r.name as role_name, t.name as tenant_name, t.domain as tenant_domain,
               t.sip_domain
        FROM users u
        LEFT JOIN tenants t ON u.tenant_id = t.id
        LEFT JOIN user_roles ur ON u.id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.id
        WHERE u.id = :user_id AND u.deleted_at IS NULL
    """
    user = await execute_query_one(query, {"user_id": current_user.user_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found")

    return {
        "id": str(user["id"]),
        "username": user["username"],
        "email": user["email"],
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "role": user.get("role_name"),
        "allowed_modules": user.get("allowed_modules") or [],
        "tenant": {
            "id": str(user["tenant_id"]) if user["tenant_id"] else None,
            "name": user.get("tenant_name"),
            "domain": user.get("tenant_domain"),
            "sip_domain": user.get("sip_domain"),
            "allowed_modules": user.get("allowed_modules") or []
        } if user.get("tenant_id") else None,
        "created_at": user.get("created_at")
    }


@router.post("/seed-superadmin")
async def seed_super_admin(payload: SeedSuperAdminRequest):
    """
    Initial bootstrap endpoint to create the primary SUPER_ADMIN user if none exists.
    """
    existing_admin = await execute_query_one(
        "SELECT u.id FROM users u JOIN user_roles ur ON u.id = ur.user_id JOIN roles r ON ur.role_id = r.id WHERE r.name = 'SUPER_ADMIN'"
    )
    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Super admin user already exists on this platform."
        )

    pwd_hash = hash_password(payload.password)

    async def create_admin_tx(session):
        # Fetch SUPER_ADMIN role ID
        from sqlalchemy.sql import text
        role_res = await session.execute(text("SELECT id FROM roles WHERE name = 'SUPER_ADMIN'"))
        role_row = role_res.fetchone()
        if not role_row:
            raise Exception("SUPER_ADMIN role missing in database schema")
        role_id = role_row[0]

        user_res = await session.execute(
            text("""
            INSERT INTO users (tenant_id, username, email, password_hash, first_name, last_name)
            VALUES (NULL, :username, :email, :pwd_hash, :first_name, :last_name)
            RETURNING id
            """),
            {
                "username": payload.username,
                "email": payload.email,
                "pwd_hash": pwd_hash,
                "first_name": payload.first_name,
                "last_name": payload.last_name
            }
        )
        user_row = user_res.fetchone()
        user_id = user_row[0]

        await session.execute(
            text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
            {"user_id": user_id, "role_id": role_id}
        )
        return str(user_id)

    created_id = await execute_transaction(create_admin_tx)


    return {
        "message": "Super Admin user created successfully",
        "user_id": created_id,
        "username": payload.username
    }
