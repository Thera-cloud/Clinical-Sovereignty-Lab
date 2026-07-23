#!/usr/bin/env python3
"""Send one Public Trial Daily Digest email (manual / cron on GREEN)."""
import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _nginx_stats(log_path: str = "/var/log/nginx/access.log") -> dict:
    internal = set(
        ip.strip()
        for ip in os.getenv("PUBLIC_TRIAL_INTERNAL_IPS", "170.62.100.237").split(",")
        if ip.strip()
    )
    unique: set = set()
    hints: list = []
    if not os.path.isfile(log_path):
        return {"unique_ips": None, "referrer_hints": []}
    line_re = re.compile(
        r'^(?P<ip>\S+) .+ \[(?P<ts>[^\]]+)\] "GET /try\.html .+" '
        r'"(?P<ref>[^"]*)" "(?P<ua>[^"]*)"'
    )
    for raw in open(log_path, errors="ignore"):
        m = line_re.match(raw)
        if not m:
            continue
        ip = m.group("ip")
        if ip in internal:
            continue
        unique.add(ip)
        ref = (m.group("ref") or "").lower()
        ua = m.group("ua") or ""
        source = ""
        if "linkedin" in ref:
            source = "LinkedIn"
        elif "android" in ua.lower():
            source = "Android"
        if source:
            label = source
            if "android" in ua.lower():
                label = f"{source} · Android"
            hints.append(label)
    return {"unique_ips": len(unique), "referrer_hints": hints}


async def main() -> int:
    from app.services.public_trial_digest import PublicTrialDigest

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

        nginx = await _nginx_stats()
        overrides: dict = {"unique_ips": nginx.get("unique_ips")}
        env_ips = os.getenv("PUBLIC_TRIAL_DIGEST_UNIQUE_IPS", "").strip()
        if env_ips.isdigit():
            overrides["unique_ips"] = int(env_ips)
        hints = nginx.get("referrer_hints") or []
        if hints:
            overrides["_latest_source_label"] = hints[-1]
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
        return 0 if result["sent"] else 2
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1
    finally:
        if db_pool:
            await db_pool.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
