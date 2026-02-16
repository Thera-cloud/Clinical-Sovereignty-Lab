"""
Tests for AI Modes — TriCorder, Archivist, Guardian, Supervisor.
"""

import pytest
from uuid import uuid4

from app.services.ai_modes import (
    TriCorderMode,
    ArchivistMode,
    GuardianMode,
    SupervisorMode,
    AI_MODE_REGISTRY,
    get_ai_mode,
)


# ─── Registry & Factory ─────────────────────────────────────────────────────

class TestAIModeRegistry:
    def test_all_four_modes_registered(self):
        assert "tri_corder" in AI_MODE_REGISTRY
        assert "archivist" in AI_MODE_REGISTRY
        assert "guardian" in AI_MODE_REGISTRY
        assert "supervisor" in AI_MODE_REGISTRY
        assert len(AI_MODE_REGISTRY) == 4

    def test_get_ai_mode_returns_correct_classes(self, fake_pool):
        assert isinstance(get_ai_mode("tri_corder", fake_pool), TriCorderMode)
        assert isinstance(get_ai_mode("archivist", fake_pool), ArchivistMode)
        assert isinstance(get_ai_mode("guardian", fake_pool), GuardianMode)
        assert isinstance(get_ai_mode("supervisor", fake_pool), SupervisorMode)

    def test_get_ai_mode_raises_for_unknown(self, fake_pool):
        with pytest.raises(ValueError, match="Unknown AI mode"):
            get_ai_mode("nonexistent", fake_pool)


# ─── TriCorder Mode ─────────────────────────────────────────────────────────

class TestTriCorderMode:
    @pytest.mark.asyncio
    async def test_activate_returns_calibrating(self, fake_pool):
        mode = TriCorderMode(db_pool=fake_pool)
        result = await mode.activate(session_id=uuid4())
        assert result["mode"] == "tri_corder"
        assert result["status"] == "calibrating"
        assert result["duration_seconds"] == 30
        assert mode._active is True

    @pytest.mark.asyncio
    async def test_process_collects_samples(self, fake_pool):
        mode = TriCorderMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4())
        result = await mode.process({
            "hrv": 800, "gsr": 5.0, "voice_stress": 0.3, "breathing_rate": 14,
        })
        assert result["status"] == "calibrating"
        assert result["samples_collected"] == 1

    @pytest.mark.asyncio
    async def test_process_inactive_returns_error(self, fake_pool):
        mode = TriCorderMode(db_pool=fake_pool)
        result = await mode.process({"hrv": 800})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_generate_output_no_samples(self, fake_pool):
        mode = TriCorderMode(db_pool=fake_pool)
        mode._active = True
        result = await mode.generate_output()
        assert "error" in result

    @pytest.mark.asyncio
    async def test_generate_output_with_samples(self, fake_pool, fake_conn):
        mode = TriCorderMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4())

        # Feed multiple samples
        for i in range(5):
            await mode.process({
                "hrv": 800 + i * 10,
                "gsr": 5.0 + i * 0.1,
                "voice_stress": 0.3,
                "breathing_rate": 14,
            })

        output = await mode.generate_output()
        assert output["mode"] == "tri_corder"
        assert output["status"] == "complete"
        assert "baseline" in output
        assert "avg_hrv_ms" in output["baseline"]
        assert "stress_index" in output["baseline"]
        assert 0 <= output["baseline"]["stress_index"] <= 1
        assert output["samples_collected"] == 5

    def test_deactivate(self, fake_pool):
        mode = TriCorderMode(db_pool=fake_pool)
        mode._active = True
        result = mode.deactivate()
        assert result["status"] == "deactivated"
        assert mode._active is False


# ─── Archivist Mode ─────────────────────────────────────────────────────────

class TestArchivistMode:
    @pytest.mark.asyncio
    async def test_activate_returns_active(self, fake_pool):
        mode = ArchivistMode(db_pool=fake_pool)
        result = await mode.activate(session_id=uuid4(), user_id=uuid4())
        assert result["mode"] == "archivist"
        assert result["status"] == "active"
        assert result["chapter"] == 1

    @pytest.mark.asyncio
    async def test_process_records_fragments(self, fake_pool):
        mode = ArchivistMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4())
        result = await mode.process({"text": "When I was young..."})
        assert result["status"] == "recording"
        assert result["fragments_in_chapter"] == 1

    @pytest.mark.asyncio
    async def test_process_inactive_returns_error(self, fake_pool):
        mode = ArchivistMode(db_pool=fake_pool)
        result = await mode.process({"text": "hello"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_auto_advance_chapter(self, fake_pool):
        mode = ArchivistMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4())
        # Feed 10 fragments to trigger auto-advance
        for i in range(10):
            result = await mode.process({"text": f"Fragment {i}"})
        assert result["status"] == "new_chapter"
        assert result["chapter"] == 2

    @pytest.mark.asyncio
    async def test_explicit_new_chapter(self, fake_pool):
        mode = ArchivistMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4())
        await mode.process({"text": "First fragment"})
        result = await mode.process({
            "text": "Start new chapter",
            "new_chapter": True,
            "chapter_title": "The Middle Years",
        })
        assert result["status"] == "new_chapter"

    @pytest.mark.asyncio
    async def test_generate_output_biography(self, fake_pool, fake_conn):
        mode = ArchivistMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4(), family_id=uuid4())
        await mode.process({"text": "My earliest memory..."})
        await mode.process({"text": "Growing up in the 60s..."})
        output = await mode.generate_output()
        assert output["mode"] == "archivist"
        assert output["status"] == "complete"
        assert "biography" in output
        assert output["biography"]["total_fragments"] == 2


# ─── Guardian Mode ──────────────────────────────────────────────────────────

