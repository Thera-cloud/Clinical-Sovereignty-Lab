"""Growth claims registry + publisher gate + retract cascade (M2 / W11 / W12).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("growth_claims")


def _claim_id(text: str, artifact_uri: str = "") -> str:
    return hashlib.sha256(f"{text}|{artifact_uri}".encode()).hexdigest()[:24]


async def upsert_claim(
    db_pool,
    *,
    claim_text: str,
    evidence_class: str,
    artifact_uri: str = "",
    envelope_id: Optional[str] = None,
    ttl_hours: int = 168,
    claim_id: Optional[str] = None,
) -> Optional[str]:
    if not db_pool or not claim_text:
        return None
    cid = claim_id or _claim_id(claim_text, artifact_uri)
    expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    # QUANTUM-CRYSTAL-ARCH — W7 marketing dual-write into outcome_envelope
    env_id = envelope_id
    if not env_id:
        try:
            from app.services.ln7_outcome_envelope import write_envelope

            env_id = await write_envelope(
                db_pool,
                loop_name="marketing",
                event_kind="growth_claim",
                domain_tag="marketing",
                source_node="growth_claims",
                attribution={"claim_id": cid, "evidence_class": evidence_class},
                metrics={"artifact_uri": artifact_uri or "", "ttl_hours": ttl_hours},
                provenance={"claim_text_sha": _claim_id(claim_text, "")},
            )
        except Exception as e:
            logger.warning("claim envelope dual-write: %s", e)
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO growth_claims (
                    claim_id, claim_text, evidence_class, artifact_uri,
                    envelope_id, expires_at, status, updated_at
                ) VALUES ($1, $2, $3, $4, $5::uuid, $6, 'active', NOW())
                ON CONFLICT (claim_id) DO UPDATE SET
                    claim_text = EXCLUDED.claim_text,
                    evidence_class = EXCLUDED.evidence_class,
                    artifact_uri = EXCLUDED.artifact_uri,
                    envelope_id = COALESCE(EXCLUDED.envelope_id, growth_claims.envelope_id),
                    expires_at = EXCLUDED.expires_at,
                    status = 'active',
                    updated_at = NOW()
                """,
                cid,
                claim_text,
                evidence_class,
                artifact_uri or None,
                env_id,
                expires,
            )
        return cid
    except Exception as e:
        logger.warning("upsert_claim failed: %s", e)
        return None


async def assert_claims_publishable(
    db_pool,
    claim_ids: Sequence[str],
    *,
    channel: str = "email",
) -> Dict[str, Any]:
    """Refuse publish if any claim missing/expired/short_horizon on unretractable channel."""
    if not claim_ids:
        return {"ok": False, "error": "missing_claim_ids"}
    if not db_pool:
        return {"ok": False, "error": "no_db"}
    unretractable = channel in ("email", "syndicate", "syndicated")
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT claim_id, status, evidence_class, expires_at
                FROM growth_claims
                WHERE claim_id = ANY($1::text[])
                """,
                list(claim_ids),
            )
        found = {r["claim_id"]: dict(r) for r in rows}
        for cid in claim_ids:
            row = found.get(cid)
            if not row:
                return {"ok": False, "error": "claim_missing", "claim_id": cid}
            if row["status"] != "active":
                return {"ok": False, "error": "claim_not_active", "claim_id": cid}
            if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc):
                return {"ok": False, "error": "claim_expired", "claim_id": cid}
            if unretractable and row["evidence_class"] == "short_horizon":
                return {
                    "ok": False,
                    "error": "short_horizon_on_unretractable",
                    "claim_id": cid,
                }
        return {"ok": True, "n": len(claim_ids)}
    except Exception as e:
        logger.warning("assert_claims_publishable failed: %s", e)
        return {"ok": False, "error": str(e)}


async def retract_claim(db_pool, claim_id: str, *, reason: str = "") -> bool:
    if not db_pool or not claim_id:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE growth_claims
                SET status = 'retracted', updated_at = NOW(),
                    surface_map_json = surface_map_json || $2::jsonb
                WHERE claim_id = $1
                """,
                claim_id,
                json.dumps({"retract_reason": reason}),
            )
        await retract_surfaces(db_pool, claim_id)
        return True
    except Exception as e:
        logger.warning("retract_claim failed: %s", e)
        return False


async def retract_surfaces(db_pool, claim_id: str) -> Dict[str, Any]:
    """W12: update owned surfaces from locked retract_surface_map.json."""
    from app.services.ln7_frozen_config import load_json

    smap = load_json("retract_surface_map.json", {}) or {}
    actions = []
    try:
        async with db_pool.acquire() as conn:
            for surface in smap.get("surfaces") or []:
                sid = surface.get("id")
                if sid == "skyeye_content_queue":
                    await conn.execute(
                        """
                        UPDATE skyeye_content_queue
                        SET status = 'cancelled'
                        WHERE status = ANY($1::text[])
                          AND (
                            content ILIKE '%' || $2 || '%'
                            OR (metadata->>'claim_ids') ILIKE '%' || $2 || '%'
                          )
                        """,
                        surface.get("statuses") or ["pending", "scheduled"],
                        claim_id,
                    )
                    actions.append("skyeye_content_queue_cancel")
                elif sid == "directory_profile_fields":
                    # Clear growth claim refs from profile_data (JSONB patch)
                    await conn.execute(
                        """
                        UPDATE users
                        SET profile_data = (
                            COALESCE(profile_data, '{}'::jsonb)
                            - 'growth_claim_ids'
                            - 'growth_claim_text'
                            - 'directory_growth_blurb'
                        )
                        WHERE profile_data::text ILIKE '%' || $1 || '%'
                        """,
                        claim_id,
                    )
                    actions.append("directory_profile_fields_clear")
                elif sid == "sovereign_command_growth":
                    # Flag for dashboard grep/rewrite job (no silent HTML rewrite)
                    await conn.execute(
                        """
                        INSERT INTO skyeye_activity (type, content, platform, created_at)
                        VALUES (
                            'growth_claim_retract_flag',
                            $1::text,
                            'growth',
                            NOW()
                        )
                        """,
                        json.dumps(
                            {
                                "claim_id": claim_id,
                                "action": "grep_and_flag",
                                "paths": surface.get("paths") or [],
                            }
                        ),
                    )
                    actions.append("sovereign_command_growth_flag")
    except Exception as e:
        logger.warning("retract_surfaces failed: %s", e)
        return {"ok": False, "actions": actions, "error": str(e)}
    return {"ok": True, "actions": actions}


async def derive_from_template(
    db_pool,
    template_id: str,
    *,
    fields: Dict[str, Any],
    artifact_uri: str = "",
    envelope_id: Optional[str] = None,
) -> Optional[str]:
    from app.services.ln7_frozen_config import load_json

    templates = (load_json("claim_templates.json", {}) or {}).get("templates") or []
    tmpl = next((t for t in templates if t.get("id") == template_id), None)
    if not tmpl:
        return None
    text = str(tmpl.get("text") or "").format(**fields)
    return await upsert_claim(
        db_pool,
        claim_text=text,
        evidence_class=str(tmpl.get("evidence_class") or "short_horizon"),
        artifact_uri=artifact_uri,
        envelope_id=envelope_id,
        ttl_hours=int(tmpl.get("ttl_hours") or 168),
    )
