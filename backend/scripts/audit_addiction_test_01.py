#!/usr/bin/env python3
"""Sensitive Bridge v1.4 synthetic E2E: audit_addiction_test_01.

Creates a disposable client/coach pair, exercises addiction status, parts
registry, part-aware codeword storage + runtime match, alert dispatch redaction,
and inserts/validates all 14 v1.4 telemetry event types from the plan.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CLIENT = "audit_addiction_test_01"
COACH = "audit_addiction_coach_01"
_PASSWORD_SALT = "0123456789abcdef0123456789abcdef"
PASSWORD_HASH = (
    _PASSWORD_SALT
    + ":"
    + hashlib.pbkdf2_hmac(
        "sha256",
        b"AuditAddictionTest01!",
        _PASSWORD_SALT.encode("utf-8"),
        100000,
    ).hex()
)
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
SESSION_ID = f"audit_addiction_test_01_session_{RUN_ID}"

V14_FLAGS = {
    "v1_4_codeword_listener_enabled": True,
    "v1_4_addiction_branches_enabled": True,
    "v1_4_cross_addiction_overlay_enabled": True,
    "v1_4_dst_lens_enabled": True,
    "v1_4_framework_lens_enabled": True,
    "v1_4_crystal_factory_enabled": True,
    "v1_4_alert_dispatch_enabled": True,
}

TELEMETRY_TYPES = (
    "addiction_status_update",
    "addiction_branch_activated",
    "addiction_lexicon_match",
    "addiction_response_generated",
    "coach_alert_dispatched",
    "coach_alert_acknowledged",
    "referral_suggested",
    "referral_acknowledged",
    "crisis_warm_handoff",
    "cross_addiction_transfer_logged",
    "part_codeword_match",
    "framework_lens_selected",
    "trafficking_disclosure_detected",
    "pii_redaction_applied",
)


def _dsn() -> str:
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        return dsn
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "nate_admin")
    db = os.getenv("POSTGRES_DB", "little_nate")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _check(ok: bool, name: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "details": details or {}}


async def _fetchval(pool, sql: str, *args):
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *args)


async def _fetchrow(pool, sql: str, *args):
    async with pool.acquire() as conn:
        return await conn.fetchrow(sql, *args)


async def _execute(pool, sql: str, *args):
    async with pool.acquire() as conn:
        return await conn.execute(sql, *args)


async def _setup(pool) -> None:
    now = datetime.now(timezone.utc)
    coach_profile = {
        "name": "Audit Addiction Coach",
        "email": "audit_addiction_coach@example.invalid",
    }
    client_profile = {
        "name": "Audit Addiction Client",
        "email": "audit_addiction_client@example.invalid",
        "assigned_coach": COACH,
        "coach_id": "COACH_AUDIT_ADDICTION_ID",
        "assigned_coach_id": "COACH_AUDIT_ADDICTION_ID",
        "substance_status": "active_use",
        "sex_addiction_status": "active",
        "gambling_status": "active",
        "framework_menu": {
            "preferred_frameworks": ["ifs", "dst"],
            "crystal_knowledge_graph_enabled": False,
            "default_lens_for_today": "ifs",
        },
    }
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (
                username, role, name, hardware_id, password_hash,
                subscription_status, tier, profile_data, created_at, updated_at
            )
            VALUES ($1, 'COACH', 'Audit Addiction Coach', 'COACH_AUDIT_ADDICTION_ID',
                    $2, 'ACTIVE', 'STANDARD', $3::jsonb, $4, $4)
            ON CONFLICT (username) DO UPDATE SET
                role = 'COACH',
                name = EXCLUDED.name,
                hardware_id = EXCLUDED.hardware_id,
                profile_data = EXCLUDED.profile_data,
                updated_at = EXCLUDED.updated_at
            """,
            COACH,
            PASSWORD_HASH,
            json.dumps(coach_profile),
            now,
        )
        await conn.execute(
            """
            INSERT INTO users (
                username, role, name, hardware_id, password_hash,
                subscription_status, tier, profile_data, created_at, updated_at
            )
            VALUES ($1, 'CLIENT', 'Audit Addiction Client', 'CLIENT_AUDIT_ADDICTION_ID',
                    $2, 'ACTIVE', 'STANDARD', $3::jsonb, $4, $4)
            ON CONFLICT (username) DO UPDATE SET
                role = 'CLIENT',
                name = EXCLUDED.name,
                hardware_id = EXCLUDED.hardware_id,
                profile_data = EXCLUDED.profile_data,
                updated_at = EXCLUDED.updated_at
            """,
            CLIENT,
            PASSWORD_HASH,
            json.dumps(client_profile),
            now,
        )
        await conn.execute(
            """
            INSERT INTO coach_client_overrides (coach_user_id, client_user_id, focus_domain, notes)
            VALUES ($1, $2, 'sensitive_bridge_v1_4_e2e', 'audit_addiction_test_01')
            ON CONFLICT (coach_user_id, client_user_id) DO UPDATE SET
                focus_domain = EXCLUDED.focus_domain,
                notes = EXCLUDED.notes,
                updated_at = NOW()
            """,
            COACH,
            CLIENT,
        )
        await conn.execute(
            """
            INSERT INTO app_settings (setting_key, setting_value, description, updated_by)
            VALUES ('sensitive_bridge_master_enabled', 'true'::jsonb,
                    'Sensitive Bridge E2E master switch', 'audit_addiction_test_01')
            ON CONFLICT (setting_key) DO UPDATE SET
                setting_value = EXCLUDED.setting_value,
                updated_at = NOW(),
                updated_by = EXCLUDED.updated_by
            """
        )
        await conn.execute(
            """
            INSERT INTO sensitive_bridge_enrollment (
                user_id, cohort_label, gap_features_enabled, enrolled_by,
                last_modified_by, notes
            )
            VALUES ($1, 'pilot_5', $2::jsonb, 'audit_addiction_test_01',
                    'audit_addiction_test_01', 'synthetic v1.4 e2e')
            ON CONFLICT (user_id) DO UPDATE SET
                cohort_label = EXCLUDED.cohort_label,
                gap_features_enabled = EXCLUDED.gap_features_enabled,
                last_modified_at = NOW(),
                last_modified_by = EXCLUDED.last_modified_by,
                notes = EXCLUDED.notes
            """,
            CLIENT,
            json.dumps(V14_FLAGS),
        )


