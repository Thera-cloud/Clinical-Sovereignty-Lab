"""
Tests for LivedWisdomService — therapeutic insight extraction and Night School integration.
"""

import pytest
from uuid import uuid4

from app.services.lived_wisdom import (
    LivedWisdomService,
    TECHNIQUE_KEYWORDS,
    COPING_KEYWORDS,
    TRIGGER_KEYWORDS,
    BREAKTHROUGH_KEYWORDS,
)


# ─── Helpers ───────────────────────────────────────────────────────────────────

def make_service(fake_pool):
    return LivedWisdomService(db_pool=fake_pool)


def make_messages(texts):
    """Build a list of message dicts from a list of strings."""
    return [{"text": t, "sender_type": "client", "sender_id": str(uuid4())} for t in texts]


# ─── Keyword Lists ───────────────────────────────────────────────────────────

class TestKeywordLists:
    def test_technique_keywords_not_empty(self):
        assert len(TECHNIQUE_KEYWORDS) > 5

    def test_coping_keywords_not_empty(self):
        assert len(COPING_KEYWORDS) > 3

    def test_trigger_keywords_not_empty(self):
        assert len(TRIGGER_KEYWORDS) > 3

    def test_breakthrough_keywords_not_empty(self):
        assert len(BREAKTHROUGH_KEYWORDS) > 3


# ─── Heuristic Extraction ───────────────────────────────────────────────────

class TestKeywordExtraction:
    def test_extract_technique(self, fake_pool):
        svc = make_service(fake_pool)
        results = svc._extract_by_keywords(
            "The breathing exercise really helped me calm down during the panic attack.",
            "technique",
            TECHNIQUE_KEYWORDS,
        )
        assert len(results) >= 1
        assert results[0]["type"] == "technique"
        assert "breathing exercise" in results[0]["keyword"]

    def test_extract_coping(self, fake_pool):
        svc = make_service(fake_pool)
        results = svc._extract_by_keywords(
            "What helps me is going for a walk when I feel overwhelmed.",
            "coping",
            COPING_KEYWORDS,
        )
        assert len(results) >= 1
        assert results[0]["type"] == "coping"

    def test_extract_trigger(self, fake_pool):
        svc = make_service(fake_pool)
        results = svc._extract_by_keywords(
            "Every time my boss raises his voice it triggers me badly.",
            "trigger",
            TRIGGER_KEYWORDS,
        )
        assert len(results) >= 1
        assert results[0]["type"] == "trigger"

    def test_extract_breakthrough(self, fake_pool):
        svc = make_service(fake_pool)
        results = svc._extract_by_keywords(
            "I realized for the first time that I was repeating my mother's pattern.",
            "breakthrough",
            BREAKTHROUGH_KEYWORDS,
        )
        assert len(results) >= 1
        assert results[0]["type"] == "breakthrough"

    def test_extract_empty_text(self, fake_pool):
        svc = make_service(fake_pool)
        results = svc._extract_by_keywords("", "technique", TECHNIQUE_KEYWORDS)
        assert results == []

    def test_extract_short_sentences_skipped(self, fake_pool):
        svc = make_service(fake_pool)
        results = svc._extract_by_keywords("Yes cope.", "coping", COPING_KEYWORDS)
        assert results == []

    def test_caps_at_10_per_type(self, fake_pool):
        svc = make_service(fake_pool)
        text = ". ".join([f"I cope with {i} things when I feel stressed" for i in range(20)])
        results = svc._extract_by_keywords(text, "coping", COPING_KEYWORDS)
        assert len(results) <= 10


# ─── Session Wisdom Extraction ───────────────────────────────────────────────

class TestExtractSessionWisdom:
    @pytest.mark.asyncio
    async def test_empty_messages(self, fake_pool, fake_conn):
        svc = make_service(fake_pool)
        result = await svc.extract_session_wisdom(
            session_id=uuid4(), user_id=uuid4(), messages=[]
        )
        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_extracts_from_session_messages(self, fake_pool, fake_conn):
        svc = make_service(fake_pool)
        messages = make_messages([
            "The mindfulness exercise was very helpful today.",
            "I realized I've been avoiding the real issue all along.",
        ])
        result = await svc.extract_session_wisdom(
            session_id=uuid4(), user_id=uuid4(), messages=messages
        )
        # Should extract technique (mindfulness) and breakthrough (realized)
        assert len(result) >= 1


# ─── Sanctuary Wisdom Extraction ─────────────────────────────────────────────

class TestExtractSanctuaryWisdom:
    @pytest.mark.asyncio
    async def test_empty_messages(self, fake_pool, fake_conn):
        svc = make_service(fake_pool)
        result = await svc.extract_sanctuary_wisdom(
            session_id=uuid4(), family_id=uuid4(), messages=[]
        )
        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_extracts_family_wisdom(self, fake_pool, fake_conn):
        svc = make_service(fake_pool)
        messages = make_messages([
            "Whenever dad raises his voice it triggers everyone.",
            "The grounding technique helped us stay calm during the argument.",
        ])
        result = await svc.extract_sanctuary_wisdom(
            session_id=uuid4(), family_id=uuid4(), messages=messages,
        )
        assert len(result) >= 1


# ─── Night School Integration (queries) ─────────────────────────────────────

class TestNightSchoolIntegration:
    @pytest.mark.asyncio
    async def test_get_client_wisdom_empty(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        svc = make_service(fake_pool)
        result = await svc.get_client_wisdom(uuid4())
        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_get_family_wisdom_empty(self, fake_pool, fake_conn):
        fake_conn._fetch_results = []
        svc = make_service(fake_pool)
        result = await svc.get_family_wisdom(uuid4())
        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_approve_wisdom(self, fake_pool, fake_conn):
        svc = make_service(fake_pool)
        result = await svc.approve_wisdom(uuid4())
        # Returns bool based on "UPDATE 1" in execute result
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_update_effectiveness_clamps(self, fake_pool, fake_conn):
        svc = make_service(fake_pool)
        # Test clamping: score > 1.0 should be clamped to 1.0
        await svc.update_effectiveness(uuid4(), 2.5)
        assert len(fake_conn._executed) == 1
        _, args = fake_conn._executed[0]
        assert args[1] == 1.0  # Clamped

    @pytest.mark.asyncio
    async def test_update_effectiveness_clamps_low(self, fake_pool, fake_conn):
        svc = make_service(fake_pool)
        await svc.update_effectiveness(uuid4(), -0.5)
        _, args = fake_conn._executed[0]
        assert args[1] == 0.0  # Clamped
