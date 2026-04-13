"""CreativeDirective — the single authoritative payload dispatched to SSE/Studio.

Produced by the UCD decision flow:
  TMC -> Modality Selector -> Temporal Orchestrator -> LoRA -> NCE read -> CreativeDirective
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


MOMENT_CLASSES = (
    "THRESHOLD", "BREAKTHROUGH", "INTEGRATION",
    "RECURRENCE", "REST", "CRISIS", "HERITAGE",
)

MODALITIES = (
    "panel", "video", "audio_narrative",
    "text_reflection", "guided_meditation", "composite",
)

PIPELINE_TARGETS = ("sse", "studio", "both")


@dataclass
class CreativeDirective:
    directive_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    moment_class: str = "REST"
    selected_modality: str = "panel"
    pipeline_target: str = "sse"
    delivery_window: dict = field(default_factory=dict)
    lora_model_ref: Optional[str] = None
    nso_snapshot: Optional[dict] = None
    intensity: float = 0.0
    coherence_context: str = ""
    trigger: str = "manual"
    tmc_confidence: float = 0.0
    safety_gate: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    narrative_context: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict) -> "CreativeDirective":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


async def log_directive(directive: CreativeDirective, db_pool) -> None:
    """Persist a CreativeDirective to ucd_creative_directives table."""
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO ucd_creative_directives "
                "(directive_id, user_id, moment_class, selected_modality, "
                "delivery_window, lora_model_ref, nso_snapshot, "
                "directive_payload, pipeline_target, status) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                uuid.UUID(directive.directive_id),
                directive.user_id,
                directive.moment_class,
                directive.selected_modality,
                json.dumps(directive.delivery_window),
                directive.lora_model_ref,
                json.dumps(directive.nso_snapshot, default=str) if directive.nso_snapshot else None,
                directive.to_json(),
                directive.pipeline_target,
                "pending",
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Directive log failed: %s", e)


async def mark_directive_executed(directive_id: str, db_pool) -> None:
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "UPDATE ucd_creative_directives SET status='executed', "
                "executed_at=NOW() WHERE directive_id=$1",
                uuid.UUID(directive_id),
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Directive mark-executed failed: %s", e)
