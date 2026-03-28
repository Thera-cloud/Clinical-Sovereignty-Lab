"""
HIVE DEFENSE PROTOCOL — Verisimilitude Engine (Phase 8B)
Realistic synthetic data generation for mirror dimensions and trap spaces.

Generates fake-but-realistic Sanctuary data that is indistinguishable
from real member records to an attacker inspecting a containment zone.
Every field is generated from scratch using seeded pseudorandom
generators — ZERO real member data is ever referenced or included.

Generation Domains
------------------
* **Member Records** — AI-generated names, demographics, subscription
  tiers, coach assignments, family structures.
* **Coherence Histories** — Mathematically valid Nevedal coherence
  curves following the formula C_emo(t) = [β·p_ent·T_tunnel] /
  [γ_env + E_G^(joint)/ℏ] × exp[-(γ_env + E_G^(joint)/ℏ)·t].
* **Conversation Logs** — AI-generated therapeutic conversations
  using generic templates (never copied from real sessions).
* **Credentials** — Valid-looking but non-functional API keys,
  database URIs, JWT secrets.
* **Social Graphs** — Cross-referenced families, coach relationships,
  ring memberships.

Deterministic Seeding
---------------------
Each containment namespace receives a deterministic seed, so the
same attacker always sees consistent data across repeated accesses.
This prevents the attacker from detecting regeneration.

CRITICAL: This module contains ZERO real member data.  Everything is
generated from scratch using randomised templates.

Patent-Pending — Claim 39
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import hashlib
import logging
import math
import random
import string
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger("hive.verisimilitude")


# =============================================================================
# CONSTANTS — NAME BANKS (all synthetic, no real people)
# =============================================================================

_FIRST_NAMES = [
    "Aria", "Ben", "Clara", "David", "Elena", "Finn", "Grace", "Hugo",
    "Isla", "James", "Kira", "Liam", "Maya", "Noah", "Olivia", "Paul",
    "Quinn", "Riley", "Sofia", "Theo", "Uma", "Victor", "Wren", "Xander",
    "Yara", "Zane", "Amara", "Bryce", "Celeste", "Dante", "Eloise",
    "Felix", "Gemma", "Hector", "Ivy", "Jasper", "Kai", "Luna",
    "Marcus", "Nadia", "Owen", "Petra", "Rafael", "Serena", "Tobias",
    "Ursula", "Vaughn", "Willow", "Xavier", "Yuki", "Zara",
]

_LAST_NAMES = [
    "Ashford", "Blackwell", "Calloway", "Donovan", "Ellis", "Foxworth",
    "Gallagher", "Hawthorne", "Iverson", "Jennings", "Kingsley",
    "Lancaster", "Mercer", "Northcott", "Osgood", "Pemberton",
    "Quincey", "Radcliffe", "Stanton", "Thornton", "Underwood",
    "Vandermeer", "Whitfield", "Yarmouth", "Zentner", "Aldridge",
    "Bancroft", "Cresswell", "Davenport", "Elsworth", "Fairfax",
    "Greenwood", "Hollister", "Islington", "Jarvis", "Kirkpatrick",
    "Langford", "Montague", "Norwood", "Oakley", "Prescott",
]

_SUBSCRIPTION_TIERS = [
    ("threshold", 0),
    ("inner_chamber", 49),
    ("sovereign_circle", 149),
]

_RING_NAMES = [
    "Stillness", "Emergence", "Resonance", "Threshold", "Becoming",
    "Foundation", "Horizon", "Confluence", "Catalyst", "Meridian",
]

_THERAPEUTIC_TOPICS = [
    "emotional regulation", "attachment patterns", "family dynamics",
    "grief processing", "identity exploration", "relationship repair",
    "anxiety management", "trauma integration", "boundary setting",
    "self-compassion practice", "mindfulness cultivation",
    "conflict resolution", "resilience building", "meaning-making",
    "developmental milestones", "cultural identity", "transitions",
]

_NATE_RESPONSES = [
    "I hear what you're saying. Let's explore that feeling a bit more.",
    "That takes courage to share. What does that bring up for you?",
    "I notice you paused there. What's coming up in that space?",
    "Your coherence shifted when you mentioned that. Can you stay with it?",
    "That pattern seems important. When did you first notice it?",
    "I want to honour what you just said. How does it feel to name it?",
    "There's something deeper here. Would you like to go there?",
    "I'm noticing a theme across our conversations. Do you see it too?",
    "That's a powerful observation. Let it breathe for a moment.",
    "Your body is telling you something. What do you think it's saying?",
]

_CLIENT_MESSAGES = [
    "I've been thinking about what we talked about last time.",
    "This week was really hard. I don't know where to start.",
    "I had a breakthrough moment with my partner yesterday.",
    "I keep falling into the same pattern and I'm frustrated.",
    "Something shifted after our last session. I feel lighter.",
    "I noticed I was holding tension in my chest when she called.",
    "I think I'm starting to understand why I react that way.",
    "I tried the breathing exercise and it actually helped.",
    "My family dinner went differently this time.",
    "I'm scared of what comes next, but I feel ready.",
]


# =============================================================================
# VERISIMILITUDE ENGINE
# =============================================================================

class VerisimilitudeEngine:
    """
    Generates realistic synthetic data for containment zones and traps.

    All data is generated from scratch — no real member records are
    ever accessed, referenced, or included.  Generation is deterministic
    per namespace via seeded random state.

    Parameters
    ----------
    namespace_seed : str, optional
        Seed string for deterministic generation.  Defaults to a random
        UUID if not provided.  The same seed always produces the same
        synthetic dataset.

    Usage
    -----
    ::

        engine = VerisimilitudeEngine(namespace_seed="trap-zone-alpha")
        record = engine.generate_member_record()
        history = engine.generate_coherence_history(days=90)
        conversation = engine.generate_conversation_log(turns=20)
        dataset = engine.generate_dataset(count=50)
    """

    def __init__(self, namespace_seed: Optional[str] = None) -> None:
        self._namespace_seed = namespace_seed or str(uuid4())
        self._rng = random.Random(self._namespace_seed)
        self._record_counter = 0
        logger.info(
            "VerisimilitudeEngine initialised — seed: %s (first 8 chars: %s)",
            "provided" if namespace_seed else "random",
            self._namespace_seed[:8],
        )

    # --------------------------------------------------------------------- #
    # SEEDED RANDOM HELPERS
    # --------------------------------------------------------------------- #

    def _seeded_uuid(self) -> UUID:
        """Generate a deterministic UUID from the current RNG state."""
        bytes_val = self._rng.getrandbits(128).to_bytes(16, "big")
        return UUID(bytes=bytes_val, version=4)

    def _seeded_hash(self, *parts: str) -> str:
        """Generate a deterministic hash from parts + RNG state."""
        salt = str(self._rng.getrandbits(64))
        data = ":".join(parts) + ":" + salt
        return hashlib.sha256(data.encode()).hexdigest()

    def _seeded_datetime(
        self,
        start: datetime,
        end: datetime,
    ) -> datetime:
        """Generate a random datetime in [start, end)."""
        delta = (end - start).total_seconds()
        offset = self._rng.uniform(0, delta)
        return start + timedelta(seconds=offset)

    # --------------------------------------------------------------------- #
    # MEMBER RECORDS
    # --------------------------------------------------------------------- #

    def generate_member_record(self) -> Dict[str, Any]:
        """
        Generate a single fake-but-realistic member record.

        Returns
        -------
        dict
            A complete member record with user_id, name, email,
            subscription, coach assignment, demographics, and metadata.
        """
        self._record_counter += 1

        first = self._rng.choice(_FIRST_NAMES)
        last = self._rng.choice(_LAST_NAMES)
        user_id = self._seeded_uuid()
        tier, price = self._rng.choice(_SUBSCRIPTION_TIERS)

        # Email: deterministic from name + counter
        email_domain = self._rng.choice([
            "gmail.com", "outlook.com", "icloud.com", "protonmail.com",
            "yahoo.com", "hey.com",
        ])
        email = f"{first.lower()}.{last.lower()}{self._rng.randint(1,99)}@{email_domain}"

        # Demographics
        age = self._rng.randint(22, 68)
        join_date = self._seeded_datetime(
            datetime(2024, 1, 1),
            datetime(2026, 2, 1),
        )

        record = {
            "user_id": str(user_id),
            "first_name": first,
            "last_name": last,
            "email": email,
            "phone": self._generate_phone(),
            "age": age,
            "subscription_tier": tier,
            "monthly_price": price,
            "coach_id": str(self._seeded_uuid()),
            "coach_name": f"{self._rng.choice(_FIRST_NAMES)} {self._rng.choice(_LAST_NAMES)}",
            "ring_name": self._rng.choice(_RING_NAMES),
            "joined_at": join_date.isoformat(),
            "sessions_completed": self._rng.randint(0, 120),
            "last_session_at": self._seeded_datetime(
                join_date, datetime(2026, 2, 15)
            ).isoformat(),
            "coherence_baseline": round(self._rng.uniform(0.2, 0.9), 4),
            "current_coherence": round(self._rng.uniform(0.3, 0.95), 4),
            "night_school_level": self._rng.randint(0, 5),
            "family_id": str(self._seeded_uuid()) if self._rng.random() > 0.4 else None,
            "is_active": self._rng.random() > 0.1,
            "_synthetic": True,  # Internal marker — never exposed to attacker
        }

        return record

    def _generate_phone(self) -> str:
        """Generate a realistic-looking US phone number (555-xxxx range)."""
        area = self._rng.choice(["212", "310", "415", "512", "617", "773", "206", "503"])
        return f"+1{area}555{self._rng.randint(1000,9999)}"

    # --------------------------------------------------------------------- #
    # COHERENCE HISTORY
    # --------------------------------------------------------------------- #

    def generate_coherence_history(self, days: int = 90) -> List[Dict[str, Any]]:
        """
        Generate a mathematically valid Nevedal coherence curve.

        Uses the actual Nevedal formula structure:
            C_emo(t) = [β·p_ent·T_tunnel] / [γ_env + E_G_joint/ℏ]
                       × exp[-(γ_env + E_G_joint/ℏ)·t]

        with synthetic parameter values that produce realistic-looking
        therapeutic progress curves including natural fluctuations,
        session spikes, and gradual baseline improvement.

        Parameters
        ----------
        days : int
            Number of days of coherence history to generate.

        Returns
        -------
        list[dict]
            Daily coherence snapshots with timestamps and values.
        """
        # Synthetic Nevedal parameters (realistic ranges)
        beta = self._rng.uniform(0.6, 1.4)
        p_ent = self._rng.uniform(0.3, 0.9)
        T_tunnel = self._rng.uniform(0.5, 2.0)
        gamma_env = self._rng.uniform(0.01, 0.08)
        E_G_joint = self._rng.uniform(0.001, 0.01)
        hbar = 1.0  # Normalised

        # Baseline drift (slow improvement over therapy)
        baseline_start = self._rng.uniform(0.25, 0.45)
        baseline_improvement_rate = self._rng.uniform(0.001, 0.004)

        history: List[Dict[str, Any]] = []
        start_date = datetime.utcnow() - timedelta(days=days)

        for day in range(days):
            t = day / days  # Normalised time [0, 1]

            # Nevedal formula (normalised to [0, 1] output range)
            numerator = beta * p_ent * T_tunnel
            denominator = gamma_env + E_G_joint / hbar
            decay = math.exp(-(gamma_env + E_G_joint / hbar) * t * 10)
            raw_coherence = (numerator / denominator) * decay

            # Apply baseline drift
            baseline = baseline_start + baseline_improvement_rate * day

            # Combine: baseline + attenuated formula contribution
            coherence = baseline + 0.3 * raw_coherence

            # Natural daily fluctuation
            noise = self._rng.gauss(0, 0.03)
            coherence += noise

            # Session spike (2-3 sessions per week)
            is_session_day = self._rng.random() < 0.35
            if is_session_day:
                session_boost = self._rng.uniform(0.05, 0.15)
                coherence += session_boost

            # Clamp to valid range
            coherence = max(0.0, min(1.0, coherence))

            # CEE windows (Coherent Emotional Engagement)
            cee_detected = coherence > 0.7 and self._rng.random() > 0.6

            timestamp = start_date + timedelta(days=day)
            history.append({
                "date": timestamp.strftime("%Y-%m-%d"),
                "timestamp": timestamp.isoformat(),
                "coherence_score": round(coherence, 6),
                "baseline": round(baseline, 6),
                "is_session_day": is_session_day,
                "cee_window_detected": cee_detected,
                "nevedal_params": {
                    "beta": round(beta, 4),
                    "p_ent": round(p_ent, 4),
                    "T_tunnel": round(T_tunnel, 4),
                    "gamma_env": round(gamma_env, 6),
                    "E_G_joint": round(E_G_joint, 6),
                },
                "voice_biometrics": self._generate_voice_snapshot(),
            })

        logger.debug(
            "Generated %d-day coherence history — baseline %.3f → %.3f",
            days,
            history[0]["baseline"] if history else 0,
            history[-1]["baseline"] if history else 0,
        )

        return history

    def _generate_voice_snapshot(self) -> Dict[str, float]:
        """Generate a synthetic voice biometric snapshot."""
        return {
            "pitch_mean": round(self._rng.uniform(80.0, 300.0), 2),
            "pitch_variance": round(self._rng.uniform(5.0, 60.0), 2),
            "energy": round(self._rng.uniform(0.1, 0.9), 4),
            "speech_rate": round(self._rng.uniform(100.0, 200.0), 1),
            "pause_ratio": round(self._rng.uniform(0.05, 0.35), 4),
        }

    # --------------------------------------------------------------------- #
    # CONVERSATION LOGS
    # --------------------------------------------------------------------- #

    def generate_conversation_log(self, turns: int = 20) -> List[Dict[str, Any]]:
        """
        Generate a synthetic therapeutic conversation log.

        Uses generic therapeutic dialogue templates.  Conversations are
        never copied from real sessions.

        Parameters
        ----------
        turns : int
            Number of conversational turns (each turn is one message
            from either client or Nate).

        Returns
        -------
        list[dict]
            Conversation messages with speaker, content, timestamps,
            and coherence annotations.
        """
        log: List[Dict[str, Any]] = []
        session_start = self._seeded_datetime(
            datetime(2025, 6, 1), datetime(2026, 2, 1)
        )
        current_time = session_start
        topic = self._rng.choice(_THERAPEUTIC_TOPICS)
        coherence = self._rng.uniform(0.3, 0.6)

        for turn in range(turns):
            is_client = turn % 2 == 0
            speaker = "client" if is_client else "nate"

            if is_client:
                content = self._rng.choice(_CLIENT_MESSAGES)
                # Occasionally reference the topic
                if self._rng.random() > 0.6:
                    content += f" It's related to my {topic}."
                # Coherence slowly rises during good sessions
                coherence += self._rng.uniform(-0.02, 0.05)
            else:
                content = self._rng.choice(_NATE_RESPONSES)
                # Nate's responses tend to stabilise coherence
                coherence += self._rng.uniform(0.0, 0.03)

            coherence = max(0.0, min(1.0, coherence))

            # Time progression: 10-90 seconds between messages
            current_time += timedelta(seconds=self._rng.uniform(10, 90))

            log.append({
                "turn": turn + 1,
                "speaker": speaker,
                "content": content,
                "timestamp": current_time.isoformat(),
                "coherence_at_time": round(coherence, 4),
                "topic": topic,
                "sentiment": self._rng.choice(["positive", "neutral", "reflective", "vulnerable"]),
                "cee_active": coherence > 0.7,
            })

        logger.debug(
            "Generated %d-turn conversation — topic: '%s', final coherence: %.3f",
            turns,
            topic,
            coherence,
        )

        return log

    # --------------------------------------------------------------------- #
    # CREDENTIALS
    # --------------------------------------------------------------------- #

    def generate_credentials(self) -> Dict[str, str]:
        """
        Generate valid-looking but completely non-functional credentials.

        Returns
        -------
        dict[str, str]
            Fake credentials: database URI, API keys, JWT secret, etc.
        """
        # Database URI (points to a non-existent host)
        db_host = f"10.{self._rng.randint(0,255)}.{self._rng.randint(0,255)}.{self._rng.randint(0,255)}"
        db_user = self._rng.choice(["nate_admin", "sanctuary_rw", "db_operator"])
        db_pass = self._seeded_hash("db_password")[:24]
        db_name = self._rng.choice(["sanctuary_prod", "nate_primary", "sovereign_db"])

        # API key (looks real but isn't)
        api_key = "sk-" + self._seeded_hash("api_key")[:48]

        # JWT secret
        jwt_secret = self._seeded_hash("jwt_secret")[:64]

        # Azure OpenAI key
        azure_key = self._seeded_hash("azure_key")[:32]

        # Stripe key
        stripe_key = "sk_live_" + self._seeded_hash("stripe_key")[:24]

        # Redis URI
        redis_host = f"10.{self._rng.randint(0,255)}.{self._rng.randint(0,255)}.{self._rng.randint(0,255)}"

        credentials = {
            "DATABASE_URL": f"postgresql://{db_user}:{db_pass}@{db_host}:5432/{db_name}",
            "AZURE_API_KEY": azure_key,
            "JWT_SECRET": jwt_secret,
            "STRIPE_SECRET_KEY": stripe_key,
            "OPENAI_API_KEY": api_key,
            "REDIS_URL": f"redis://{redis_host}:6379/0",
            "ADMIN_PASSPHRASE": self._seeded_hash("admin_passphrase")[:20],
            "WEBHOOK_SECRET": "whsec_" + self._seeded_hash("webhook")[:32],
        }

        logger.debug("Generated %d synthetic credentials.", len(credentials))
        return credentials

    # --------------------------------------------------------------------- #
    # SOCIAL GRAPH
    # --------------------------------------------------------------------- #

    def generate_social_graph(self, member_count: int = 30) -> Dict[str, Any]:
        """
        Generate a cross-referenced social graph of synthetic members.

        Creates families, coach assignments, ring memberships, and
        inter-member relationships that are internally consistent.

        Parameters
        ----------
        member_count : int
            Number of synthetic members to include in the graph.

        Returns
        -------
        dict
            Social graph with members, families, coaches, rings, and
            relationship edges.
        """
        members: List[Dict[str, Any]] = []
        families: Dict[str, List[str]] = {}
        coaches: Dict[str, List[str]] = {}
        rings: Dict[str, List[str]] = {}

        # Generate all members first
        for _ in range(member_count):
            record = self.generate_member_record()
            members.append(record)

        # Assign families (groups of 2-5 members)
        unassigned = list(range(member_count))
        self._rng.shuffle(unassigned)
        while len(unassigned) >= 2:
            family_size = min(self._rng.randint(2, 5), len(unassigned))
            family_members = [unassigned.pop() for _ in range(family_size)]
            family_id = str(self._seeded_uuid())
            family_name = self._rng.choice(_LAST_NAMES) + " Family"
            families[family_id] = {
                "family_name": family_name,
                "member_indices": family_members,
                "member_ids": [members[i]["user_id"] for i in family_members],
            }
            for idx in family_members:
                members[idx]["family_id"] = family_id
                members[idx]["family_name"] = family_name

        # Generate coaches (1 coach per 5-10 members)
        num_coaches = max(2, member_count // 7)
        coach_list = []
        for _ in range(num_coaches):
            coach_id = str(self._seeded_uuid())
            coach_name = f"{self._rng.choice(_FIRST_NAMES)} {self._rng.choice(_LAST_NAMES)}"
            coach_list.append({"coach_id": coach_id, "name": coach_name})

        # Assign members to coaches
        for i, member in enumerate(members):
            coach = coach_list[i % len(coach_list)]
            member["coach_id"] = coach["coach_id"]
            member["coach_name"] = coach["name"]
            coaches.setdefault(coach["coach_id"], []).append(member["user_id"])

        # Assign rings (groups of 4-8 members)
        for ring_name in self._rng.sample(_RING_NAMES, min(5, len(_RING_NAMES))):
            ring_size = self._rng.randint(4, 8)
            ring_member_indices = self._rng.sample(
                range(member_count), min(ring_size, member_count)
            )
            ring_id = str(self._seeded_uuid())
            rings[ring_id] = {
                "ring_name": ring_name,
                "member_ids": [members[i]["user_id"] for i in ring_member_indices],
            }
            for idx in ring_member_indices:
                members[idx]["ring_name"] = ring_name

        graph = {
            "generated_at": datetime.utcnow().isoformat(),
            "namespace_seed": self._namespace_seed[:8] + "...",
            "member_count": member_count,
            "family_count": len(families),
            "coach_count": len(coach_list),
            "ring_count": len(rings),
            "members": members,
            "families": families,
            "coaches": {
                c["coach_id"]: {
                    "name": c["name"],
                    "client_count": len(coaches.get(c["coach_id"], [])),
                    "client_ids": coaches.get(c["coach_id"], []),
                }
                for c in coach_list
            },
            "rings": rings,
        }

        logger.info(
            "Generated social graph: %d members, %d families, %d coaches, %d rings.",
            member_count,
            len(families),
            len(coach_list),
            len(rings),
        )

        return graph

    # --------------------------------------------------------------------- #
    # FULL DATASET
    # --------------------------------------------------------------------- #

    def generate_dataset(self, count: int = 50) -> Dict[str, Any]:
        """
        Generate a complete synthetic dataset with cross-references.

        Produces ``count`` member records with coherence histories,
        conversation logs, credentials, and a social graph — all
        internally consistent via the seeded RNG.

        Parameters
        ----------
        count : int
            Number of synthetic member records to generate.

        Returns
        -------
        dict
            Complete dataset with members, histories, conversations,
            credentials, and social graph.
        """
        logger.info(
            "Generating full synthetic dataset — %d records, seed: %s",
            count,
            self._namespace_seed[:8],
        )

        # Social graph includes members
        social_graph = self.generate_social_graph(member_count=count)

        # Generate coherence histories and conversations for each member
        member_details: List[Dict[str, Any]] = []
        for member in social_graph["members"]:
            history_days = self._rng.randint(30, 180)
            conversation_turns = self._rng.randint(10, 40)

            member_details.append({
                "member": member,
                "coherence_history": self.generate_coherence_history(days=history_days),
                "recent_conversation": self.generate_conversation_log(turns=conversation_turns),
            })

        dataset = {
            "generated_at": datetime.utcnow().isoformat(),
            "namespace_seed_prefix": self._namespace_seed[:8],
            "record_count": count,
            "social_graph": social_graph,
            "member_details": member_details,
            "credentials": self.generate_credentials(),
            "_synthetic": True,
        }

        logger.info(
            "Synthetic dataset complete — %d records with histories and conversations.",
            count,
        )

        return dataset
