"""
SOVEREIGN SWARM — Sovereign Mind Orchestrator (Layer 2: Command)
Central intelligence for the Sovereign Swarm Intelligence Framework.

Patent Claims: 1, 3, 11, 18, 21, 22.

The Sovereign Mind:
    - Processes commands from Big Nate (human AI companion interface)
    - Generates operational briefings synthesizing all swarm data
    - Creates strategy proposals for human approval
    - Absorbs Fibre wisdom into the swarm's collective knowledge
    - Issues directives to Fibres through the Wisdom Mesh
    - Orchestrates cross-domain synthesis from multiple Fibres
    - Evaluates whether to spawn new Fibres
    - Records Fibre losses and triggers memorial encoding
    - Provides fleet-level swarm overview
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID, uuid4

import structlog

from app.models.fibre import FibreStatus, FibreType
from app.models.mesh import MeshMessage, MeshMessageType, MeshPriority, MeshTopology
from app.models.quakete import RingState
from app.models.swarm import (
    FibreSummary,
    SwarmDirective,
    SwarmState,
)

if TYPE_CHECKING:
    from app.services.coherence_engine import CoherenceEngine
    from app.services.fibre_manager import FibreManager
    from app.services.foresight_engine import ForesightEngine
    from app.services.identity_chain import IdentityChainService
    from app.services.pattern_engine import TransgenerationalPatternEngine
    from app.services.quakete.cosmic_ring import CosmicRingManager
    from app.services.quakete.memorial import MemorialService
    from app.services.quakete.trail_map import FibreTrailMap
    from app.services.sovereign_immunity import SovereignImmunityService
    from app.services.strategic_memory import StrategicMemoryService
    from app.services.wisdom_mesh import WisdomMeshService

# Well-known UUID for Sovereign Mind (used when publishing directives)
SOVEREIGN_MIND_SENDER_ID = UUID("00000000-0000-0000-0000-000000000001")


# =============================================================================
# SOVEREIGN MIND (Patent Claims 1, 3, 11, 18, 21, 22)
# =============================================================================


class SovereignMind:
    """
    Central orchestrator for the Sovereign Swarm Intelligence Framework.
    Layer 2: Command — processes Big Nate commands, synthesizes swarm data,
    issues directives, and governs Fibre lifecycle.
    """

    def __init__(
        self,
        db_pool,
        redis=None,
        *,
        fibre_manager: Optional["FibreManager"] = None,
        wisdom_mesh: Optional["WisdomMeshService"] = None,
        coherence_engine: Optional["CoherenceEngine"] = None,
        foresight_engine: Optional["ForesightEngine"] = None,
        pattern_engine: Optional["TransgenerationalPatternEngine"] = None,
        immunity: Optional["SovereignImmunityService"] = None,
        identity_chain: Optional["IdentityChainService"] = None,
        strategic_memory: Optional["StrategicMemoryService"] = None,
        trail_map: Optional["FibreTrailMap"] = None,
        ring_manager: Optional["CosmicRingManager"] = None,
        memorial_service: Optional["MemorialService"] = None,
    ) -> None:
        """
        Initialize the Sovereign Mind with optional service dependencies.
        All dependencies except db_pool and redis default to None for graceful degradation.

        Args:
            db_pool: Database connection pool (required for strategic memory fallback).
            redis: Redis client (optional, for direct cache ops).
            fibre_manager: Fibre lifecycle management (Patent Claim 18).
            wisdom_mesh: Distributed knowledge sync and directive publishing.
            coherence_engine: 5-layer coherence measurement.
            foresight_engine: Prediction and forecasting.
            pattern_engine: Transgenerational pattern recognition.
            immunity: Security and validation layer.
            identity_chain: Cryptographic identity.
            strategic_memory: 6-layer strategic memory.
            trail_map: Swarm-wide health and silent Fibre detection (Patent Claim 26.1b–c).
            ring_manager: Cosmic Relational Ring operations (Patent Claim 26.1h).
            memorial_service: Lost Fibre memorial encoding (Patent Claim 26.3).
        """
        self.db_pool = db_pool
        self.redis = redis
        self.fibre_manager = fibre_manager
        self.wisdom_mesh = wisdom_mesh
        self.coherence_engine = coherence_engine
        self.foresight_engine = foresight_engine
        self.pattern_engine = pattern_engine
        self.immunity = immunity
        self.identity_chain = identity_chain
        self.strategic_memory = strategic_memory or self._create_fallback_memory()
        self.trail_map = trail_map
        self.ring_manager = ring_manager
        self.memorial_service = memorial_service
        self._log = structlog.get_logger()

    def _create_fallback_memory(self) -> "StrategicMemoryService":
        """Create a minimal StrategicMemoryService when none provided."""
        from app.services.strategic_memory import StrategicMemoryService
        return StrategicMemoryService(self.db_pool)

    # -------------------------------------------------------------------------
    # 1. PROCESS COMMAND (Patent Claim 1 — Central Command Processing)
    # -------------------------------------------------------------------------

    async def process_command(
        self,
        command: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Parse command intent, validate through Sovereign Immunity, and route
        to the appropriate handler. Patent Claim 1.

        Recognized intents: briefing, strategy, directive, inquiry, overview.

        Returns:
            Structured response: {type, content, timestamp}.
        """
        context = context or {}
        timestamp = datetime.now(timezone.utc).isoformat()

        # Validate through Sovereign Immunity if available
        if self.immunity:
            try:
                sanitized = self.immunity.sanitize_input(
                    {"command": command, **context},
                    source="big_nate_command",
                )
                command = sanitized.get("command", command)
            except Exception as e:
                self._log.warning("immunity_sanitization_failed", error=str(e))
                # Continue with original command on sanitization failure

        intent = self._parse_command_intent(command)
        self._log.info("command_processed", intent=intent, command_preview=command[:80])

        try:
            if intent == "briefing":
                content = await self.generate_briefing(
                    focus_areas=context.get("focus_areas"),
                )
                return {"type": "briefing", "content": content, "timestamp": timestamp}
            elif intent == "strategy":
                content = await self.generate_proposal(
                    objective=context.get("objective", command),
                    rationale=context.get("rationale", ""),
                    domain_tags=context.get("domain_tags"),
                    human_approves_auto=context.get("human_approves_auto", False),
                )
                return {"type": "strategy_proposal", "content": content, "timestamp": timestamp}
            elif intent == "directive":
                directive_data = context.get("directive") or {}
                directive = SwarmDirective(
                    directive_type=directive_data.get("directive_type", "standing_order"),
                    target_fibre_ids=directive_data.get("target_fibre_ids", []),
                    target_fibre_types=directive_data.get("target_fibre_types", []),
                    content=directive_data.get("content", {}),
                    priority=directive_data.get("priority", "normal"),
                )
                content = await self.issue_directive(directive)
                return {"type": "directive_ack", "content": content, "timestamp": timestamp}
            elif intent == "overview":
                content = await self.get_swarm_overview()
                return {
                    "type": "swarm_overview",
                    "content": content.model_dump() if hasattr(content, "model_dump") else content,
                    "timestamp": timestamp,
                }
            elif intent == "inquiry":
                domain_tags = context.get("domain_tags") or self._extract_domains_from_command(command)
                content = await self.synthesize_cross_domain(domain_tags or ["operational"])
                return {"type": "inquiry_response", "content": content, "timestamp": timestamp}
            else:
                return {
                    "type": "unknown",
                    "content": {"message": f"Unrecognized command intent: {intent}"},
                    "timestamp": timestamp,
                }
        except Exception as e:
            self._log.exception("command_processing_failed", intent=intent, error=str(e))
            return {
                "type": "error",
                "content": {"error": str(e), "intent": intent},
                "timestamp": timestamp,
            }

    def _parse_command_intent(self, command: str) -> str:
        """Parse command text into intent: briefing, strategy, directive, inquiry, overview."""
        cmd_lower = command.lower().strip()
        if any(w in cmd_lower for w in ("briefing", "brief", "summarize", "status report")):
            return "briefing"
        if any(w in cmd_lower for w in ("strategy", "proposal", "suggest", "recommend")):
            return "strategy"
        if any(w in cmd_lower for w in ("directive", "order", "instruct", "command")):
            return "directive"
        if any(w in cmd_lower for w in ("overview", "swarm", "fleet", "inventory")):
            return "overview"
        return "inquiry"

    def _extract_domains_from_command(self, command: str) -> List[str]:
        """Extract domain tags from natural language command."""
        domains = []
        cmd_lower = command.lower()
        domain_map = {
            "clinical": ["clinical", "therapy", "client"],
            "marketing": ["marketing", "campaign", "funnel"],
            "cultural": ["cultural", "culture", "society"],
            "operational": ["operational", "operations", "system"],
            "foresight": ["foresight", "predict", "forecast"],
            "swarm": ["swarm", "fibre", "mesh"],
        }
        for domain, keywords in domain_map.items():
            if any(kw in cmd_lower for kw in keywords):
                domains.append(domain)
        return domains or ["operational"]

    # -------------------------------------------------------------------------
    # 2. GENERATE BRIEFING (Patent Claim 3 — Operational Synthesis)
    # -------------------------------------------------------------------------

    async def generate_briefing(
        self,
        focus_areas: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Pull latest from all 6 strategic memory layers, synthesize coherence
        state, foresight alerts, pattern activations, and swarm health.
        Patent Claim 3.
        """
        focus_areas = focus_areas or []
        briefing: Dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "focus_areas": focus_areas,
            "strategic_memory": {},
            "coherence": {},
            "foresight_alerts": [],
            "pattern_activations": [],
            "swarm_health": {},
        }

        # Layer 1–6 from strategic memory
        if self.strategic_memory:
            try:
                orders = await self.strategic_memory.get_active_standing_orders()
                briefing["strategic_memory"]["standing_orders"] = orders
            except Exception as e:
                self._log.warning("briefing_standing_orders_failed", error=str(e))
                briefing["strategic_memory"]["standing_orders"] = []

            try:
                insights = await self.strategic_memory.get_recent_insights(hours=24)
                briefing["strategic_memory"]["recent_insights"] = insights[:20]
            except Exception as e:
                self._log.warning("briefing_insights_failed", error=str(e))
                briefing["strategic_memory"]["recent_insights"] = []

            try:
                coherence_brief = await self.strategic_memory.get_latest_coherence_briefing()
                briefing["strategic_memory"]["latest_coherence_briefing"] = coherence_brief
            except Exception as e:
                self._log.warning("briefing_coherence_briefing_failed", error=str(e))
                briefing["strategic_memory"]["latest_coherence_briefing"] = None

            try:
                foresight = await self.strategic_memory.get_active_foresight_alerts()
                briefing["foresight_alerts"] = foresight
            except Exception as e:
                self._log.warning("briefing_foresight_failed", error=str(e))

        # Coherence engine pulse snapshot
        if self.coherence_engine:
            try:
                snapshot = await self.coherence_engine.generate_pulse_snapshot()
                briefing["coherence"] = {
                    "global_index": snapshot.global_coherence_index,
                    "layer_scores": snapshot.layer_scores,
                    "trending_themes": snapshot.trending_themes,
                    "notable_changes": snapshot.notable_changes,
                }
            except Exception as e:
                self._log.warning("briefing_coherence_engine_failed", error=str(e))

        # Pattern activations (from pattern engine if available)
        if self.pattern_engine:
            try:
                # TransgenerationalPatternEngine doesn't expose get_activations;
                # use empty for now, or call analyze_emotional_themes per family if needed
                briefing["pattern_activations"] = []
            except Exception as e:
                self._log.warning("briefing_patterns_failed", error=str(e))

        # Swarm health from trail map (Patent Claim 26.1b–c)
        if self.trail_map:
            try:
                health = self.trail_map.get_swarm_health()
                briefing["swarm_health"] = health
            except Exception as e:
                self._log.warning("briefing_trail_map_failed", error=str(e))

        return briefing

    # -------------------------------------------------------------------------
    # 3. GENERATE PROPOSAL (Patent Claims 11, 21 — Strategy Proposals)
    # -------------------------------------------------------------------------

    async def generate_proposal(
        self,
        objective: str,
        rationale: str,
        domain_tags: Optional[List[str]] = None,
        human_approves_auto: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a StrategyProposal in strategic memory. Auto-assess risk level.
        If low risk and human_approves_auto: auto-execute. Patent Claims 11, 21.
        """
        domain_tags = domain_tags or []
        risk = self._assess_proposal_risk(objective, domain_tags)

        proposal = await self.strategic_memory.create_proposal(
            title=objective[:256],
            description=rationale,
            action_type=domain_tags[0] if domain_tags else "general",
            proposed_by="sovereign_mind",
            risk=risk,
            execution_payload={"objective": objective, "rationale": rationale, "domains": domain_tags},
            auto_execute_hours=2 if (risk == "low" and human_approves_auto) else None,
        )

        if risk == "low" and human_approves_auto:
            try:
                auto_executed = await self.strategic_memory.check_auto_executions()
                if auto_executed:
                    proposal["status"] = "auto_executed"
                    proposal["executed_at"] = datetime.now(timezone.utc).isoformat()
            except Exception as e:
                self._log.warning("proposal_auto_execute_failed", error=str(e))

        return {
            "proposal_id": str(proposal.get("proposal_id", "")),
            "title": proposal.get("title", objective),
            "risk": risk,
            "status": proposal.get("status", "pending_approval"),
            "auto_execute_eligible": risk == "low" and human_approves_auto,
        }

    def _assess_proposal_risk(self, objective: str, domain_tags: List[str]) -> str:
        """Auto-assess risk based on scope and domain."""
        scope_high = any(w in objective.lower() for w in ("critical", "delete", "remove", "override"))
        if scope_high or "critical" in domain_tags:
            return "critical"
        if len(domain_tags) > 3 or "high" in objective.lower():
            return "high"
        if len(domain_tags) > 1:
            return "medium"
        return "low"

    # -------------------------------------------------------------------------
    # 4. ABSORB FIBRE WISDOM (Patent Claim 18 — Collective Knowledge)
    # -------------------------------------------------------------------------

    async def absorb_fibre_wisdom(
        self,
        fibre_id: str,
        wisdom_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Record insight in strategic memory Layer 2. Check for convergence
        with other recent insights. If convergence detected, escalate to briefing.
        Patent Claim 18.
        """
        title = wisdom_payload.get("title", f"Wisdom from {fibre_id}")[:256]
        body = wisdom_payload.get("body", str(wisdom_payload))
        domain = wisdom_payload.get("domain", "operational")
        confidence = float(wisdom_payload.get("confidence", 0.6))
        tags = wisdom_payload.get("tags", [])

        insight = await self.strategic_memory.log_insight(
            title=title,
            body=body,
            domain=domain,
            confidence=confidence,
            tags=tags,
            source_fibre_id=UUID(fibre_id) if self._is_valid_uuid(fibre_id) else None,
            source_type="fibre",
        )

        # Check for convergence with recent insights
        recent = await self.strategic_memory.get_recent_insights(hours=2, domain=domain)
        convergence = self._detect_insight_convergence(body, recent, str(insight.get("insight_id", "")))

        if convergence:
            self._log.info("convergence_detected", fibre_id=fibre_id, theme=convergence.get("theme"))
            # Escalate: could trigger briefing or alert
            return {
                "absorbed": True,
                "insight_id": str(insight.get("insight_id", "")),
                "convergence_detected": True,
                "convergence_theme": convergence.get("theme"),
                "escalated": True,
            }

        return {
            "absorbed": True,
            "insight_id": str(insight.get("insight_id", "")),
            "convergence_detected": False,
        }

    def _detect_insight_convergence(
        self,
        body: str,
        recent: List[Dict],
        current_id: str,
    ) -> Optional[Dict[str, str]]:
        """Simple overlap-based convergence detection."""
        if len(recent) < 2:
            return None
        body_words = set(re.split(r"\W+", body.lower())) - {"", "a", "an", "the"}
        for r in recent:
            if str(r.get("insight_id")) == current_id:
                continue
            other = r.get("body", "") or ""
            other_words = set(re.split(r"\W+", other.lower())) - {"", "a", "an", "the"}
            overlap = len(body_words & other_words) / max(1, min(len(body_words), len(other_words)))
            if overlap > 0.4:
                return {"theme": other[:100], "overlap": overlap}
        return None

    @staticmethod
    def _is_valid_uuid(s: str) -> bool:
        try:
            UUID(s)
            return True
        except (ValueError, TypeError):
            return False

    # -------------------------------------------------------------------------
    # 5. ISSUE DIRECTIVE (Patent Claim 22 — Mesh Directives)
    # -------------------------------------------------------------------------

    async def issue_directive(self, directive: SwarmDirective) -> Dict[str, Any]:
        """
        Validate directive through immunity, publish to Wisdom Mesh,
        record in strategic memory Layer 1 as standing order. Patent Claim 22.
        """
        # Validate through immunity if available
        if self.immunity:
            try:
                # Build a synthetic message for validation
                test_body = {
                    "directive_type": directive.directive_type,
                    "content": directive.content,
                }
                sanitized = self.immunity.sanitize_input(test_body, source="sovereign_mind")
                directive = SwarmDirective(
                    directive_type=directive.directive_type,
                    target_fibre_ids=directive.target_fibre_ids,
                    target_fibre_types=directive.target_fibre_types,
                    content=sanitized.get("content", directive.content),
                    priority=directive.priority,
                )
            except Exception as e:
                self._log.warning("directive_immunity_sanitization_failed", error=str(e))

        # Publish to Wisdom Mesh
        published = False
        if self.wisdom_mesh:
            try:
                msg = MeshMessage(
                    message_type=MeshMessageType.DIRECTIVE,
                    priority=MeshPriority.HIGH if directive.priority == "high" else MeshPriority.NORMAL,
                    sender_id=SOVEREIGN_MIND_SENDER_ID,
                    sender_type="sovereign_mind",
                    domain_tags=directive.target_fibre_types or ["general"],
                    topology_level=MeshTopology.LEVEL_0_SOVEREIGN,
                    body={
                        "directive_id": str(directive.directive_id),
                        "directive_type": directive.directive_type,
                        "content": directive.content,
                        "target_fibre_ids": directive.target_fibre_ids,
                    },
                )
                published = await self.wisdom_mesh.publish(msg)
            except Exception as e:
                self._log.warning("directive_mesh_publish_failed", error=str(e))

        # Record as standing order in Layer 1
        if self.strategic_memory:
            try:
                order = await self.strategic_memory.create_standing_order(
                    title=f"Directive: {directive.directive_type}",
                    directive=str(directive.content),
                    origin="big_nate_direct",
                    domain_tags=directive.target_fibre_types or [],
                    created_by="sovereign_mind",
                )
            except Exception as e:
                self._log.warning("directive_standing_order_failed", error=str(e))
                order = None
        else:
            order = None

        return {
            "directive_id": str(directive.directive_id),
            "published_to_mesh": published,
            "standing_order_id": str(order["order_id"]) if order else None,
        }

    # -------------------------------------------------------------------------
    # 6. SYNTHESIZE CROSS-DOMAIN (Patent Claim 3 — Cross-Domain Synthesis)
    # -------------------------------------------------------------------------

    async def synthesize_cross_domain(
        self,
        domain_tags: List[str],
    ) -> Dict[str, Any]:
        """
        Query insights across specified domains, find convergence patterns,
        generate synthesis report. Patent Claim 3.
        """
        if not self.strategic_memory:
            return {"domains": domain_tags, "insights": [], "convergence": [], "synthesis": ""}

        all_insights: List[Dict] = []
        for domain in domain_tags:
            try:
                insights = await self.strategic_memory.get_recent_insights(hours=48, domain=domain)
                all_insights.extend([{**i, "domain": domain} for i in insights])
            except Exception as e:
                self._log.warning("synthesis_domain_failed", domain=domain, error=str(e))

        # Sort by confidence
        all_insights.sort(key=lambda x: float(x.get("confidence", 0)), reverse=True)

        # Find cross-domain themes (simple keyword overlap)
        theme_counts: Dict[str, int] = {}
        for i in all_insights:
            body = (i.get("body") or "")[:200]
            for tag in (i.get("tags") or []):
                theme_counts[tag] = theme_counts.get(tag, 0) + 1

        top_themes = sorted(theme_counts.items(), key=lambda x: -x[1])[:5]
        synthesis = (
            f"Cross-domain synthesis across {', '.join(domain_tags)}: "
            f"{len(all_insights)} insights. Top themes: {', '.join(t[0] for t in top_themes)}."
        )

        return {
            "domains": domain_tags,
            "insights": all_insights[:30],
            "convergence_themes": [t[0] for t in top_themes],
            "synthesis": synthesis,
        }

    # -------------------------------------------------------------------------
    # 7. EVALUATE SPAWN (Patent Claim 18 — Fibre Spawning)
    # -------------------------------------------------------------------------

    async def evaluate_spawn(
        self,
        fibre_type: str,
        justification: str,
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check current fibre inventory. Evaluate if new fibre is needed:
        type not represented, or demand exceeds capacity. Patent Claim 18.
        """
        current = await self._get_fibre_inventory()
        by_type = current.get("by_type", {})
        total = current.get("total", 0)

        type_represented = fibre_type in by_type and by_type[fibre_type] > 0
        demand_exceeds = total > 0 and by_type.get(fibre_type, 0) < 2  # heuristic

        should_spawn = (not type_represented) or demand_exceeds
        reasoning_parts = []
        if not type_represented:
            reasoning_parts.append(f"No Fibre of type '{fibre_type}' currently active.")
        if demand_exceeds:
            reasoning_parts.append(f"Only {by_type.get(fibre_type, 0)} '{fibre_type}' Fibre(s); demand may exceed capacity.")
        if not should_spawn:
            reasoning_parts.append(f"Type '{fibre_type}' already well-represented ({by_type.get(fibre_type, 0)} active).")

        config_suggestion = {
            "fibre_type": fibre_type,
            "domain_tags": [domain or fibre_type],
            "justification": justification,
        }

        return {
            "should_spawn": should_spawn,
            "reasoning": " ".join(reasoning_parts),
            "config_suggestion": config_suggestion,
            "current_inventory": by_type,
        }

    async def _get_fibre_inventory(self) -> Dict[str, Any]:
        """Get fibre counts by type from fibre manager or strategic memory."""
        if self.fibre_manager:
            try:
                items = await self.fibre_manager.inventory()
                by_type: Dict[str, int] = {}
                for i in items:
                    t = i.get("type", "unknown")
                    by_type[t] = by_type.get(t, 0) + 1
                return {"by_type": by_type, "total": len(items)}
            except Exception as e:
                self._log.warning("inventory_fibre_manager_failed", error=str(e))
        if self.strategic_memory:
            try:
                overview = await self.strategic_memory.get_swarm_overview()
                fibres = overview.get("fibres", [])
                by_type = {}
                for f in fibres:
                    t = f.get("type", "unknown")
                    by_type[t] = by_type.get(t, 0) + 1
                return {"by_type": by_type, "total": len(fibres)}
            except Exception as e:
                self._log.warning("inventory_strategic_memory_failed", error=str(e))
        return {"by_type": {}, "total": 0}

    # -------------------------------------------------------------------------
    # 8. RECORD FIBRE LOSS (Patent Claim 26.3 — Memorial Encoding)
    # -------------------------------------------------------------------------

    async def record_fibre_loss(
        self,
        fibre_id: str,
        cause: str = "atrophic_dissipation",
    ) -> Dict[str, Any]:
        """
        Record loss in strategic memory Layer 6. Trigger memorial encoding
        through ring_manager / memorial service. Patent Claim 26.3.
        """
        # Log to Layer 6
        if self.strategic_memory:
            try:
                await self.strategic_memory.log_swarm_event(
                    event_type="fibre_loss",
                    fibre_id=UUID(fibre_id) if self._is_valid_uuid(fibre_id) else None,
                    details={"cause": cause, "fibre_id": fibre_id},
                )
            except Exception as e:
                self._log.warning("record_loss_swarm_event_failed", error=str(e))

        # Memorial encoding via memorial_service (uses ring_manager internally)
        memorial = None
        if self.memorial_service:
            try:
                # Get last known health from trail if available
                last_health = 0.0
                if self.trail_map:
                    trails = getattr(self.trail_map, "_trails", {})
                    t = trails.get(fibre_id)
                    if t:
                        last_health = getattr(t, "communication_health", 0.0) or 0.0
                memorial = self.memorial_service.create_memorial(
                    lost_fibre_id=fibre_id,
                    lost_fibre_type="unknown",
                    last_health=last_health,
                    last_mission=cause,
                )
            except Exception as e:
                self._log.warning("memorial_creation_failed", fibre_id=fibre_id, error=str(e))

        # Dissolve ring if fibre was in one
        if self.ring_manager:
            try:
                ring = self.ring_manager.get_fibre_ring(fibre_id)
                if ring:
                    self.ring_manager.dissolve_ring(ring.ring_id)
            except Exception as e:
                self._log.warning("ring_dissolution_failed", fibre_id=fibre_id, error=str(e))

        return {
            "fibre_id": fibre_id,
            "cause": cause,
            "recorded": True,
            "memorial_created": memorial is not None,
        }

    # -------------------------------------------------------------------------
    # 9. GET SWARM OVERVIEW (Patent Claim 22 — Fleet-Level Overview)
    # -------------------------------------------------------------------------

    async def get_swarm_overview(self) -> SwarmState:
        """
        Build comprehensive SwarmState from all sources: fibre inventory,
        coherence, Quakete ring status, mesh health. Patent Claim 22.
        """
        fibres: List[FibreSummary] = []
        fibres_by_type: Dict[str, int] = {}
        fibres_by_autonomy: Dict[str, int] = {}

        # Fibre inventory
        if self.fibre_manager:
            try:
                items = await self.fibre_manager.inventory()
                for i in items:
                    fid = i.get("fibre_id", "")
                    fibres.append(
                        FibreSummary(
                            fibre_id=UUID(fid) if self._is_valid_uuid(fid) else uuid4(),
                            fibre_type=i.get("type", "unknown"),
                            status=i.get("status", "active"),
                            autonomy_level=i.get("autonomy", "observation"),
                            alignment_score=float((i.get("alignment") or {}).get("ethical", 1.0)),
                            token_budget_remaining=0.0,
                        )
                    )
                    fibres_by_type[i.get("type", "unknown")] = fibres_by_type.get(i.get("type", "unknown"), 0) + 1
                    fibres_by_autonomy[i.get("autonomy", "observation")] = (
                        fibres_by_autonomy.get(i.get("autonomy", "observation"), 0) + 1
                    )
            except Exception as e:
                self._log.warning("overview_fibre_inventory_failed", error=str(e))

        if not fibres and self.strategic_memory:
            try:
                overview = await self.strategic_memory.get_swarm_overview()
                for f in overview.get("fibres", []):
                    fid = f.get("fibre_id", str(uuid4()))
                    fibres.append(
                        FibreSummary(
                            fibre_id=UUID(fid) if self._is_valid_uuid(fid) else uuid4(),
                            fibre_type=f.get("type", "unknown"),
                            status=f.get("status", "active"),
                            autonomy_level=f.get("autonomy", "observation"),
                        )
                    )
                    fibres_by_type[f.get("type", "unknown")] = fibres_by_type.get(f.get("type", "unknown"), 0) + 1
            except Exception as e:
                self._log.warning("overview_strategic_memory_failed", error=str(e))

        # Coherence
        global_coherence: Optional[float] = None
        coherence_by_layer: Dict[str, float] = {}
        if self.coherence_engine:
            try:
                snap = await self.coherence_engine.generate_pulse_snapshot()
                global_coherence = snap.global_coherence_index
                coherence_by_layer = snap.layer_scores
            except Exception as e:
                self._log.warning("overview_coherence_failed", error=str(e))

        # Quakete rings
        total_rings = 0
        healthy_rings = 0
        distressed_rings = 0
        silent_fibres = 0
        if self.ring_manager:
            rings = self.ring_manager.all_rings
            total_rings = len(rings)
            for r in rings:
                state = getattr(r, "ring_state", None)
                if state == RingState.HEALTHY:
                    healthy_rings += 1
                else:
                    distressed_rings += 1
        if self.trail_map:
            silent_fibres = len(getattr(self.trail_map, "_silent_fibres", set()) or set())

        # Mesh health (from Wisdom Mesh metrics if available)
        mesh_messages_last_hour = 0
        convergence_alerts_last_hour = 0
        if self.wisdom_mesh:
            metrics = getattr(self.wisdom_mesh, "_metrics", {}) or {}
            mesh_messages_last_hour = metrics.get("messages_sent", 0)
            convergence_alerts_last_hour = metrics.get("convergence_alerts", 0)

        # Pending proposals
        pending_proposals = 0
        if self.strategic_memory:
            try:
                pending = await self.strategic_memory.get_pending_proposals()
                pending_proposals = len(pending)
            except Exception:
                pass

        return SwarmState(
            total_fibres=len(fibres),
            active_fibres=sum(1 for f in fibres if f.status == FibreStatus.ACTIVE.value),
            quarantined_fibres=sum(1 for f in fibres if f.status == FibreStatus.QUARANTINED.value),
            idle_fibres=sum(1 for f in fibres if f.status == FibreStatus.IDLE.value),
            fibres_by_type=fibres_by_type,
            fibres_by_autonomy=fibres_by_autonomy,
            fibres=fibres,
            global_coherence=global_coherence,
            coherence_by_layer=coherence_by_layer,
            total_rings=total_rings,
            healthy_rings=healthy_rings,
            distressed_rings=distressed_rings,
            silent_fibres=silent_fibres,
            mesh_messages_last_hour=mesh_messages_last_hour,
            convergence_alerts_last_hour=convergence_alerts_last_hour,
            pending_proposals=pending_proposals,
        )
