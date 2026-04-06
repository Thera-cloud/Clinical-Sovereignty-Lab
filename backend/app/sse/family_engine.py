"""SSE Family Engine — family-linked story journeys, heritage, crystal pathways.

Handles family creation, age gating, heritage landmarks, couples crystal
co-occurrence, cycle detection, dependent biome inheritance, multi-level
coaching crystal tagging, minor lifecycle management, and privacy audit.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LANDMARK_TEMPLATES = {
    "clinical": "A standing stone inscribed with ancient wisdom about healing",
    "coaching": "A great tree whose roots hold memories of growth",
    "research": "An observatory tower with starlit knowledge",
    "general": "A cairn of stacked stones marking a lesson learned",
}
QUEST_STONE_TEMPLATE = "A weathered shield mounted on a tree, marking where a guardian completed their quest for {goal}"

_BRIGHT_BIOME_MAP = {
    "dark_forest": "enchanted_forest",
    "fortress_plains": "sunlit_plains",
    "river_valley": "enchanted_river",
    "crystal_mountains": "crystal_meadows",
    "open_sky": "open_sky",
}


def _compute_age(dob: date) -> int:
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _age_tier(age: int) -> str:
    if age < 13:
        return "child"
    if age < 18:
        return "adolescent"
    return "adult"


# ── 1. create_family_unit ─────────────────────────────────────────────

async def create_family_unit(head_user_id: str, family_name: str, db_pool) -> dict:
    family_code = f"FAM_{uuid.uuid4().hex[:8].upper()}"
    fid = str(uuid.uuid4())
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO families (id, family_code, name) VALUES ($1::uuid, $2, $3)",
            fid, family_code, family_name)
        await conn.execute(
            "INSERT INTO family_members (family_id, user_id, role, display_name) "
            "VALUES ($1, $2, 'head', $3)",
            family_code, head_user_id, family_name)
    return {"family_id": family_code, "family_uuid": fid, "name": family_name}


# ── 2. add_family_member ─────────────────────────────────────────────

async def add_family_member(
    family_id: str, user_id: str, role: str, display_name: str,
    date_of_birth: Optional[str], db_pool, consenting_parent_id: Optional[str] = None,
) -> dict:
    dob = None
    age_gated = False
    if date_of_birth:
        dob = date.fromisoformat(date_of_birth)
        age = _compute_age(dob)
        if age < 18:
            age_gated = True
            if not consenting_parent_id:
                return {"error": "Parental consent required for minors"}

    consent_at = datetime.now(timezone.utc) if age_gated and consenting_parent_id else None
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO family_members "
            "(family_id, user_id, role, display_name, date_of_birth, age_gated, "
            " consent_recorded_at, consent_parent_id) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            family_id, user_id, role, display_name, dob, age_gated,
            consent_at, consenting_parent_id)
    return {"added": True, "age_gated": age_gated, "role": role}


# ── 3. get_family_constellation ───────────────────────────────────────

async def get_family_constellation(family_id: str, db_pool) -> dict:
    async with db_pool.acquire() as conn:
        members = await conn.fetch(
            "SELECT fm.user_id, fm.role, fm.display_name, fm.date_of_birth, "
            "fm.age_gated, fm.emancipated, "
            "j.current_biome, j.panels_generated, j.last_panel_at, "
            "f.archetype_hint, f.archetype_image_url "
            "FROM family_members fm "
            "LEFT JOIN sse_user_journeys j ON j.user_id = fm.user_id "
            "LEFT JOIN sse_identity_forge f ON (f.user_id = fm.user_id OR "
            "  f.user_id = (SELECT hardware_id FROM users WHERE username = fm.user_id LIMIT 1)) "
            "WHERE fm.family_id = $1 ORDER BY fm.joined_at", family_id)
    return {"family_id": family_id, "members": [dict(m) for m in members]}


# ── 4. get_family_for_user ────────────────────────────────────────────

async def get_family_for_user(user_id: str, db_pool) -> Optional[dict]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT family_id, role FROM family_members "
            "WHERE user_id = $1 LIMIT 1", user_id)
        if not row:
            hw = await conn.fetchval(
                "SELECT hardware_id FROM users WHERE username = $1 LIMIT 1", user_id)
            if hw:
                row = await conn.fetchrow(
                    "SELECT family_id, role FROM family_members WHERE user_id = $1 LIMIT 1", hw)
        if not row:
            return None
        members = await conn.fetch(
            "SELECT user_id, role, display_name, date_of_birth, age_gated "
            "FROM family_members WHERE family_id = $1", row["family_id"])
    return {"family_id": row["family_id"], "user_role": row["role"],
            "members": [dict(m) for m in members]}


# ── 5. generate_shared_event ─────────────────────────────────────────

async def generate_shared_event(family_id: str, event_type: str, event_data: dict, db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO family_shared_events (family_id, event_type, event_data) "
            "VALUES ($1, $2, $3::jsonb)", family_id, event_type, json.dumps(event_data))


# ── 6. check_age_gate ────────────────────────────────────────────────

async def check_age_gate(user_id: str, db_pool) -> dict:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT date_of_birth, age_gated, emancipated FROM family_members "
            "WHERE user_id = $1 LIMIT 1", user_id)
    if not row or not row["date_of_birth"]:
        return {"age_gated": False, "age_tier": "adult", "allowed_themes": None}
    age = _compute_age(row["date_of_birth"])
    tier = _age_tier(age)
    if row.get("emancipated"):
        return {"age_gated": False, "age_tier": tier, "allowed_themes": None}
    from app.services.age_appropriate_calibration import CHILD_CONFIG, ADOLESCENT_CONFIG
    cfg = CHILD_CONFIG if tier == "child" else (ADOLESCENT_CONFIG if tier == "adolescent" else None)
    return {
        "age_gated": row["age_gated"],
        "age_tier": tier,
        "age": age,
        "allowed_themes": cfg.techniques if cfg else None,
    }


# ── 7. get_heritage_landmarks ─────────────────────────────────────────

async def get_heritage_landmarks(user_id: str, db_pool) -> list:
    """Parent LOCKED crystals + completed quests → landmarks for child's journey."""
    async with db_pool.acquire() as conn:
        fm = await conn.fetchrow(
            "SELECT family_id FROM family_members WHERE user_id = $1 LIMIT 1", user_id)
        if not fm:
            return []
        parents = await conn.fetch(
            "SELECT user_id FROM family_members WHERE family_id = $1 AND role IN ('head','spouse')",
            fm["family_id"])
        if not parents:
            return []
        parent_ids = [p["user_id"] for p in parents]
        landmarks: list = []
        for pid in parent_ids:
            uid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id=$1 OR username=$1 LIMIT 1", pid)
            if uid:
                crystals = await conn.fetch(
                    "SELECT domain FROM nate_intelligence_crystals "
                    "WHERE user_id=$1 AND confidence >= 0.85 AND superseded_by IS NULL "
                    "ORDER BY confidence DESC LIMIT 5", uid)
                for c in crystals:
                    tmpl = LANDMARK_TEMPLATES.get(c["domain"], LANDMARK_TEMPLATES["general"])
                    landmarks.append({"type": "crystal", "domain": c["domain"], "visual": tmpl})
            quests = await conn.fetch(
                "SELECT goal FROM sse_quests WHERE user_id=$1 AND status='completed' "
                "ORDER BY completed_at DESC LIMIT 3", pid)
            for q in quests:
                landmarks.append({"type": "quest_stone",
                                  "visual": QUEST_STONE_TEMPLATE.format(goal=q["goal"][:60])})
    return landmarks


