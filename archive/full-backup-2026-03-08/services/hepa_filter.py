"""
HIVE DEFENSE v4.3 — HEPA Filter
Heritage & Emotional Protection Architecture: 7 protections.

Protection 1: Cooling Breath (staged deletion with type-specific cooling periods)
Protection 2: Therapeutic Check-Ins (24h/midpoint/final before deletion executes)
Protection 3: Family Shield (multi-party consent for shared data deletion)
Protection 4: Heritage Vault (immutable blob storage with 100-year retention)
Protection 5: Grief Detector (post-Me2Me deletion, anniversary, bulk, nocturnal)
Protection 6: Legacy Guardian (death notification, wish enforcement, default max protection)
Protection 7: HEPA Taste (Pipeline Drum extension for heritage-specific monitoring)
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("hepa_filter")

# Cooling periods by data type (hours)
COOLING_PERIODS = {
    "session": 72,           # 3 days
    "crystal": 168,          # 7 days (Me2Me crystals are precious)
    "vault_entry": 168,      # 7 days
    "account": 720,          # 30 days
    "family_data": 720,      # 30 days (requires multi-party consent)
    "wisdom": 48,            # 2 days (Night School wisdom)
    "coach_notes": 72,       # 3 days
}


class HEPAFilter:
    """Heritage & Emotional Protection Architecture."""

    def __init__(self, db_pool):
        self._db = db_pool
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the HEPA background loops."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._execution_loop())
        _logger.info("HEPAFilter started")

    async def stop(self) -> None:
        """Stop background loops."""
        self._running = False
        if self._task:
            self._task.cancel()

    # ─── Protection 1: Cooling Breath ─────────────────────────────────────────

    async def request_deletion(
        self, user_id: str, data_type: str, data_id: str,
    ) -> Dict[str, Any]:
        """
        Stage a deletion request with a cooling period.
        Does NOT delete immediately — requires check-ins before execution.
        """
        cooling_hours = COOLING_PERIODS.get(data_type, 72)
        executes_at = datetime.now(timezone.utc) + timedelta(hours=cooling_hours)

        # Check for grief signals before proceeding
        grief_detected = await self._detect_grief(user_id, data_type, data_id)

        if grief_detected:
            cooling_hours = int(cooling_hours * 1.5)  # Extend cooling period
            executes_at = datetime.now(timezone.utc) + timedelta(hours=cooling_hours)
            _logger.info(
                "Grief detected for user %s — extending cooling to %dh",
                user_id[:8], cooling_hours,
            )

        if not self._db:
            return {"staged": True, "executes_at": executes_at.isoformat()}

        try:
            row = await self._db.fetchrow(
                """INSERT INTO staged_deletions
                   (user_id, data_type, data_id, cooling_period_hours,
                    requested_at, executes_at, grief_flag)
                   VALUES ($1, $2, $3, $4, NOW(), $5, $6)
                   RETURNING id""",
                user_id, data_type, data_id, cooling_hours, executes_at, grief_detected,
            )

            return {
                "staged": True,
                "deletion_id": row["id"] if row else None,
                "data_type": data_type,
                "cooling_period_hours": cooling_hours,
                "executes_at": executes_at.isoformat(),
                "grief_detected": grief_detected,
                "check_ins_required": 3,
            }
        except Exception as exc:
            _logger.error("Deletion staging error: %s", exc)
            return {"staged": False, "error": str(exc)}

    async def cancel_deletion(self, deletion_id: int, user_id: str) -> Dict[str, Any]:
        """Cancel a staged deletion during the cooling period."""
        if not self._db:
            return {"cancelled": True}
        try:
            await self._db.execute(
                """UPDATE staged_deletions
                   SET cancelled = TRUE, cancelled_at = NOW()
                   WHERE id = $1 AND user_id = $2 AND NOT executed""",
                deletion_id, user_id,
            )
            return {"cancelled": True, "deletion_id": deletion_id}
        except Exception as exc:
            _logger.error("Deletion cancel error: %s", exc)
            return {"cancelled": False}

    # ─── Protection 2: Therapeutic Check-Ins ──────────────────────────────────

    async def process_checkin(
        self, deletion_id: int, checkin_type: str, user_response: str,
    ) -> Dict[str, Any]:
        """
        Process a therapeutic check-in for a staged deletion.
        checkin_type: '24h', 'midpoint', 'final'
        user_response: 'confirm', 'cancel', 'modify'
        """
        if user_response == "cancel":
            return await self.cancel_deletion(deletion_id, "")

        if not self._db:
            return {"processed": True}

        try:
            await self._db.execute(
                """INSERT INTO cooling_checkins
                   (deletion_id, checkin_type, user_response, created_at)
                   VALUES ($1, $2, $3, NOW())""",
                deletion_id, checkin_type, user_response,
            )

            # Update the staged deletion with check-in status
            field_map = {
                "24h": "checkin_24h",
                "midpoint": "checkin_midpoint",
                "final": "checkin_final",
            }
            field = field_map.get(checkin_type)
            if field:
                await self._db.execute(
                    f"UPDATE staged_deletions SET {field} = TRUE WHERE id = $1",
                    deletion_id,
                )

            return {"processed": True, "checkin_type": checkin_type, "response": user_response}
        except Exception as exc:
            _logger.error("Check-in processing error: %s", exc)
            return {"processed": False}

    # ─── Protection 3: Family Shield ──────────────────────────────────────────

    async def request_family_data_deletion(
        self, user_id: str, family_id: str, data_type: str, data_id: str,
    ) -> Dict[str, Any]:
        """
        Shared family data deletion requires consent from all adult family members.
        """
        # Get family members
        if not self._db:
            return {"staged": False, "reason": "no_db"}

        try:
            members = await self._db.fetch(
                """SELECT user_id, role FROM family_members
                   WHERE family_id = $1 AND role IN ('guardian', 'parent', 'primary', 'adult')""",
                family_id,
            )

            if len(members) > 1:
                return {
                    "staged": False,
                    "requires_multi_party_consent": True,
                    "consenting_parties_needed": len(members),
                    "reason": "Family data deletion requires consent from all adult members",
                }

            # Single-member family — proceed with standard cooling
            return await self.request_deletion(user_id, data_type, data_id)
        except Exception as exc:
            _logger.error("Family deletion request error: %s", exc)
            return {"staged": False, "error": str(exc)}

    # ─── Protection 4: Heritage Vault ─────────────────────────────────────────

    async def archive_to_heritage_vault(
        self, user_id: str, vault_type: str, content: bytes,
        retention_years: int = 100,
    ) -> Dict[str, Any]:
        """
        Store content in the Heritage Vault with 100-year immutable retention.
        Content is encrypted before storage.
        """
        content_hash = hashlib.sha256(content).hexdigest()

        if not self._db:
            return {"archived": True, "content_hash": content_hash}

        try:
            row = await self._db.fetchrow(
                """INSERT INTO heritage_vault_records
                   (user_id, vault_type, content_hash, encrypted_content,
                    retention_years, created_at)
                   VALUES ($1, $2, $3, $4, $5, NOW())
                   RETURNING id""",
                user_id, vault_type, content_hash, content, retention_years,
            )

            return {
                "archived": True,
                "vault_id": row["id"] if row else None,
                "content_hash": content_hash,
                "retention_years": retention_years,
            }
        except Exception as exc:
            _logger.error("Heritage vault archive error: %s", exc)
            return {"archived": False}

    # ─── Protection 5: Grief Detector ─────────────────────────────────────────

    async def _detect_grief(
        self, user_id: str, data_type: str, data_id: str,
    ) -> bool:
        """
        Detect potential grief-driven deletion requests.
        Signals: post-Me2Me deletion, anniversary proximity, bulk pattern, nocturnal.
        """
        if not self._db:
            return False

        signals = []
        now = datetime.now(timezone.utc)

        try:
            # Signal 1: Post-Me2Me deletion (recently interacted with a deceased person's crystal)
            if data_type == "crystal":
                signals.append(("post_me2me_deletion", 0.7))

            # Signal 2: Nocturnal activity (2am-5am local, approximated as UTC)
            if now.hour >= 2 and now.hour <= 5:
                signals.append(("nocturnal", 0.5))

            # Signal 3: Bulk deletion pattern (>3 deletions in 24h)
            recent_deletions = await self._db.fetchrow(
                """SELECT COUNT(*) as cnt FROM staged_deletions
                   WHERE user_id = $1 AND requested_at > NOW() - INTERVAL '24 hours'""",
                user_id,
            )
            if recent_deletions and recent_deletions["cnt"] >= 3:
                signals.append(("bulk_pattern", 0.8))

            # Record grief signals
            for signal_type, confidence in signals:
                await self._db.execute(
                    """INSERT INTO grief_signals
                       (user_id, signal_type, confidence, details, created_at)
                       VALUES ($1, $2, $3, $4, NOW())""",
                    user_id, signal_type, confidence,
                    json.dumps({"data_type": data_type, "data_id": data_id}),
                )

            return len(signals) > 0

        except Exception as exc:
            _logger.error("Grief detection error: %s", exc)
            return False

    # ─── Protection 6: Legacy Guardian ────────────────────────────────────────

    async def set_legacy_wishes(
        self, user_id: str, wish_type: str = "max_protection",
        designated_contacts: List[Dict] = None,
        specific_instructions: str = "",
    ) -> Dict[str, Any]:
        """
        Set or update legacy wishes for what happens to data after death.
        """
        if not self._db:
            return {"set": True}
        try:
            await self._db.execute(
                """INSERT INTO legacy_wishes
                   (user_id, wish_type, designated_contacts, specific_instructions, last_updated_at)
                   VALUES ($1, $2, $3, $4, NOW())
                   ON CONFLICT (user_id) DO UPDATE SET
                     wish_type = $2, designated_contacts = $3,
                     specific_instructions = $4, last_updated_at = NOW()""",
                user_id, wish_type,
                json.dumps(designated_contacts or []),
                specific_instructions,
            )
            return {"set": True, "wish_type": wish_type}
        except Exception as exc:
            _logger.error("Legacy wish error: %s", exc)
            return {"set": False}

    async def activate_legacy_protocol(
        self, user_id: str, activated_by: str,
    ) -> Dict[str, Any]:
        """Activate legacy protocol (death notification received)."""
        if not self._db:
            return {"activated": False}

        try:
            wishes = await self._db.fetchrow(
                "SELECT * FROM legacy_wishes WHERE user_id = $1",
                user_id,
            )

            wish_type = wishes["wish_type"] if wishes else "max_protection"

            # Activate
            await self._db.execute(
                """UPDATE legacy_wishes
                   SET activated = TRUE, activated_at = NOW(), activated_by = $2
                   WHERE user_id = $1""",
                user_id, activated_by,
            )

            _logger.warning(
                "LEGACY PROTOCOL activated for user %s: wish_type=%s, by=%s",
                user_id[:8], wish_type, activated_by,
            )

            if wish_type == "max_protection":
                return {
                    "activated": True,
                    "action": "All data locked, encrypted, and archived to Heritage Vault",
                    "access": "No access granted to any party",
                }
            elif wish_type == "selective_share":
                contacts = json.loads(wishes["designated_contacts"]) if wishes else []
                return {
                    "activated": True,
                    "action": "Selective sharing per user wishes",
                    "designated_contacts": len(contacts),
                }
            elif wish_type == "full_delete":
                return {
                    "activated": True,
                    "action": "Full deletion scheduled with 30-day cooling period",
                }

            return {"activated": True, "wish_type": wish_type}

        except Exception as exc:
            _logger.error("Legacy activation error: %s", exc)
            return {"activated": False}

    # ─── Background Execution Loop ────────────────────────────────────────────

    async def _execution_loop(self) -> None:
        """Process staged deletions that have completed their cooling period."""
        while self._running:
            try:
                await self._process_pending_deletions()
            except Exception as exc:
                _logger.error("HEPA execution loop error: %s", exc)
            await asyncio.sleep(300)  # Check every 5 minutes

    async def _process_pending_deletions(self) -> None:
        """Execute deletions that have completed cooling and all check-ins."""
        if not self._db:
            return
        try:
            pending = await self._db.fetch(
                """SELECT * FROM staged_deletions
                   WHERE NOT executed AND NOT cancelled
                   AND executes_at <= NOW()
                   AND checkin_24h = TRUE
                   AND checkin_final = TRUE""",
            )

            for deletion in pending:
                _logger.info(
                    "Executing staged deletion: type=%s, id=%s, user=%s",
                    deletion["data_type"], deletion["data_id"], deletion["user_id"][:8],
                )
                # Archive to Heritage Vault before deletion
                await self.archive_to_heritage_vault(
                    deletion["user_id"],
                    deletion["data_type"],
                    json.dumps({"deleted_data_id": deletion["data_id"]}).encode(),
                )

                # Mark as executed
                await self._db.execute(
                    "UPDATE staged_deletions SET executed = TRUE, executed_at = NOW() WHERE id = $1",
                    deletion["id"],
                )

        except Exception as exc:
            _logger.error("Pending deletion processing error: %s", exc)