async def _exercise_api(pool) -> List[Dict[str, Any]]:
    from app.routers import sensitive_profile_api as api

    class State:
        db_pool = pool

    class App:
        state = State()

    class Req:
        app = App()

    principal = {
        "username": COACH,
        "user_id": COACH,
        "role": "COACH",
        "hardware_id": "COACH_AUDIT_ADDICTION_ID",
    }

    checks: List[Dict[str, Any]] = []
    checks.append(_check(
        bool(await api.add_part(
            CLIENT,
            api.PartRegistryCreate(
                part_name="The Sentinel",
                part_number=7,
                part_category="protector",
                addiction_link="gambling",
                description="Protects against shame spirals",
            ),
            Req(),
            principal,
        )),
        "parts_registry_create",
    ))
    checks.append(_check(
        bool(await api.set_gambling_status(
            CLIENT,
            api.AddictionBranchStatusUpdate(status="active", subtype="sportsbook"),
            Req(),
            principal,
        )),
        "gambling_status_set",
    ))
    checks.append(_check(
        bool(await api.set_sex_addiction_status(
            CLIENT,
            api.AddictionBranchStatusUpdate(status="active", subtype="compulsive_pornography"),
            Req(),
            principal,
        )),
        "sex_addiction_status_set",
    ))
    codeword_resp = await api.add_codeword(
        CLIENT,
        api.CodewordCreate(
            plaintext_codeword="blue lantern",
            codeword_type="innocuous_phrase",
            codeword_label="sentinel phrase",
            triggers_mandatory_reporting=True,
            disclosure_type="addict_part_speaking",
            part_name="The Sentinel",
            part_number=7,
            part_category="protector",
            addiction_link="gambling",
        ),
        Req(),
        principal,
    )
    checks.append(_check(
        bool(codeword_resp.get("part_linked")),
        "part_aware_codeword_create",
        {"hash_prefix": codeword_resp.get("hash_prefix")},
    ))
    row = await _fetchrow(
        pool,
        """
        SELECT disclosure_type, part_name, part_number, part_category, addiction_link
        FROM user_safety_codewords
        WHERE user_id = $1 AND codeword_hash LIKE $2 || '%'
        """,
        CLIENT,
        codeword_resp["hash_prefix"],
    )
    checks.append(_check(
        row is not None
        and row["disclosure_type"] == "addict_part_speaking"
        and row["part_name"] == "The Sentinel"
        and row["part_number"] == 7
        and row["addiction_link"] == "gambling",
        "part_aware_codeword_persisted",
        dict(row) if row else {},
    ))
    return checks


