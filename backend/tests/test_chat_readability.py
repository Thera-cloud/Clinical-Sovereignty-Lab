"""Tests for Big Nate Chat readability normalization."""

from app.services.chat_formatting import normalize_chat_readability


def test_expands_jammed_table_row_on_one_line():
    jammed = (
        "| 1 | 3:00 PM | CUR | [Awaiting URL] | | 1 | 8:00 PM | ORIG | Draft one. |"
    )
    out = normalize_chat_readability(jammed)
    assert "DAY 1 — 3:00 PM — CUR" in out
    assert "DAY 1 — 8:00 PM — ORIG" in out
    assert "[Awaiting URL]" in out
    assert "Draft one." in out


def test_preserves_plain_paragraphs():
    text = "Hello\n\nSecond paragraph."
    assert normalize_chat_readability(text) == text


def test_skips_markdown_separator_rows():
    text = "| Day | Time | Lane |\n| --- | --- | --- |\n| 1 | 8:00 PM | ORIG | Body |"
    out = normalize_chat_readability(text)
    assert "---" not in out
    assert "DAY 1 — 8:00 PM — ORIG" in out
    assert "Body" in out
