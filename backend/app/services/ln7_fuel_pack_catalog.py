"""Unique incident-derived CI packs for PRE6 fuel (not LIVING_BUG clones).

Writes catalog_* dirs under the writable living root ($DATA_DIR). Never
replays a used pack name. Never writes into the read-only app bind-mount
unless LN7_CATALOG_ALLOW_REPO=1.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import difflib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("ln7_fuel_pack_catalog")

CATALOG_PREFIX = "catalog_"


@dataclass(frozen=True)
class CatalogSpec:
    slug: str
    title: str
    prompt: str
    rel: str
    broken: str
    fixed: str
    looks_needle: str


def _unified(rel: str, old: str, new: str) -> str:
    old_l = old.splitlines(keepends=True)
    new_l = new.splitlines(keepends=True)
    if old_l and not old_l[-1].endswith("\n"):
        old_l[-1] += "\n"
    if new_l and not new_l[-1].endswith("\n"):
        new_l[-1] += "\n"
    return "".join(
        difflib.unified_diff(old_l, new_l, fromfile=f"a/{rel}", tofile=f"b/{rel}")
    )


def catalog_specs() -> List[CatalogSpec]:
    """Distinct real-incident bugs. Each slug is a new trainable pack."""
    return [
        CatalogSpec(
            slug="rsync_no_delete",
            title="Ban rsync --delete on GREEN deploy",
            prompt=(
                "broken/deploy.py uses rsync --delete. Remove --delete only. "
                "Return ONLY a unified diff for broken/deploy.py. No markdown fences."
            ),
            rel="broken/deploy.py",
            broken=(
                '"""Broken on purpose — rsync --delete wipes extras."""\n\n'
                "def deploy_cmd() -> str:\n"
                "    # BUG: --delete wiped Flutter/dashboard extras\n"
                '    return "rsync -avz --delete ./dashboard/ /var/www/sovereign-command/"\n\n'
                "def looks_fixed(cmd: str) -> bool:\n"
                '    return "--delete" not in cmd and "rsync" in cmd\n'
            ),
            fixed=(
                '"""Broken on purpose — rsync --delete wipes extras."""\n\n'
                "def deploy_cmd() -> str:\n"
                "    # Fixed: additive rsync only\n"
                '    return "rsync -avz ./dashboard/ /var/www/sovereign-command/"\n\n'
                "def looks_fixed(cmd: str) -> bool:\n"
                '    return "--delete" not in cmd and "rsync" in cmd\n'
            ),
            looks_needle="rsync -avz ./dashboard/",
        ),
        CatalogSpec(
            slug="group_by_positional",
            title="GROUP BY 1 not aliased family_id",
            prompt=(
                "broken/query.py groups by family_id alias which shadows users.family_id. "
                "Change GROUP BY family_id to GROUP BY 1. Return ONLY a unified diff "
                "for broken/query.py. No markdown fences."
            ),
            rel="broken/query.py",
            broken=(
                '"""Broken on purpose — GROUP BY alias shadows column."""\n\n'
                "def family_sql() -> str:\n"
                "    # BUG: GROUP BY family_id hits users.family_id UUID\n"
                '    return "SELECT COALESCE(profile_data->>\'family_id\', \'NONE\') '
                'as family_id FROM users GROUP BY family_id"\n\n'
                "def looks_fixed(sql: str) -> bool:\n"
                '    return "GROUP BY 1" in sql and "GROUP BY family_id" not in sql\n'
            ),
            fixed=(
                '"""Broken on purpose — GROUP BY alias shadows column."""\n\n'
                "def family_sql() -> str:\n"
                "    # Fixed: positional GROUP BY\n"
                '    return "SELECT COALESCE(profile_data->>\'family_id\', \'NONE\') '
                'as family_id FROM users GROUP BY 1"\n\n'
                "def looks_fixed(sql: str) -> bool:\n"
                '    return "GROUP BY 1" in sql and "GROUP BY family_id" not in sql\n'
            ),
            looks_needle="GROUP BY 1",
        ),
        CatalogSpec(
            slug="no_require_auth",
            title="Use get_current_user not require_auth",
            prompt=(
                "broken/router.py imports require_auth from api_server (does not exist). "
                "Import get_current_user instead. Return ONLY a unified diff for "
                "broken/router.py. No markdown fences."
            ),
            rel="broken/router.py",
            broken=(
                '"""Broken on purpose — require_auth ImportError."""\n\n'
                "def auth_import() -> str:\n"
                "    # BUG: require_auth is not in api_server\n"
                '    return "from app.services.api_server import require_auth"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "get_current_user" in s and "require_auth" not in s\n'
            ),
            fixed=(
                '"""Broken on purpose — require_auth ImportError."""\n\n'
                "def auth_import() -> str:\n"
                "    # Fixed: Dict-returning get_current_user\n"
                '    return "from app.services.api_server import get_current_user"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "get_current_user" in s and "require_auth" not in s\n'
            ),
            looks_needle="get_current_user",
        ),
        CatalogSpec(
            slug="vault_chown",
            title="chown 1000:1000 after vault write",
            prompt=(
                "broken/vault.py writes a vault file without chown. Add "
                "chown 1000:1000 after the write. Return ONLY a unified diff for "
                "broken/vault.py. No markdown fences."
            ),
            rel="broken/vault.py",
            broken=(
                '"""Broken on purpose — root-owned vault file."""\n\n'
                "def after_write() -> str:\n"
                "    # BUG: root:root 600 blocks UID 1000\n"
                '    return "write metrics.json"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "chown 1000:1000" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — root-owned vault file."""\n\n'
                "def after_write() -> str:\n"
                "    # Fixed: bridge UID owns the file\n"
                '    return "write metrics.json && chown 1000:1000 metrics.json"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "chown 1000:1000" in s\n'
            ),
            looks_needle="chown 1000:1000",
        ),
        CatalogSpec(
            slug="environment_match",
            title="ENVIRONMENT=production on bridge and backend",
            prompt=(
                "broken/compose.py sets ENVIRONMENT=development on the bridge. "
                "Change it to production. Return ONLY a unified diff for "
                "broken/compose.py. No markdown fences."
            ),
            rel="broken/compose.py",
            broken=(
                '"""Broken on purpose — Redis auth prefix split."""\n\n'
                "def bridge_env() -> str:\n"
                "    # BUG: nate:development:auth vs nate:production:auth\n"
                '    return "ENVIRONMENT=development"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "ENVIRONMENT=production" in s and "development" not in s\n'
            ),
            fixed=(
                '"""Broken on purpose — Redis auth prefix split."""\n\n'
                "def bridge_env() -> str:\n"
                "    # Fixed: match backend prefix\n"
                '    return "ENVIRONMENT=production"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "ENVIRONMENT=production" in s and "development" not in s\n'
            ),
            looks_needle="ENVIRONMENT=production",
        ),
        CatalogSpec(
            slug="company_id_dual",
            title="Set company_id column and JSONB",
            prompt=(
                "broken/assign.py updates only the company_id column. Also set "
                "profile_data.company_id. Return ONLY a unified diff for "
                "broken/assign.py. No markdown fences."
            ),
            rel="broken/assign.py",
            broken=(
                '"""Broken on purpose — company_id column-only."""\n\n'
                "def assign_sql() -> str:\n"
                "    # BUG: JSONB company_id left stale\n"
                '    return "UPDATE users SET company_id = $1"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "jsonb_set" in s and "{company_id}" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — company_id column-only."""\n\n'
                "def assign_sql() -> str:\n"
                "    # Fixed: column + JSONB\n"
                '    return "UPDATE users SET company_id = $1, profile_data = '
                "jsonb_set(profile_data, '{company_id}', to_jsonb($1::text))\"\n\n"
                "def looks_fixed(s: str) -> bool:\n"
                '    return "jsonb_set" in s and "{company_id}" in s\n'
            ),
            looks_needle="jsonb_set",
        ),
        CatalogSpec(
            slug="main_dart_nocache",
            title="no-cache on main.dart.js",
            prompt=(
                "broken/nginx.py lacks a no-cache location for main.dart.js. Add it. "
                "Return ONLY a unified diff for broken/nginx.py. No markdown fences."
            ),
            rel="broken/nginx.py",
            broken=(
                '"""Broken on purpose — Cloudflare served stale main.dart.js."""\n\n'
                "def locations() -> str:\n"
                "    # BUG: main.dart.js cached 4h at edge\n"
                '    return "location = /index.html { no-cache }"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "main.dart.js" in s and "no-cache" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — Cloudflare served stale main.dart.js."""\n\n'
                "def locations() -> str:\n"
                "    # Fixed: bootstrap + main.dart.js no-cache\n"
                '    return "location = /main.dart.js { no-cache }"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "main.dart.js" in s and "no-cache" in s\n'
            ),
            looks_needle="main.dart.js",
        ),
        CatalogSpec(
            slug="token_source_tag",
            title="use_tokens must pass source=",
            prompt=(
                "broken/billing.py calls use_tokens without source=. Add "
                'source="ai_chat". Return ONLY a unified diff for broken/billing.py. '
                "No markdown fences."
            ),
            rel="broken/billing.py",
            broken=(
                '"""Broken on purpose — unattributed token tx."""\n\n'
                "def charge() -> str:\n"
                "    # BUG: usage map shows unknown\n"
                '    return "use_tokens(uid, n)"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return \'source="ai_chat"\' in s or "source=\'ai_chat\'" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — unattributed token tx."""\n\n'
                "def charge() -> str:\n"
                "    # Fixed: canonical source tag\n"
                '    return \'use_tokens(uid, n, source="ai_chat")\'\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return \'source="ai_chat"\' in s or "source=\'ai_chat\'" in s\n'
            ),
            looks_needle='source="ai_chat"',
        ),
        CatalogSpec(
            slug="postgres_host_docker",
            title="POSTGRES_HOST=postgres inside Docker",
            prompt=(
                "broken/bridge.py uses POSTGRES_HOST=localhost. Change to postgres. "
                "Return ONLY a unified diff for broken/bridge.py. No markdown fences."
            ),
            rel="broken/bridge.py",
            broken=(
                '"""Broken on purpose — localhost is the container."""\n\n'
                "def pg_host() -> str:\n"
                "    # BUG: JSON fallback, no UserStore\n"
                '    return "localhost"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return s.strip() == "postgres"\n'
            ),
            fixed=(
                '"""Broken on purpose — localhost is the container."""\n\n'
                "def pg_host() -> str:\n"
                "    # Fixed: compose service name\n"
                '    return "postgres"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return s.strip() == "postgres"\n'
            ),
            looks_needle="postgres",
        ),
        CatalogSpec(
            slug="compose_prod_file",
            title="Always -f docker-compose.prod.yml",
            prompt=(
                "broken/deploy.py runs bare docker compose up. Add "
                "-f docker-compose.prod.yml. Return ONLY a unified diff for "
                "broken/deploy.py. No markdown fences."
            ),
            rel="broken/deploy.py",
            broken=(
                '"""Broken on purpose — wrong volume mounts."""\n\n'
                "def up_cmd() -> str:\n"
                "    # BUG: uses docker-compose.yml (bridge data ro)\n"
                '    return "docker compose up -d backend"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "-f docker-compose.prod.yml" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — wrong volume mounts."""\n\n'
                "def up_cmd() -> str:\n"
                "    # Fixed: prod compose file\n"
                '    return "docker compose -f docker-compose.prod.yml up -d backend"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "-f docker-compose.prod.yml" in s\n'
            ),
            looks_needle="docker-compose.prod.yml",
        ),
        CatalogSpec(
            slug="tokens_not_platforms",
            title="Observer queries skyeye_platform_tokens",
            prompt=(
                "broken/observer.py selects from skyeye_platforms for connection "
                "status. Query skyeye_platform_tokens instead. Return ONLY a "
                "unified diff for broken/observer.py. No markdown fences."
            ),
            rel="broken/observer.py",
            broken=(
                '"""Broken on purpose — platforms table has no tokens."""\n\n'
                "def connected_sql() -> str:\n"
                "    # BUG: status/token_status columns do not exist\n"
                '    return "SELECT platform FROM skyeye_platforms"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "skyeye_platform_tokens" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — platforms table has no tokens."""\n\n'
                "def connected_sql() -> str:\n"
                "    # Fixed: token table is authoritative\n"
                '    return "SELECT platform FROM skyeye_platform_tokens"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "skyeye_platform_tokens" in s\n'
            ),
            looks_needle="skyeye_platform_tokens",
        ),
        CatalogSpec(
            slug="silent_except_log",
            title="Log swallowed observer exceptions",
            prompt=(
                "broken/agent.py has except Exception: return []. Add a warning log. "
                "Return ONLY a unified diff for broken/agent.py. No markdown fences."
            ),
            rel="broken/agent.py",
            broken=(
                '"""Broken on purpose — silent empty poll."""\n\n'
                "def on_error() -> str:\n"
                "    # BUG: schema mismatch hidden\n"
                '    return "except Exception: return []"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "logger.warning" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — silent empty poll."""\n\n'
                "def on_error() -> str:\n"
                "    # Fixed: visible failure\n"
                '    return "except Exception as e: logger.warning(\'%s\', e); return []"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "logger.warning" in s\n'
            ),
            looks_needle="logger.warning",
        ),
        CatalogSpec(
            slug="sites_enabled_bak",
            title="No nginx backups in sites-enabled",
            prompt=(
                "broken/nginx.py stores api.sovereignsanctuary.net.bak in "
                "sites-enabled. Move backups out. Return ONLY a unified diff for "
                "broken/nginx.py. No markdown fences."
            ),
            rel="broken/nginx.py",
            broken=(
                '"""Broken on purpose — duplicate server_name."""\n\n'
                "def backup_path() -> str:\n"
                "    # BUG: include sites-enabled/* loads the bak\n"
                '    return "/etc/nginx/sites-enabled/api.bak"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "/etc/nginx/backups/" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — duplicate server_name."""\n\n'
                "def backup_path() -> str:\n"
                "    # Fixed: backups dir is not included\n"
                '    return "/etc/nginx/backups/api.bak"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "/etc/nginx/backups/" in s\n'
            ),
            looks_needle="/etc/nginx/backups/",
        ),
        CatalogSpec(
            slug="webauthn_issued_at",
            title="WebAuthn challenge needs issued_at",
            prompt=(
                "broken/webauthn.py stores a challenge without issued_at. Add the "
                "companion timestamp field. Return ONLY a unified diff for "
                "broken/webauthn.py. No markdown fences."
            ),
            rel="broken/webauthn.py",
            broken=(
                '"""Broken on purpose — replayable challenge."""\n\n'
                "def challenge_keys() -> str:\n"
                "    # BUG: no 120s TTL companion\n"
                '    return "webauthn_challenge"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "webauthn_challenge_issued_at" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — replayable challenge."""\n\n'
                "def challenge_keys() -> str:\n"
                "    # Fixed: TTL companion\n"
                '    return "webauthn_challenge,webauthn_challenge_issued_at"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "webauthn_challenge_issued_at" in s\n'
            ),
            looks_needle="webauthn_challenge_issued_at",
        ),
        CatalogSpec(
            slug="crystal_scope_narrow",
            title="Crystal scope never widens",
            prompt=(
                "broken/crystal.py widens user scope to global. Keep user scope. "
                "Return ONLY a unified diff for broken/crystal.py. No markdown fences."
            ),
            rel="broken/crystal.py",
            broken=(
                '"""Broken on purpose — privacy widen."""\n\n'
                "def next_scope() -> str:\n"
                "    # BUG: user:{name} must never become global\n"
                '    return "global"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return s.startswith("user:") and "global" not in s\n'
            ),
            fixed=(
                '"""Broken on purpose — privacy widen."""\n\n'
                "def next_scope() -> str:\n"
                "    # Fixed: scope only narrows\n"
                '    return "user:client"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return s.startswith("user:") and "global" not in s\n'
            ),
            looks_needle="user:client",
        ),
        CatalogSpec(
            slug="qb_no_token_log",
            title="Never log QuickBooks access_token",
            prompt=(
                "broken/qb.py logs the access_token. Log only the status code. "
                "Return ONLY a unified diff for broken/qb.py. No markdown fences."
            ),
            rel="broken/qb.py",
            broken=(
                '"""Broken on purpose — token in logs."""\n\n'
                "def log_line() -> str:\n"
                "    # BUG: Intuit audit fail\n"
                '    return "access_token=secret"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "access_token" not in s and "status=" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — token in logs."""\n\n'
                "def log_line() -> str:\n"
                "    # Fixed: status only\n"
                '    return "status=200"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "access_token" not in s and "status=" in s\n'
            ),
            looks_needle="status=200",
        ),
        CatalogSpec(
            slug="force_recreate_ban",
            title="No --force-recreate on GREEN",
            prompt=(
                "broken/deploy.py uses --force-recreate. Remove that flag. "
                "Return ONLY a unified diff for broken/deploy.py. No markdown fences."
            ),
            rel="broken/deploy.py",
            broken=(
                '"""Broken on purpose — vault wipe 2026-05-12."""\n\n'
                "def deploy() -> str:\n"
                "    # BUG: bind mount detached, empty vaults\n"
                '    return "docker compose up -d --force-recreate backend"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "--force-recreate" not in s and "up -d" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — vault wipe 2026-05-12."""\n\n'
                "def deploy() -> str:\n"
                "    # Fixed: safe_deploy.sh path\n"
                '    return "docker compose -f docker-compose.prod.yml up -d backend"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "--force-recreate" not in s and "up -d" in s\n'
            ),
            looks_needle="up -d backend",
        ),
        CatalogSpec(
            slug="empty_list_not_dict",
            title="Empty collection returns []",
            prompt=(
                "broken/api.py returns {} for an empty collection. Return []. "
                "Return ONLY a unified diff for broken/api.py. No markdown fences."
            ),
            rel="broken/api.py",
            broken=(
                '"""Broken on purpose — auditor WARNING on {}."""\n\n'
                "def payload() -> object:\n"
                "    # BUG: 200 + {} is WARNING\n"
                "    return {}\n\n"
                "def looks_fixed(v: object) -> bool:\n"
                "    return isinstance(v, list) and v == []\n"
            ),
            fixed=(
                '"""Broken on purpose — auditor WARNING on {}."""\n\n'
                "def payload() -> object:\n"
                "    # Fixed: empty list is TRUSTED\n"
                "    return []\n\n"
                "def looks_fixed(v: object) -> bool:\n"
                "    return isinstance(v, list) and v == []\n"
            ),
            looks_needle="return []",
        ),
        CatalogSpec(
            slug="auth_id_not_user_id",
            title="app.auth exports get_current_user_id",
            prompt=(
                "broken/auth.py imports get_current_user from app.auth. Use "
                "get_current_user_id. Return ONLY a unified diff for broken/auth.py. "
                "No markdown fences."
            ),
            rel="broken/auth.py",
            broken=(
                '"""Broken on purpose — retired import name."""\n\n'
                "def dep() -> str:\n"
                "    # BUG: ImportError from app.auth\n"
                '    return "from app.auth import get_current_user"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "get_current_user_id" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — retired import name."""\n\n'
                "def dep() -> str:\n"
                "    # Fixed: str identity helper\n"
                '    return "from app.auth import get_current_user_id"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "get_current_user_id" in s\n'
            ),
            looks_needle="get_current_user_id",
        ),
        CatalogSpec(
            slug="usage_filter_action",
            title="Usage map filters action not amount sign",
            prompt=(
                "broken/usage.py filters amount < 0. Filter action IN "
                "('deduct','usage') instead. Return ONLY a unified diff for "
                "broken/usage.py. No markdown fences."
            ),
            rel="broken/usage.py",
            broken=(
                '"""Broken on purpose — misses action=usage rows."""\n\n'
                "def where() -> str:\n"
                "    # BUG: add_token_usage logs positive amounts\n"
                '    return "amount < 0"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "action IN" in s and "amount < 0" not in s\n'
            ),
            fixed=(
                '"""Broken on purpose — misses action=usage rows."""\n\n'
                "def where() -> str:\n"
                "    # Fixed: deduct + usage\n"
                '    return "action IN (\'deduct\', \'usage\')"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "action IN" in s and "amount < 0" not in s\n'
            ),
            looks_needle="action IN",
        ),
        CatalogSpec(
            slug="profile_json_guard",
            title="profile_data may arrive as string",
            prompt=(
                "broken/profile.py calls .get on profile_data without a str guard. "
                "Parse JSON when it is a string. Return ONLY a unified diff for "
                "broken/profile.py. No markdown fences."
            ),
            rel="broken/profile.py",
            broken=(
                '"""Broken on purpose — str has no .get."""\n\n'
                "def read_name(profile) -> str:\n"
                "    # BUG: JSONB sometimes deserializes as str\n"
                '    return profile.get("name", "")\n\n'
                "def looks_fixed() -> bool:\n"
                "    try:\n"
                '        return read_name(\'{"name": "Ada"}\') == "Ada"\n'
                "    except Exception:\n"
                "        return False\n"
            ),
            fixed=(
                '"""Broken on purpose — str has no .get."""\n\n'
                "import json\n\n"
                "def read_name(profile) -> str:\n"
                "    # Fixed: coerce string JSONB\n"
                "    if isinstance(profile, str):\n"
                "        profile = json.loads(profile)\n"
                '    return profile.get("name", "")\n\n'
                "def looks_fixed() -> bool:\n"
                "    try:\n"
                '        return read_name(\'{"name": "Ada"}\') == "Ada"\n'
                "    except Exception:\n"
                "        return False\n"
            ),
            looks_needle='{"name": "Ada"}',
        ),
        CatalogSpec(
            slug="safe_deploy_wrapper",
            title="GREEN deploys go through safe_deploy.sh",
            prompt=(
                "broken/prod.py ssh-es docker compose directly. Use "
                "scripts/safe_deploy.sh. Return ONLY a unified diff for "
                "broken/prod.py. No markdown fences."
            ),
            rel="broken/prod.py",
            broken=(
                '"""Broken on purpose — unguarded compose."""\n\n'
                "def green_up() -> str:\n"
                "    # BUG: skipped vault count guard\n"
                '    return "docker compose -f docker-compose.prod.yml up -d backend"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "safe_deploy.sh" in s\n'
            ),
            fixed=(
                '"""Broken on purpose — unguarded compose."""\n\n'
                "def green_up() -> str:\n"
                "    # Fixed: vault snapshot + count\n"
                '    return "bash scripts/safe_deploy.sh backend"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "safe_deploy.sh" in s\n'
            ),
            looks_needle="safe_deploy.sh",
        ),
        CatalogSpec(
            slug="to_jsonb_int_cast",
            title="asyncpg to_jsonb needs ::int",
            prompt=(
                "broken/sql.py calls to_jsonb($1) without a cast. Use to_jsonb($1::int). "
                "Return ONLY a unified diff for broken/sql.py. No markdown fences."
            ),
            rel="broken/sql.py",
            broken=(
                '"""Broken on purpose — polymorphic anyelement."""\n\n'
                "def set_balance() -> str:\n"
                "    # BUG: DatatypeMismatchError under asyncpg\n"
                '    return "to_jsonb($1)"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "to_jsonb($1::int)" in s.replace(" ", "")\n'
            ),
            fixed=(
                '"""Broken on purpose — polymorphic anyelement."""\n\n'
                "def set_balance() -> str:\n"
                "    # Fixed: explicit int\n"
                '    return "to_jsonb($1::int)"\n\n'
                "def looks_fixed(s: str) -> bool:\n"
                '    return "to_jsonb($1::int)" in s.replace(" ", "")\n'
            ),
            looks_needle="to_jsonb($1::int)",
        ),
        CatalogSpec(
            slug="expected_role_login",
            title="login_request must send expected_role",
            prompt=(
                "broken/login.py sends login_request without expected_role. Add it. "
                "Return ONLY a unified diff for broken/login.py. No markdown fences."
            ),
            rel="broken/login.py",
            broken=(
                '"""Broken on purpose — dual CLIENT/COACH routing."""\n\n'
                "def payload() -> dict:\n"
                "    # BUG: first hash wins\n"
                '    return {"type": "login_request", "username": "x"}\n\n'
                "def looks_fixed(d: dict) -> bool:\n"
                '    return d.get("expected_role") in ("CLIENT", "COACH", "ADMIN")\n'
            ),
            fixed=(
                '"""Broken on purpose — dual CLIENT/COACH routing."""\n\n'
                "def payload() -> dict:\n"
                "    # Fixed: portal role\n"
                '    return {"type": "login_request", "username": "x", '
                '"expected_role": "COACH"}\n\n'
                "def looks_fixed(d: dict) -> bool:\n"
                '    return d.get("expected_role") in ("CLIENT", "COACH", "ADMIN")\n'
            ),
            looks_needle="expected_role",
        ),
    ]


