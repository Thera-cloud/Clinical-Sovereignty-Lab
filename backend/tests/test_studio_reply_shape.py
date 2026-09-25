"""Reply shape: no stock opener, long questions offer a length, both drafts wait."""

import asyncio

from app.services.studio_product_brief import sanitize_onair
from app.services.studio_reply_shape import (
    LENGTH_ASK,
    drop_lengths,
    is_long_question,
    length_pick,
    strip_stock_open,
    take_length,
    arm_lengths,
)


def test_stock_opener_is_stripped():
    raw = "Honestly, I think the point you landed on is the consumer product."
    cleaned = strip_stock_open(raw)
    assert not cleaned.lower().startswith("honestly")
    assert "consumer product" in cleaned
    assert sanitize_onair("Man, that's a great question, Big Nate. The tail is the product.")
    out = sanitize_onair("Honestly, the tail of that is the product.")
    assert not out.lower().startswith("honestly")


def test_long_question_and_picks():
    short = "Nate, what do you think?"
    long = "Nate, " + " ".join(["what do you think about staying on this one topic"] * 8) + "?"
    assert not is_long_question(short)
    assert is_long_question(long)
    assert length_pick("the short one") == "short"
    assert length_pick("more defined") == "long"
    assert length_pick("tell me about the weather") is None


def test_ready_length_returns_the_armed_draft():
    async def _run():
        drop_lengths("shape-sid")

        async def _short():
            return "Short take on the product."

        async def _long():
            return "Defined take on the product, with the reframe."

        arm_lengths(
            "shape-sid",
            "long question",
            asyncio.create_task(_short()),
            asyncio.create_task(_long()),
        )
        got = await take_length("shape-sid", "the short version")
        assert got == "Short take on the product."
        assert await take_length("shape-sid", "short") is None

    asyncio.run(_run())
    assert "short version" in LENGTH_ASK
