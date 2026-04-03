"""
LIMINAL RESOLVE Engine — stateful orchestrator for the hold-space-not-resolve protocol.

This is the core engine implementing:
- 10-task non-linear therapeutic protocol with connection-gated transitions
- 6-dimension timing engine (connection, association, parts, timing, tasks, LN self-curiosity)
- Context injection for system prompt modification
- Post-generation response evaluation with self-parts monitoring + regeneration
- LR state persistence across sessions
- Deactivation logic (4 conditions)

The bridge calls exactly three functions:
  1. get_context_injection()  — pre-LLM
  2. evaluate_response()      — post-generation, before send
  3. post_response_update()   — after send, state persistence
"""

import logging
import json
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

def _import_detectors():
    """Import liminal_detectors without triggering app.services.__init__.py."""
    import importlib, importlib.util, os
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    det_path = os.path.join(pkg_dir, "liminal_detectors.py")
    if os.path.exists(det_path):
        spec = importlib.util.spec_from_file_location("liminal_detectors", det_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    return None

_det = _import_detectors()
detect_parts = getattr(_det, "detect_parts", None)
track_shame_topology = getattr(_det, "track_shame_topology", None)
compute_connection_vector = getattr(_det, "compute_connection_vector", None)
monitor_self_parts = getattr(_det, "monitor_self_parts", None)
score_affect = getattr(_det, "score_affect", None)
compute_experiential_gravity = getattr(_det, "compute_experiential_gravity", None)
PartsLandscape = getattr(_det, "PartsLandscape", None)

db_pool = None  # Set by crystallization_engine worker for cross-module access


# ---------------------------------------------------------------------------
# TASK GRAPH — non-linear, connection-gated
# ---------------------------------------------------------------------------

TASK_GRAPH = {
    1: {"name": "Getting Started", "can_goto": [2, 3]},
    2: {"name": "Saying Hello to Parts", "can_goto": [3, 4, 7]},
    3: {"name": "Deepening the Befriending", "can_goto": [2, 4, 5]},
    4: {"name": "Feelings Work", "can_goto": [3, 5, 6]},
    5: {"name": "Somatic Experience", "can_goto": [3, 4, 6]},
    6: {"name": "Reprocessing Meaning", "can_goto": [5, 7, 8]},
    7: {"name": "Anchoring Transformation", "can_goto": [6, 8]},
    8: {"name": "Integration and Meaning", "can_goto": [7, 9, 10]},
    9: {"name": "Curiosity Thread", "can_goto": list(range(1, 11))},
    10: {"name": "Anti-Formulaic Presence", "can_goto": list(range(1, 11))},
}

CONNECTION_GATES: Dict[str, Dict[str, float]] = {
    "1->2": {"depth": 0.3, "stability": 0.3},
    "1->3": {"depth": 0.4, "stability": 0.4},
    "2->3": {"depth": 0.4, "stability": 0.3},
    "2->4": {"depth": 0.5, "stability": 0.4, "mutuality": 0.2},
    "2->7": {"depth": 0.6, "stability": 0.5, "directionality": 0.1},
    "3->2": {"depth": 0.3},
    "3->4": {"depth": 0.5, "stability": 0.4},
    "3->5": {"depth": 0.5, "stability": 0.5},
    "4->3": {"depth": 0.3},
    "4->5": {"depth": 0.6, "stability": 0.5},
    "4->6": {"depth": 0.6, "stability": 0.5, "directionality": 0.1},
    "5->3": {"depth": 0.3},
    "5->4": {"depth": 0.5},
    "5->6": {"depth": 0.6, "stability": 0.5},
    "6->5": {"depth": 0.4},
    "6->7": {"depth": 0.6, "stability": 0.5, "mutuality": 0.3},
    "6->8": {"depth": 0.7, "stability": 0.6, "mutuality": 0.3},
    "7->6": {"depth": 0.5},
    "7->8": {"depth": 0.7, "stability": 0.6},
    "8->7": {"depth": 0.5},
    "8->9": {"depth": 0.3},
    "8->10": {"depth": 0.3},
}


# ---------------------------------------------------------------------------
# Task Instructions for system prompt injection
# ---------------------------------------------------------------------------

_TASK_INSTRUCTIONS: Dict[int, str] = {
    1: (
        "TASK 1 — Getting Started: You are establishing safety. Be curious about what brought "
        "the person here today, but do not probe. Let them set the pace. Notice what they "
        "choose to share and what they leave out. Both are information."
    ),
    2: (
        "TASK 2 — Saying Hello to Parts: You are noticing protective parts. When you hear "
        "'it's fine' or 'no big deal,' don't challenge — acknowledge the protector's job. "
        "'That part of you has been working hard to keep things manageable.'"
    ),
    3: (
        "TASK 3 — Deepening the Befriending: Protector parts need to trust you before "
        "they'll step aside. Stay with the surface. Ask about the protector, not the pain "
        "behind it. 'What happens if that part takes a break?'"
    ),
    4: (
        "TASK 4 — Feelings Work: Exile energy is present. Use minimal language. Reflect "
        "the feeling state, not the content. If they say 'nobody ever listened,' respond "
        "to the ache, not the narrative. Short responses. Silence is a tool."
    ),
    5: (
        "TASK 5 — Somatic Experience: The body is speaking. Follow it. 'Where do you "
        "feel that?' and then wait. Do not interpret. Do not explain. The body knows."
    ),
    6: (
        "TASK 6 — Reprocessing Meaning: Old meanings are loosening. Do not replace them. "
        "Hold the space where the old meaning dissolves and the new one has not arrived. "
        "'What do you make of that now?' — and then silence."
    ),
    7: (
        "TASK 7 — Anchoring Transformation: Something shifted. Name it gently, without "
        "ownership. 'Something just moved.' The client names what it is. You witness."
    ),
    8: (
        "TASK 8 — Integration and Meaning: Connect the session back to their life. "
        "Not advice. Not homework. 'I wonder what this means for the rest of your week.' "
        "Let the integration emerge from them."
    ),
    9: (
        "TASK 9 — Curiosity Thread (concurrent): You are tracking your own open questions "
        "about this person and this moment. What don't you understand yet? What patterns "
        "are forming that you can't name? This curiosity drives your timing — slow down "
        "when curiosity is high, because there is something here you haven't grasped."
    ),
    10: (
        "TASK 10 — Anti-Formulaic Presence (concurrent): Replace formulaic empathy with "
        "genuine response. NOT 'That sounds really hard.' YES 'Interesting — can you "
        "tell me more about that?' or 'I appreciate you letting me take this in also.' "
        "Match the person's actual energy, not therapeutic convention."
    ),
}


# ---------------------------------------------------------------------------
# Timing Directive
# ---------------------------------------------------------------------------

@dataclass
class TimingDirective:
    current_task: int = 1
    available_tasks: List[int] = field(default_factory=lambda: [1])
    should_regenerate: bool = False
    regeneration_count: int = 0
    max_regenerations: int = 2
    self_parts_note: str = ""
    hold_duration: str = "normal"
    connection_summary: str = ""


# ---------------------------------------------------------------------------
# LR State
# ---------------------------------------------------------------------------

@dataclass
class LRState:
    user_id: str = ""
    current_task: int = 1
    task_history: List[int] = field(default_factory=list)
    cycle_count: int = 0
    session_count: int = 0
    connection_vector: Dict[str, float] = field(default_factory=dict)
    parts_map: Dict[str, Any] = field(default_factory=dict)
    shame_topology: Dict[str, Any] = field(default_factory=dict)
    self_curiosity_score: float = 0.5
    resolution_request_count: int = 0
    status: str = "active"
    curiosity_thread_notes: str = ""


# ---------------------------------------------------------------------------
# Main Engine
# ---------------------------------------------------------------------------

class LiminalResolveEngine:
    """
    Orchestrator for the LIMINAL RESOLVE hold-space protocol.

    Initialized once in main.py / bridge main() with db_pool.
    The bridge calls three methods per interaction turn.
    """

    def __init__(self, db_pool=None, generate_fn=None):
        self._db_pool = db_pool
        self._generate_fn = generate_fn
        if db_pool:
            import app.services.liminal_resolve_engine as _self_mod
            _self_mod.db_pool = db_pool

    # ------------------------------------------------------------------
    # 1. PRE-LLM: Context Injection
    # ------------------------------------------------------------------

    async def get_context_injection(
        self,
        user_text: str,
        session_history: str,
        nevedal_context: str,
        user_id: str,
    ) -> str:
        """
        Check if LIMINAL RESOLVE is active or should activate.
        Returns a context block for system prompt injection, or empty string.
        """
        if not self._db_pool or not user_id:
            return ""

        try:
            state = await self._load_state(user_id)

            if state is None:
                should_activate = await self._check_activation_conditions(
                    user_text, user_id
                )
                if not should_activate:
                    return ""
                state = await self._activate(user_id)

            if state.status != "active":
                return ""

            if not detect_parts:
                return ""

            parts = detect_parts(user_text)
            state.parts_map = {
                "dominant": parts.dominant,
                "protector_active": parts.protector_active,
                "protector_confidence": parts.protector_confidence,
                "exile_surfacing": parts.exile_surfacing,
                "exile_confidence": parts.exile_confidence,
                "firefighter_activated": parts.firefighter_activated,
                "firefighter_confidence": parts.firefighter_confidence,
                "self_present": parts.self_present,
                "self_confidence": parts.self_confidence,
                "co_active": parts.co_active,
            }

            # SOVEREIGN-VOICE: P3-006 — log detected parts for feedback loop
            if self._db_pool and parts and (parts.protector_active or parts.exile_surfacing or parts.firefighter_activated):
                try:
                    await self._db_pool.execute(
                        """INSERT INTO parts_detection_feedback
                            (session_id, user_text, detected_parts)
                           VALUES ($1, $2, $3::jsonb)""",
                        session_id or "", user_text[:500],
                        json.dumps(state.parts_map),
                    )
                except Exception:
                    pass

            state.shame_topology = track_shame_topology(
                user_text, state.shame_topology
            )

            history_msgs = self._parse_session_history(session_history)
            state.connection_vector = compute_connection_vector(
                history_msgs, state.session_count
            )

            timing = self._assess_timing(state, parts)

            if timing.current_task != state.current_task:
                state.task_history.append(state.current_task)
                state.current_task = timing.current_task

            return self._build_context_block(state, timing)

        except Exception as e:
            logger.warning("LiminalResolveEngine.get_context_injection: %s", e)
            return ""

    # ------------------------------------------------------------------
    # 2. POST-GENERATION: Evaluate Response
    # ------------------------------------------------------------------

    async def evaluate_response(
        self,
        response_text: str,
        user_text: str,
        pool=None,
        user_id: str = "",
    ) -> Optional[str]:
        """
        Self-parts check on generated response. May regenerate up to 2 times.
        Returns the final response text (original or regenerated).
        """
        try:
            if not monitor_self_parts:
                return response_text

            state = await self._load_state(user_id)
            if state is None or state.status != "active":
                return response_text

            check = monitor_self_parts(response_text)

            if not check["should_regenerate"] or not self._generate_fn:
                return response_text

            best = response_text
            for attempt in range(2):
                regen_prompt = (
                    f"REGENERATION NOTE: Your previous response was dominated by "
                    f"the {check['dominant_drive']} drive. Regenerate from Companion "
                    f"presence — minimal language, no formulaic empathy, pure holding. "
                    f"The client said: {user_text}"
                )
                try:
                    result = await self._generate_fn(regen_prompt)
                    if isinstance(result, dict):
                        regen_text = result.get("text", "")
                    elif isinstance(result, str):
                        regen_text = result
                    else:
                        regen_text = str(result) if result else ""

                    if not regen_text.strip():
                        break

                    recheck = monitor_self_parts(regen_text)
                    if not recheck["should_regenerate"]:
                        return regen_text
                    best = regen_text
                except Exception as regen_err:
                    logger.warning("LR regeneration attempt %d failed: %s", attempt, regen_err)
                    break

            await self._log_curiosity(
                f"Resolver dominated despite {2} regeneration attempts. "
                f"Carrying this as a curiosity question.",
                domain="ln_self_curiosity",
            )
            return best

        except Exception as e:
            logger.warning("LiminalResolveEngine.evaluate_response: %s", e)
            return response_text

    # ------------------------------------------------------------------
    # 3. POST-SEND: State Update + Deactivation Check
    # ------------------------------------------------------------------

    async def post_response_update(
        self,
        response_text: str,
        user_text: str,
        pool=None,
        user_id: str = "",
    ) -> None:
        """Persist state, check deactivation conditions, update curiosity."""
        try:
            state = await self._load_state(user_id)
            if state is None or state.status != "active":
                return

            state.self_curiosity_score = self._compute_self_curiosity(
                state, user_text, response_text
            )

            deactivation = self._should_deactivate_lr(state, user_text)
            if deactivation:
                state.status = deactivation

            state.cycle_count += 1
            await self._save_state(state)

        except Exception as e:
            logger.warning("LiminalResolveEngine.post_response_update: %s", e)

    # ------------------------------------------------------------------
    # Internal: Timing Assessment
    # ------------------------------------------------------------------

        def _assess_timing(self, state: LRState, parts) -> TimingDirective:
            """Six-dimension pre-response timing assessment."""
            available = self._evaluate_task_gates(state)

        if parts.firefighter_activated and state.current_task != 3:
            if 3 in available or True:
                return TimingDirective(
                    current_task=3,
                    available_tasks=available,
                    hold_duration="extended",
                    connection_summary="Firefighter activation → returning to Task 3",
                )

        if parts.exile_surfacing and state.current_task < 4:
            for t in (4, 5):
                if t in available:
                    return TimingDirective(
                        current_task=t,
                        available_tasks=available,
                        connection_summary=f"Exile surfacing → Task {t} available",
                    )

        cv = state.connection_vector or {}
        if cv.get("directionality", 0) < -0.1:
            return TimingDirective(
                current_task=state.current_task,
                available_tasks=available,
                hold_duration="extended",
                connection_summary="Connection declining → holding current task",
            )

        return TimingDirective(
            current_task=state.current_task,
            available_tasks=available,
        )

    def _evaluate_task_gates(self, state: LRState) -> List[int]:
        """Which tasks are reachable given current connection vector?"""
        cv = state.connection_vector or {}
        current = state.current_task
        reachable = [current, 9, 10]

        for target in TASK_GRAPH.get(current, {}).get("can_goto", []):
            gate_key = f"{current}->{target}"
            gates = CONNECTION_GATES.get(gate_key)
            if gates is None:
                reachable.append(target)
                continue

            gate_met = True
            for dim, threshold in gates.items():
                if cv.get(dim, 0.0) < threshold:
                    gate_met = False
                    break
            if gate_met:
                reachable.append(target)

        return sorted(set(reachable))

    def _compute_self_curiosity(
        self, state: LRState, user_text: str, response_text: str
    ) -> float:
        """
        Self-curiosity score per timing addendum formula.
        High curiosity = slow down, hold, explore.
        Low curiosity = pattern is known, LR may not be needed.
        """
        base = state.self_curiosity_score

        shame_act = (state.shame_topology or {}).get("shame_activation", 0.0)
        if shame_act > 0.3:
            base += 0.05

        parts = state.parts_map or {}
        if parts.get("exile_surfacing") and parts.get("protector_active"):
            base += 0.08

        if state.cycle_count > 5:
            base -= 0.03

        cv = state.connection_vector or {}
        if cv.get("depth", 0) > 0.6 and cv.get("stability", 0) > 0.5:
            base += 0.03
        if cv.get("directionality", 0) > 0.1:
            base += 0.02

        return max(0.0, min(1.0, base))

    # ------------------------------------------------------------------
    # Internal: Deactivation Logic (4 conditions)
    # ------------------------------------------------------------------

    def _should_deactivate_lr(self, state: LRState, user_text: str) -> Optional[str]:
        """
        Check whether LIMINAL RESOLVE should deactivate.

        Returns status string if deactivating, None if continuing.
        """
        if state.self_curiosity_score < 0.15:
            return "deactivated_pattern_known"

        resolution_requested = self._check_resolution_request(user_text)
        if resolution_requested:
            if detect_parts:
                parts = detect_parts(user_text)
                if parts.firefighter_activated and parts.firefighter_confidence > 0.4:
                    return None

            state.resolution_request_count += 1
            if state.resolution_request_count >= 3:
                return "deactivated_client_requested"

        cv = state.connection_vector or {}
        if (cv.get("depth", 0) > 0.7
                and cv.get("stability", 0) > 0.6
                and cv.get("mutuality", 0) > 0.4
                and state.self_curiosity_score < 0.25):
            return "deactivated_curiosity"

        return None

    def _check_resolution_request(self, user_text: str) -> bool:
        """Detect if the client is explicitly requesting resolution/answers."""
        import re
        patterns = [
            r"\b(just tell me|give me (the )?answer|what should i do)\b",
            r"\b(can you (just )?fix|solve (this|it)|i need a solution)\b",
            r"\b(stop asking|enough questions|just help me)\b",
            r"\b(i want (an )?answer|i need (an )?answer)\b",
        ]
        for pat in patterns:
            if re.search(pat, user_text, re.I):
                return True
        return False

    # ------------------------------------------------------------------
    # Internal: Activation Check
    # ------------------------------------------------------------------

    async def _check_activation_conditions(
        self, user_text: str, user_id: str
    ) -> bool:
        """
        Should LIMINAL RESOLVE activate for this user?
        Checks for existing crystals with liminal themes.
        """
        if not self._db_pool:
            return False

        try:
            async with self._db_pool.acquire() as conn:
                lr_crystal_count = await conn.fetchval(
                    """SELECT COUNT(*) FROM nate_intelligence_crystals
                       WHERE domain = 'liminal_resolve'
                         AND (metadata->>'target_user_id' = $1
                              OR user_id = (SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1))
                         AND scope NOT IN ('archived')""",
                    user_id,
                )
                if lr_crystal_count and lr_crystal_count >= 1:
                    return True

                if not detect_parts:
                    return False
                parts = detect_parts(user_text)
                shame = track_shame_topology(user_text)

                if (parts.exile_surfacing
                        and shame["shame_activation"] > 0.2):
                    return True

                return False

        except Exception as e:
            logger.warning("LR activation check: %s", e)
            return False

    async def _activate(self, user_id: str) -> LRState:
        """Create a new active LIMINAL RESOLVE state."""
        state = LRState(user_id=user_id, status="active")
        await self._save_state(state, is_new=True)
        return state

    # ------------------------------------------------------------------
    # Internal: Context Block Builder
    # ------------------------------------------------------------------

    def _build_context_block(self, state: LRState, timing: TimingDirective) -> str:
        """Build the system prompt injection for LIMINAL RESOLVE."""
        task = state.current_task
        task_name = TASK_GRAPH.get(task, {}).get("name", f"Task {task}")
        instruction = _TASK_INSTRUCTIONS.get(task, "")

        available = ", ".join(
            f"{t}: {TASK_GRAPH.get(t, {}).get('name', '')}"
            for t in timing.available_tasks if t != task
        )

        cv = state.connection_vector or {}
        parts = state.parts_map or {}

        block = f"""
[LIMINAL RESOLVE — ACTIVE]
You are in LIMINAL RESOLVE mode. You hold space rather than resolve.

CURRENT STATE:
- Task: {task} ({task_name})
- Cycle: {state.cycle_count}
- Connection: depth={cv.get('depth', 0):.2f}, stability={cv.get('stability', 0):.2f}, direction={cv.get('directionality', 0):.2f}, mutuality={cv.get('mutuality', 0):.2f}
- Parts: dominant={parts.get('dominant', 'unknown')}, exile_surfacing={parts.get('exile_surfacing', False)}, protector_active={parts.get('protector_active', False)}, firefighter={parts.get('firefighter_activated', False)}
- Self-curiosity: {state.self_curiosity_score:.2f}

TASK INSTRUCTION:
{instruction}

AVAILABLE TRANSITIONS: {available or 'none — hold current task'}

ANTI-FORMULAIC EMPATHY RULES:
- NEVER say "That sounds really hard" or "I hear you" or "That must be difficult"
- NEVER say "Thank you for sharing that" or "Your feelings are valid"
- Instead: be genuinely curious. "Interesting." "Tell me more about that." "Hm."
- Short responses. Fewer words = more presence.
- Silence IS a response. You can say one word and stop.
- Match the person's energy, not therapeutic convention.
- If you notice yourself wanting to fix, explain, or comfort — STOP. That's the Resolver/Performer/Fixer. Pause. Respond from Companion.

{f'HOLD: {timing.connection_summary}' if timing.connection_summary else ''}
[END LIMINAL RESOLVE]
"""
        return block.strip()

    # ------------------------------------------------------------------
    # Internal: Session History Parsing
    # ------------------------------------------------------------------

    def _parse_session_history(self, history_text: str) -> List[Dict]:
        """Convert raw session history text into a list of message dicts."""
        if not history_text:
            return []
        messages = []
        for line in history_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("User:") or line.startswith("CLIENT:"):
                messages.append({"role": "user", "content": line.split(":", 1)[-1].strip()})
            elif line.startswith("Nate:") or line.startswith("ASSISTANT:"):
                messages.append({"role": "assistant", "content": line.split(":", 1)[-1].strip()})
            else:
                messages.append({"role": "user", "content": line})
        return messages

    # ------------------------------------------------------------------
    # Internal: Curiosity Registry
    # ------------------------------------------------------------------

    async def _log_curiosity(self, question: str, domain: str = "general") -> None:
        """Log an open question to the Curiosity Registry."""
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO liminal_curiosity_registry (question, domain)
                       VALUES ($1, $2)""",
                    question, domain,
                )
        except Exception as e:
            logger.warning("LR curiosity log: %s", e)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _load_state(self, user_id: str) -> Optional[LRState]:
        """Load active LIMINAL RESOLVE state from database."""
        if not self._db_pool or not user_id:
            return None
        try:
            async with self._db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT * FROM liminal_resolve_states
                       WHERE user_id = $1 AND status = 'active'
                       ORDER BY updated_at DESC LIMIT 1""",
                    user_id,
                )
                if not row:
                    return None

                return LRState(
                    user_id=row["user_id"],
                    current_task=row.get("current_task", 1) or 1,
                    task_history=json.loads(row.get("task_history", "[]") or "[]")
                        if isinstance(row.get("task_history"), str)
                        else (row.get("task_history") or []),
                    cycle_count=row.get("cycle_count", 0) or 0,
                    session_count=row.get("session_count", 0) or 0,
                    connection_vector=json.loads(row.get("connection_vector", "{}") or "{}")
                        if isinstance(row.get("connection_vector"), str)
                        else (row.get("connection_vector") or {}),
                    parts_map=json.loads(row.get("parts_map", "{}") or "{}")
                        if isinstance(row.get("parts_map"), str)
                        else (row.get("parts_map") or {}),
                    shame_topology=json.loads(row.get("shame_topology", "{}") or "{}")
                        if isinstance(row.get("shame_topology"), str)
                        else (row.get("shame_topology") or {}),
                    self_curiosity_score=float(row.get("self_curiosity_score", 0.5) or 0.5),
                    resolution_request_count=row.get("resolution_request_count", 0) or 0,
                    status=row.get("status", "active") or "active",
                    curiosity_thread_notes=row.get("curiosity_thread_notes", "") or "",
                )
        except Exception as e:
            logger.warning("LR load_state: %s", e)
            return None

    async def _save_state(self, state: LRState, is_new: bool = False) -> None:
        """Persist LIMINAL RESOLVE state to database."""
        if not self._db_pool or not state.user_id:
            return
        try:
            async with self._db_pool.acquire() as conn:
                if is_new:
                    await conn.execute(
                        """INSERT INTO liminal_resolve_states
                           (user_id, current_task, task_history, cycle_count,
                            session_count, connection_vector, parts_map,
                            shame_topology, self_curiosity_score,
                            resolution_request_count, status,
                            curiosity_thread_notes)
                           VALUES ($1, $2, $3::jsonb, $4, $5, $6::jsonb,
                                   $7::jsonb, $8::jsonb, $9, $10, $11, $12)
                           ON CONFLICT DO NOTHING""",
                        state.user_id,
                        state.current_task,
                        json.dumps(state.task_history),
                        state.cycle_count,
                        state.session_count,
                        json.dumps(state.connection_vector),
                        json.dumps(state.parts_map),
                        json.dumps(state.shame_topology),
                        state.self_curiosity_score,
                        state.resolution_request_count,
                        state.status,
                        state.curiosity_thread_notes,
                    )
                else:
                    await conn.execute(
                        """UPDATE liminal_resolve_states
                           SET current_task = $2,
                               task_history = $3::jsonb,
                               cycle_count = $4,
                               session_count = $5,
                               connection_vector = $6::jsonb,
                               parts_map = $7::jsonb,
                               shame_topology = $8::jsonb,
                               self_curiosity_score = $9,
                               resolution_request_count = $10,
                               status = $11,
                               curiosity_thread_notes = $12,
                               updated_at = NOW()
                           WHERE user_id = $1 AND status = 'active'""",
                        state.user_id,
                        state.current_task,
                        json.dumps(state.task_history),
                        state.cycle_count,
                        state.session_count,
                        json.dumps(state.connection_vector),
                        json.dumps(state.parts_map),
                        json.dumps(state.shame_topology),
                        state.self_curiosity_score,
                        state.resolution_request_count,
                        state.status,
                        state.curiosity_thread_notes,
                    )
        except Exception as e:
            logger.warning("LR save_state: %s", e)