# ── 8. get_couples_crystal_overlap ────────────────────────────────────

async def get_couples_crystal_overlap(spouse1_id: str, spouse2_id: str, db_pool) -> dict:
    async with db_pool.acquire() as conn:
        def _resolve(uid):
            return conn.fetchval("SELECT id FROM users WHERE hardware_id=$1 OR username=$1 LIMIT 1", uid)
        u1, u2 = await _resolve(spouse1_id), await _resolve(spouse2_id)
        if not u1 or not u2:
            return {"shared_domains": [], "shared_npc_seeds": []}
        d1 = await conn.fetch(
            "SELECT DISTINCT domain FROM nate_intelligence_crystals "
            "WHERE user_id=$1 AND superseded_by IS NULL AND domain IS NOT NULL", u1)
        d2 = await conn.fetch(
            "SELECT DISTINCT domain FROM nate_intelligence_crystals "
            "WHERE user_id=$1 AND superseded_by IS NULL AND domain IS NOT NULL", u2)
        s1 = {r["domain"] for r in d1}
        shared = [d for d in s1 if d in {r["domain"] for r in d2}]
    seeds = [{"domain": d, "crystal_count_combined": 2} for d in shared[:5]]
    return {"shared_domains": shared, "shared_npc_seeds": seeds}


