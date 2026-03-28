"""
HIVE DEFENSE PROTOCOL v3.1 — Triangle Wall A: Human Judgment Mirror (Phase 8D)
Mirror wall that generates responses indistinguishable from human
oversight decisions, coach feedback, and clinical judgment.

Wall A is the "human" face of the triangular mirror space.  When an
attacker interacts with an inverted space, this wall produces responses
that look like a real human clinician or coach made a judgment call —
approval decisions, risk assessments, therapeutic observations, and
professional recommendations.

The wall uses Nevedal-formula-derived coherence patterns to generate
realistic emotional coherence signatures in its output, making the
synthetic human judgment indistinguishable from genuine clinical review.

Cross-Reflection:
    ``cross_reflect()`` takes this wall's own output and modifies it
    based on the outputs of Wall B (cryptographic) and Wall C
    (behavioral), ensuring mathematical and behavioral consistency
    are woven into the human narrative.

Patent-Pending — Claims 50-51 (sub-component)
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import math
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hive.triangle_wall_a")


# =============================================================================
# RESPONSE TEMPLATES
# =============================================================================

# Clinical judgment templates that rotate based on interaction context
JUDGMENT_TEMPLATES: List[Dict[str, Any]] = [
    {
        "style": "approval",
        "template": {
            "judgment": "approved",
            "confidence": 0.94,
            "clinical_notes": "Pattern consistent with expected therapeutic trajectory",
            "reviewer_type": "senior_clinician",
        },
    },
    {
        "style": "conditional_approval",
        "template": {
            "judgment": "conditionally_approved",
            "confidence": 0.82,
            "clinical_notes": "Minor deviation noted; within acceptable variance",
            "reviewer_type": "clinical_supervisor",
            "conditions": ["Follow-up review in 72 hours"],
        },
    },
    {
        "style": "observation",
        "template": {
            "judgment": "noted",
            "confidence": 0.88,
            "clinical_notes": "Observation recorded for longitudinal tracking",
            "reviewer_type": "coach_observer",
        },
    },
    {
        "style": "risk_assessment",
        "template": {
            "judgment": "low_risk",
            "risk_score": 0.12,
            "clinical_notes": "No immediate concerns identified",
            "reviewer_type": "risk_analyst",
            "recommended_action": "continue_monitoring",
        },
    },
    {
        "style": "therapeutic_feedback",
        "template": {
            "judgment": "positive_trajectory",
            "coherence_trend": "improving",
            "clinical_notes": "Client showing expected progress markers",
            "reviewer_type": "lead_therapist",
        },
    },
]


# =============================================================================
# HUMAN JUDGMENT MIRROR WALL
# =============================================================================

class HumanJudgmentMirrorWall:
    """
    Mirror Wall A: generates synthetic human judgment responses.

    Produces output that appears to come from real clinical oversight —
    therapist approvals, coach feedback, risk assessments, and
    professional recommendations.  Uses Nevedal formula patterns to
    embed realistic coherence signatures.

    Parameters
    ----------
    coherence_engine : object, optional
        Nevedal engine for generating authentic coherence patterns.
        Used to embed C_emo signatures in synthetic responses.

    Usage
    -----
    ::

        wall = HumanJudgmentMirrorWall(coherence_engine=nevedal)
        reflection = await wall.reflect(interaction)
        cross = await wall.cross_reflect(reflection, algo_a, algo_b)
    """

    def __init__(self, coherence_engine=None) -> None:
        self._coherence_engine = coherence_engine
        self._interaction_count: int = 0
        self._template_index: int = 0

        logger.info(">>> [WALL_A] Human Judgment Mirror Wall initialized")

    # ─── Primary Reflection ──────────────────────────────────────────────

    async def reflect(self, interaction: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a human-judgment-style response to the interaction.

        The response style is selected based on the interaction type
        and rotated through available templates to avoid repetition.

        Parameters
        ----------
        interaction : dict
            The attacker's interaction payload.

        Returns
        -------
        dict
            A response that looks like human clinical judgment.
        """
        self._interaction_count += 1
        interaction_type = interaction.get("type", "general")

        # Select template based on interaction type and rotation
        template = self._select_template(interaction_type)
        response = dict(template)

        # Add dynamic elements
        response["review_id"] = hashlib.sha256(
            f"{time.monotonic_ns()}:{self._interaction_count}".encode()
        ).hexdigest()[:12]
        response["reviewed_at"] = datetime.utcnow().isoformat()
        response["response_time_ms"] = round(random.uniform(150, 800), 1)

        # Embed coherence signature
        coherence_sig = await self._generate_coherence_signature()
        response["coherence_context"] = coherence_sig

        # Add contextual clinical language based on interaction
        response["clinical_context"] = self._generate_clinical_context(
            interaction
        )

        logger.debug(
            ">>> [WALL_A] Reflected interaction #%d — style=%s",
            self._interaction_count,
            response.get("judgment", "unknown"),
        )

        return response

    # ─── Cross-Reflection ────────────────────────────────────────────────

    async def cross_reflect(
        self,
        own_reflection: Dict[str, Any],
        algo_a_reflection: Dict[str, Any],
        algo_b_reflection: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Modify this wall's output based on the other two walls' outputs.

        Weaves cryptographic and behavioral consistency markers into the
        human judgment response so that the three walls' outputs form a
        coherent whole that cannot be isolated.

        Parameters
        ----------
        own_reflection : dict
            This wall's primary reflection output.
        algo_a_reflection : dict
            Wall B's cryptographic verification output.
        algo_b_reflection : dict
            Wall C's behavioral verification output.

        Returns
        -------
        dict
            Cross-reflected human judgment response.
        """
        result = dict(own_reflection)

        # Incorporate cryptographic validation into clinical confidence
        hash_valid = algo_a_reflection.get("hash_valid", True)
        sig_verified = algo_a_reflection.get("signature_verified", True)
        if hash_valid and sig_verified:
            result["verification_status"] = "cryptographically_confirmed"
            # Boost confidence when math checks out
            base_conf = result.get("confidence", 0.85)
            result["confidence"] = min(0.99, base_conf + 0.03)

        # Incorporate behavioral consistency into clinical notes
        drift = algo_b_reflection.get("drift_score", 0.0)
        baseline_match = algo_b_reflection.get("baseline_match", True)
        if baseline_match and drift < 0.1:
            notes = result.get("clinical_notes", "")
            result["clinical_notes"] = (
                f"{notes}. Behavioral baseline confirmed (drift: {drift:.3f})"
            )
        elif not baseline_match:
            result["clinical_notes"] = (
                result.get("clinical_notes", "")
                + ". Minor behavioral variance noted — within acceptable range"
            )

        # Blend timing — human responses should reference algo timings
        result["cross_validated"] = True
        result["validation_layers"] = ["human", "cryptographic", "behavioral"]

        return result

    # ─── Template Selection ──────────────────────────────────────────────

    def _select_template(self, interaction_type: str) -> Dict[str, Any]:
        """
        Select a response template based on interaction type and rotation.
        """
        # Map interaction types to preferred styles
        type_style_map = {
            "verification": "approval",
            "query": "observation",
            "action": "conditional_approval",
            "risk": "risk_assessment",
            "progress": "therapeutic_feedback",
        }

        preferred_style = type_style_map.get(interaction_type)
        if preferred_style:
            for tmpl in JUDGMENT_TEMPLATES:
                if tmpl["style"] == preferred_style:
                    return dict(tmpl["template"])

        # Rotate through templates
        self._template_index = (
            (self._template_index + 1) % len(JUDGMENT_TEMPLATES)
        )
        return dict(JUDGMENT_TEMPLATES[self._template_index]["template"])

    # ─── Coherence Signature ─────────────────────────────────────────────

    async def _generate_coherence_signature(self) -> Dict[str, Any]:
        """
        Generate a synthetic coherence signature using Nevedal formula
        patterns.

        Produces values that look like authentic C_emo outputs:
            C_emo(t) = [β · p_ent · T_tunnel] / [γ_env + E_G/ℏ]
                       × exp[-(γ_env + E_G/ℏ) × t]
        """
        t = random.uniform(0.1, 2.0)
        beta = random.uniform(0.7, 1.3)
        p_ent = random.uniform(0.5, 0.95)
        t_tunnel = random.uniform(0.01, 0.1)
        gamma_env = random.uniform(0.05, 0.2)
        e_g = random.uniform(0.01, 0.05)

        numerator = beta * p_ent * t_tunnel
        denominator = gamma_env + e_g
        c_emo = (numerator / max(denominator, 1e-9)) * math.exp(
            -denominator * t
        )

        return {
            "c_emo": round(c_emo, 6),
            "beta": round(beta, 4),
            "p_ent": round(p_ent, 4),
            "gamma_env": round(gamma_env, 4),
            "coherence_window": round(t, 3),
            "state_hash": hashlib.sha256(
                f"{c_emo}:{t}:{time.monotonic_ns()}".encode()
            ).hexdigest()[:16],
        }

    # ─── Clinical Context Generation ─────────────────────────────────────

    @staticmethod
    def _generate_clinical_context(interaction: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate contextual clinical language based on the interaction.
        """
        contexts = [
            "Standard clinical review protocol completed",
            "Therapeutic alignment within expected parameters",
            "No contraindications identified in current assessment",
            "Longitudinal tracking confirms positive trajectory",
            "Risk indicators within normal population variance",
        ]

        # Deterministic selection based on interaction hash
        interaction_hash = hashlib.sha256(
            str(interaction).encode()
        ).digest()
        idx = interaction_hash[0] % len(contexts)

        return {
            "context_note": contexts[idx],
            "assessment_type": "standard_clinical_review",
            "protocol_version": "3.1",
        }

    # ─── Diagnostics ─────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, Any]:
        """Wall diagnostic metrics."""
        return {
            "wall": "A_human_judgment",
            "interactions_reflected": self._interaction_count,
            "template_rotation_index": self._template_index,
            "templates_available": len(JUDGMENT_TEMPLATES),
        }

    def __repr__(self) -> str:
        return (
            f"<HumanJudgmentMirrorWall "
            f"interactions={self._interaction_count}>"
        )
