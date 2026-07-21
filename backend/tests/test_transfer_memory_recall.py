"""Tests for imported transfer memory recall (Claude ingest + vault FTS)."""

import json

import pytest

from app.services.transfer_memory_recall import (
    format_deep_memory_prompt_instruction,
    search_imported_transfer_history,
    should_search_imported_history,
)
from app.services.vault.transfer_crystal import TransferCrystalBuilder


class TestParseClaude:
    def test_parse_claude_conversation_shape_with_user_and_assistant(self):
        raw = json.dumps({
            "chats": [{
                "name": "Family stress",
                "created_at": "2024-06-01T12:00:00Z",
                "chat_messages": [
                    {"sender": "human", "text": "My dad makes me anxious", "created_at": 1717243200},
                    {"sender": "assistant", "text": "That sounds heavy.", "created_at": 1717243201},
                ],
            }],
        }).encode()

        builder = TransferCrystalBuilder(db_pool=None)
        conversations = builder.parse_claude(raw)

        assert len(conversations) == 1
        assert conversations[0]["title"] == "Family stress"
        roles = [m["role"] for m in conversations[0]["messages"]]
        assert roles == ["user", "assistant"]
        assert "anxious" in conversations[0]["messages"][0]["text"]

    def test_parse_claude_legacy_prompt_completion_types(self):
        raw = json.dumps({
            "conversations": [{
                "title": "Legacy chat",
                "messages": [
                    {
                        "type": "prompt",
                        "message": [{"type": "p", "data": "I feel stuck"}],
                        "create_time": 1717243200,
                    },
                    {
                        "type": "completion",
                        "message": [{"type": "p", "data": "Tell me more about stuck."}],
                        "create_time": 1717243201,
                    },
                ],
            }],
        }).encode()

        builder = TransferCrystalBuilder(db_pool=None)
        conversations = builder.parse_claude(raw)

        assert len(conversations) == 1
        assert len(conversations[0]["messages"]) == 2
        assert conversations[0]["messages"][0]["role"] == "user"
        assert conversations[0]["messages"][1]["role"] == "assistant"


class TestMemorySearchTrigger:
    """Mirror platform-transfer fast path from bridge _ChatMemorySearchTrigger."""

    def test_platform_recall_phrase_triggers(self):
        import re

        text = "Do you remember when I told Claude about my dad?"
        assert re.search(
            r"\b(when i (was|used|talked) (on|with)|told (claude|chatgpt|gemini|replika))\b",
            text,
            re.I,
        )

    def test_soft_import_trigger_single_platform_mention(self):
        assert should_search_imported_history("What was in my ChatGPT export about divorce?")
        assert should_search_imported_history("Tell me about my imported history")
        assert should_search_imported_history("What did I ask in Google AI Mode about anxiety?")
        assert should_search_imported_history("Can you read my MyActivity download?")
        assert not should_search_imported_history("How are you today?")


class TestGoogleAiModeParse:
    def test_detect_and_parse_myactivity_blocks(self):
        sample = (
            "AI Mode\n\n"
            "Searched for how do I download AI chats from google?\n"
            "Jul 21, 2026, 9:21:03 AM PDT\n"
            "Your prompt:\n"
            "how do I download AI chats from google?\n\n"
            "Search's response:\n"
            "Yes, your AI chat history (Gemini) is saved.\n"
            "Searched for why do I feel anxious at night\n"
            "Jun 1, 2026, 8:00:00 PM PDT\n"
            "Your prompt:\n"
            "why do I feel anxious at night\n\n"
            "Search's response:\n"
            "Nighttime anxiety is common when the day quiets down.\n"
        ).encode()

        builder = TransferCrystalBuilder(db_pool=None)
        assert builder.detect_source("MyActivity_AI Mode.txt", sample) == "google_ai_mode"
        convs = builder.parse_google_ai_mode(sample)
        assert len(convs) >= 1
        msgs = convs[0]["messages"]
        assert any(m["role"] == "user" and "download AI chats" in m["text"] for m in msgs)
        assert any(m["role"] == "assistant" and "Gemini" in m["text"] for m in msgs)
        assert any(m["role"] == "user" and "anxious at night" in m["text"] for m in msgs)

    def test_parse_myactivity_crlf_without_searched_for(self):
        # Real Google exports use CRLF; many turns omit the "Searched for" line.
        sample = (
            "AI Mode\r\n\r\n"
            "Jul 21, 2026, 9:21:03\u202fAM PDT\r\n"
            "Your prompt:\r\n"
            "how do I download AI chats from google?\r\n\r\n"
            "Search's response:\r\n"
            "Yes, your AI chat history (Gemini) is saved.\r\n"
            "Jun 1, 2026, 8:00:00 PM PDT\r\n"
            "Your prompt:\r\n"
            "why do I feel anxious at night\r\n\r\n"
            "Search's response:\r\n"
            "Nighttime anxiety is common.\r\n"
        ).encode()

        builder = TransferCrystalBuilder(db_pool=None)
        assert builder.detect_source("MyActivity_AI Mode.txt", sample) == "google_ai_mode"
        convs = builder.parse_google_ai_mode(sample)
        assert len(convs) >= 1
        user_texts = [m["text"] for m in convs[0]["messages"] if m["role"] == "user"]
        assert any("download AI chats" in t for t in user_texts)
        assert any("anxious at night" in t for t in user_texts)


class TestFlatImportWrap:
    def test_gemini_flat_messages_wrap_to_conversation(self):
        flat = [
            {"text": "I feel alone", "timestamp": 1},
            {"text": "Work is hard", "timestamp": 2},
        ]
        convs = TransferCrystalBuilder._flat_messages_to_conversations(flat, "gemini")
        assert len(convs) == 1
        assert convs[0]["title"] == "Gemini import"
        assert len(convs[0]["messages"]) == 2
        assert convs[0]["messages"][0]["role"] == "user"

    def test_stub_crystal_has_continuity_fields(self):
        stub = TransferCrystalBuilder._stub_crystal(
            "claude", {"message_count": 12, "conversation_count": 3},
        )
        assert "claude" in stub["core_identity_summary"]
        assert stub.get("_stub") is True


class TestDeepMemoryPrompt:
    def test_imported_section_gets_platform_wording(self):
        ctx = (
            "IMPORTED PLATFORM HISTORY (1 found — from AI platforms BEFORE Sanctuary):\n"
            "[CLAUDE — Family stress]\nUser: My dad..."
        )
        instr = format_deep_memory_prompt_instruction(ctx)
        assert "IMPORTED PLATFORM HISTORY" in instr
        assert "were NOT in those threads" in instr
        assert "Never say 'we talked'" in instr

    def test_nate_section_gets_remember_wording(self):
        ctx = "CONVERSATION HISTORY MATCHES (1 found):\n[Jan 01] user: hello"
        instr = format_deep_memory_prompt_instruction(ctx)
        assert "remember when you told me" in instr


@pytest.mark.asyncio
async def test_search_imported_transfer_history_empty_without_db():
    result = await search_imported_transfer_history(
        None, username="u1", hardware_id="hw1", search_terms="anxiety",
    )
    assert result == ""
