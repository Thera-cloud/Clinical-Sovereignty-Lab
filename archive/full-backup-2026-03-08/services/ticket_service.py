"""
LITTLE NATE — Golden Ticket Service
Handles prospect-to-client conversion: account creation, data migration,
and Vault warm memory initialization.
"""

import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import hashlib

from app.config import settings


class TicketService:
    """Manages Golden Ticket lifecycle and prospect → client conversion."""

    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def create_client_from_prospect(
        self,
        prospect_id: str,
        password: Optional[str] = None,
        late_redemption: bool = False
    ) -> dict:
        """
        Full conversion pipeline:
        1. Create client account in users table
        2. Copy prospect story into Vault warm memory
        3. Copy assessment goals into coaching plan
        4. Set subscription to TRIAL (14 days)
        5. Mark prospect as converted
        6. Prepare Little Nate's first greeting
        """
        async with self.db_pool.acquire() as conn:
            # Load prospect data
            prospect = await conn.fetchrow(
                "SELECT * FROM prospects WHERE id = $1", prospect_id
            )
            if not prospect:
                raise ValueError(f"Prospect {prospect_id} not found")

            # Load assessment
            assessment = await conn.fetchrow(
                "SELECT * FROM coaching_assessments WHERE prospect_id = $1",
                prospect_id
            )

            # Load story store
            story = await conn.fetchrow(
                "SELECT * FROM prospect_story_store WHERE prospect_id = $1",
                prospect_id
            )

            # Generate credentials
            username = self._email_to_username(prospect["email"])
            temp_password = password or secrets.token_urlsafe(12)
            # Hash password using same scheme as bridge_server.py (salt:hex PBKDF2-SHA256)
            _salt = secrets.token_hex(16)
            _hashed = hashlib.pbkdf2_hmac('sha256', temp_password.encode(), _salt.encode(), 100000)
            password_hash = f"{_salt}:{_hashed.hex()}"

            # Determine tier
            tier = "TRIAL" if not late_redemption else "STANDARD"

            # Build intake data from assessment
            intake_data = {"goals": [], "modality": "General"}
            if assessment:
                goals = assessment["goals"]
                if isinstance(goals, str):
                    goals = json.loads(goals)
                intake_data["goals"] = [g.get("title", "") for g in goals] if goals else []
                intake_data["coaching_plan"] = {
                    "goals": goals,
                    "legacy_statement": assessment.get("legacy_statement", ""),
                    "source": "drip_campaign_assessment"
                }

            # Create user account
            user = await conn.fetchrow(
                """INSERT INTO users
                   (username, password_hash, role, tier, name, email,
                    subscription_status, intake_data)
                   VALUES ($1, $2, 'CLIENT', $3, $4, $5, $6, $7::jsonb)
                   RETURNING *""",
                username,
                password_hash,
                tier,
                prospect["first_name"] or username,
                prospect["email"],
                "TRIAL_ACTIVE" if tier == "TRIAL" else "ACTIVE",
                json.dumps(intake_data)
            )

            client_id = user["id"]

            # Update prospect with conversion info
            await conn.execute(
                """UPDATE prospects
                   SET converted_to_client_id = $2,
                       converted_at = NOW(),
                       status = 'converted'
                   WHERE id = $1""",
                prospect_id, client_id
            )

            # Mark assessment as migrated
            if assessment:
                await conn.execute(
                    """UPDATE coaching_assessments
                       SET migrated_to_vault = TRUE, migrated_at = NOW(),
                           user_id = $2
                       WHERE prospect_id = $1""",
                    prospect_id, client_id
                )

            # Link all prospect data to the new user_id
            await conn.execute(
                "UPDATE nate_insights SET user_id = $2 WHERE prospect_id = $1",
                prospect_id, client_id
            )
            await conn.execute(
                "UPDATE quiz_responses SET user_id = $2 WHERE prospect_id = $1",
                prospect_id, client_id
            )
            await conn.execute(
                "UPDATE prospect_story_store SET user_id = $2 WHERE prospect_id = $1",
                prospect_id, client_id
            )

            # Load individual insights for detailed memory seeding
            insights = await conn.fetch(
                """SELECT ni.insight_text, ni.strength, ni.growth_area, q.title, q.quiz_order
                   FROM nate_insights ni
                   JOIN quizzes q ON q.id = ni.quiz_id
                   WHERE ni.prospect_id = $1
                   ORDER BY q.quiz_order""",
                prospect_id
            )

            # Initialize warm memory in Vault
            await self._init_vault_memory(conn, client_id, prospect, story, assessment, insights)

            # Create story.json for bridge server relational context
            await self._init_story_json(client_id, prospect, story, assessment, insights)

            print(f">>> [TICKET] Created client {username} (ID: {client_id}) from prospect {prospect_id}")

            return {
                "client_id": str(client_id),
                "username": username,
                "temp_password": temp_password,
                "tier": tier,
                "late_redemption": late_redemption
            }

    async def _init_vault_memory(self, conn, client_id, prospect, story, assessment, insights=None):
        """
        Seed Little Nate's memory with the prospect's journey data.
        Creates initial memory entries so Nate's first session
        references their quiz journey.
        """
        memories = []

        # Memory 1: Journey start
        memories.append({
            "role": "SYSTEM",
            "content": (
                f"This client ({prospect['first_name'] or 'the client'}) joined through the "
                f"Emotional Coherence Drip Campaign. They completed {story['quizzes_completed'] if story else 0} quizzes "
                f"over 5 days. Their journey started on "
                f"{prospect['journey_started_at'].strftime('%B %d, %Y') if prospect.get('journey_started_at') else 'recently'}."
            ),
            "modality": "system_import"
        })

        # Memory 2: Cumulative narrative
        if story and story.get("cumulative_narrative"):
            memories.append({
                "role": "SYSTEM",
                "content": f"Cumulative emotional narrative from drip quizzes:\n{story['cumulative_narrative']}",
                "modality": "drip_narrative"
            })

        # Memory 3: Emotional profile
        if story and story.get("emotional_profile"):
            profile = story["emotional_profile"]
            if isinstance(profile, str):
                profile = json.loads(profile)
            if profile:
                memories.append({
                    "role": "SYSTEM",
                    "content": f"Emotional profile from assessment:\n{json.dumps(profile, indent=2)}",
                    "modality": "assessment_profile"
                })

        # Memory 4: Assessment snapshot
        if assessment and assessment.get("snapshot"):
            memories.append({
                "role": "SYSTEM",
                "content": f"Coaching assessment:\n{assessment['snapshot']}",
                "modality": "assessment"
            })

        # Memory 5: Goals
        if assessment and assessment.get("goals"):
            goals = assessment["goals"]
            if isinstance(goals, str):
                goals = json.loads(goals)
            goals_text = "\n".join(
                f"- Goal {g.get('priority', i+1)}: {g.get('title', '')} — {g.get('description', '')}"
                for i, g in enumerate(goals)
            )
            memories.append({
                "role": "SYSTEM",
                "content": f"Coaching goals from assessment:\n{goals_text}",
                "modality": "coaching_goals"
            })

        # Memory 6: Individual quiz insights (so Nate remembers specific things)
        if insights:
            for ins in insights:
                memories.append({
                    "role": "SYSTEM",
                    "content": (
                        f"Quiz {ins['quiz_order']} ({ins['title']}) insight:\n"
                        f"{ins['insight_text']}\n"
                        f"Strength: {ins['strength']}. Growth area: {ins['growth_area']}."
                    ),
                    "modality": f"quiz_insight_{ins['quiz_order']}"
                })

        # Memory 7: First greeting context
        name = prospect["first_name"] or "friend"
        memories.append({
            "role": "NATE",
            "content": (
                f"We've been talking for five days now, {name}. "
                f"Through quizzes and reflections, I've learned things about you that usually take much longer to surface. "
                f"This is our first real session together — but we're not starting from zero. "
                f"I already know your patterns, your strengths, and where you want to grow. "
                f"Let's build on what we've started."
            ),
            "modality": "first_greeting"
        })

        # Insert all memories
        for mem in memories:
            await conn.execute(
                """INSERT INTO memory_ledger (user_id, role, content, modality)
                   VALUES ($1, $2, $3, $4)""",
                client_id, mem["role"], mem["content"], mem.get("modality")
            )

    async def _init_story_json(self, client_id, prospect, story, assessment, insights=None):
        """
        Create story.json for the bridge server's relational context system.
        This is the file-based memory that Nate reads during sessions.
        """
        import os

        data_dir = os.getenv("DATA_DIR", "/app/data")
        vault_dir = Path(data_dir) / "Vaults" / "Clients" / str(client_id)
        vault_dir.mkdir(parents=True, exist_ok=True)

        story_data = {
            "name": prospect.get("first_name") or "Friend",
            "source": "drip_campaign",
            "converted_at": datetime.utcnow().isoformat(),
            "quizzes_completed": story["quizzes_completed"] if story else 0,
            "cumulative_narrative": story.get("cumulative_narrative", "") if story else "",
            "patterns": json.loads(story["patterns"]) if story and story.get("patterns") else [],
            "emotional_profile": json.loads(story["emotional_profile"]) if story and story.get("emotional_profile") and isinstance(story["emotional_profile"], str) else (story.get("emotional_profile") or {}),
            "assessment": {
                "snapshot": assessment.get("snapshot", "") if assessment else "",
                "goals": json.loads(assessment["goals"]) if assessment and isinstance(assessment.get("goals"), str) else (assessment.get("goals") or []) if assessment else [],
                "legacy_statement": assessment.get("legacy_statement", "") if assessment else ""
            },
            "insights": []
        }

        if insights:
            for ins in insights:
                story_data["insights"].append({
                    "quiz_order": ins["quiz_order"],
                    "quiz_title": ins["title"],
                    "insight_text": ins["insight_text"],
                    "strength": ins["strength"],
                    "growth_area": ins["growth_area"]
                })

        story_file = vault_dir / "story.json"
        story_file.write_text(json.dumps(story_data, indent=2, default=str))
        print(f">>> [TICKET] Created story.json for client {client_id} at {story_file}")

        # Also create memory.json from memory_ledger entries
        # (bridge server reads this for session context)
        memory_file = vault_dir / "memory.json"
        if not memory_file.exists():
            memory_file.write_text(json.dumps([], indent=2))
            print(f">>> [TICKET] Created memory.json for client {client_id}")

    @staticmethod
    def _email_to_username(email: str) -> str:
        """Convert email to a clean username."""
        local = email.split("@")[0]
        # Clean: only alphanumeric and underscores
        clean = "".join(c if c.isalnum() or c == "_" else "_" for c in local)
        return clean.lower()[:50]
