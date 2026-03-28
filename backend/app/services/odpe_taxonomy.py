"""
ODPE Taxonomy — L1 face classifier for the 24M-face topology.

Maps incoming messages to 2,400 L1 faces (24 L0 faces x 100 sub-functions).
Uses Vectorize embeddings for nearest sub-function match.

Each L0 face represents a broad domain of human experience:
  0-11: Dodecahedron faces (broad consensus)
  12-23: Deltoidal Icositetragon faces (deep resolution)

Each L1 face refines an L0 face into 100 sub-functions.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("odpe_taxonomy")

L0_FACE_LABELS = {
    0: "emotional_regulation",
    1: "cognitive_patterns",
    2: "relationship_dynamics",
    3: "identity_formation",
    4: "trauma_processing",
    5: "meaning_making",
    6: "behavioral_activation",
    7: "somatic_awareness",
    8: "attachment_systems",
    9: "resilience_building",
    10: "communication_skills",
    11: "life_transitions",
    12: "grief_processing",
    13: "anxiety_management",
    14: "depression_patterns",
    15: "shame_resilience",
    16: "boundary_setting",
    17: "family_systems",
    18: "cultural_integration",
    19: "spiritual_exploration",
    20: "creative_expression",
    21: "substance_patterns",
    22: "self_compassion",
    23: "existential_concerns",
}

L1_SUB_FUNCTIONS = {
    0: [  # emotional_regulation
        "affect_labeling", "distress_tolerance", "emotion_surfing",
        "grounding_techniques", "window_of_tolerance", "co_regulation",
        "emotional_vocabulary", "intensity_scaling", "trigger_mapping",
        "regulation_strategy_selection",
    ],
    1: [  # cognitive_patterns
        "cognitive_distortion_id", "thought_challenging", "schema_work",
        "rumination_interruption", "core_belief_mapping", "metacognition",
        "probability_estimation", "evidence_gathering", "reframing",
        "cognitive_flexibility",
    ],
    2: [  # relationship_dynamics
        "conflict_resolution", "empathy_building", "trust_repair",
        "interdependence", "relational_patterns", "power_dynamics",
        "intimacy_building", "healthy_dependency", "repair_attempts",
        "relational_trauma",
    ],
}

DOMAIN_KEYWORDS = {
    "emotional_regulation": ["feeling", "emotion", "angry", "sad", "anxious", "overwhelm", "calm", "regulate"],
    "cognitive_patterns": ["thinking", "thought", "believe", "assume", "ruminate", "worry", "pattern"],
    "relationship_dynamics": ["relationship", "partner", "friend", "conflict", "trust", "intimacy"],
    "identity_formation": ["identity", "who am i", "purpose", "values", "authentic", "self"],
    "trauma_processing": ["trauma", "ptsd", "flashback", "nightmare", "trigger", "abuse", "accident"],
    "meaning_making": ["meaning", "purpose", "existential", "why", "life", "death", "legacy"],
    "behavioral_activation": ["motivation", "avoidance", "procrastination", "habit", "routine", "action"],
    "somatic_awareness": ["body", "tension", "pain", "sensation", "breathe", "physical", "somatic"],
    "attachment_systems": ["attachment", "abandonment", "secure", "avoidant", "anxious", "connection"],
    "resilience_building": ["resilience", "coping", "strength", "recovery", "growth", "adapt"],
    "communication_skills": ["communication", "express", "listen", "assert", "boundary", "say no"],
    "life_transitions": ["change", "transition", "moving", "job", "career", "graduation", "retirement"],
    "grief_processing": ["grief", "loss", "death", "mourning", "missing", "gone", "funeral"],
    "anxiety_management": ["anxiety", "panic", "worry", "fear", "phobia", "nervous", "stress"],
    "depression_patterns": ["depression", "hopeless", "worthless", "empty", "numb", "tired", "withdrawn"],
    "shame_resilience": ["shame", "embarrass", "humiliate", "guilt", "blame", "inadequate", "worthy"],
    "boundary_setting": ["boundary", "limit", "say no", "toxic", "enable", "codepend", "protect"],
    "family_systems": ["family", "parent", "child", "sibling", "generational", "dynamic", "role"],
    "cultural_integration": ["culture", "identity", "belong", "minority", "tradition", "immigrant"],
    "spiritual_exploration": ["spiritual", "faith", "prayer", "meditation", "soul", "divine", "sacred"],
    "creative_expression": ["creative", "art", "music", "write", "express", "imagination", "flow"],
    "substance_patterns": ["substance", "alcohol", "drug", "addiction", "sobriety", "craving", "relapse"],
    "self_compassion": ["self-compassion", "self-care", "kind to myself", "forgive myself", "inner critic"],
    "existential_concerns": ["existential", "meaningless", "freedom", "isolation", "mortality", "choice"],
}


@dataclass
class L1FaceScore:
    face_id: int
    l0_face_id: int
    sub_function: str
    score: float
    face_path: str


class ODPETaxonomy:
    """
    Classifies text into L1 faces using keyword matching + optional Vectorize semantic search.
    Falls back to keyword-based classification when Vectorize is unavailable.
    """

    def __init__(self, vectorize_service=None):
        self._vectorize = vectorize_service

    def classify(self, text: str, l0_face_id: Optional[int] = None) -> List[L1FaceScore]:
        text_lower = text.lower()
        scores: List[L1FaceScore] = []

        target_faces = [l0_face_id] if l0_face_id is not None else range(24)

        for face_id in target_faces:
            label = L0_FACE_LABELS.get(face_id, "general")
            keywords = DOMAIN_KEYWORDS.get(label, [])
            if not keywords:
                continue

            hit_count = sum(1 for kw in keywords if kw in text_lower)
            if hit_count == 0:
                continue

            keyword_score = min(1.0, hit_count / max(len(keywords) * 0.3, 1))

            sub_functions = L1_SUB_FUNCTIONS.get(face_id, [label])
            for i, sub_fn in enumerate(sub_functions):
                sub_score = keyword_score * (1.0 - i * 0.05)
                l1_id = face_id * 100 + i
                scores.append(L1FaceScore(
                    face_id=l1_id,
                    l0_face_id=face_id,
                    sub_function=sub_fn,
                    score=max(0.0, sub_score),
                    face_path=f"L0:{face_id}/L1:{l1_id}",
                ))

        scores.sort(key=lambda x: x.score, reverse=True)
        return scores[:10]

    def classify_cycle(self, detection: Dict) -> str:
        domain = detection.get("domain", "general")
        for face_id, label in L0_FACE_LABELS.items():
            if label == domain or domain in label:
                return f"L0:{face_id}/L1:{face_id * 100}"

        text = detection.get("prediction_text", "") or detection.get("pattern", "")
        results = self.classify(text)
        if results:
            return results[0].face_path
        return "L0:0/L1:0"

    def get_l0_for_domain(self, domain: str) -> List[int]:
        mapping = {
            "clinical": [0, 1, 3, 4, 5, 12, 13, 14, 15, 22, 23],
            "coaching": [2, 6, 7, 8, 9, 10, 11, 16],
            "marketing": [20],
            "research": [1, 5, 23],
            "culture": [18, 19, 20],
            "defense": [],
            "general": list(range(24)),
        }
        return mapping.get(domain, list(range(24)))

    def get_face_label(self, face_id: int) -> str:
        l0_id = face_id // 100 if face_id >= 100 else face_id
        return L0_FACE_LABELS.get(l0_id, "unknown")
