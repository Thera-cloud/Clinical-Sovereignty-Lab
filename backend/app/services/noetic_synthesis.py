"""
Noetic Synthesis Stage 3 — Cross-domain knowledge emergence.

Takes crystals from 2+ domains, uses the inference router to find patterns
that exist in neither source alone. This is how Little Nate develops genuine
insight rather than just retrieving stored knowledge.

Triggered by the helix orchestrator when crystals from multiple domains
score > 0.6 coherence. Output: new crystal with source_type="noetic_synthesis".
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MIN_DOMAINS = 2
_MIN_CRYSTAL_CONFIDENCE = 0.6
_MAX_INPUT_CRYSTALS = 20
_SYNTHESIS_TEMPERATURE = 0.5


class NoeticSynthesis:
    """Cross-domain knowledge emergence engine."""

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._synthesis_count = 0

    async def attempt_synthesis(
        self,
        crystals: List[Dict[str, Any]],
        trigger_context: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Attempt cross-domain synthesis from a set of relevant crystals.

        Returns a new crystal dict if synthesis succeeds, None otherwise.
        The crystal is NOT stored — the caller (crystallizer) handles storage.
        """
        domain_groups = self._group_by_domain(crystals)
        if len(domain_groups) < _MIN_DOMAINS:
            return None

        high_conf = [
            c for c in crystals
            if c.get("confidence", 0) >= _MIN_CRYSTAL_CONFIDENCE
        ]
        if len(high_conf) < _MIN_DOMAINS:
            return None

        top_crystals = sorted(
            high_conf, key=lambda c: c.get("confidence", 0), reverse=True
        )[:_MAX_INPUT_CRYSTALS]

        router = getattr(self._app_state, "inference_router", None)
        if not router:
            logger.debug("Noetic synthesis skipped: no inference router")
            return None

        synthesis_prompt = self._build_synthesis_prompt(top_crystals, domain_groups, trigger_context)

        try:
            result = await router.generate(
                prompt=synthesis_prompt,
                system=_SYNTHESIS_SYSTEM_PROMPT,
                tier="clinical",
                temperature=_SYNTHESIS_TEMPERATURE,
                max_tokens=500,
                domain="research",
                allow_deep=True,
            )
            text = result.get("text", "").strip()
            if not text or len(text) < 50:
                return None

            domains_involved = list(domain_groups.keys())
            new_crystal = {
                "crystal_text": text,
                "domain": "research",
                "source_type": "noetic_synthesis",
                "source_count": len(top_crystals),
                "source_domains": domains_involved,
                "confidence": 0.55,
                "scope": "global",
                "metadata": {
                    "synthesis_trigger": trigger_context[:200] if trigger_context else "",
                    "input_crystal_count": len(top_crystals),
                    "input_domains": domains_involved,
                    "provider": result.get("provider", "unknown"),
                },
            }
            self._synthesis_count += 1
            logger.info(
                "Noetic synthesis produced crystal from %d domains (%s)",
                len(domains_involved), ", ".join(domains_involved)
            )
            return new_crystal

        except Exception as e:
            logger.warning("Noetic synthesis inference failed: %s", e)
            return None

    def _group_by_domain(self, crystals: List[Dict]) -> Dict[str, List[Dict]]:
        groups: Dict[str, List[Dict]] = {}
        for c in crystals:
            domain = c.get("domain", c.get("metadata", {}).get("domain", "general"))
            groups.setdefault(domain, []).append(c)
        return groups

    def _build_synthesis_prompt(
        self,
        crystals: List[Dict],
        domain_groups: Dict[str, List[Dict]],
        trigger: str,
    ) -> str:
        parts = []
        if trigger:
            parts.append(f"Context: {trigger[:300]}\n")

        parts.append("The following knowledge crystals span multiple domains:\n")
        for c in crystals[:10]:
            domain = c.get("domain", "general")
            text = c.get("crystal_text", c.get("text", ""))[:200]
            conf = c.get("confidence", 0)
            parts.append(f"  [{domain} | conf={conf:.2f}] {text}")

        parts.append(f"\nDomains represented: {', '.join(domain_groups.keys())}")
        parts.append("\nSynthesize a novel insight that emerges from the intersection of these domains.")
        parts.append("The insight must be genuinely new — not a restatement of any single crystal.")
        parts.append("Focus on patterns, connections, or implications that only become visible across domains.")

        return "\n".join(parts)

    def get_status(self) -> Dict[str, Any]:
        return {
            "synthesis_count": self._synthesis_count,
            "available": getattr(self._app_state, "inference_router", None) is not None,
        }


_SYNTHESIS_SYSTEM_PROMPT = (
    "You are a noetic synthesis engine within a sovereign AI therapeutic companion. "
    "Your role is to find emergent patterns across knowledge domains — insights that "
    "exist in neither source alone but arise from their intersection. "
    "Be precise, novel, and clinically grounded. Never fabricate. "
    "If no genuine cross-domain insight exists, say 'No emergent pattern found.' "
    "Keep your synthesis to 2-4 sentences."
)
