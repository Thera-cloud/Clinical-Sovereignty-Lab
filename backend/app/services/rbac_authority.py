from typing import Dict, List, Optional, Tuple, AsyncGenerator
import asyncpg
from fastapi import HTTPException, status
from datetime import datetime, timedelta

from app.core.config import settings
from app.services.user_store import get_user_by_id

class PermissionLevel:
    NONE = 0
    USER = 1
    COACH = 10
    ADMIN = 50
    SUPERADMIN = 100

class Role:
    USER = "user"
    COACH = "coach"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"

PERMISSIONS = {
    'chat.basic': PermissionLevel.USER,
    'chat.crisis': PermissionLevel.COACH,
    'coach.assign': PermissionLevel.COACH,
    'admin.users': PermissionLevel.ADMIN,
    'admin.bypass': PermissionLevel.SUPERADMIN,
    'crisis.escalate': PermissionLevel.COACH,
    'crisis.intervene': PermissionLevel.ADMIN,
}

class RBACService:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_user_roles(self, user_id: int) -> List[str]:
        """Get all roles for a user"""
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT role_name 
                    FROM user_roles 
                    WHERE user_id = $1 AND active = true
                    """,
                    user_id
                )
                return [row['role_name'] for row in rows]
        except Exception as e:
            print(f"RBAC: Error fetching roles for user {user_id}: {e}")
            return []

    async def get_user_permissions(self, user_id: int) -> Dict[str, bool]:
        """Get permission flags for user"""
        roles = await self.get_user_roles(user_id)
        perms = {}
        for perm_name, required_level in PERMISSIONS.items():
            perms[perm_name] = any(self._role_has_level(role, required_level) for role in roles)
        return perms

    def _role_has_level(self, role: str, required_level: int) -> bool:
        level_map = {
            Role.USER: PermissionLevel.USER,
            Role.COACH: PermissionLevel.COACH,
            Role.ADMIN: PermissionLevel.ADMIN,
            Role.SUPERADMIN: PermissionLevel.SUPERADMIN,
        }
        return level_map.get(role, PermissionLevel.NONE) >= required_level

    async def check_permission(self, user_id: int, permission: str, *, strict: bool = True) -> bool:
        """Check if user has specific permission"""
        if not strict and user_id == 1:  # Big Nate bypass
            return True
        
        perms = await self.get_user_permissions(user_id)
        return perms.get(permission, False)

    async def authorize_handler(
        self, 
        user_id: int, 
        handler_name: str, 
        required_perms: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """Authorize handler execution with specific permissions"""
        for perm in required_perms:
            if not await self.check_permission(user_id, perm):
                return False, f"Missing permission: {perm}"
        return True, None

    async def get_user_authority_level(self, user_id: int) -> int:
        """Get highest authority level (0-100)"""
        roles = await self.get_user_roles(user_id)
        max_level = PermissionLevel.NONE
        for role in roles:
            level = {
                Role.SUPERADMIN: PermissionLevel.SUPERADMIN,
                Role.ADMIN: PermissionLevel.ADMIN,
                Role.COACH: PermissionLevel.COACH,
                Role.USER: PermissionLevel.USER,
            }.get(role, PermissionLevel.NONE)
            max_level = max(max_level, level)
        return max_level

# Global singleton
_rbac_service: Optional[RBACService] = None

async def init_rbac_service(pool: asyncpg.Pool) -> RBACService:
    global _rbac_service
    if _rbac_service is None:
        _rbac_service = RBACService(pool)
    return _rbac_service

def get_rbac_service() -> RBACService:
    if _rbac_service is None:
        raise RuntimeError("RBAC service not initialized")
    return _rbac_service

async def require_permission(user_id: int, permission: str) -> None:
    """Decorator-friendly permission check"""
    rbac = get_rbac_service()
    if not await rbac.check_permission(user_id, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {permission}"
        )

async def require_handler_access(user_id: int, handler_name: str) -> None:
    """Check handler-specific access"""
    rbac = get_rbac_service()
    required = {
        'chat': ['chat.basic'],
        'crisis_check': ['chat.crisis'],
        'coach_assign': ['coach.assign'],
    }.get(handler_name, ['chat.basic'])
    
    authorized, reason = await rbac.authorize_handler(user_id, handler_name, required)
    if not authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=reason or "Access denied"
        )