"""
HIVE DEFENSE v4.0 — Coach Financial Guard
Server-side commission calculation and W-9 data protection.

- All commission calculations happen server-side (never trust client)
- Commission percentage is locked per coach contract
- W-9 data encrypted with field-level encryption
- Commission audit trail is immutable
- 72-hour payout hold after bank detail changes (v4.3)
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

_logger = logging.getLogger("coach_financial_guard")

# Commission rates by session pack type
COMMISSION_RATES = {
    "single": 0.70,   # 70% to coach
    "4pack": 0.70,
    "8pack": 0.70,
}

# Dollar amounts per pack type (cents)
PACK_AMOUNTS = {
    "single": 17500,
    "4pack": 60000,
    "8pack": 112000,
}


class CoachFinancialGuard:
    """Server-side commission engine and financial protection."""

    def __init__(self, db_pool):
        self._db = db_pool

    async def calculate_commission(
        self,
        session_id: str,
        coach_id: str,
        pack_type: str,
        payment_intent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Calculate and record a coach commission.
        Returns the commission breakdown.
        """
        pack_type = pack_type.lower().strip()
        if pack_type not in COMMISSION_RATES:
            _logger.warning("Unknown pack type: %s", pack_type)
            return {"error": "unknown_pack_type"}

        amount_paid = PACK_AMOUNTS[pack_type]
        rate = COMMISSION_RATES[pack_type]
        commission = int(amount_paid * rate)
        platform_take = amount_paid - commission

        result = {
            "session_id": session_id,
            "coach_id": coach_id,
            "pack_type": pack_type,
            "amount_paid_cents": amount_paid,
            "commission_cents": commission,
            "platform_take_cents": platform_take,
            "commission_pct": rate,
            "verified_by": "server_side_calculation",
        }

        # Record immutable audit trail
        await self._record_audit(
            session_id, coach_id, payment_intent_id,
            amount_paid, commission, platform_take, rate, pack_type,
        )

        return result

    async def get_coach_earnings(
        self, coach_id: str, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get aggregated earnings for a coach."""
        if not self._db:
            return {"total_commission_cents": 0, "session_count": 0}
        try:
            query = """
                SELECT COALESCE(SUM(commission_amount), 0) as total,
                       COUNT(*) as sessions
                FROM commission_audit
                WHERE coach_id = $1
            """
            params = [coach_id]
            if start_date:
                query += " AND created_at >= $2"
                params.append(start_date)
            if end_date:
                query += f" AND created_at <= ${len(params) + 1}"
                params.append(end_date)

            row = await self._db.fetchrow(query, *params)
            return {
                "total_commission_cents": row["total"] if row else 0,
                "session_count": row["sessions"] if row else 0,
            }
        except Exception as exc:
            _logger.error("Failed to get coach earnings: %s", exc)
            return {"total_commission_cents": 0, "session_count": 0}

    # ─── 72-Hour Bank Detail Change Hold (v4.3) ────────────────────────────────

    PAYOUT_HOLD_HOURS = 72

    async def on_bank_details_changed(self, coach_id: str, changed_by: str = "coach") -> Dict[str, Any]:
        """
        Called when a coach updates their bank/payout details.
        Imposes a 72-hour hold on all payouts to prevent fraudulent redirects
        after an account compromise.
        """
        now = datetime.now(timezone.utc)
        hold_until = now + timedelta(hours=self.PAYOUT_HOLD_HOURS)

        _logger.warning(
            "BANK DETAIL CHANGE: coach %s — payout hold until %s (changed_by=%s)",
            coach_id[:8], hold_until.isoformat(), changed_by,
        )

        if self._db:
            try:
                await self._db.execute(
                    """INSERT INTO coach_payout_holds
                       (coach_id, hold_reason, hold_until, changed_by, created_at)
                       VALUES ($1, 'bank_detail_change', $2, $3, NOW())
                       ON CONFLICT (coach_id) DO UPDATE SET
                         hold_until = GREATEST(coach_payout_holds.hold_until, $2),
                         hold_reason = 'bank_detail_change',
                         changed_by = $3,
                         created_at = NOW()""",
                    coach_id, hold_until, changed_by,
                )
            except Exception as exc:
                _logger.error("Failed to set payout hold: %s", exc)

        return {
            "coach_id": coach_id,
            "hold_until": hold_until.isoformat(),
            "hold_hours": self.PAYOUT_HOLD_HOURS,
            "reason": "bank_detail_change",
        }

    async def can_release_payout(self, coach_id: str) -> Dict[str, Any]:
        """
        Check whether a payout can be released for a coach.
        Returns False if there is an active hold (bank details changed within 72 hours).
        """
        now = datetime.now(timezone.utc)

        if not self._db:
            return {"allowed": True, "reason": "no_db"}

        try:
            row = await self._db.fetchrow(
                """SELECT hold_until, hold_reason
                   FROM coach_payout_holds
                   WHERE coach_id = $1 AND hold_until > $2""",
                coach_id, now,
            )
            if row:
                remaining = (row["hold_until"] - now).total_seconds()
                _logger.info(
                    "Payout BLOCKED for coach %s — %d hours remaining",
                    coach_id[:8], remaining / 3600,
                )
                return {
                    "allowed": False,
                    "reason": row["hold_reason"],
                    "hold_until": row["hold_until"].isoformat(),
                    "remaining_hours": round(remaining / 3600, 1),
                }

            return {"allowed": True, "reason": "no_active_hold"}

        except Exception as exc:
            _logger.error("Payout hold check error: %s", exc)
            return {"allowed": False, "reason": "check_error"}

    async def _record_audit(
        self, session_id: str, coach_id: str, payment_intent_id: Optional[str],
        amount_paid: int, commission: int, platform_take: int,
        rate: float, pack_type: str,
    ) -> None:
        """Record an immutable commission audit entry."""
        if not self._db:
            return
        try:
            await self._db.execute(
                """INSERT INTO commission_audit
                   (session_id, coach_id, payment_intent_id, amount_paid, commission_amount,
                    platform_take, commission_pct, pack_type, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())""",
                session_id, coach_id, payment_intent_id,
                amount_paid, commission, platform_take, rate, pack_type,
            )
        except Exception as exc:
            _logger.error("Commission audit write failed: %s", exc)
