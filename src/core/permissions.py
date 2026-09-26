from typing import Optional, List
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.core.security import decode_token
from src.core.database import execute_query_one

security_bearer = HTTPBearer(auto_error=True)


class CurrentUser:
    """Authenticated user context object."""
    def __init__(self, user_id: str, tenant_id: Optional[str], username: str, email: str, role: str):
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.username = username
        self.email = email
        self.role = role

    @property
    def is_super_admin(self) -> bool:
        return self.role == "SUPER_ADMIN"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_bearer)
) -> CurrentUser:
    """
    FastAPI dependency to authenticate requests and return CurrentUser context.
    Fails if token is invalid or expired.
    """
    token = credentials.credentials
    payload = decode_token(token)
    
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing subject user ID",
        )

    # Fetch fresh user record & role from DB
    query = """
        SELECT u.id, u.tenant_id, u.username, u.email, u.is_active, r.name as role_name
        FROM users u
        LEFT JOIN user_roles ur ON u.id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.id
        WHERE u.id = :user_id AND u.deleted_at IS NULL
    """
    user_row = await execute_query_one(query, {"user_id": user_id})

    if not user_row or not user_row.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled or does not exist",
        )

    return CurrentUser(
        user_id=str(user_row["id"]),
        tenant_id=str(user_row["tenant_id"]) if user_row["tenant_id"] else None,
        username=user_row["username"],
        email=user_row["email"],
        role=user_row.get("role_name") or "AGENT"
    )


def require_roles(allowed_roles: List[str]):
    """
    Dependency factory enforcing role-based access control.
    """
    async def role_checker(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action forbidden for role '{current_user.role}'. Required roles: {allowed_roles}"
            )
        return current_user
    return role_checker


def validate_tenant_access(current_user: CurrentUser, target_tenant_id: str):
    """
    Enforces strict multi-tenant isolation.
    Super Admin can access any tenant; Tenant Admin/Supervisor/Agent can ONLY access their own tenant.
    """
    if current_user.is_super_admin:
        return
    if not current_user.tenant_id or current_user.tenant_id != target_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant isolation violation: Access denied to requested tenant resource"
        )
