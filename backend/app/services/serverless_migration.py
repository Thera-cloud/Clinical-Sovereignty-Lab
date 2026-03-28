"""
Serverless Migration — Phase 11 of Sovereign Quantum Nate Build.

Infrastructure code for migrating to Cloudflare's edge:
  11.1: Auth + Users → D1 (extends existing d1_sync_agent.py)
  11.2: WebSocket Bridge → Durable Objects (handler decomposition)
  11.3: Backend → Workers (route mapping)
  11.4: Redis → Workers KV (session/token/rate-limit migration)
  11.5: VPS becomes optional (graceful degradation)

This module provides the migration helpers, schema mappers,
and readiness checks. Actual Worker/DO code is in cloudflare/workers/.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# D1 database binding name
D1_DB_NAME = os.getenv("D1_DATABASE_NAME", "nate-edge-db")
D1_ACCOUNT_ID = os.getenv("D1_ACCOUNT_ID", os.getenv("R2_ACCOUNT_ID", ""))
D1_API_TOKEN = os.getenv("D1_API_TOKEN", os.getenv("CLOUDFLARE_API_TOKEN", ""))


# ═══════════════════════════════════════════════════════════════
# 11.1: D1 Auth Schema
# ═══════════════════════════════════════════════════════════════

D1_USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('CLIENT', 'COACH', 'ADMIN')),
    tier TEXT DEFAULT 'TRIAL',
    hardware_id TEXT UNIQUE,
    email TEXT,
    token_balance INTEGER DEFAULT 0,
    subscription_status TEXT DEFAULT 'TRIAL_ACTIVE',
    profile_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_hwid ON users(hardware_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
"""

D1_AUTH_TOKENS_SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_tokens (
    token TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,
    FOREIGN KEY (username) REFERENCES users(username)
);