# ── 9. detect_family_cycles ───────────────────────────────────────────

async def detect_family_cycles(family_id: str, db_pool) -> list:
    """Cross-reference cycle data across family members for temporal correlations."""
    async with db_pool.acquire() as conn:
        members = await conn.fetch(
            "SELECT user_id FROM family_members WHERE family_id = $1", family_id)
        if len(members) < 2:
            return []
        cycles: List[dict] = []
        uids = [m["user_id"] for m in members]
        for uid in uids:
            resolved = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id=$1 OR username=$1 LIMIT 1", uid)
            if not resolved:
                continue
            row = await conn.fetchrow(
                "SELECT coherence_pct, growth_pct FROM nevedal_metrics "
                "WHERE user_id=$1 ORDER BY recorded_at DESC LIMIT 1", resolved)
            if row and row["coherence_pct"] is not None and row["coherence_pct"] < 30:
                cycles.append({"user_id": uid, "coherence_pct": float(row["coherence_pct"]),
                                "signal": "low_coherence"})
    if len(cycles) >= 2:
        return [{"type": "family_storm", "affected": [c["user_id"] for c in cycles],
                 "signals": cycles}]
    return []


# ── 10. get_dependent_start_biome ─────────────────────────────────────

async def get_dependent_start_biome(parent_user_id: str, db_pool) -> str:
    async with db_pool.acquire() as conn:
        biome = await conn.fetchval(
            "SELECT current_biome FROM sse_user_journeys WHERE user_id = $1", parent_user_id)
    return _BRIGHT_BIOME_MAP.get(biome or "dark_forest", "enchanted_forest")


# ── 11. tag_session_crystal ───────────────────────────────────────────

async def tag_session_crystal(
    crystal_id: str, session_type: str, family_id: str,
    participant_ids: List[str], db_pool,
) -> dict:
    """Tag a crystal with family session context and duplicate for participants."""
    async with db_pool.acquire() as conn:
        crystal = await conn.fetchrow(
            "SELECT crystal_text, domain, confidence, user_id "
            "FROM nate_intelligence_crystals WHERE id=$1::uuid", crystal_id)
        if not crystal:
            return {"tagged": False, "reason": "crystal_not_found"}

        meta = json.dumps({"session_type": session_type, "family_id": family_id})
        await conn.execute(
            "UPDATE nate_intelligence_crystals SET scope = $1 WHERE id = $2::uuid",
            f"family:{family_id}", crystal_id)

        duplicated = 0
        speaker = str(crystal["user_id"])
        for pid in participant_ids:
            if pid == speaker:
                continue
            resolved = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id=$1 OR username=$1 LIMIT 1", pid)
            if not resolved:
                continue
            text = crystal["crystal_text"] or ""
            conf = (crystal["confidence"] or 0.5) * 0.7
            # Age-filter for children
            age_info = await check_age_gate(pid, db_pool)
            if age_info.get("age_tier") == "child":
                for term in ("trauma", "abuse", "suicid", "self-harm", "dissociat"):
                    if term in text.lower():
                        text = "[age-filtered]"
                        break
            new_id = str(uuid.uuid4())
            await conn.execute(
                "INSERT INTO nate_intelligence_crystals "
                "(id, user_id, crystal_text, domain, confidence, scope) "
                "VALUES ($1::uuid, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING",
                new_id, resolved, text, crystal["domain"], conf,
                f"family:{family_id}")
            duplicated += 1
    return {"tagged": True, "duplicated": duplicated, "session_type": session_type}


# ── 12. get_family_session_crystals ───────────────────────────────────

async def get_family_session_crystals(user_id: str, family_id: str, db_pool) -> dict:
    result: Dict[str, list] = {"individual": [], "couples": [], "parent_child": [], "family_group": []}
    async with db_pool.acquire() as conn:
        resolved = await conn.fetchval(
            "SELECT id FROM users WHERE hardware_id=$1 OR username=$1 LIMIT 1", user_id)
        if not resolved:
            return result
        rows = await conn.fetch(
            "SELECT crystal_text, domain, confidence, scope FROM nate_intelligence_crystals "
            "WHERE user_id=$1 AND superseded_by IS NULL "
            "ORDER BY created_at DESC LIMIT 30", resolved)
        for r in rows:
            scope = r["scope"] or ""
            entry = {"domain": r["domain"], "text": (r["crystal_text"] or "")[:100]}
            if scope.startswith("family:"):
                result.setdefault("family_group", []).append(entry)
            else:
                result["individual"].append(entry)
    return result