class TestGuardianMode:
    @pytest.mark.asyncio
    async def test_activate_returns_active(self, fake_pool):
        mode = GuardianMode(db_pool=fake_pool)
        result = await mode.activate(
            session_id=uuid4(),
            minor_id=uuid4(),
            guardian_id=uuid4(),
        )
        assert result["mode"] == "guardian"
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_process_extracts_themes(self, fake_pool):
        mode = GuardianMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4())
        result = await mode.process({
            "message_text": "I'm really worried about school and my grades",
        })
        assert result["status"] == "monitoring"
        assert result["themes_detected"] >= 1

    @pytest.mark.asyncio
    async def test_process_inactive_returns_error(self, fake_pool):
        mode = GuardianMode(db_pool=fake_pool)
        result = await mode.process({"message_text": "hello"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_extract_safe_theme_school(self):
        theme = GuardianMode._extract_safe_theme("I hate school")
        assert theme == "school concerns"

    @pytest.mark.asyncio
    async def test_extract_safe_theme_peer(self):
        theme = GuardianMode._extract_safe_theme("My friend won't talk to me")
        assert theme == "peer relationships"

    @pytest.mark.asyncio
    async def test_extract_safe_theme_none(self):
        theme = GuardianMode._extract_safe_theme("The weather is nice today")
        assert theme is None

    @pytest.mark.asyncio
    async def test_generate_output_no_themes(self, fake_pool):
        mode = GuardianMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4())
        output = await mode.generate_output()
        assert output["mode"] == "guardian"
        assert output["status"] == "complete"
        assert "No specific concerns" in output["summary"]

    @pytest.mark.asyncio
    async def test_generate_output_with_themes(self, fake_pool, fake_conn):
        mode = GuardianMode(db_pool=fake_pool)
        await mode.activate(
            session_id=uuid4(),
            minor_id=uuid4(),
            guardian_id=uuid4(),
        )
        await mode.process({"message_text": "I'm anxious about school"})
        await mode.process({"message_text": "My friend is being mean"})
        output = await mode.generate_output()
        assert "themes" in output
        assert len(output["themes"]) >= 2
        assert "privacy_notice" in output


# ─── Supervisor Mode ────────────────────────────────────────────────────────

class TestSupervisorMode:
    @pytest.mark.asyncio
    async def test_activate_returns_active(self, fake_pool):
        mode = SupervisorMode(db_pool=fake_pool)
        result = await mode.activate(session_id=uuid4(), coach_id=uuid4())
        assert result["mode"] == "supervisor"
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_process_collects_messages(self, fake_pool):
        mode = SupervisorMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4())
        result = await mode.process({
            "sender_type": "coach",
            "message_text": "I understand how you feel",
        })
        assert result["status"] == "collecting"
        assert result["messages_analyzed"] == 1

    @pytest.mark.asyncio
    async def test_process_inactive_returns_error(self, fake_pool):
        mode = SupervisorMode(db_pool=fake_pool)
        result = await mode.process({"sender_type": "coach", "message_text": "hi"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_generate_output_no_messages(self, fake_pool):
        mode = SupervisorMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4())
        output = await mode.generate_output()
        assert output["status"] == "no_data"

    @pytest.mark.asyncio
    async def test_generate_output_full_analysis(self, fake_pool):
        mode = SupervisorMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4(), coach_id=uuid4())

        # Simulate a coaching session
        await mode.process({"sender_type": "client", "message_text": "I've been feeling anxious lately"})
        await mode.process({"sender_type": "coach", "message_text": "I understand how that must feel. Tell me more about that."})
        await mode.process({"sender_type": "client", "message_text": "It started when I changed jobs"})
        await mode.process({"sender_type": "coach", "message_text": "It sounds like the transition triggered some stress. That makes sense."})
        await mode.process({"sender_type": "client", "message_text": "Yes exactly"})
        await mode.process({"sender_type": "coach", "message_text": "How do you typically cope when you feel overwhelmed?"})

        output = await mode.generate_output()
        assert output["mode"] == "supervisor"
        assert output["status"] == "complete"
        assert "analysis" in output
        analysis = output["analysis"]
        assert "empathy_score" in analysis
        assert "technique_score" in analysis
        assert "balance_score" in analysis
        assert "overall_score" in analysis
        assert "grade" in analysis
        assert analysis["grade"] in ["EXCELLENT", "PROFICIENT", "DEVELOPING", "NEEDS_IMPROVEMENT"]
        assert 0 <= analysis["empathy_score"] <= 1
        assert 0 <= analysis["overall_score"] <= 1
        assert "recommendations" in output
        assert isinstance(output["recommendations"], list)
        assert analysis["total_coach_messages"] == 3
        assert analysis["total_client_messages"] == 3

    @pytest.mark.asyncio
    async def test_empathy_detection(self, fake_pool):
        mode = SupervisorMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4())
        # Coach uses many empathy keywords
        await mode.process({"sender_type": "coach", "message_text": "I hear you. I understand how that must be."})
        await mode.process({"sender_type": "coach", "message_text": "Tell me more. That's important to explore."})
        await mode.process({"sender_type": "client", "message_text": "Thank you"})
        output = await mode.generate_output()
        assert output["analysis"]["empathy_score"] > 0

    @pytest.mark.asyncio
    async def test_technique_detection(self, fake_pool):
        mode = SupervisorMode(db_pool=fake_pool)
        await mode.activate(session_id=uuid4())
        await mode.process({"sender_type": "coach", "message_text": "It sounds like you're feeling stuck. Another way to look at this might be..."})
        await mode.process({"sender_type": "client", "message_text": "Hmm interesting"})
        output = await mode.generate_output()
        techniques = output["analysis"]["techniques_detected"]
        assert len(techniques) > 0
