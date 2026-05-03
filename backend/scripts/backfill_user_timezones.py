"""Backfill users.timezone via phone/address/ip cascade for rows still on default_utc.

  Default: dry-run (no writes). Mutate only with:  python backfill_user_timezones.py --execute

  Run inside backend container so DATABASE_URL matches production:

    docker compose -f docker-compose.prod.yml exec -T backend \\
      python /app/scripts/backfill_user_timezones.py

  If you copied the script to /tmp, either set BACKEND_ROOT=/app or use the repo path
  under /app/scripts (compose bind-mount). This script adds /app to sys.path when
  ``app`` lives at /app/app.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from typing import Any, Callable, Dict, Optional

# Ensure `app` package resolves (`python /tmp/...` puts /tmp first on sys.path).
_script_dir = os.path.dirname(os.path.abspath(__file__))


def _backend_roots() -> list[str]:
    env = os.environ.get("BACKEND_ROOT", "").strip().rstrip("/")
    # Order: explicit env, parent of backend/scripts (…/backend), Docker app root.
    out = [
        os.path.abspath(os.path.join(_script_dir, "..")),
        "/app",
    ]
    if env:
        out.insert(0, env)
    return out


def _ensure_app_on_path() -> None:
    """Insert the directory that *contains* the top-level ``app/`` package (i.e. …/backend or /app)."""
    marker = ("app", "utils", "timezone_resolver.py")
    for r in _backend_roots():
        if not r:
            continue
        if os.path.isfile(os.path.join(r, *marker)):
            if r not in sys.path:
                sys.path.insert(0, r)
            return
    # Docker: code at /app/app/… — prepend so /tmp-run scripts still resolve ``app``.
    if os.path.isfile("/app/app/utils/timezone_resolver.py"):
        sys.path.insert(0, "/app")


def _load_resolve_user_timezone() -> Callable[..., Any]:
    _ensure_app_on_path()
    try:
        from app.utils.timezone_resolver import resolve_user_timezone

        return resolve_user_timezone
    except ModuleNotFoundError as e:
        # Bracket image without package wiring or script copied to /tmp only.
        candidates = [
            "/app/app/utils/timezone_resolver.py",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "utils", "timezone_resolver.py"),
        ]
        for path in candidates:
            path = os.path.abspath(path)
            if not os.path.isfile(path):
                continue
            spec = importlib.util.spec_from_file_location("timezone_resolver_backfill", path)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            fn = getattr(mod, "resolve_user_timezone", None)
            if callable(fn):
                return fn
        print(
            "Cannot import resolve_user_timezone. Deploy backend/app/utils/timezone_resolver.py "
            "to GREEN (mount /app/app). Original error:",
            e,
            file=sys.stderr,
        )
        sys.exit(1)


_ensure_app_on_path()


def _profile_data_dict(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


def _address_parts(profile: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    addr = profile.get("address")
    if isinstance(addr, str):
        try:
            addr = json.loads(addr)
        except Exception:
            addr = None
    if not isinstance(addr, dict):
        return None, None
    country = addr.get("country") or addr.get("country_code")
    if country is not None:
        country = str(country).strip() or None
    postal = addr.get("postal_code") or addr.get("zip") or addr.get("postal")
    if postal is not None:
        postal = str(postal).strip() or None
    return country, postal


async def main(dry_run: bool = True) -> None:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL required", file=sys.stderr)
        sys.exit(1)

    import asyncpg

    resolve_user_timezone = _load_resolve_user_timezone()

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT id, username, phone, profile_data, last_login_ip, timezone, timezone_source
            FROM users
            WHERE COALESCE(timezone_source, 'default_utc') = 'default_utc'
            ORDER BY username
            """
        )
        print(f"Found {len(rows)} users with timezone_source=default_utc")

        for row in rows:
            profile = _profile_data_dict(row["profile_data"])
            country, postal = _address_parts(profile)
            phone = row["phone"]
            if phone is not None:
                phone = str(phone).strip() or None
            ip = row["last_login_ip"]
            if ip is not None:
                ip = str(ip).strip() or None

            tz, source = resolve_user_timezone(
                explicit_setting=None,
                browser_tz=None,
                phone_number=phone,
                address_country=country,
                address_postal=postal,
                ip_address=ip,
            )

            cur_tz = row["timezone"] or "UTC"
            print(f"  {row['username']}: {cur_tz!r} -> {tz!r} (source={source})")

            if dry_run:
                continue

            if tz == "UTC" and source == "default_utc":
                continue

            await conn.execute(
                """
                UPDATE users
                SET timezone = $1,
                    timezone_source = $2,
                    timezone_updated_at = NOW()
                WHERE id = $3
                """,
                tz,
                source,
                row["id"],
            )

        print("Done" if not dry_run else "DRY RUN — no changes made")
    finally:
        await conn.close()


if __name__ == "__main__":
    dry = "--execute" not in sys.argv
    asyncio.run(main(dry_run=dry))
