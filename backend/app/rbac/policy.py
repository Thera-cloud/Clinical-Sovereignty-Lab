from typing import Dict, List, Any, Optional, Callable
from enum import Enum

from app.db.models import UserRole
from app.services.crisis_engine import CrisisLevel


class DataClassification(Enum):
    PUBLIC = "public"
    SENSITIVE = "sensitive"
    CONFIDENTIAL = "confidential"
    CRITICAL = "critical"


class ToolScope:
    def __init__(self, predicate: Callable[[dict], bool]):
        self.predicate = predicate


class ToolPolicy:
    def __init__(
        self,
        name: str,
        data_classification: DataClassification,
        scope: Optional[ToolScope] = None,
        crisis_override: Optional[CrisisLevel] = None,
    ):
        self.name = name
        self.data_classification = data_classification
        self.scope = scope
        self.crisis_override = crisis_override


class RBACPolicy:
    def __init__(self):
        self._policies: Dict[str, ToolPolicy] = {}
        self._role_tools: Dict[str, List[str]] = {}
        self._load_policies()

    def _load_policies(self) -> None:
        """Centralized policy definitions - single source of truth"""
        # ADMIN: Full access
        self._role_tools[UserRole.ADMIN.value] = [
            "execute_code",
            "read_file",
            "write_file",
            "search_code",
            "list_directory",
            "read_db",
            "write_db",
        ]

        # SUPERVISOR: Audit + read-only
        self._role_tools["supervisor"] = [
            "search_code",
            "list_directory",
            "read_audit",
        ]

        # COACH: Session tools only
        self._role_tools["coach"] = ["read_session", "write_session"]

        # CLIENT: Minimal
        self._role_tools["client"] = ["read_profile"]

        # Tool classifications
        self._policies["execute_code"] = ToolPolicy(
            name="execute_code",
            data_classification=DataClassification.CRITICAL,
            crisis_override=CrisisLevel.IMMINENT,
        )
        self._policies["write_file"] = ToolPolicy(
            name="write_file",
            data_classification=DataClassification.CRITICAL,
        )
        self._policies["read_file"] = ToolPolicy(
            name="read_file",
            data_classification=DataClassification.CONFIDENTIAL,
        )

    def get_allowed_tools(self, role: str) -> List[str]:
        """Get tools allowed for role"""
        return self._role_tools.get(role.lower(), [])

    def is_tool_allowed(self, tool_name: str, role: str) -> bool:
        """Check if tool is allowed for role"""
        allowed = self.get_allowed_tools(role)
        return tool_name in allowed

    def get_tool_policy(self, tool_name: str) -> Optional[ToolPolicy]:
        """Get policy for specific tool"""
        return self._policies.get(tool_name)

    def check_scope(self, tool_name: str, context: dict, role: str) -> bool:
        """Enforce scope predicate"""
        policy = self.get_tool_policy(tool_name)
        if not policy or not policy.scope:
            return True
        return policy.scope.predicate(context)


# Global policy singleton
policy = RBACPolicy()
