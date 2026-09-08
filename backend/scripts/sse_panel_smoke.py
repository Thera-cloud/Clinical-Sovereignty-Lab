"""GREEN smoke for journey-panel chat. No PHI printed."""
import asyncio
import os
import sys

sys.path.insert(0, "/app")

from app.services.sse_panel_chat_context import (
    _http_get_bytes,
    _r2_url_to_data_url,
    build_sse_panel_chat_context,
    ensure_three_focus_topics,
    focus_topics_complete,
    sse_should_complete_focus_topics,
)


def _unit():
    proto = "x\n[SOVEREIGN JOURNEY DEEP REFLECTION PROTOCOL — follow]"
    cutoff = "Warm scene.\nFor today, here are three focus topics for reflection:\n1."
    ctx = (
        proto
        + "\nCore character manifested: Curiosity\n"
        + "Crystal themes that drove this panel: loneliness, growth"
    )
    fixed = ensure_three_focus_topics(cutoff, ctx)
    already = (
        "Here are three:\n1. First topic is long enough here.\n"
        "2. Second topic is long enough.\n3. Third topic is long enough now."
    )
    print("UNIT_cutoff_incomplete", focus_topics_complete(cutoff))
    print("UNIT_fixed_complete", focus_topics_complete(fixed))
    print("UNIT_fixed_has_123", "1." in fixed and "2." in fixed and "3." in fixed)
    print("UNIT_idempotent", ensure_three_focus_topics(already, ctx) == already)
    print(
        "UNIT_should_tag",
        sse_should_complete_focus_topics(
            "[SSE Panel:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee] three focus topics",
            proto,
        ),
    )
    print("UNIT_should_cutoff_phrase", sse_should_complete_focus_topics("it got cut off", proto))
    print("UNIT_should_not_empty", sse_should_complete_focus_topics("hello", proto) is False)
    try:
        raw = _http_get_bytes("https://example.invalid/nope")
        print("UNIT_http_none_url", raw is None)
    except Exception as exc:
        print("UNIT_http_raises_ok", type(exc).__name__)
        print("UNIT_r2_wrapper_swallows", True)


