#!/usr/bin/env python3
"""One-off: post a short test message to the LinkedIn company page (post_as=company)."""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")


async def main() -> int:
    import asyncpg
    from app.services.platforms import get_adapter

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    try:
        adapter = get_adapter("linkedin", pool)
        if not adapter:
            print("No LinkedIn adapter", file=sys.stderr)
            return 1
        ok = await adapter.authenticate()
        if not ok:
            print(f"LinkedIn authenticate failed: {getattr(adapter, '_last_error', 'unknown')}", file=sys.stderr)
            return 1

        org = getattr(adapter, "_org_urn", None)
        print(f"org_urn={org}")

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        text = (
            "Company page connectivity test — Sovereign Sanctuary. "
            "If you see this on our organization page, routing is working. "
            f"({stamp})\n\n"
            "Nathaniel reviewed + approved — Little Nate, your AI companion"
        )
        result = await adapter.post_content(text=text, post_as="company")
        print(f"success={result.success} post_id={result.post_id} url={result.post_url} error={result.error}")
        return 0 if result.success else 2
    finally:
        await pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
