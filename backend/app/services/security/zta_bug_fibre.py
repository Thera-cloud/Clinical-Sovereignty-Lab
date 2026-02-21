"""
HIVE DEFENSE v4.4 — ZTA Bug Fibre
Layer 4 of Castle Defense architecture.

Specialized tracing Fibre that attaches to the PipelineDrum's resonance
engine output.  Traces every signal through the mirror boundary and pairs
with Skeptic + Critic guards for adversarial evaluation.

The ZTA Bug captures the full signal path:
  origin → drum sensor → resonance level → mirror reflection → response

If the Skeptic and Critic disagree, the bug escalates to the SentinelMesh.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("hive.zta_bug")

MAX_TRACE_HISTORY = 500
DISAGREEMENT_THRESHOLD = 0.4  # Skeptic-Critic spread that triggers escalation


@dataclass
class DrumTrace:
    """A captured signal trace from the PipelineDrum."""
    trace_id: str = ""
    timestamp: float = 0.0
    source_ip: str = ""
    path: str = ""
    method: str = ""
    user_id: str = ""
    sensors: Dict[str, float] = field(default_factory=dict)
    resonance_level: int = 0
    resonance_score: float = 0.0
    skeptic_malice: float = 0.0
    critic_innocence: float = 0.0
    consensus: str = ""  # "agree_safe", "agree_threat", "disagreement"
    escalated: bool = False
    meta_signal: float = 0.0  # Fed back into Drum

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "source_ip": self.source_ip,
            "path": self.path,
            "user_id": self.user_id,
            "sensors": self.sensors,
            "resonance_level": self.resonance_level,
            "resonance_score": round(self.resonance_score, 3),
            "skeptic_malice": round(self.skeptic_malice, 3),
            "critic_innocence": round(self.critic_innocence, 3),
            "consensus": self.consensus,
            "escalated": self.escalated,
            "meta_signal": round(self.meta_signal, 3),
        }


class ZTABugFibre:
    """
    Tracing Fibre that sits between the PipelineDrum and the MirrorShell.
    Captures signal traces and feeds them through Skeptic + Critic guards.
    """

    def __init__(self):
        self._traces: Deque[DrumTrace] = deque(maxlen=MAX_TRACE_HISTORY)
        self._skeptic: Optional[Any] = None  # SkepticGuard
        self._critic: Optional[Any] = None   # CriticGuard
        self._sentinel_mesh: Optional[Any] = None
        self._escalation_count = 0
        self._total_traces = 0
        self._agreement_count = 0
        self._disagreement_count = 0
        logger.info("ZTA Bug Fibre initialized")

    def attach_guards(self, skeptic, critic) -> None:
        """Attach Skeptic and Critic guard Fibres."""
        self._skeptic = skeptic
        self._critic = critic
        logger.info("ZTA Bug: Skeptic + Critic guards attached")

    def attach_sentinel_mesh(self, mesh) -> None:
        """Attach SentinelMesh for escalation."""
        self._sentinel_mesh = mesh

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "total_traces": self._total_traces,
            "recent_traces": len(self._traces),
            "agreements": self._agreement_count,
            "disagreements": self._disagreement_count,
            "escalations": self._escalation_count,
            "guards_attached": self._skeptic is not None and self._critic is not None,
        }

    async def trace(
        self,
        trace_id: str,
        sensors: Dict[str, float],
        resonance_level: int,
        resonance_score: float,
        source_ip: str = "",
        path: str = "",
        method: str = "",
        user_id: str = "",
    ) -> DrumTrace:
        """
        Capture a signal trace from the PipelineDrum and evaluate it
        through the Skeptic + Critic guard pair.

        Returns the trace with consensus and meta-signal.
        """
        self._total_traces += 1

        trace = DrumTrace(
            trace_id=trace_id,
            timestamp=time.time(),
            source_ip=source_ip,
            path=path,
            method=method,
            user_id=user_id,
            sensors=sensors,
            resonance_level=resonance_level,
            resonance_score=resonance_score,
        )

        # Evaluate through Skeptic guard
        if self._skeptic:
            trace.skeptic_malice = await self._skeptic.evaluate(
                sensors=sensors,
                resonance_level=resonance_level,
                resonance_score=resonance_score,
                source_ip=source_ip,
                path=path,
                user_id=user_id,
            )

        # Evaluate through Critic guard
        if self._critic:
            trace.critic_innocence = await self._critic.evaluate(
                sensors=sensors,
                resonance_level=resonance_level,
                resonance_score=resonance_score,
                source_ip=source_ip,
                path=path,
                user_id=user_id,
                skeptic_malice=trace.skeptic_malice,
            )

        # Determine consensus
        spread = abs(trace.skeptic_malice - (1.0 - trace.critic_innocence))

        if spread < DISAGREEMENT_THRESHOLD:
            # Consensus
            combined = (trace.skeptic_malice + (1.0 - trace.critic_innocence)) / 2
            if combined > 0.6:
                trace.consensus = "agree_threat"
            else:
                trace.consensus = "agree_safe"
            self._agreement_count += 1
        else:
            # Disagreement — escalate
            trace.consensus = "disagreement"
            trace.escalated = True
            self._disagreement_count += 1
            self._escalation_count += 1

            if self._sentinel_mesh:
                try:
                    await self._sentinel_mesh.on_zta_escalation(trace.to_dict())
                except Exception as e:
                    logger.warning("Sentinel escalation failed: %s", e)

            logger.warning(
                "ZTA Bug DISAGREEMENT: trace=%s skeptic=%.2f critic=%.2f spread=%.2f",
                trace.trace_id, trace.skeptic_malice,
                trace.critic_innocence, spread,
            )

        # Compute meta-signal (fed back into the Drum as 5th signal)
        if trace.consensus == "agree_threat":
            trace.meta_signal = trace.skeptic_malice * 1.2
        elif trace.consensus == "disagreement":
            trace.meta_signal = max(trace.skeptic_malice, 1.0 - trace.critic_innocence) * 0.8
        else:
            trace.meta_signal = 0.0

        self._traces.append(trace)
        return trace

    def get_recent_traces(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent traces for monitoring."""
        traces = list(self._traces)
        traces.reverse()
        return [t.to_dict() for t in traces[:limit]]

    def get_escalations(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get traces that triggered escalation."""
        escalated = [t for t in self._traces if t.escalated]
        escalated.reverse()
        return [t.to_dict() for t in escalated[:limit]]


# Singleton
_bug_instance: Optional[ZTABugFibre] = None


def get_zta_bug() -> ZTABugFibre:
    global _bug_instance
    if _bug_instance is None:
        _bug_instance = ZTABugFibre()
    return _bug_instance
