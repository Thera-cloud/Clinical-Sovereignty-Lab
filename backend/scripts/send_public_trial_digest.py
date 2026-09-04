#!/usr/bin/env python3
"""Send one Public Trial Daily Digest email (manual / cron on GREEN)."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> int:
    from app.services.public_trial_digest import (
        PublicTrialDigest,
        parse_try_html_unique_ips,
    )

    db_pool = None
    try:
        import asyncpg
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            print("DATABASE_URL required", file=sys.stderr)
            return 1
        db_pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        from app.websocket.notification_system import NotificationSystem
        data_dir = os.getenv("DATA_DIR", "/app/data")
        api_key = os.getenv("SENDGRID_API_KEY", "")
        notifications = NotificationSystem(data_dir, sendgrid_key=api_key or None)

        window_start = datetime.now(timezone.utc) - timedelta(hours=24)
        log_path = os.getenv("PUBLIC_TRIAL_NGINX_ACCESS_LOG", "/var/log/nginx/access.log")
        nginx_ips = parse_try_html_unique_ips(log_path, window_start)
        overrides: dict = {}
        env_ips = os.getenv("PUBLIC_TRIAL_DIGEST_UNIQUE_IPS", "").strip()
        if env_ips.isdigit():
            overrides["unique_ips"] = int(env_ips)
        elif nginx_ips is not None:
            overrides["unique_ips"] = nginx_ips
        env_label = os.getenv("PUBLIC_TRIAL_SOURCE_LABEL", "").strip()
        if env_label:
            overrides["_latest_source_label"] = env_label

        digest = PublicTrialDigest(
            db_pool=db_pool,
            notification_system=notifications,
            redis_url=os.getenv("REDIS_URL", ""),
        )
        # Manual/cron script: force=True bypasses same-day restart dedupe
        result = await digest.build_and_send(overrides=overrides, force=True)
        print(f"subject={result['subject']}")
        print(f"sent={result['sent']}")
        print(f"organic_conversations={result['data'].get('organic_conv_count')}")
        print(f"unique_ips={result['data'].get('unique_ips')}")
        return 0 if result["sent"] else 2
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    finally:
        if db_pool:
            await db_pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
