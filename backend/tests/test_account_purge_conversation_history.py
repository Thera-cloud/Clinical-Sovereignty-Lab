"""Account purge must delete conversation_history (data-deletion.html contract)."""
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"
DATA_DELETION = Path(__file__).resolve().parents[2] / "dashboard" / "data-deletion.html"


def _purge_block() -> str:
    text = MAIN.read_text(encoding="utf-8")
    start = text.find("async def _account_purge_loop")
    assert start > 0, "_account_purge_loop missing from main.py"
    # Bound to the next sibling task init after the loop body
    end = text.find("_purge_task = _asyncio_purge.create_task", start)
    assert end > start
    return text[start:end]


def test_purge_deletes_conversation_history():
    block = _purge_block()
    assert "DELETE FROM conversation_history" in block
    assert "DELETE FROM sessions" in block
    assert "DELETE FROM nate_nudges" in block
    assert "DELETE FROM nevedal_metrics" in block
    # Must run before users anonymize so username/id lookups still resolve
    ch_i = block.index("DELETE FROM conversation_history")
    anon_i = block.index("name = 'Deleted User'")
    assert ch_i < anon_i


def test_data_deletion_page_promises_conversation_history():
    html = DATA_DELETION.read_text(encoding="utf-8")
    assert "Conversation history" in html
    assert "chat transcripts" in html.lower() or "text messages" in html.lower()