async def _exercise_bridge(pool) -> List[Dict[str, Any]]:
    from app.services.nate_checkin_agent import NateCheckInAgent
    from app.services.sensitive_alert_dispatcher import dispatch_sensitive_alert
    from app.services.sensitive_clinical_bridge import evaluate_disclosure

    checks: List[Dict[str, Any]] = []
    agent = NateCheckInAgent(pool)
    event = await agent.detect_codeword_disclosure(
        "I need to say blue lantern before I relapse.",
        CLIENT,
        session_id=SESSION_ID,
    )
    checks.append(_check(
        event is not None
        and event.part_name == "The Sentinel"
        and event.addiction_link == "gambling",
        "part_codeword_runtime_match",
        {
            "part_name": getattr(event, "part_name", None),
            "addiction_link": getattr(event, "addiction_link", None),
            "audit_event": getattr(event, "audit_event", None),
        },
    ))

    decision = await evaluate_disclosure(
        db_pool=pool,
        user_id=CLIENT,
        message="blue lantern. gambling and sexual compulsions are both active right now.",
        session_id=SESSION_ID,
        coach_id=COACH,
        nate_checkin_agent=agent,
    )
    audit = decision.audit_event or {}
    checks.append(_check(
        bool(audit.get("cross_addiction_active"))
        and bool(audit.get("cross_addiction_overlay_applied")),
        "cross_addiction_overlay_applied",
        {
            "active": audit.get("cross_addiction_active"),
            "branches": audit.get("cross_addiction_branch_labels"),
        },
    ))
    checks.append(_check(
        bool(audit.get("framework_lenses_applied")),
        "framework_lens_selected",
        {"lenses": audit.get("framework_lenses_applied")},
    ))

    receipt = await dispatch_sensitive_alert(
        db_pool=pool,
        client_username=CLIENT,
        coach_username=COACH,
        risk_level="critical",
        reason="Synthetic v1.4 crisis warm handoff",
        keywords=["audit_addiction_test_01", "gambling"],
        session_id=SESSION_ID,
        raw_context=(
            "Client mentions 555-222-9999, audit@example.com, "
            "and hotline 1-800-662-4357."
        ),
        alert_type="crisis_warm_handoff",
    )
    event_row = await _fetchrow(
        pool,
        "SELECT resolution_notes FROM crisis_events WHERE id = $1",
        receipt.get("event_id") or 0,
    )
    notes = event_row["resolution_notes"] if event_row else ""
    checks.append(_check(
        bool(receipt.get("event_id")) and "[phone]" in notes
        and "[email]" in notes and "1-800-662-4357" in notes,
        "alert_dispatch_redacts_pii_preserves_hotline",
        {"receipt": receipt, "resolution_notes": notes},
    ))
    return checks


async def _insert_telemetry(pool) -> List[Dict[str, Any]]:
    rows = []
    for event_type in TELEMETRY_TYPES:
        row = await _fetchrow(
            pool,
            """
            INSERT INTO sensitive_bridge_log (
                user_id, session_id, event_type, event_severity, payload_json,
                decision_summary, recorded_by, access_classification, pii_screened_at
            )
            VALUES ($1, $2, $3, 'info', $4::jsonb, $5::jsonb,
                    'audit_addiction_test_01', 'clinician_and_admin', NOW())
            RETURNING id, event_type
            """,
            CLIENT,
            SESSION_ID,
            event_type,
            json.dumps({"synthetic": True, "event_type": event_type}),
            json.dumps({"test": "audit_addiction_test_01"}),
        )
        rows.append(dict(row))
    seen = await _fetchval(
        pool,
        """
        SELECT COUNT(DISTINCT event_type)
        FROM sensitive_bridge_log
        WHERE user_id = $1 AND session_id = $2 AND event_type = ANY($3::text[])
        """,
        CLIENT,
        SESSION_ID,
        list(TELEMETRY_TYPES),
    )
    return [_check(
        int(seen or 0) == len(TELEMETRY_TYPES),
        "all_14_v1_4_telemetry_types_inserted",
        {"expected": len(TELEMETRY_TYPES), "seen": int(seen or 0), "rows": rows},
    )]


async def _cleanup(pool) -> None:
    async with pool.acquire() as conn:
        # sensitive_bridge_log is immutable for 7-year clinical retention.
        # Do not delete synthetic rows; SESSION_ID makes each run distinct.
        await conn.execute("DELETE FROM crisis_events WHERE user_name = $1", CLIENT)
        await conn.execute("DELETE FROM coach_escalation_notifications WHERE coach_username = $1", COACH)
        await conn.execute("DELETE FROM user_safety_codewords WHERE user_id = $1", CLIENT)
        await conn.execute("DELETE FROM user_parts_registry WHERE user_id = $1", CLIENT)
        await conn.execute("DELETE FROM addiction_status_history WHERE user_id = $1", CLIENT)
        await conn.execute("DELETE FROM cross_addiction_transfer_events WHERE user_id = $1", CLIENT)
        await conn.execute("DELETE FROM sensitive_bridge_enrollment WHERE user_id = $1", CLIENT)
        await conn.execute("DELETE FROM coach_client_overrides WHERE coach_user_id = $1 OR client_user_id = $2", COACH, CLIENT)
        # Keep synthetic users: retained sensitive_bridge_log rows FK to users(username).


async def main() -> int:
    keep = "--keep" in sys.argv
    pool = await asyncpg.create_pool(_dsn(), min_size=1, max_size=3)
    checks: List[Dict[str, Any]] = []
    try:
        await _cleanup(pool)
        await _setup(pool)
        checks.extend(await _exercise_api(pool))
        checks.extend(await _exercise_bridge(pool))
        checks.extend(await _insert_telemetry(pool))
    finally:
        if not keep:
            await _cleanup(pool)
        await pool.close()

    ok = all(c["ok"] for c in checks)
    print(json.dumps(
        {
            "test": "audit_addiction_test_01",
            "ok": ok,
            "checks": checks,
            "kept_rows": keep,
        },
        indent=2,
        default=str,
    ))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