def catalog_pack_name(slug: str) -> str:
    return f"{CATALOG_PREFIX}{slug}"


def catalog_pack_names() -> List[str]:
    return [catalog_pack_name(s.slug) for s in catalog_specs()]


def _is_repo_tree(root: Path) -> bool:
    try:
        from app.services.ln7_living_packs import _PACKS_ROOT

        return root.resolve() == _PACKS_ROOT.resolve()
    except Exception:
        return False


def materialize_catalog_pack(root: Path, spec: CatalogSpec) -> Dict[str, Any]:
    name = catalog_pack_name(spec.slug)
    pack = root / name
    broken_dir = pack / "broken"
    tests_dir = pack / "tests"
    broken_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)
    (broken_dir / "__init__.py").write_text(
        '"""Broken on purpose — catalog incident pack."""\n',
        encoding="utf-8",
    )
    target = Path(spec.rel)
    (pack / target).parent.mkdir(parents=True, exist_ok=True)
    (pack / target).write_text(spec.broken, encoding="utf-8")
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_fix.py").write_text(
        _test_module_for(spec),
        encoding="utf-8",
    )
    (pack / "golden.patch").write_text(
        _unified(spec.rel, spec.broken, spec.fixed), encoding="utf-8"
    )
    task = {
        "task_key": f"ci_{name}",
        "title": spec.title,
        "prompt": spec.prompt,
        "test_path": "tests/test_fix.py",
        "target_files": [spec.rel],
        "domain": "coding",
        "domain_tag": "python",
        "split": "train",
        "provenance": {"kind": "fuel_catalog", "slug": spec.slug},
    }
    (pack / "task.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "pack_name": name, "path": str(pack)}


def _test_module_for(spec: CatalogSpec) -> str:
    rel = spec.rel
    mod = Path(rel).stem
    if spec.slug == "empty_list_not_dict":
        return (
            "from broken.api import payload, looks_fixed\n\n\n"
            "def test_fixed():\n"
            "    assert looks_fixed(payload())\n"
        )
    if spec.slug == "expected_role_login":
        return (
            "from broken.login import payload, looks_fixed\n\n\n"
            "def test_fixed():\n"
            "    assert looks_fixed(payload())\n"
        )
    if spec.slug == "profile_json_guard":
        return (
            "from broken.profile import looks_fixed\n\n\n"
            "def test_fixed():\n"
            "    assert looks_fixed()\n"
        )
    # Default: looks_fixed(public_fn())
    fn = {
        "rsync_no_delete": ("deploy", "deploy_cmd"),
        "group_by_positional": ("query", "family_sql"),
        "no_require_auth": ("router", "auth_import"),
        "vault_chown": ("vault", "after_write"),
        "environment_match": ("compose", "bridge_env"),
        "company_id_dual": ("assign", "assign_sql"),
        "main_dart_nocache": ("nginx", "locations"),
        "token_source_tag": ("billing", "charge"),
        "postgres_host_docker": ("bridge", "pg_host"),
        "compose_prod_file": ("deploy", "up_cmd"),
        "tokens_not_platforms": ("observer", "connected_sql"),
        "silent_except_log": ("agent", "on_error"),
        "sites_enabled_bak": ("nginx", "backup_path"),
        "webauthn_issued_at": ("webauthn", "challenge_keys"),
        "crystal_scope_narrow": ("crystal", "next_scope"),
        "qb_no_token_log": ("qb", "log_line"),
        "force_recreate_ban": ("deploy", "deploy"),
        "auth_id_not_user_id": ("auth", "dep"),
        "usage_filter_action": ("usage", "where"),
        "safe_deploy_wrapper": ("prod", "green_up"),
        "to_jsonb_int_cast": ("sql", "set_balance"),
    }.get(spec.slug, (mod, "looks_fixed"))
    module, func = fn
    if func == "looks_fixed":
        return (
            f"from broken.{module} import looks_fixed\n\n\n"
            f"def test_fixed():\n"
            f"    raise AssertionError('missing public fn mapping')\n"
        )
    return (
        f"from broken.{module} import {func}, looks_fixed\n\n\n"
        f"def test_fixed():\n"
        f"    assert looks_fixed({func}())\n"
    )


def ensure_catalog_packs() -> Dict[str, Any]:
    """Materialize missing catalog_* packs on the writable living root."""
    from app.services.ln7_living_packs import packs_root

    root = packs_root()
    allow_repo = os.getenv("LN7_CATALOG_ALLOW_REPO", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if _is_repo_tree(root) and not allow_repo:
        return {
            "ok": True,
            "wrote": 0,
            "names": [],
            "skipped": "repo_tree",
            "root": str(root),
        }
    wrote: List[str] = []
    existing = 0
    for spec in catalog_specs():
        name = catalog_pack_name(spec.slug)
        if (root / name / "task.json").is_file():
            existing += 1
            continue
        try:
            materialize_catalog_pack(root, spec)
            wrote.append(name)
        except Exception as e:
            logger.warning("catalog materialize %s: %s", name, e)
    return {
        "ok": True,
        "wrote": len(wrote),
        "existing": existing,
        "names": wrote,
        "root": str(root),
        "catalog_size": len(catalog_specs()),
    }


def catalog_slugs_unique() -> Tuple[bool, List[str]]:
    slugs = [s.slug for s in catalog_specs()]
    dup = sorted({s for s in slugs if slugs.count(s) > 1})
    return (not dup, dup)