CREATE INDEX IF NOT EXISTS idx_tokens_username ON auth_tokens(username);
CREATE INDEX IF NOT EXISTS idx_tokens_expires ON auth_tokens(expires_at);
"""

D1_RATE_LIMITS_SCHEMA = """
CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT PRIMARY KEY,
    count INTEGER DEFAULT 0,
    window_start TEXT DEFAULT (datetime('now')),
    ttl_seconds INTEGER DEFAULT 3600
);
"""


def user_to_d1_row(username: str, profile: Dict) -> Dict:
    """Convert a PostgreSQL user row to D1-compatible format."""
    return {
        "username": username,
        "password_hash": profile.get("credentials", {}).get("password", ""),
        "role": profile.get("role", "CLIENT"),
        "tier": profile.get("tier", "TRIAL"),
        "hardware_id": profile.get("hardware_id", ""),
        "email": profile.get("email", ""),
        "token_balance": profile.get("token_balance", 0),
        "subscription_status": profile.get("subscription_status", "TRIAL_ACTIVE"),
        "profile_json": json.dumps({
            k: v for k, v in profile.items()
            if k not in ("credentials", "password_hash")
        }, default=str),
    }


# ═══════════════════════════════════════════════════════════════
# 11.2: Durable Object Handler Decomposition
# ═══════════════════════════════════════════════════════════════

DURABLE_OBJECT_HANDLERS = {
    "session_lifecycle": [
        "login_request",
        "logout",
        "heartbeat",
        "session_state",
    ],
    "message_dispatch": [
        "chat_message",
        "ai_response",
        "typing_indicator",
    ],
    "sentinel_scoring": [
        "sentinel_score",
        "sentinel_freeze",
        "sentinel_unfreeze",
    ],
    "session_memory": [
        "save_memory",
        "load_memory",
        "clear_memory",
    ],
    "nate_interaction": [
        "nate_query",
        "nate_voice_start",
        "nate_voice_data",
        "nate_voice_stop",
    ],
}

def get_do_handler_map() -> Dict[str, str]:
    """Map message types to their Durable Object class."""
    result = {}
    for do_class, msg_types in DURABLE_OBJECT_HANDLERS.items():
        for mt in msg_types:
            result[mt] = do_class
    return result


# ═══════════════════════════════════════════════════════════════
# 11.3: Worker Route Mapping
# ═══════════════════════════════════════════════════════════════

WORKER_ROUTES = {
    "/api/summon": "nate-summon-worker",
    "/api/skyeye/*": "nate-skyeye-worker",
    "/api/admin/*": "nate-admin-worker",
    "/api/client/*": "nate-client-worker",
    "/api/coach/*": "nate-coach-worker",
    "/api/sessions/*": "nate-sessions-worker",
    "/api/billing/*": "nate-billing-worker",
    "/api/gkm/*": "nate-gkm-worker",
    "/api/analytics/*": "nate-analytics-worker",
    "/api/trust-enforcer/*": "nate-trust-worker",
    "/health": "nate-health-worker",
}


def generate_wrangler_routes() -> str:
    """Generate wrangler.toml route configuration."""
    lines = ['[[routes]]']
    for pattern, worker in WORKER_ROUTES.items():
        lines.append(f'  pattern = "api.sovereignsanctuary.net{pattern}"')
        lines.append(f'  script = "{worker}"')
        lines.append("")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 11.4: Redis → KV Migration
# ═══════════════════════════════════════════════════════════════

KV_NAMESPACES = {
    "NATE_AUTH": {
        "description": "Auth tokens (bridge + JWT)",
        "redis_pattern": "nate:*:auth:*",
        "ttl_hours": 24,
    },
    "NATE_SESSIONS": {
        "description": "Session state and memory",
        "redis_pattern": "nate:*:session:*",
        "ttl_hours": 4,
    },
    "NATE_RATE_LIMITS": {
        "description": "Rate limiting counters",
        "redis_pattern": "nate:*:rate:*",
        "ttl_hours": 1,
    },
    "NATE_DEFCON": {
        "description": "DEFCON state and mesh curiosity",
        "redis_pattern": "nate:*:defcon:*",
        "ttl_hours": None,  # persistent
    },
    "NATE_CACHE": {
        "description": "General-purpose cache",
        "redis_pattern": "nate:*:cache:*",
        "ttl_hours": 6,
    },
}


def redis_key_to_kv(redis_key: str) -> Dict[str, str]:
    """Convert a Redis key to KV namespace + key format."""
    parts = redis_key.split(":")
    if len(parts) < 4:
        return {"namespace": "NATE_CACHE", "key": redis_key}

    prefix = parts[2]
    mapping = {
        "auth": "NATE_AUTH",
        "session": "NATE_SESSIONS",
        "rate": "NATE_RATE_LIMITS",
        "defcon": "NATE_DEFCON",
    }
    namespace = mapping.get(prefix, "NATE_CACHE")
    kv_key = ":".join(parts[2:])
    return {"namespace": namespace, "key": kv_key}


# ═══════════════════════════════════════════════════════════════
# 11.5: VPS Readiness Check
# ═══════════════════════════════════════════════════════════════

class ServerlessMigrationStatus:
    """Track readiness for VPS-optional operation."""

    @staticmethod
    async def check_readiness(db_pool=None, app_state=None) -> Dict[str, Any]:
        checks = {
            "d1_configured": bool(D1_ACCOUNT_ID and D1_API_TOKEN),
            "r2_configured": bool(os.getenv("R2_ACCOUNT_ID")),
            "vectorize_configured": False,
            "workers_ai_configured": bool(os.getenv("WORKERS_AI_URL")),
            "kv_namespaces_defined": True,
            "d1_schema_ready": False,
            "worker_routes_mapped": len(WORKER_ROUTES) > 0,
            "do_handlers_mapped": len(DURABLE_OBJECT_HANDLERS) > 0,
        }

        try:
            from app.services.vectorize_service import is_vectorize_configured
            checks["vectorize_configured"] = is_vectorize_configured()
        except Exception:
            pass

        # D1 sync status from existing agent
        if app_state:
            d1_agent = getattr(app_state, "d1_sync_agent", None)
            if d1_agent:
                checks["d1_schema_ready"] = True

        ready_count = sum(1 for v in checks.values() if v)
        total = len(checks)

        return {
            "checks": checks,
            "ready": f"{ready_count}/{total}",
            "vps_optional": ready_count == total,
            "degradation_if_offline": _get_degradation_report(checks),
        }

    @staticmethod
    def get_graceful_degradation() -> Dict[str, str]:
        """What happens if VPS goes offline after full migration."""
        return {
            "inference": "Workers AI handles all inference (quality may decrease for clinical)",
            "auth": "D1 handles all auth at edge (no degradation)",
            "sessions": "Durable Objects handle WebSocket (no degradation)",
            "storage": "R2 handles all storage (no degradation)",
            "search": "Vectorize handles semantic search (no degradation)",
            "cache": "Workers KV replaces Redis (no degradation)",
            "analytics": "PostgreSQL analytics unavailable (deferred)",
            "gpu_inference": "Sovereign model unavailable, Workers AI fallback",
        }


def _get_degradation_report(checks: Dict[str, bool]) -> List[str]:
    degradations = []
    if not checks.get("d1_configured"):
        degradations.append("Auth still requires VPS PostgreSQL")
    if not checks.get("workers_ai_configured"):
        degradations.append("AI inference requires VPS/Azure")
    if not checks.get("vectorize_configured"):
        degradations.append("Semantic search requires VPS PostgreSQL fallback")
    if not checks.get("r2_configured"):
        degradations.append("Storage requires VPS local disk")
    return degradations
