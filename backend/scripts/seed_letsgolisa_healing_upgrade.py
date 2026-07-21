#!/usr/bin/env python3
"""
Seed LetsGoLisa healing-journey upgrade artifacts on GREEN.

1) User-scoped clinical crystal (Nate recall + presession crystal memory)
2) Vault story.json little_nate_notes (remember_to / watch_for)
3) Next scheduled coaching_sessions.intake_note for CoachN (no retell)

Run inside nate_bridge or nate_backend with DATA_DIR pointing at bridge vaults:
  docker compose -f docker-compose.prod.yml exec -T bridge \
    python /app/scripts/seed_letsgolisa_healing_upgrade.py

Or from host with DATABASE_URL + path to story.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow import when run from /app/scripts inside container
sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HW = "CLIENT_LETSGOLISA_ID"
USERNAME = "LetsGoLisa"

CRYSTAL_TEXT = (
    "HOW YOU RESPOND TO LetsGoLisa (Lisa West) — clinical style DNA: "
    "Trust protocol: answer then deepen; never deepen then avoid. "
    "Never open with 'I sense a feeling' or 'Underneath, I hear'. "
    "Session modes: PANEL (name characters; faith OK; honor symbol substitution), "
    "MARRIAGE (Bill/unseen — stay relational), "
    "CRISIS (car/numb/dark — stabilize, no panels, offer CoachN). "
    "Retain: character naming, faith language, repair-when-called-out, "
    "shadow work without forcing Serpent. "
    "COACH HANDOFF (Jul 19–20 2026): grandfather CSA disclosure during hands/panel "
    "work; Jul 20 birthday-eve invisibility, Bill silent after she sobbed about "
    "feeling unseen, she sat numb in car as dark fell — CoachN must not make her retell."
)

REMEMBER = [
    "TRUST: answer first, then deepen — never deflect with 'which part feels most important'.",
    "MODES: Panel vs Marriage vs Crisis (car/numb/dark = Crisis — no panels).",
    "COACH HANDOFF Jul19–20: grandfather CSA disclosure; birthday invisibility; Bill silent after sobs; car/numb/dark — CoachN already briefed.",
    "RETAIN: name characters; faith language OK; repair when called out; honor spider/jackal instead of Serpent if she prefers.",
]

WATCH = [
    "Crisis markers: sitting in car, numb, getting dark, 'no pulse' after honesty with Bill.",
    "Template 'I sense a feeling…' openers erode her trust — she was lied to as a child.",
]

INTAKE_NOTE = (
    "Nate→CoachN handoff (auto 2026-07-21) — Lisa need not retell: "
    "Jul 19 disclosed grandfather sexual abuse (hands/panel work); weeping "
    "Dawnsinger breakthrough. Jul 20 birthday eve — felt invisible (Bill/Kate "
    "no plans); poured out to Bill sobbing, he said nothing; sat in car numb "
    "as dark fell; unsure marriage can change. Prioritize visibility wound + "
    "marital rupture + recent CSA disclosure before more panel depth."
)


def _story_path() -> Path:
    data = os.environ.get("DATA_DIR", "/app/data")
    return Path(data) / "Vaults" / "Clients" / HW / "story.json"


def update_story() -> None:
    path = _story_path()
    if not path.exists():
        print(f"WARN: story.json missing at {path}")
        return
    story = json.loads(path.read_text(encoding="utf-8"))
    notes = story.setdefault("little_nate_notes", {"remember_to": [], "watch_for": []})
    rem = list(notes.get("remember_to") or [])
    watch = list(notes.get("watch_for") or [])
    for r in REMEMBER:
        if r not in rem:
            rem.insert(0, r)
    for w in WATCH:
        if w not in watch:
            watch.insert(0, w)
    notes["remember_to"] = rem[:12]
    notes["watch_for"] = watch[:12]
    alliance = story.setdefault("therapeutic_alliance", {})
    builders = list(alliance.get("what_builds_trust") or [])
    for b in (
        "Direct answers before mirroring",
        "Naming characters when asked",
        "Owning avoidance then answering",
    ):
        if b not in builders:
            builders.insert(0, b)
    alliance["what_builds_trust"] = builders[:8]
    patterns = story.setdefault("patterns", {}).setdefault("when_activated", {})
    helps = list(patterns.get("what_helps") or [])
    doesnt = list(patterns.get("what_doesnt_help") or [])
    for h in ("Direct named answers", "Character naming", "Faith language when she uses it"):
        if h not in helps:
            helps.insert(0, h)
    for d in (
        "I sense a feeling… openers",
        "which part feels most important after full disclosure",
        "Snark about sleep/meds",
        "Forcing Serpent symbol after she asked for spider/jackal",
    ):
        if d not in doesnt:
            doesnt.insert(0, d)
    patterns["what_helps"] = helps[:8]
    patterns["what_doesnt_help"] = doesnt[:8]
    story["_healing_upgrade_seeded_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(story, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chown(path, 1000, 1000)
    except (PermissionError, AttributeError, OSError):
        pass
    os.chmod(path, 0o644)
    print(f"OK: updated {path}")


async def seed_pg() -> None:
    import asyncpg

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("WARN: DATABASE_URL unset — skip PG crystal/intake")
        return
    conn = await asyncpg.connect(url)
    try:
        uid = await conn.fetchval(
            "SELECT id FROM users WHERE username = $1 OR hardware_id = $2 LIMIT 1",
            USERNAME,
            HW,
        )
        if not uid:
            print("WARN: user not found")
            return
        content_hash = hashlib.sha256(
            f"{uid}|letsgolisa_healing_style_v1|{CRYSTAL_TEXT}".encode()
        ).hexdigest()
        row = await conn.fetchrow(
            """
            INSERT INTO nate_intelligence_crystals
                (crystal_text, domain, scope, topics, source_count,
                 generation, confidence, content_hash, user_id, origin_surface, metadata)
            VALUES (
                $1, 'clinical', 'user',
                ARRAY['client_style','letsgolisa','coach_handoff','trust_protocol'],
                2, 0, 0.88, $2, $3, 'client_style_override',
                $4::jsonb
            )
            ON CONFLICT (content_hash) DO UPDATE SET
                crystal_text = EXCLUDED.crystal_text,
                confidence = GREATEST(nate_intelligence_crystals.confidence, EXCLUDED.confidence),
                updated_at = NOW()
            RETURNING id
            """,
            CRYSTAL_TEXT,
            content_hash,
            uid,
            json.dumps({"style_id": "letsgolisa", "seed": "healing_upgrade_2026_07_21"}),
        )
        print(f"OK: crystal id={row['id'] if row else '?'}")

        # Prefer next scheduled session for CoachN; else most recent open row
        updated = await conn.execute(
            """
            UPDATE coaching_sessions
            SET intake_note = $1
            WHERE id = (
                SELECT id FROM coaching_sessions
                WHERE (client_id = $2 OR client_id = $3)
                  AND status IN ('scheduled', 'confirmed', 'pending')
                  AND scheduled_start > NOW() - INTERVAL '1 day'
                ORDER BY scheduled_start ASC
                LIMIT 1
            )
            """,
            INTAKE_NOTE,
            HW,
            USERNAME,
        )
        if updated.endswith("0"):
            # Fallback: insert a coach-facing note into skyeye_activity for audit trail
            await conn.execute(
                """
                INSERT INTO skyeye_activity (platform, type, content, severity, metadata, created_at)
                VALUES ('coach_handoff', 'letsgolisa_coach_brief', $1, 'info', $2::jsonb, NOW())
                """,
                INTAKE_NOTE,
                json.dumps({"client": USERNAME, "hw": HW, "coach": "CoachN"}),
            )
            print("OK: no upcoming session — wrote skyeye_activity coach brief")
        else:
            print(f"OK: intake_note updated ({updated})")
    finally:
        await conn.close()


def main() -> int:
    update_story()
    try:
        import asyncio

        asyncio.run(seed_pg())
    except Exception as e:
        print(f"WARN: PG seed failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