# ── 13. post_crystallize_family_tag ───────────────────────────────────

async def post_crystallize_family_tag(user_id: str, session_metadata: dict, db_pool):
    """Post-crystallization hook — tags recent crystals with family context."""
    session_type = session_metadata.get("session_type", "individual")
    family_id = session_metadata.get("family_id", "")
    participant_ids = session_metadata.get("participant_ids", [])
    if not family_id or session_type == "individual":
        return

    async with db_pool.acquire() as conn:
        resolved = await conn.fetchval(
            "SELECT id FROM users WHERE hardware_id=$1 OR username=$1 LIMIT 1", user_id)
        if not resolved:
            return
        recent = await conn.fetch(
            "SELECT id FROM nate_intelligence_crystals "
            "WHERE user_id=$1 AND created_at > now() - interval '5 minutes' "
            "ORDER BY created_at DESC LIMIT 10", resolved)
    for r in recent:
        await tag_session_crystal(str(r["id"]), session_type, family_id, participant_ids, db_pool)


# ── 14. get_minor_parent_view ─────────────────────────────────────────

async def get_minor_parent_view(parent_id: str, child_id: str, db_pool) -> dict:
    """Age-appropriate view of child's journey for the parent."""
    async with db_pool.acquire() as conn:
        child_fm = await conn.fetchrow(
            "SELECT family_id, age_gated, emancipated, date_of_birth "
            "FROM family_members WHERE user_id = $1 LIMIT 1", child_id)
        if not child_fm or child_fm.get("emancipated"):
            return {"error": "not_accessible"}
        parent_fm = await conn.fetchrow(
            "SELECT role FROM family_members WHERE user_id=$1 AND family_id=$2 LIMIT 1",
            parent_id, child_fm["family_id"])
        if not parent_fm or parent_fm["role"] not in ("head", "spouse"):
            return {"error": "not_authorized"}

        journey = await conn.fetchrow(
            "SELECT current_biome, panels_generated FROM sse_user_journeys WHERE user_id=$1",
            child_id)
        forge = await conn.fetchrow(
            "SELECT archetype_hint, archetype_image_url FROM sse_identity_forge "
            "WHERE user_id=$1 OR user_id=(SELECT hardware_id FROM users WHERE username=$1 LIMIT 1)",
            child_id)
        quests = await conn.fetch(
            "SELECT goal, status FROM sse_quests WHERE user_id=$1 ORDER BY started_at DESC LIMIT 5",
            child_id)
        panels = await conn.fetch(
            "SELECT r2_url, generated_at FROM sse_panel_log WHERE user_id=$1 "
            "ORDER BY generated_at DESC LIMIT 6", child_id)

        age = _compute_age(child_fm["date_of_birth"]) if child_fm["date_of_birth"] else 0
        tier = _age_tier(age)
        show_narratives = tier == "child"  # 13-17 gets thumbnails only

        await conn.execute(
            "INSERT INTO family_shared_events (family_id, event_type, event_data) "
            "VALUES ($1, 'parent_view_access', $2::jsonb)",
            child_fm["family_id"],
            json.dumps({"accessor": parent_id, "target": child_id}))

    return {
        "biome": journey["current_biome"] if journey else None,
        "panels_generated": journey["panels_generated"] if journey else 0,
        "archetype": dict(forge) if forge else None,
        "quests": [dict(q) for q in quests],
        "panel_thumbnails": [{"url": p["r2_url"], "date": str(p["generated_at"])} for p in panels],
        "show_narratives": show_narratives,
        "age_tier": tier,
    }


# ── 15. emancipate_minor ─────────────────────────────────────────────

async def emancipate_minor(user_id: str, reason: str, admin_id: str, db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE family_members SET age_gated = false, emancipated = true, "
            "emancipated_reason = $1 WHERE user_id = $2",
            reason, user_id)
        fm = await conn.fetchrow(
            "SELECT family_id FROM family_members WHERE user_id = $1 LIMIT 1", user_id)
        if fm:
            await conn.execute(
                "INSERT INTO family_shared_events (family_id, event_type, event_data) "
                "VALUES ($1, 'emancipation', $2::jsonb)",
                fm["family_id"],
                json.dumps({"user_id": user_id, "reason": reason, "admin_id": admin_id}))
