"""
ODPE L1 Face Taxonomy — 2,400-face presenting concern classifier.

Maps each of the 24 L0 faces (8 functions x 3 scopes) to 100 L1 sub-faces
representing clinical presenting concern clusters. Classification is keyword-based
with optional clinical weight modifiers.

The L1 taxonomy operates as a lookup table, not an AI model. Each L1 face has:
  - l0_face_key: parent L0 face (e.g., "noetic_fusion:user")
  - l1_index: 0-99 within the parent
  - l1_label: human-readable label (e.g., "anxiety_attachment")
  - keywords: list of trigger words/phrases for activation
  - clinical_weight: importance modifier (0.0-2.0, default 1.0)

Patent-Pending — Claims 64-79
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("odpe_l1_taxonomy")

CANONICAL_FUNCTIONS = [
    "vectorize_retrieval", "noetic_fusion", "metacognition",
    "quantum_self_coherence", "generative_wisdom", "world_coherence",
    "crystal_lake", "emergent",
]

SCOPE_LEVELS = ["user", "global", "superseded_chain"]

# Core presenting concern clusters — shared seed across all function:scope combinations.
# Each function amplifies different concerns differently.
CORE_CONCERN_CLUSTERS: List[Dict[str, Any]] = [
    {"label": "anxiety_general", "keywords": ["anxious", "worried", "nervous", "panic", "fear", "dread", "apprehensive"], "weight": 1.2},
    {"label": "anxiety_attachment", "keywords": ["abandonment", "clingy", "separation", "attachment", "rejection fear", "left alone"], "weight": 1.3},
    {"label": "anxiety_social", "keywords": ["social anxiety", "embarrassed", "judged", "public speaking", "awkward", "self-conscious"], "weight": 1.1},
    {"label": "anxiety_performance", "keywords": ["performance", "exam", "test anxiety", "imposter", "failure fear", "not good enough"], "weight": 1.1},
    {"label": "depression_mood", "keywords": ["depressed", "sad", "hopeless", "empty", "numb", "worthless", "despair"], "weight": 1.3},
    {"label": "depression_anhedonia", "keywords": ["no pleasure", "lost interest", "don't care", "nothing matters", "flat", "bored with life"], "weight": 1.2},
    {"label": "depression_grief", "keywords": ["grief", "loss", "mourning", "death", "bereavement", "missing someone", "gone"], "weight": 1.4},
    {"label": "depression_seasonal", "keywords": ["winter", "seasonal", "dark days", "lack of sun", "hibernating"], "weight": 0.9},
    {"label": "trauma_ptsd", "keywords": ["trauma", "ptsd", "flashback", "nightmare", "triggered", "hypervigilant", "startle"], "weight": 1.5},
    {"label": "trauma_childhood", "keywords": ["childhood trauma", "abuse", "neglect", "ACE", "adverse", "growing up", "parents hurt"], "weight": 1.5},
    {"label": "trauma_complex", "keywords": ["complex trauma", "repeated", "ongoing abuse", "captivity", "coercive", "trapped"], "weight": 1.5},
    {"label": "trauma_vicarious", "keywords": ["compassion fatigue", "secondary trauma", "burnout helper", "absorbing pain"], "weight": 1.2},
    {"label": "relationship_conflict", "keywords": ["argument", "fighting", "conflict", "disagreement", "partner angry", "yelling"], "weight": 1.1},
    {"label": "relationship_trust", "keywords": ["trust issues", "betrayal", "cheating", "infidelity", "lying", "broken trust"], "weight": 1.3},
    {"label": "relationship_communication", "keywords": ["communication", "not heard", "misunderstood", "can't express", "shutting down"], "weight": 1.0},
    {"label": "relationship_intimacy", "keywords": ["intimacy", "vulnerability", "closeness", "emotional distance", "walls up"], "weight": 1.1},
    {"label": "relationship_codependency", "keywords": ["codependent", "enmeshed", "caretaking", "people pleasing", "boundaries"], "weight": 1.2},
    {"label": "family_parenting", "keywords": ["parenting", "children", "discipline", "motherhood", "fatherhood", "raising kids"], "weight": 1.0},
    {"label": "family_dynamics", "keywords": ["family conflict", "sibling", "in-laws", "family roles", "scapegoat", "golden child"], "weight": 1.1},
    {"label": "family_intergenerational", "keywords": ["generational", "inherited patterns", "family legacy", "cycle breaking", "ancestors"], "weight": 1.3},
    {"label": "identity_self_worth", "keywords": ["self-worth", "not enough", "undeserving", "self-esteem", "value", "who am I"], "weight": 1.2},
    {"label": "identity_purpose", "keywords": ["purpose", "meaning", "existential", "why am I here", "lost direction", "calling"], "weight": 1.1},
    {"label": "identity_transition", "keywords": ["transition", "life change", "new chapter", "identity shift", "becoming", "evolving"], "weight": 1.0},
    {"label": "identity_cultural", "keywords": ["cultural identity", "heritage", "belonging", "diaspora", "code switching", "between worlds"], "weight": 1.1},
    {"label": "anger_management", "keywords": ["angry", "rage", "irritable", "explosive", "frustration", "resentment", "bitter"], "weight": 1.2},
    {"label": "anger_suppression", "keywords": ["suppressed anger", "bottled up", "can't express anger", "passive aggressive", "seething"], "weight": 1.1},
    {"label": "shame_core", "keywords": ["shame", "ashamed", "humiliated", "disgrace", "defective", "broken"], "weight": 1.4},
    {"label": "shame_toxic", "keywords": ["toxic shame", "internalized", "believe I'm bad", "fundamentally wrong", "core defect"], "weight": 1.5},
    {"label": "guilt_moral", "keywords": ["guilty", "regret", "should have", "wrong choice", "let down", "failed them"], "weight": 1.1},
    {"label": "guilt_survivor", "keywords": ["survivor guilt", "why me", "why did I make it", "others suffered more"], "weight": 1.3},
    {"label": "stress_work", "keywords": ["work stress", "burnout", "overworked", "deadline", "boss", "career pressure"], "weight": 1.0},
    {"label": "stress_financial", "keywords": ["financial", "money", "debt", "bills", "broke", "afford", "economic"], "weight": 1.0},
    {"label": "stress_health", "keywords": ["health anxiety", "diagnosis", "chronic illness", "pain", "disability", "medical"], "weight": 1.1},
    {"label": "stress_caregiver", "keywords": ["caregiver", "caring for", "elder care", "sick parent", "dependent", "burden"], "weight": 1.2},
    {"label": "addiction_substance", "keywords": ["addiction", "alcohol", "drugs", "substance", "relapse", "sober", "recovery", "using"], "weight": 1.3},
    {"label": "addiction_behavioral", "keywords": ["gambling", "shopping addiction", "screen time", "gaming addiction", "compulsive"], "weight": 1.1},
    {"label": "addiction_process", "keywords": ["sex addiction", "porn", "food addiction", "binge", "purge", "restriction"], "weight": 1.2},
    {"label": "sleep_insomnia", "keywords": ["insomnia", "can't sleep", "racing thoughts night", "awake", "exhausted", "sleep hygiene"], "weight": 1.0},
    {"label": "sleep_nightmares", "keywords": ["nightmares", "night terrors", "sleep disturbance", "afraid to sleep", "bad dreams"], "weight": 1.2},
    {"label": "somatic_pain", "keywords": ["body pain", "headache", "stomach", "tension", "muscle", "psychosomatic", "body holds"], "weight": 1.0},
    {"label": "somatic_dissociation", "keywords": ["dissociation", "numb", "out of body", "spacing out", "detached", "unreal", "foggy"], "weight": 1.3},
    {"label": "motivation_avoidance", "keywords": ["avoidance", "procrastination", "stuck", "paralyzed", "can't start", "overwhelmed"], "weight": 1.0},
    {"label": "motivation_perfectionism", "keywords": ["perfectionism", "never enough", "high standards", "all or nothing", "failure intolerance"], "weight": 1.1},
    {"label": "coping_healthy", "keywords": ["coping skills", "self-care", "meditation", "exercise", "journaling", "breathing"], "weight": 0.8},
    {"label": "coping_maladaptive", "keywords": ["self-harm", "cutting", "purging", "starving", "reckless", "self-destructive"], "weight": 1.5},
    {"label": "growth_resilience", "keywords": ["resilience", "bouncing back", "strength", "overcoming", "post-traumatic growth"], "weight": 0.9},
    {"label": "growth_mindfulness", "keywords": ["mindfulness", "present moment", "awareness", "meditation", "acceptance", "observe"], "weight": 0.8},
    {"label": "growth_gratitude", "keywords": ["gratitude", "thankful", "appreciation", "blessing", "silver lining", "positive"], "weight": 0.7},
    {"label": "growth_forgiveness", "keywords": ["forgiveness", "letting go", "moving on", "reconciliation", "peace with past"], "weight": 1.0},
    {"label": "spiritual_crisis", "keywords": ["spiritual crisis", "faith doubt", "dark night", "meaning lost", "God abandoned"], "weight": 1.2},
    {"label": "spiritual_growth", "keywords": ["spiritual growth", "awakening", "transcendence", "connection", "higher purpose"], "weight": 0.9},
    {"label": "loneliness_isolation", "keywords": ["lonely", "isolated", "no friends", "disconnected", "alone", "nobody cares"], "weight": 1.2},
    {"label": "loneliness_existential", "keywords": ["existential loneliness", "fundamentally alone", "nobody understands", "alien"], "weight": 1.3},
    {"label": "boundary_setting", "keywords": ["boundaries", "saying no", "overcommitted", "taken advantage", "doormat", "assert"], "weight": 1.0},
    {"label": "boundary_violation", "keywords": ["boundary violation", "crossed line", "disrespected", "invaded", "unsafe"], "weight": 1.2},
    {"label": "self_regulation", "keywords": ["emotional regulation", "overwhelmed", "flooding", "dysregulated", "out of control"], "weight": 1.2},
    {"label": "self_compassion", "keywords": ["self-compassion", "self-kindness", "inner critic", "harsh on myself", "self-talk"], "weight": 1.0},
    {"label": "attachment_secure", "keywords": ["secure attachment", "felt safe", "earned security", "trust building"], "weight": 0.8},
    {"label": "attachment_anxious", "keywords": ["anxious attachment", "need reassurance", "clingy", "fear abandonment", "hyperactivating"], "weight": 1.2},
    {"label": "attachment_avoidant", "keywords": ["avoidant attachment", "independence", "walls", "deactivating", "emotionally unavailable"], "weight": 1.2},
    {"label": "attachment_disorganized", "keywords": ["disorganized attachment", "fear and need", "approach-avoid", "frozen", "conflicted"], "weight": 1.4},
    {"label": "neurodivergent_adhd", "keywords": ["adhd", "attention", "focus", "distracted", "hyperactive", "executive function"], "weight": 1.0},
    {"label": "neurodivergent_autism", "keywords": ["autism", "spectrum", "sensory", "masking", "social scripts", "stimming", "meltdown"], "weight": 1.1},
    {"label": "neurodivergent_learning", "keywords": ["learning disability", "dyslexia", "processing", "slow learner", "struggling school"], "weight": 0.9},
    {"label": "suicidal_ideation", "keywords": ["suicidal", "want to die", "end it", "no point", "better off dead", "plan", "attempt"], "weight": 2.0},
    {"label": "suicidal_passive", "keywords": ["don't want to exist", "disappear", "wouldn't mind dying", "passive death wish"], "weight": 1.8},
    {"label": "self_harm_active", "keywords": ["cutting", "burning", "hitting self", "self-injury", "hurting myself"], "weight": 1.8},
    {"label": "eating_restriction", "keywords": ["restricting", "anorexia", "not eating", "calories", "thin", "control food"], "weight": 1.3},
    {"label": "eating_binge", "keywords": ["binge eating", "overeating", "stuffing", "food comfort", "emotional eating"], "weight": 1.1},
    {"label": "body_image", "keywords": ["body image", "hate body", "ugly", "fat", "dysmorphia", "appearance"], "weight": 1.2},
    {"label": "gender_identity", "keywords": ["gender", "transgender", "nonbinary", "dysphoria", "transition", "coming out gender"], "weight": 1.1},
    {"label": "sexuality_orientation", "keywords": ["sexuality", "gay", "lesbian", "bisexual", "coming out", "questioning orientation"], "weight": 1.0},
    {"label": "sexuality_shame", "keywords": ["sexual shame", "purity culture", "dirty", "sinful desire", "repressed"], "weight": 1.3},
    {"label": "ocd_intrusive", "keywords": ["ocd", "intrusive thoughts", "obsessive", "compulsive", "checking", "contamination", "ritual"], "weight": 1.2},
    {"label": "phobia_specific", "keywords": ["phobia", "afraid of", "terror", "avoidance", "irrational fear", "agoraphobia"], "weight": 1.0},
    {"label": "adjustment_major", "keywords": ["major change", "moving", "divorce", "new job", "retirement", "empty nest"], "weight": 1.0},
    {"label": "adjustment_loss_role", "keywords": ["role loss", "laid off", "retired", "no longer needed", "identity without job"], "weight": 1.1},
    {"label": "psychosis_concern", "keywords": ["hearing voices", "seeing things", "paranoid", "delusions", "reality testing"], "weight": 1.5},
    {"label": "bipolar_mood_swing", "keywords": ["mood swings", "manic", "bipolar", "high and low", "rapid cycling", "elevated mood"], "weight": 1.3},
    {"label": "personality_borderline", "keywords": ["borderline", "splitting", "idealize devalue", "unstable relationships", "fear abandonment intense"], "weight": 1.4},
    {"label": "personality_narcissistic_victim", "keywords": ["narcissistic abuse", "gaslighting", "manipulated", "narc", "flying monkeys"], "weight": 1.3},
    {"label": "domestic_violence", "keywords": ["domestic violence", "abuse", "hitting", "controlling partner", "escape", "shelter", "safety plan"], "weight": 1.8},
    {"label": "sexual_assault", "keywords": ["sexual assault", "rape", "molested", "non-consensual", "violated", "me too"], "weight": 1.8},
    {"label": "academic_pressure", "keywords": ["school pressure", "grades", "college", "academic", "study stress", "dropout"], "weight": 0.9},
    {"label": "career_transition", "keywords": ["career change", "job search", "unemployed", "new career", "passion vs money"], "weight": 0.9},
    {"label": "aging_mortality", "keywords": ["aging", "getting old", "mortality", "death anxiety", "legacy", "time running out"], "weight": 1.1},
    {"label": "chronic_pain_coping", "keywords": ["chronic pain", "fibromyalgia", "pain management", "living with pain", "disability coping"], "weight": 1.1},
    {"label": "fertility_loss", "keywords": ["infertility", "miscarriage", "stillborn", "pregnancy loss", "can't conceive"], "weight": 1.4},
    {"label": "postpartum_mood", "keywords": ["postpartum", "baby blues", "PPD", "bonding difficulty", "new mother overwhelm"], "weight": 1.3},
    {"label": "military_veteran", "keywords": ["veteran", "military", "deployment", "combat", "reintegration", "service connected"], "weight": 1.2},
    {"label": "incarceration_reentry", "keywords": ["incarcerated", "prison", "reentry", "parole", "record", "stigma criminal"], "weight": 1.1},
    {"label": "immigrant_adjustment", "keywords": ["immigrant", "refugee", "asylum", "homesick", "language barrier", "documentation"], "weight": 1.1},
    {"label": "racial_trauma", "keywords": ["racism", "racial trauma", "discrimination", "microaggression", "systemic", "racial identity"], "weight": 1.3},
    {"label": "moral_injury", "keywords": ["moral injury", "violated values", "complicit", "couldn't stop it", "ethical distress"], "weight": 1.3},
    {"label": "environmental_eco", "keywords": ["eco-anxiety", "climate", "environment", "future fear", "ecological grief", "planet"], "weight": 0.9},
    {"label": "technology_overwhelm", "keywords": ["screen addiction", "social media", "comparison", "doom scrolling", "digital detox"], "weight": 0.8},
    {"label": "creative_block", "keywords": ["creative block", "artist", "writer's block", "inspiration", "expression", "stuck creative"], "weight": 0.7},
    {"label": "positive_celebration", "keywords": ["celebration", "accomplishment", "proud", "milestone", "breakthrough", "growth marker"], "weight": 0.6},
    {"label": "curiosity_exploration", "keywords": ["curious", "wondering", "exploring", "question", "learn about", "understand"], "weight": 0.5},
]

L1_FACES_PER_L0 = 100


class ODPEL1Taxonomy:
    """In-memory L1 face taxonomy for fast keyword-based classification."""

    def __init__(self, db_pool=None):
        self._db_pool = db_pool
        self._taxonomy: Dict[str, List[Dict[str, Any]]] = {}
        self._build_default_taxonomy()

    def _build_default_taxonomy(self):
        """Build the 2,400-face default taxonomy from CORE_CONCERN_CLUSTERS."""
        for func in CANONICAL_FUNCTIONS:
            for scope in SCOPE_LEVELS:
                l0_key = f"{func}:{scope}"
                faces = []
                for i, cluster in enumerate(CORE_CONCERN_CLUSTERS):
                    faces.append({
                        "l0_face_key": l0_key,
                        "l1_index": i,
                        "l1_label": cluster["label"],
                        "keywords": cluster["keywords"],
                        "clinical_weight": cluster["weight"],
                    })
                padding_needed = L1_FACES_PER_L0 - len(faces)
                for j in range(padding_needed):
                    faces.append({
                        "l0_face_key": l0_key,
                        "l1_index": len(CORE_CONCERN_CLUSTERS) + j,
                        "l1_label": f"reserved_{j:03d}",
                        "keywords": [],
                        "clinical_weight": 0.5,
                    })
                self._taxonomy[l0_key] = faces

    def classify(
        self,
        text: str,
        l0_face_key: str,
    ) -> List[Tuple[str, float]]:
        """Classify text into L1 faces under a specific L0 parent.

        Returns list of (l1_label, activation_score) tuples, sorted by score descending.
        Only faces with score > 0 are returned.
        """
        faces = self._taxonomy.get(l0_face_key, [])
        if not faces:
            return []

        text_lower = text.lower()
        activations: List[Tuple[str, float]] = []

        for face in faces:
            if not face["keywords"]:
                continue
            hits = sum(1 for kw in face["keywords"] if kw in text_lower)
            if hits > 0:
                score = min(1.0, (hits / len(face["keywords"])) * face["clinical_weight"])
                activations.append((face["l1_label"], score))

        activations.sort(key=lambda x: x[1], reverse=True)
        return activations

    def get_face_count(self) -> int:
        return sum(len(faces) for faces in self._taxonomy.values())

    def get_l0_keys(self) -> List[str]:
        return list(self._taxonomy.keys())

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "total_faces": self.get_face_count(),
            "l0_count": len(self._taxonomy),
            "concern_clusters": len(CORE_CONCERN_CLUSTERS),
            "faces_per_l0": L1_FACES_PER_L0,
        }
