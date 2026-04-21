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

from app.services.exceptions import (
    ProposalNotFoundException,
    ProposalValidationError,
    StrategyException,
)


# ─── Proposal validation rules ───
# Title must be descriptive enough that an admin reading it in an email can
# tell what they're approving without opening another tool. "verify" fails;
# "Verify client coherence metrics across all active users" passes.
_PROPOSAL_TITLE_MIN_LEN = 10

_PROPOSAL_REQUIRED_FIELDS = (
    "title",          # >= _PROPOSAL_TITLE_MIN_LEN chars
    "objective",      # WHAT will happen (1-2 sentences)
    "reasoning",      # WHY this is being proposed
    "action_steps",   # bullet list of concrete steps that execute
    "expected_impact",  # what changes after execution
    "rollback",       # what happens if this goes wrong
)


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
        # ─── Self-contained proposal fields (FIX 1 of proposal enrichment) ───
        # Every proposal that lands in the deploy queue must answer these so
        # the operator can approve from email/SMS without opening another tool.
        objective: Optional[str] = None,
        reasoning: Optional[str] = None,
        action_steps: Optional[List[str]] = None,
        expected_impact: Optional[str] = None,
        rollback: Optional[str] = None,
        deployment_window: Optional[str] = None,
        data_sources: Optional[List[str]] = None,
        token_cost_estimate: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a strategy proposal after validating it is self-contained.

        Rejects (with ``ProposalValidationError``) any proposal where the
        operator could not make an informed decision from the resulting
        email alone — i.e. missing title (>= 10 chars), objective,
        reasoning, action_steps, expected_impact, or rollback.
        """
        # ─── Validation ───
        title_clean = (title or "").strip()
        missing: List[str] = []
        if len(title_clean) < _PROPOSAL_TITLE_MIN_LEN:
            missing.append(f"title (got {len(title_clean)} chars, need >= {_PROPOSAL_TITLE_MIN_LEN})")
        if not (objective or "").strip():
            missing.append("objective")
        if not (reasoning or "").strip():
            missing.append("reasoning")
        if not action_steps or not any(str(s).strip() for s in action_steps):
            missing.append("action_steps")
        if not (expected_impact or "").strip():
            missing.append("expected_impact")
        if not (rollback or "").strip():
            missing.append("rollback")

        if missing:
            reason = "; ".join(missing)
            print(
                f">>> [PROPOSAL_REJECTED] proposed_by={proposed_by} "
                f"title={title_clean[:60]!r} missing={missing}"
            )
            raise ProposalValidationError(
                reason=reason,
                missing_fields=missing,
                title=title_clean,
                proposed_by=proposed_by,
            )

        # ─── Auto-execute safeguard (FIX 4) ───
        # Only LOW-risk proposals with a concrete objective may auto-execute.
        # MEDIUM/HIGH/CRITICAL always require explicit approval.
        auto_exec = None
        if auto_execute_hours and risk == "low" and (objective or "").strip():
            auto_exec = datetime.utcnow() + timedelta(hours=auto_execute_hours)

        # ─── Build description if caller passed only the structured fields ───
        # Keeps the legacy `description` column populated as a single-paragraph
        # human-readable summary; the rich detail lives in metadata.details.
        clean_steps = [str(s).strip() for s in action_steps if str(s).strip()]
        if not (description or "").strip():
            description = (
                f"{objective.strip()}\n\nReasoning: {reasoning.strip()}\n\n"
                f"Steps:\n- " + "\n- ".join(clean_steps)
            )

        # ─── Stash structured fields in metadata.details for the email template ───
        meta = dict(metadata or {})
        meta["details"] = {
            "objective": objective.strip(),
            "reasoning": reasoning.strip(),
            "action_steps": clean_steps,
            "expected_impact": expected_impact.strip(),
            "rollback": rollback.strip(),
            "deployment_window": (deployment_window or "").strip() or None,
            "data_sources": list(data_sources) if data_sources else [],
            "token_cost_estimate": (token_cost_estimate or "").strip() or None,
        }

        # Mirror the rollback text into rollback_payload so legacy consumers
        # (admin UI, audit log) see it without parsing metadata.details.
        rb_payload: Optional[Dict[str, Any]]
        if isinstance(rollback_payload, dict):
            rb_payload = dict(rollback_payload)
            rb_payload.setdefault("description", rollback.strip())
        else:
            rb_payload = {"description": rollback.strip()}

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO strategy_proposals
                    (title, description, action_type, proposed_by, risk, status,
                     execution_payload, rollback_payload, auto_execute_after, metadata)
                VALUES ($1, $2, $3, $4, $5, 'pending_approval', $6, $7, $8, $9)
                RETURNING *
            """, title_clean, description, action_type, proposed_by, risk,
                 json.dumps(execution_payload or {}),
                 json.dumps(rb_payload),
                 auto_exec, json.dumps(meta))
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
            # QUANTUM-CRYSTAL-ARCH: crystallize coherence briefing into intelligence pool
            if row:
                try:
                    gap = briefing.get("gap_analysis_summary", "")
                    themes = briefing.get("trending_themes", [])
                    recs = briefing.get("recommendations", [])
                    crystal_parts = []
                    if gap:
                        crystal_parts.append(f"Gap analysis: {gap}")
                    if themes:
                        crystal_parts.append(f"Themes: {', '.join(themes[:5])}")
                    if recs:
                        crystal_parts.append(f"Recommendations: {'; '.join(recs[:3])}")
                    if crystal_parts:
                        crystal_text = "COHERENCE BRIEFING — " + " | ".join(crystal_parts)
                        import hashlib
                        content_hash = hashlib.sha256(crystal_text.encode()).hexdigest()
                        await conn.execute(
                            """INSERT INTO nate_intelligence_crystals
                               (crystal_text, domain, scope, topics, source_count,
                                generation, confidence, content_hash, origin_surface)
                             VALUES ($1, 'coherence', 'global', $2, 1, 0, 0.60, $3,
                                     'coherence_briefing')
                             ON CONFLICT (content_hash) DO NOTHING""",
                            crystal_text,
                            themes[:10] if themes else [],
                            content_hash,
                        )
                        from app.services.vectorize_service import index_wisdom, is_vectorize_configured
                        if is_vectorize_configured():
                            await index_wisdom(
                                user_id="nate_crystal",
                                wisdom_id=f"crystal_{content_hash[:16]}",
                                insight_type="coherence_briefing",
                                content=crystal_text,
                                source="coherence_briefing",
                                domain="coherence",
                            )
                except Exception as _cb_err:
                    logger.debug("Coherence briefing crystallize non-fatal: %s", _cb_err)
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
            insight_title = (insight.get("title") or "").strip() or "Unnamed insight"
            insight_body = (insight.get("body") or "").strip()
            confidence = float(insight.get("confidence") or 0.0)
            tags = list(insight.get("tags") or [])

            # Pad short insight titles so the proposal title still meets the
            # >= 10 char rule enforced by create_proposal validation.
            base_title = f"Act on insight: {insight_title}"
            try:
                proposal = await self.create_proposal(
                    title=base_title[:240],
                    description="",  # auto-built from objective + reasoning + steps below
                    action_type="insight_driven_strategy",
                    proposed_by="sovereign_mind_L2_L3",
                    risk="low",
                    execution_payload={"source_insight_id": str(insight["insight_id"])},
                    metadata={
                        "cross_layer": "L2→L3",
                        "source_confidence": confidence,
                        "source_tags": tags,
                    },
                    objective=(
                        f"Promote the L2 insight \"{insight_title}\" into a "
                        f"reviewed strategy proposal so the swarm can act on it."
                    ),
                    reasoning=(
                        f"Insight crossed the {confidence_threshold:.2f} confidence "
                        f"threshold (recorded confidence={confidence:.2f}) within the "
                        f"last 7 days, indicating a stable observation worth converting "
                        f"into deliberate action.\n\nInsight body:\n{insight_body}"
                    ),
                    action_steps=[
                        "Review the source insight and its supporting evidence",
                        "Confirm the action aligns with active standing orders",
                        "Mark the insight as promoted to prevent duplicate proposals",
                    ],
                    expected_impact=(
                        "A high-confidence observation gets human review instead of "
                        "decaying in the insight log; if approved, downstream Fibres "
                        "receive a directive aligned with the insight."
                    ),
                    rollback=(
                        "Read-only promotion — rejecting this proposal leaves the "
                        "source insight untouched in the L2 log."
                    ),
                    data_sources=["insight_log"],
                    token_cost_estimate="Minimal — under $0.01 (DB write only)",
                )
                promoted.append(proposal)
            except ProposalValidationError as exc:
                # Should not happen with the synthesized fields above, but log
                # rather than abort the whole batch.
                print(
                    f">>> [L2→L3] Skipped insight {insight.get('insight_id')}: "
                    f"{exc.message}"
                )

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
