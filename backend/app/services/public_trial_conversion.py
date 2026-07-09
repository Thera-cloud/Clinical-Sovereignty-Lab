"""Public Trial Funnel — Phase 3 conversion helper.

Extracted from `register_new_user()` (a protected file) to keep the bridge
diff small. Best-effort merge of anonymous trial history into a newly
created `TRIAL_FREE` account. Match priority: `trial_token` (survives
cross-device/cross-browser/delayed-organic signups, see `public_trial_leads`)
then `device_uuid_hash` (same-device click-through fallback), else no match.

Signup-never-fail guarantee: every DB operation here is wrapped so that any
exception degrades to `{"merged": False, "reason": "exception"}` — the
caller (`register_new_user`) treats that identically to "no match" and
proceeds with normal successful account creation regardless. This module
must never be able to fail a registration.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def compute_device_uuid_hash(client_uuid: str) -> str:
    """Mirrors public_trial_gate.compute_device_uuid_hash — duplicated here
    (not imported) so this module has zero dependency on the trial-turn gate
    module; it only needs the hash function, not any trial-gate state."""
    return hashlib.sha256((client_uuid or "").encode("utf-8")).hexdigest()


async def try_merge_trial_data(
    db_pool,
    device_fingerprint: Optional[str],
    trial_token: Optional[str],
    new_username: str,
) -> Dict[str, Any]:
    """Best-effort merge. Never raises. Returns:
      {"merged": bool, "via": "trial_token"|"device_uuid_hash"|None, "reason": str|None}
    """
    if not db_pool:
        return {"merged": False, "via": None, "reason": "no_db_pool"}
    if not new_username:
        return {"merged": False, "via": None, "reason": "no_username"}

    device_fingerprint = (device_fingerprint or "").strip()
    trial_token = (trial_token or "").strip()

    try:
        async with db_pool.acquire() as conn:
            device_uuid_hash: Optional[str] = None
            matched_via: Optional[str] = None

            # Priority 1: trial_token via public_trial_leads (cross-device path).
            # Deliberately NOT filtering on unsubscribed_at — see Phase 3 plan note:
            # unsubscribing from follow-up email is a separate consent from wanting
            # the conversation history merged.
            if trial_token:
                token_hash = hashlib.sha256(trial_token.encode("utf-8")).hexdigest()
                lead = await conn.fetchrow(
                    "SELECT device_uuid_hash FROM public_trial_leads "
                    "WHERE token_hash = $1 AND expires_at > NOW()",
                    token_hash,
                )
                if lead and lead["device_uuid_hash"]:
                    device_uuid_hash = lead["device_uuid_hash"]
                    matched_via = "trial_token"
                    await conn.execute(
                        "UPDATE public_trial_leads SET converted = TRUE, "
                        "converted_username = $1, converted_at = NOW() WHERE token_hash = $2",
                        new_username, token_hash,
                    )

            # Priority 2 (fallback): device_uuid_hash computed from the raw
            # client UUID. Gap 1 fix: never recompute the ip|ua composite here —
            # device_uuid_hash is derived from the UUID alone, the one component
            # that survives across the trial session and the signup session.
            if not device_uuid_hash and device_fingerprint:
                device_uuid_hash = compute_device_uuid_hash(device_fingerprint)
                matched_via = "device_uuid_hash"

            if not device_uuid_hash:
                return {"merged": False, "via": None, "reason": "no_identifier"}

            row = await conn.fetchrow(
                "SELECT trial_history FROM public_summon_usage WHERE device_uuid_hash = $1",
                device_uuid_hash,
            )
            if not row:
                return {"merged": False, "via": matched_via, "reason": "no_row_match"}

            history = row["trial_history"]
            if isinstance(history, str):
                try:
                    history = json.loads(history)
                except Exception:
                    history = []
            history = history or []

            session_id = f"trial_{device_uuid_hash[:8]}"
            valid_pairs: list = []
            if history:
                # Bug fix: Postgres NOW() is frozen for the whole transaction, so a
                # bare INSERT loop gives every merged row the SAME created_at. Recall
                # queries elsewhere (`ORDER BY created_at DESC LIMIT n`) then return an
                # arbitrary subset of tied rows — Nate "forgets" part of the trial
                # chat non-deterministically. Space rows 1s apart, oldest→newest, so
                # chronological order and recency-based LIMITs behave correctly.
                valid_pairs = [
                    ((p.get("user") or "").strip(), (p.get("assistant") or "").strip())
                    for p in history if isinstance(p, dict)
                ]
                valid_pairs = [(u, a) for u, a in valid_pairs if u or a]
                n = len(valid_pairs)
                merge_now = datetime.now(timezone.utc)
                async with conn.transaction():
                    for idx, (user_text, ai_text) in enumerate(valid_pairs):
                        row_ts = merge_now - timedelta(seconds=(n - 1 - idx))
                        await conn.execute(
                            """
                            INSERT INTO conversation_history
                                (user_id, session_id, user_text, ai_text, metadata, created_at)
                            VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                            """,
                            new_username, session_id, user_text, ai_text,
                            json.dumps({"source": "public_trial_merge", "via": matched_via}),
                            row_ts,
                        )

            await conn.execute(
                """
                UPDATE public_summon_usage
                SET converted = TRUE, converted_username = $1, converted_at = NOW(),
                    trial_history = '[]'::jsonb
                WHERE device_uuid_hash = $2
                """,
                new_username, device_uuid_hash,
            )

            # QUANTUM-CRYSTAL-ARCH: vault + crystal ingestion (fire-and-forget; never blocks signup)
            if history and valid_pairs:
                try:
                    from app.services.trial_merge_ingestion import schedule_trial_merge_ingestion
                    schedule_trial_merge_ingestion(
                        db_pool,
                        username=new_username,
                        valid_pairs=valid_pairs,
                        session_id=session_id,
                        matched_via=matched_via or "",
                    )
                except Exception as sched_err:
                    logger.warning(
                        "public_trial_conversion: ingestion schedule failed for %s: %s",
                        new_username, sched_err,
                    )

            return {"merged": True, "via": matched_via, "reason": None}
    except Exception as e:
        logger.warning(
            "public_trial_conversion: merge failed for %s, continuing registration: %s",
            new_username, e,
        )
        return {"merged": False, "via": None, "reason": "exception"}


async def check_registration_spike(db_pool) -> None:
    """Fire-and-forget: compares today's TRIAL_FREE registration count against
    the trailing 7-day daily average and logs a WARNING if it exceeds 3x.
    Never raises — this is observability only, never a gate on registration."""
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            today_count = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE registration_type = 'TRIAL_FREE' "
                "AND created_at >= date_trunc('day', NOW())"
            )
            baseline = await conn.fetchval(
                "SELECT COUNT(*)::float / 7 FROM users WHERE registration_type = 'TRIAL_FREE' "
                "AND created_at >= NOW() - INTERVAL '7 days' AND created_at < date_trunc('day', NOW())"
            )
            baseline = baseline or 0.0
            if baseline > 0 and today_count > baseline * 3:
                logger.warning(
                    "public_trial_conversion: TRIAL_FREE registration spike — "
                    "today=%s vs 7-day baseline avg=%.1f (>3x)",
                    today_count, baseline,
                )
            elif baseline == 0 and today_count > 15:
                # No baseline yet (new feature) — use an absolute floor so a
                # scripted burst on day one still surfaces in logs.
                logger.warning(
                    "public_trial_conversion: TRIAL_FREE registrations today=%s "
                    "with no established baseline yet (floor=15)",
                    today_count,
                )
    except Exception as e:
        logger.warning("public_trial_conversion: spike check failed (non-fatal): %s", e)
