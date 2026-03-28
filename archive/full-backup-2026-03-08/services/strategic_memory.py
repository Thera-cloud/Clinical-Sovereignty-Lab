"""
SOVEREIGN SWARM — Strategic Memory Service
CRUD and query operations for all 6 strategic memory layers.

Layers:
    L1 Standing Orders     — Persistent directives governing Fibre behavior
    L2 Insight Log         — Tagged observations with confidence ratings
    L3 Strategy Proposals  — Deploy queue with approval/auto-execute
    L4 Coherence Briefings — Periodic synthesis from coherence engine
    L5 Foresight Alerts    — Predictive entries with confidence intervals
    L6 Swarm Oversight     — Fibre inventory, mesh health, lifecycle events
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.services.exceptions import StrategyException, ProposalNotFoundException


class StrategicMemoryService:
    """Unified access to all 6 strategic memory layers."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    # =========================================================================
    # LAYER 1 — STANDING ORDERS
    # =========================================================================

    async def create_standing_order(
        self, title: str, directive: str,
        origin: str = "big_nate_direct",
        domain_tags: Optional[List[str]] = None,
        priority: int = 5,
        created_by: str = "big_nate",
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO standing_orders
                    (title, directive, origin, domain_tags, priority, created_by, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
            """, title, directive, origin, domain_tags or [], priority,
                 created_by, json.dumps(metadata or {}))
            return dict(row)

    async def get_active_standing_orders(self) -> List[Dict[str, Any]]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM standing_orders
                WHERE active = TRUE
                ORDER BY priority DESC, created_at ASC
            """)
            return [dict(r) for r in rows]

    async def update_standing_order(self, order_id: UUID, **kwargs) -> Dict[str, Any]:
        """Update fields on a standing order."""
        allowed = {"title", "directive", "domain_tags", "priority", "active",
                    "performance_score", "metadata"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            raise StrategyException("No valid fields to update")

        set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
        values = list(updates.values())

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE standing_orders SET {set_clauses}, updated_at = NOW() "
                f"WHERE order_id = $1 RETURNING *",
                order_id, *values
            )
            if not row:
                raise ProposalNotFoundException(f"Standing order {order_id} not found")
            return dict(row)

    # =========================================================================
    # LAYER 2 — INSIGHT LOG
    # =========================================================================

    async def log_insight(
        self, title: str, body: str,
        domain: str = "operational",
        confidence: float = 0.5,
        tags: Optional[List[str]] = None,
        source_fibre_id: Optional[UUID] = None,
        source_type: str = "system",
        related_insight_ids: Optional[List[UUID]] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO insight_log
                    (title, body, domain, confidence, tags, source_fibre_id,
                     source_type, related_insight_ids, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING *
            """, title, body, domain, confidence, tags or [],
                 source_fibre_id, source_type,
                 [str(uid) for uid in (related_insight_ids or [])],
                 json.dumps(metadata or {}))
            return dict(row)

    async def get_recent_insights(self, hours: int = 24, domain: Optional[str] = None) -> List[Dict]:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        async with self.db_pool.acquire() as conn:
            if domain:
                rows = await conn.fetch("""
                    SELECT * FROM insight_log
                    WHERE created_at > $1 AND domain = $2
                    ORDER BY confidence DESC, created_at DESC
                """, cutoff, domain)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM insight_log
                    WHERE created_at > $1
                    ORDER BY confidence DESC, created_at DESC
                """, cutoff)
            return [dict(r) for r in rows]

    async def promote_insight_to_order(self, insight_id: UUID) -> Dict[str, Any]:
        """Auto-promote a high-confidence insight into a Standing Order."""
        async with self.db_pool.acquire() as conn:
            insight = await conn.fetchrow(
                "SELECT * FROM insight_log WHERE insight_id = $1", insight_id
            )
            if not insight:
                raise ProposalNotFoundException(f"Insight {insight_id} not found")

            order = await self.create_standing_order(
                title=insight["title"],
                directive=insight["body"],
                origin="insight_promotion",
                domain_tags=list(insight["tags"]) if insight["tags"] else [],
                created_by="sovereign_mind",
            )

            await conn.execute("""
                UPDATE insight_log
                SET promoted_to_order = TRUE, promoted_order_id = $2
                WHERE insight_id = $1
            """, insight_id, order["order_id"])

            return order

    # =========================================================================
    # LAYER 3 — STRATEGY PROPOSALS (DEPLOY QUEUE)
    # =========================================================================

    async def create_proposal(
        self, title: str, description: str, action_type: str,
        proposed_by: str = "sovereign_mind",
        risk: str = "medium",
        execution_payload: Optional[Dict] = None,
        rollback_payload: Optional[Dict] = None,
        auto_execute_hours: Optional[int] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        auto_exec = None
        if auto_execute_hours and risk == "low":
            auto_exec = datetime.utcnow() + timedelta(hours=auto_execute_hours)

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO strategy_proposals
                    (title, description, action_type, proposed_by, risk, status,
                     execution_payload, rollback_payload, auto_execute_after, metadata)
                VALUES ($1, $2, $3, $4, $5, 'pending_approval', $6, $7, $8, $9)
                RETURNING *
            """, title, description, action_type, proposed_by, risk,
                 json.dumps(execution_payload or {}),
                 json.dumps(rollback_payload) if rollback_payload else None,
                 auto_exec, json.dumps(metadata or {}))
            return dict(row)

    async def get_pending_proposals(self) -> List[Dict]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM strategy_proposals
                WHERE status IN ('proposed', 'pending_approval')
                ORDER BY created_at DESC
            """)
            return [dict(r) for r in rows]

    async def approve_proposal(self, proposal_id: UUID, approved_by: str = "big_nate") -> Dict:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE strategy_proposals
                SET status = 'approved', approved_by = $2, approved_at = NOW(), updated_at = NOW()
                WHERE proposal_id = $1
                RETURNING *
            """, proposal_id, approved_by)
            if not row:
                raise ProposalNotFoundException(f"Proposal {proposal_id} not found")
            return dict(row)

    async def reject_proposal(self, proposal_id: UUID, reason: str = "") -> Dict:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE strategy_proposals
                SET status = 'rejected', rejection_reason = $2, updated_at = NOW()
                WHERE proposal_id = $1
                RETURNING *
            """, proposal_id, reason)
            if not row:
                raise ProposalNotFoundException(f"Proposal {proposal_id} not found")
            return dict(row)

    async def check_auto_executions(self) -> List[Dict]:
        """Find and execute proposals past their auto-execute window."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                UPDATE strategy_proposals
                SET status = 'auto_executed', executed_at = NOW(), updated_at = NOW()
                WHERE status = 'pending_approval'
                  AND auto_execute_after IS NOT NULL
                  AND auto_execute_after <= NOW()
                  AND risk = 'low'
                RETURNING *
            """)
            return [dict(r) for r in rows]

    # =========================================================================
    # LAYER 4 — COHERENCE BRIEFINGS
    # =========================================================================

    async def store_coherence_briefing(self, briefing: Dict[str, Any]) -> Dict:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO coherence_briefings
                    (period_start, period_end, global_coherence_index,
                     layer_summaries, trending_themes, gap_analysis_summary,
                     notable_changes, recommendations, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING *
            """, briefing["period_start"], briefing["period_end"],
                 briefing.get("global_coherence_index", 0),
                 json.dumps(briefing.get("layer_summaries", {})),
                 briefing.get("trending_themes", []),
                 briefing.get("gap_analysis_summary"),
                 briefing.get("notable_changes", []),
                 briefing.get("recommendations", []),
                 json.dumps(briefing.get("metadata", {})))
            return dict(row)

    async def get_latest_coherence_briefing(self) -> Optional[Dict]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM coherence_briefings
                ORDER BY generated_at DESC LIMIT 1
            """)
            return dict(row) if row else None

    # =========================================================================
    # LAYER 5 — FORESIGHT ALERTS
    # =========================================================================

    async def create_foresight_alert(self, alert: Dict[str, Any]) -> Dict:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO foresight_alerts
                    (signal_description, confidence, confidence_interval_lower,
                     confidence_interval_upper, time_horizon_hours,
                     affected_populations, recommended_actions,
                     alternative_scenarios, monitoring_indicators,
                     source_fibre_id, source_data_streams, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                RETURNING *
            """, alert["signal_description"], alert.get("confidence", 0.5),
                 alert.get("confidence_interval_lower", 0),
                 alert.get("confidence_interval_upper", 1),
                 alert.get("time_horizon_hours", 24),
                 alert.get("affected_populations", []),
                 alert.get("recommended_actions", []),
                 json.dumps(alert.get("alternative_scenarios", [])),
                 alert.get("monitoring_indicators", []),
                 alert.get("source_fibre_id"),
                 alert.get("source_data_streams", []),
                 json.dumps(alert.get("metadata", {})))
            return dict(row)

    async def get_active_foresight_alerts(self) -> List[Dict]:
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM foresight_alerts
                WHERE resolved_at IS NULL
                ORDER BY confidence DESC, created_at DESC
            """)
            return [dict(r) for r in rows]

    async def resolve_foresight_alert(
        self, alert_id: UUID, actual_outcome: str, accuracy_score: float
    ) -> Dict:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE foresight_alerts
                SET actual_outcome = $2, accuracy_score = $3, resolved_at = NOW()
                WHERE alert_id = $1
                RETURNING *
            """, alert_id, actual_outcome, accuracy_score)
            if not row:
                raise ProposalNotFoundException(f"Foresight alert {alert_id} not found")
            return dict(row)

    # =========================================================================
    # LAYER 6 — SWARM OVERSIGHT
    # =========================================================================

    async def log_swarm_event(
        self, event_type: str,
        fibre_id: Optional[UUID] = None,
        fibre_type: Optional[str] = None,
        details: Optional[Dict] = None,
        mesh_health: Optional[Dict] = None,
        active_fibre_count: int = 0,
        total_tokens_consumed: int = 0,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO swarm_oversight_log
                    (event_type, fibre_id, fibre_type, details, mesh_health,
                     active_fibre_count, total_tokens_consumed, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING *
            """, event_type, fibre_id, fibre_type,
                 json.dumps(details or {}),
                 json.dumps(mesh_health) if mesh_health else None,
                 active_fibre_count, total_tokens_consumed,
                 json.dumps(metadata or {}))
            return dict(row)

    async def get_swarm_oversight_log(self, limit: int = 50) -> List[Dict]:
        """Fetch recent swarm oversight log entries."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM swarm_oversight_log
                ORDER BY created_at DESC
                LIMIT $1
            """, limit)
            return [dict(r) for r in rows]

    async def get_swarm_overview(self) -> Dict[str, Any]:
        """Build swarm overview for briefings and the Swarm dashboard tab."""
        async with self.db_pool.acquire() as conn:
            # Active Fibres (from fibres table if exists, else from oversight log)
            try:
                fibres = await conn.fetch("""
                    SELECT fibre_id, fibre_type, status, autonomy_level, name,
                           tokens_used_this_hour, last_active
                    FROM fibres WHERE status IN ('active', 'idle')
                    ORDER BY last_active DESC NULLS LAST
                """)
                fibre_list = [
                    {
                        "fibre_id": str(f["fibre_id"]),
                        "type": f["fibre_type"],
                        "status": f["status"],
                        "autonomy": f.get("autonomy_level", "observation"),
                        "name": f.get("name", "unnamed"),
                        "tokens_hour": f.get("tokens_used_this_hour", 0),
                    }
                    for f in fibres
                ]
            except Exception:
                fibre_list = []

            # Recent events
            events = await conn.fetch("""
                SELECT * FROM swarm_oversight_log
                ORDER BY created_at DESC LIMIT 20
            """)

            # Token consumption (24h)
            token_row = await conn.fetchrow("""
                SELECT COALESCE(SUM(total_tokens_consumed), 0) as total
                FROM swarm_oversight_log
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """)

            # Recent convergences
            try:
                convergences = await conn.fetch("""
                    SELECT * FROM convergence_alerts
                    ORDER BY detected_at DESC LIMIT 5
                """)
                convergence_list = [dict(c) for c in convergences]
            except Exception:
                convergence_list = []

            return {
                "active_fibres": len(fibre_list),
                "fibres": fibre_list,
                "total_tokens_24h": token_row["total"] if token_row else 0,
                "recent_events": [dict(e) for e in events[:10]],
                "recent_convergences": convergence_list,
                "mesh_health": None,  # populated by WisdomMesh when available
            }

    # =========================================================================
    # CROSS-LAYER INTEGRATION (PhD Spec §9.7)
    # =========================================================================

    async def promote_insights_to_proposals(self, confidence_threshold: float = 0.85) -> List[Dict]:
        """
        L2 → L3: High-confidence insights that suggest actionable strategies
        are automatically promoted to Strategy Proposals for review.
        """
        async with self.db_pool.acquire() as conn:
            insights = await conn.fetch("""
                SELECT * FROM insight_log
                WHERE confidence >= $1
                  AND promoted_to_order = FALSE
                  AND created_at > NOW() - INTERVAL '7 days'
                ORDER BY confidence DESC
                LIMIT 10
            """, confidence_threshold)

        promoted = []
        for insight in insights:
            proposal = await self.create_proposal(
                title=f"[Auto] {insight['title']}",
                description=(
                    f"Auto-generated from high-confidence insight (confidence={insight['confidence']:.2f}).\n\n"
                    f"{insight['body']}"
                ),
                action_type="insight_driven_strategy",
                proposed_by="sovereign_mind_L2_L3",
                risk="low",
                execution_payload={"source_insight_id": str(insight["insight_id"])},
                metadata={
                    "cross_layer": "L2→L3",
                    "source_confidence": float(insight["confidence"]),
                    "source_tags": list(insight["tags"]) if insight.get("tags") else [],
                },
            )
            promoted.append(proposal)

        return promoted

    async def promote_briefing_to_foresight(self, briefing_id: UUID) -> Optional[Dict]:
        """
        L4 → L5: When a Coherence Briefing detects a notable change or
        gap, auto-create a Foresight Alert for predictive monitoring.
        """
        async with self.db_pool.acquire() as conn:
            briefing = await conn.fetchrow(
                "SELECT * FROM coherence_briefings WHERE briefing_id = $1",
                briefing_id,
            )
        if not briefing:
            return None

        # Parse notable changes and gap analysis
        notable = briefing.get("notable_changes") or {}
        gap = briefing.get("gap_analysis_summary") or ""
        if isinstance(notable, str):
            try:
                notable = json.loads(notable)
            except Exception:
                notable = {"raw": notable}

        # Only create foresight alert if there are notable changes
        if not notable and not gap:
            return None

        alert_data = {
            "signal": f"Coherence briefing flagged: {gap[:200] if gap else 'notable changes detected'}",
            "confidence": min(0.7, float(briefing.get("global_coherence_index", 0.5))),
            "horizon_hours": 48,
            "affected_populations": ["system"],
            "recommended_actions": briefing.get("recommendations") or [],
            "alternative_scenarios": [
                {"label": "status_quo", "description": "No intervention", "probability": 0.4},
                {"label": "intervene", "description": "Act on briefing recommendations", "probability": 0.6},
            ],
            "monitoring_indicators": ["coherence_trend", "engagement_rate"],
            "source_data_streams": ["coherence_briefings"],
            "metadata": {
                "cross_layer": "L4→L5",
                "source_briefing_id": str(briefing_id),
            },
        }
        return await self.store_foresight_alert(alert_data)

    async def promote_oversight_anomaly_to_order(
        self, event_id: UUID, directive: Optional[str] = None
    ) -> Optional[Dict]:
        """
        L6 → L1: When Swarm Oversight detects an anomaly or critical event,
        auto-create a Standing Order to prevent recurrence.
        """
        async with self.db_pool.acquire() as conn:
            event = await conn.fetchrow(
                "SELECT * FROM swarm_oversight_log WHERE event_id = $1",
                event_id,
            )
        if not event:
            return None

        event_type = event.get("event_type", "unknown")
        details = event.get("details")
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except Exception:
                details = {}

        order_directive = directive or (
            f"Swarm anomaly detected ({event_type}). "
            f"Fibre {event.get('fibre_id') or 'unknown'} ({event.get('fibre_type', '?')}) "
            f"triggered this event. Monitor and apply corrective action."
        )

        order = await self.create_standing_order(
            title=f"[Auto-L6] {event_type} response",
            directive=order_directive,
            origin="swarm_oversight_L6_L1",
            domain_tags=[event_type, "anomaly", "auto_generated"],
            created_by="sovereign_mind",
        )

        return order

    async def promote_approved_strategy_to_order(self, proposal_id: UUID) -> Optional[Dict]:
        """
        L3 → L1: When a Strategy Proposal is approved and executed,
        its successful strategy becomes a Standing Order for future reference.
        """
        async with self.db_pool.acquire() as conn:
            proposal = await conn.fetchrow(
                "SELECT * FROM strategy_proposals WHERE proposal_id = $1 AND status = 'approved'",
                proposal_id,
            )
        if not proposal:
            return None

        order = await self.create_standing_order(
            title=f"[Strategy] {proposal['title']}",
            directive=(
                f"Approved strategy (risk={proposal.get('risk', '?')}): "
                f"{proposal['description']}"
            ),
            origin="strategy_promotion_L3_L1",
            domain_tags=[proposal.get("action_type", "strategy"), "approved", "auto_promoted"],
            created_by=proposal.get("approved_by", "sovereign_mind"),
        )

        # Mark the proposal as promoted
        async with self.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE strategy_proposals
                SET metadata = metadata || $2, updated_at = NOW()
                WHERE proposal_id = $1
            """, proposal_id, json.dumps({
                "promoted_to_standing_order": str(order["order_id"]),
                "promoted_at": datetime.utcnow().isoformat(),
            }))

        return order