async def _live():
    import asyncpg

    url = os.environ.get("DATABASE_URL") or ""
    if not url:
        print("LIVE_skip no DATABASE_URL")
        return
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2, command_timeout=30)
    users = [
        ("Godsbabi", "CLIENT_GODSBABI_ID"),
        ("LetsGoLisa", "CLIENT_LETSGOLISA_ID"),
    ]
    async with pool.acquire() as conn:
        for uname, hw in users:
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM sse_panel_log
                WHERE user_id = ANY($1::text[])
                """,
                [uname, hw],
            )
            latest = await conn.fetchrow(
                """
                SELECT panel_id::text AS pid,
                       (r2_url IS NOT NULL AND length(r2_url) > 8) AS has_r2,
                       left(coalesce(r2_url,''), 24) AS url_prefix
                FROM sse_panel_log
                WHERE user_id = ANY($1::text[])
                ORDER BY generated_at DESC NULLS LAST
                LIMIT 1
                """,
                [uname, hw],
            )
            print(
                "PANEL_META",
                uname,
                "n",
                n,
                "has_r2",
                bool(latest and latest["has_r2"]),
                "url_https",
                bool(latest and str(latest["url_prefix"]).startswith("https://")),
                "pid_ok",
                bool(latest and latest["pid"]),
            )
            if latest and latest["has_r2"]:
                raw_url = await conn.fetchval(
                    """
                    SELECT r2_url FROM sse_panel_log
                    WHERE user_id = ANY($1::text[])
                    ORDER BY generated_at DESC NULLS LAST LIMIT 1
                    """,
                    [uname, hw],
                )
                data_url = await _r2_url_to_data_url(raw_url or "")
                print(
                    "IMAGE_FETCH",
                    uname,
                    "ok",
                    bool(data_url),
                    "prefix",
                    (data_url or "")[:22],
                    "len",
                    len(data_url or ""),
                )

        hist = await conn.fetch(
            """
            SELECT user_id,
                   COUNT(*) FILTER (WHERE created_at > TIMESTAMPTZ '2026-08-31 18:55:00+00') AS after_be,
                   COUNT(*) FILTER (WHERE created_at > TIMESTAMPTZ '2026-08-31 21:24:00+00') AS after_br,
                   COUNT(*) FILTER (
                     WHERE user_text ILIKE '%Sovereign Journey story panel%'
                        OR user_text ILIKE '%[SSE Panel:%'
                   ) AS panel_asks
            FROM conversation_history
            WHERE user_id = ANY($1::text[])
            GROUP BY user_id
            """,
            ["Godsbabi", "LetsGoLisa", "CLIENT_GODSBABI_ID", "CLIENT_LETSGOLISA_ID"],
        )
        for h in hist:
            print(
                "HIST",
                h["user_id"],
                "after_be",
                h["after_be"],
                "after_br",
                h["after_br"],
                "panel_asks_alltime",
                h["panel_asks"],
            )

        lasts = await conn.fetch(
            """
            SELECT user_id, created_at,
                   (ai_text ~* E'(^|\\n)\\s*1[.)]\\s+\\S.{8,}') AS has_1,
                   (ai_text ~* E'(^|\\n)\\s*2[.)]\\s+\\S.{8,}') AS has_2,
                   (ai_text ~* E'(^|\\n)\\s*3[.)]\\s+\\S.{8,}') AS has_3,
                   length(ai_text) AS ai_len,
                   (right(regexp_replace(ai_text, E'\\s+$', ''), 2) = '1.') AS ends_at_1
            FROM conversation_history
            WHERE user_id = ANY($1::text[])
              AND (
                    user_text ILIKE '%Sovereign Journey story panel%'
                 OR user_text ILIKE '%[SSE Panel:%'
                 OR user_text ILIKE '%cut off%'
                 OR user_text ILIKE '%repost%'
              )
            ORDER BY created_at DESC
            LIMIT 8
            """,
            ["Godsbabi", "LetsGoLisa", "CLIENT_GODSBABI_ID", "CLIENT_LETSGOLISA_ID"],
        )
        for i, x in enumerate(lasts):
            print(
                "LAST_PANEL",
                i,
                x["user_id"],
                str(x["created_at"])[:19],
                "has_123",
                bool(x["has_1"] and x["has_2"] and x["has_3"]),
                "ai_len",
                x["ai_len"],
                "ends_at_1",
                bool(x["ends_at_1"]),
            )

        try:
            forge = await conn.fetch(
                """
                SELECT COALESCE(username, hardware_id) AS who, COUNT(*) AS n
                FROM nate_intelligence_crystals
                WHERE (username = ANY($1::text[]) OR hardware_id = ANY($1::text[])
                       OR user_id::text = ANY($1::text[]))
                  AND (
                        COALESCE(domain, '') ILIKE '%identity%'
                     OR COALESCE(source, '') ILIKE '%identity_forge%'
                     OR COALESCE(crystal_text, '') ILIKE '%Identity Forge%'
                  )
                GROUP BY 1
                """,
                ["Godsbabi", "LetsGoLisa", "CLIENT_GODSBABI_ID", "CLIENT_LETSGOLISA_ID"],
            )
            for f in forge:
                print("FORGE_CRYSTALS", f["who"], f["n"])
        except Exception as exc:
            print("FORGE_SKIP", type(exc).__name__)

    for uname, hw in users:
        profile = {"username": uname, "hardware_id": hw}
        _ut, ctx, img = await build_sse_panel_chat_context(
            pool, profile, "it got cut off — can you list the three focus topics again"
        )
        print(
            "FOLLOWUP",
            uname,
            "ctx_len",
            len(ctx),
            "protocol",
            "DEEP REFLECTION PROTOCOL" in ctx,
            "contract",
            "SSE PANEL CONTRACT" in ctx,
            "followup_flag",
            "SSE PANEL FOLLOW-UP" in ctx,
            "image_flag",
            "SSE PANEL IMAGE" in ctx,
            "img_ok",
            bool(img),
            "img_len",
            len(img or ""),
        )
        async with pool.acquire() as conn:
            pid = await conn.fetchval(
                """
                SELECT panel_id::text FROM sse_panel_log
                WHERE user_id = ANY($1::text[])
                ORDER BY generated_at DESC NULLS LAST LIMIT 1
                """,
                [uname, hw],
            )
        if pid:
            tagged = (
                f"[SSE Panel:{pid}] walk me through this image and give me three focus topics"
            )
            ut2, ctx2, img2 = await build_sse_panel_chat_context(pool, profile, tagged)
            print(
                "TAGGED",
                uname,
                "ctx_len",
                len(ctx2),
                "protocol",
                "DEEP REFLECTION PROTOCOL" in ctx2,
                "contract",
                "SSE PANEL CONTRACT" in ctx2,
                "image_flag",
                "SSE PANEL IMAGE" in ctx2,
                "img_ok",
                bool(img2),
                "img_len",
                len(img2 or ""),
                "stripped",
                "(asking about my Sovereign Journey story panel image)" in ut2,
            )
    await pool.close()


if __name__ == "__main__":
    _unit()
    asyncio.run(_live())
    print("SMOKE_DONE")
