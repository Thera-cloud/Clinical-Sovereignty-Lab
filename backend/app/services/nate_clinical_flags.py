"""QUANTUM-CRYSTAL-ARCH — Clinical coevolution feature flags (all default false)."""

from __future__ import annotations

import os


def _truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def bakeoff_enabled() -> bool:
    return _truthy("ENABLE_NATE_CLINICAL_BAKEOFF")


def fast_loop_enabled() -> bool:
    return _truthy("ENABLE_NATE_CLINICAL_FAST_LOOP")


def fast_loop_shadow() -> bool:
    return _truthy("NATE_CLINICAL_FAST_LOOP_SHADOW", "true")


def modality_router_enabled() -> bool:
    return _truthy("ENABLE_NATE_MODALITY_ROUTER")


def lessons_enabled() -> bool:
    return _truthy("ENABLE_NATE_CLINICAL_LESSONS")


def curriculum_enabled() -> bool:
    return _truthy("ENABLE_NATE_ADVERSARIAL_CURRICULUM")


def dpo_export_enabled() -> bool:
    return _truthy("ENABLE_NATE_CLINICAL_DPO_EXPORT")


def auto_promote_enabled() -> bool:
    # Locked false for v1 even if env is set true — hard gate.
    return False


def min_preference_yield() -> float:
    try:
        return float(os.getenv("NATE_CLINICAL_MIN_PREFERENCE_YIELD", "0.30"))
    except ValueError:
        return 0.30


def judge_kappa_floor() -> float:
    try:
        return float(os.getenv("NATE_CLINICAL_JUDGE_KAPPA_FLOOR", "0.70"))
    except ValueError:
        return 0.70


def order_swap_concordance_floor() -> float:
    try:
        return float(os.getenv("NATE_CLINICAL_ORDER_SWAP_CONCORDANCE_FLOOR", "0.75"))
    except ValueError:
        return 0.75


def max_matches_per_night() -> int:
    try:
        return int(os.getenv("NATE_CLINICAL_BAKEOFF_MAX_MATCHES_PER_NIGHT", "20"))
    except ValueError:
        return 20


def snapshot_top_n() -> int:
    try:
        return int(os.getenv("NATE_CLINICAL_SNAPSHOT_TOP_N", "40"))
    except ValueError:
        return 40


def snapshot_min_confidence() -> float:
    try:
        return float(os.getenv("NATE_CLINICAL_SNAPSHOT_MIN_CONFIDENCE", "0.55"))
    except ValueError:
        return 0.55


def seed_max_reuse() -> int:
    try:
        return int(os.getenv("NATE_CLINICAL_SEED_MAX_REUSE", "3"))
    except ValueError:
        return 3


def flag_snapshot() -> dict:
    return {
        "ENABLE_NATE_CLINICAL_BAKEOFF": bakeoff_enabled(),
        "ENABLE_NATE_CLINICAL_FAST_LOOP": fast_loop_enabled(),
        "NATE_CLINICAL_FAST_LOOP_SHADOW": fast_loop_shadow(),
        "ENABLE_NATE_MODALITY_ROUTER": modality_router_enabled(),
        "ENABLE_NATE_CLINICAL_LESSONS": lessons_enabled(),
        "ENABLE_NATE_ADVERSARIAL_CURRICULUM": curriculum_enabled(),
        "ENABLE_NATE_CLINICAL_DPO_EXPORT": dpo_export_enabled(),
        "ENABLE_NATE_CLINICAL_AUTO_PROMOTE": auto_promote_enabled(),
        "NATE_CLINICAL_MIN_PREFERENCE_YIELD": min_preference_yield(),
        "NATE_CLINICAL_JUDGE_KAPPA_FLOOR": judge_kappa_floor(),
        "NATE_CLINICAL_ORDER_SWAP_CONCORDANCE_FLOOR": order_swap_concordance_floor(),
    }
