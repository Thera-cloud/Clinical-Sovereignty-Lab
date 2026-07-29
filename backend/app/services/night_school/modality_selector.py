"""
SOVEREIGN SWARM — Night School Modality Selector
Selects appropriate therapeutic modalities for parsed content.

Operational Specifications §3.2 — Modality Selection.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger("night_school.modality_selector")


# Modality keyword maps
MODALITY_KEYWORDS = {
    "EFT": ["emotionally focused", "eft", "attachment bond", "emotional engagement", "tango", "enactment"],
    "attachment_theory": ["attachment", "secure base", "safe haven", "internal working model", "bowlby", "ainsworth"],
    "narrative_therapy": ["narrative", "externalize", "story", "re-authoring", "dominant narrative"],
    "somatic_experiencing": ["somatic", "body sensation", "felt sense", "nervous system", "regulation"],
    "IFS": ["internal family systems", "ifs", "parts", "self-energy", "protector", "exile"],
    "gottman_method": ["gottman", "four horsemen", "repair attempt", "love map", "sound relationship"],
    "DBT": ["dialectical", "dbt", "distress tolerance", "emotion regulation", "mindfulness"],
    "CBT": ["cognitive behavioral", "cbt", "thought record", "cognitive distortion", "behavioral activation"],
    "MI": [
        "motivational interviewing", "change talk", "roll with resistance",
        "ambivalence", "evoking", "sustain talk", "oars", "develop discrepancy",
    ],
    "ACT": [
        "acceptance and commitment", "act therapy", "cognitive defusion",
        "values-based", "psychological flexibility", "experiential avoidance",
    ],
    "psychodynamic": ["psychodynamic", "transference", "countertransference", "unconscious", "defense mechanism"],
    "trauma_informed": ["trauma", "ptsd", "emdr", "flashback", "hypervigilance", "dissociation"],
    "family_systems": ["family system", "differentiation", "triangulation", "genogram", "bowen"],
    "crisis_intervention": ["crisis", "suicide", "safety plan", "de-escalation", "risk assessment"],
}


class ModalitySelector:
    """Selects therapeutic modalities based on parsed content analysis."""

    async def select_modalities(
        self, parsed_content: Dict[str, Any]
    ) -> List[str]:
        """
        Analyze parsed content and return a list of relevant modalities,
        ordered by relevance score.
        """
        scores: Dict[str, float] = {}

        # Collect all text from parsed content
        all_text = ""
        for section in parsed_content.get("sections", []):
            all_text += " " + section.get("content", "")
        for protocol in parsed_content.get("protocols", []):
            all_text += " " + protocol.get("context", "")
        for technique in parsed_content.get("techniques", []):
            all_text += " " + technique.get("context", "")

        lower_text = all_text.lower()

        # Score each modality
        for modality, keywords in MODALITY_KEYWORDS.items():
            count = sum(lower_text.count(kw) for kw in keywords)
            if count > 0:
                scores[modality] = min(count / 10.0, 1.0)

        # Sort by score and return top modalities
        sorted_modalities = sorted(
            scores.items(), key=lambda x: x[1], reverse=True
        )
        return [m for m, s in sorted_modalities if s > 0.1]

    def get_primary_modality(self, modalities: List[str]) -> str:
        """Get the primary modality from a list."""
        return modalities[0] if modalities else "general"
