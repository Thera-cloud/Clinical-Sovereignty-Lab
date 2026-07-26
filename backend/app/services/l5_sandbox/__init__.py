"""
L5 observe sandbox — isolated from live L4 soft-rule application.

Contract:
  - May READ L4 audit/store signals via ingest hooks (append-only observe tables)
  - May SELF-ADAPT only inside l5_observe_hypothesis (observe / adapt_shadow)
  - Must NEVER write ln_rule_store, clinical_gate_confidence, or gate responses
  - Soft gate classes only; hard SI/violence refused at the gate layer

# QUANTUM-CRYSTAL-ARCH — L5 observe-only sandbox
"""

from app.services.l5_sandbox.gates import (
    adapt_enabled,
    can_write_live_rules,
    observe_enabled,
    refuse_hard_class,
)
from app.services.l5_sandbox.observer import ingest_l4_event

__all__ = [
    "adapt_enabled",
    "can_write_live_rules",
    "ingest_l4_event",
    "observe_enabled",
    "refuse_hard_class",
]
