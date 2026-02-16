"""
Tests for NateNudgeService — proactive notification system.
"""

import pytest
from uuid import uuid4
from datetime import datetime, timedelta, timezone

from app.services.nate_nudge import NateNudgeService, NUDGE_TEMPLATES


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_service(fake_pool):
    return NateNudgeService(db_pool=fake_pool)


# ─── Template Tests ───────────────────────────────────────────────────────────

class TestNudgeTemplates:
    def test_all_required_templates_exist(self):
        """Every nudge type referenced in the service must have a template."""
        required = [
            "session_prep", "mood_check",
            "milestone_sessions", "milestone_breakthrough", "milestone_streak",
        ]
        for name in required:
            assert name in NUDGE_TEMPLATES, f"Missing template: {name}"

    def test_templates_have_title_and_content(self):
        for name, tpl in NUDGE_TEMPLATES.items():
            assert "title" in tpl, f"{name} template missing title"
            assert "content" in tpl, f"{name} template missing content"
            assert len(tpl["title"]) > 0
            assert len(tpl["content"]) > 0

    def test_session_prep_template_placeholders(self):
        """session_prep template should accept name, coach_name, hours_until."""
        tpl = NUDGE_TEMPLATES["session_prep"]
        result = tpl["content"].format(
            name="Alice", coach_name="Hope", hours_until=2
        )
        assert "Alice" in result
        assert "Hope" in result
        assert "2" in result

    def test_mood_check_template_placeholders(self):
        """mood_check template should accept name."""
        tpl = NUDGE_TEMPLATES["mood_check"]
        result = tpl["content"].format(name="Bob")
        assert "Bob" in result

    def test_milestone_sessions_template_placeholders(self):
        tpl = NUDGE_TEMPLATES["milestone_sessions"]
        result = tpl["content"].format(name="Charlie", count=25)
        assert "Charlie" in result
        assert "25" in result


# ─── Service Initialization ──────────────────────────────────────────────────

class TestNateNudgeInit:
    def test_initialization(self, fake_pool):
        svc = make_service(fake_pool)
        assert svc.db_pool is fake_pool


# ─── Session Prep Nudge Generation ──────────────────────────────────────────

class TestSessionPrepNudges:
    @pytest.mark.asyncio
    async def test_returns_int(self, fake_pool, fake_conn):
        """Should return count of nudges created (0 when no upcoming sessions)."""
        fake_conn._fetch_results = []
        svc = make_service(fake_pool)
        count = await svc.generate_session_prep_nudges()
        assert isinstance(count, int)
        assert count == 0

    @pytest.mark.asyncio
    async def test_creates_nudges_for_upcoming_sessions(self, fake_pool, fake_conn):
        """When the DB returns upcoming sessions, nudges should be created."""
        session_id = uuid4()
        client_id = uuid4()
        coach_id = uuid4()
        scheduled = datetime.now(timezone.utc) + timedelta(hours=2)

        # Simulate upcoming session rows
        fake_conn._fetch_results = [
            {
                "session_id": session_id,
                "client_id": client_id,
                "coach_id": coach_id,
                "scheduled_at": scheduled,
                "client_name": "TestUser",
                "coach_name": "Coach Hope",
            }
        ]
        svc = make_service(fake_pool)
        count = await svc.generate_session_prep_nudges()
        assert count == 1
        # Verify INSERT was called
        assert len(fake_conn._executed) >= 1
        insert_query = fake_conn._executed[-1][0]
        assert "nate_nudges" in insert_query
        assert "session_prep" in insert_query


# ─── Mood Check Nudge Generation ────────────────────────────────────────────

class TestMoodCheckNudges:
    @pytest.mark.asyncio
    async def test_returns_int(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        svc = make_service(fake_pool)
        count = await svc.generate_mood_check_nudges()
        assert isinstance(count, int)
        assert count == 0

    @pytest.mark.asyncio
    async def test_creates_mood_nudges(self, fake_pool, fake_conn):
        user_id = uuid4()
        fake_conn._fetch_results = [{"id": user_id, "name": "Alice"}]
        svc = make_service(fake_pool)
        count = await svc.generate_mood_check_nudges(interval_hours=24)
        assert count == 1
        assert len(fake_conn._executed) >= 1


# ─── Milestone Nudge Generation ─────────────────────────────────────────────

class TestMilestoneNudges:
    @pytest.mark.asyncio
    async def test_returns_int(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        svc = make_service(fake_pool)
        count = await svc.generate_milestone_nudges()
        assert isinstance(count, int)
        assert count == 0


# ─── Query & Status Methods ─────────────────────────────────────────────────

class TestNudgeQueries:
    @pytest.mark.asyncio
    async def test_get_pending_nudges_empty(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        svc = make_service(fake_pool)
        result = await svc.get_pending_nudges(uuid4())
        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_get_pending_nudges_formatting(self, fake_pool, fake_conn):
        nudge_id = uuid4()
        now = datetime.now(timezone.utc)
        fake_conn._fetch_results = [
            {
                "id": nudge_id,
                "nudge_type": "mood_check",
                "title": "How are you?",
                "content": "Check in!",
                "status": "pending",
                "scheduled_at": now,
                "sent_at": None,
                "opened_at": None,
            }
        ]
        svc = make_service(fake_pool)
        result = await svc.get_pending_nudges(uuid4())
        assert len(result) == 1
        assert result[0]["id"] == str(nudge_id)
        assert result[0]["nudge_type"] == "mood_check"
        assert result[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_mark_sent(self, fake_pool, fake_conn):
        svc = make_service(fake_pool)
        await svc.mark_sent(uuid4())
        assert len(fake_conn._executed) == 1
        assert "sent" in fake_conn._executed[0][0]

    @pytest.mark.asyncio
    async def test_mark_opened(self, fake_pool, fake_conn):
        svc = make_service(fake_pool)
        await svc.mark_opened(uuid4())
        assert len(fake_conn._executed) == 1
        assert "opened" in fake_conn._executed[0][0]

    @pytest.mark.asyncio
    async def test_dismiss(self, fake_pool, fake_conn):
        svc = make_service(fake_pool)
        await svc.dismiss(uuid4())
        assert len(fake_conn._executed) == 1
        assert "dismissed" in fake_conn._executed[0][0]


# ─── Orchestrator ────────────────────────────────────────────────────────────

class TestRunAllNudgeChecks:
    @pytest.mark.asyncio
    async def test_returns_dict_with_all_types(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        svc = make_service(fake_pool)
        result = await svc.run_all_nudge_checks()
        assert isinstance(result, dict)
        assert "session_prep" in result
        assert "mood_check" in result
        assert "milestone" in result
        assert all(isinstance(v, int) for v in result.values())
