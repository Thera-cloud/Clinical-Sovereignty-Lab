#!/usr/bin/env python3
"""Replay magicguy72 transcript through adaptive + Sensitive Bridge + LLM.

Uses only magicguy72 user lines from 2026-05-23 session. Prior turns in the
same run are injected as LIVE SESSION CONTEXT (mirrors bridge _chat_live_turns).
Optional PG conversation_history rows are prepended when DATABASE_URL is set.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO = os.path.abspath(os.path.join(_BACKEND, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from dotenv import load_dotenv

load_dotenv(os.path.join(_REPO, ".env"), override=False)

os.environ.setdefault("ENABLE_COACHING_SCOPE_GATE", "true")
os.environ.setdefault("ENABLE_CLASSIFIER_LAYER", "false")

USERNAME = "magicguy72"

# User words only — May 23 session (screenshots)
USER_TURNS: List[str] = [
    "I need to upload AI so I don't have to explain so muxhconversations I've had with Claude.ai so I don't need",
    "it's frustrating because I shouldn't need to repeat everything again. I've done it too many times with therapists and Claude. I'd rather not do it all again",
    'I feel like I\'m being heard but never get any strategies. "Talk" to help',
    '"Talk therapy" feels useless. no one wants to continue to relive the things I\'ve experience AGAIN',
    "all 3 of these align with my thinking",
]

BASE_SYSTEM = """You are Little Nate — a warm, attuned therapeutic presence on Sovereign Sanctuary.
You are speaking with magicguy72. Keep replies concise unless depth is clearly needed.
No diagnosis labels. Honor the mode instruction appended after --- if present."""


@dataclass
class TurnResult:
    turn: int
    user: str
    nate_response: str
    mode: str
    direct_response: bool
    bridge_register: Optional[str]
    bridge_audit: List[str]
    scope_labels: List[str]
    live_ctx_turns: int
    pg_history_rows: int
    signals: Dict[str, Any] = field(default_factory=dict)


def _format_live_turns(turns: List[Dict[str, str]], limit: int = 16) -> str:
    if not turns:
        return ""
    parts = ["LIVE SESSION CONTEXT (most recent turns in this session):"]
    for t in turns[-limit:]:
        u = (t.get("user_text") or "")[:400]
        a = (t.get("ai_text") or "")[:400]
        if u:
            parts.append(f"Client: {u}")
        if a:
            parts.append(f"Nate: {a}")
    return "\n".join(parts)


def _format_pg_history(rows: List[Dict[str, str]], limit: int = 12) -> str:
    if not rows:
        return ""
    parts = ["PRIOR CONVERSATION HISTORY (from database, older sessions):"]
    for r in rows[-limit:]:
        u = (r.get("user_text") or "")[:300]
        a = (r.get("ai_text") or "")[:300]
        if u:
            parts.append(f"Client: {u}")
        if a:
            parts.append(f"Nate: {a}")
    return "\n".join(parts)


async def _fetch_pg_history(db_pool, username: str, exclude_session_prefix: str = "") -> List[Dict[str, str]]:
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_text, ai_text, created_at
                  FROM conversation_history
                 WHERE user_id = $1
                   AND LENGTH(COALESCE(user_text, '')) > 5
                 ORDER BY created_at DESC
                 LIMIT 25
                """,
                username,
            )
    except Exception as e:
        print(f"[WARN] conversation_history fetch failed: {e}", file=sys.stderr)
        return []
    out = []
    for r in reversed(rows):
        out.append({"user_text": r["user_text"] or "", "ai_text": r["ai_text"] or ""})
    return out


async def _fetch_enrollment(db_pool, username: str) -> Optional[Dict[str, Any]]:
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT cohort_label, enrolled_at, enrolled_by,
                       gap_features_enabled IS NOT NULL AS has_flags
                  FROM sensitive_bridge_enrollment
                 WHERE user_id = $1
                """,
                username,
            )
            return dict(row) if row else None
    except Exception as e:
        print(f"[WARN] enrollment fetch failed: {e}", file=sys.stderr)
        return None


async def run_replay() -> List[TurnResult]:
    from app.services.little_nate_adaptive import SessionState, prepare_response, record_assistant_turn
    from app.services.sovereign_chat_client import generate_complete
    from app.services.therapeutic_controller import prepare_therapeutic_context

    db_pool = None
    pg_history: List[Dict[str, str]] = []
    enrollment = None
    db_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if not db_url:
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        user = os.getenv("POSTGRES_USER", "nate_admin")
        password = os.getenv("POSTGRES_PASSWORD", "")
        database = os.getenv("POSTGRES_DB", "little_nate")
        if password:
            db_url = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    if db_url:
        try:
            import asyncpg

            db_pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3, command_timeout=30)
            pg_history = await _fetch_pg_history(db_pool, USERNAME)
            enrollment = await _fetch_enrollment(db_pool, USERNAME)
        except Exception as e:
            print(f"[WARN] DB pool unavailable: {e}", file=sys.stderr)
            db_pool = None

    state = SessionState()
    profile = {"username": USERNAME, "hardware_id": USERNAME, "name": "magicguy72", "role": "CLIENT"}
    live_turns: List[Dict[str, str]] = []
    results: List[TurnResult] = []
    pg_block = _format_pg_history(pg_history)

    print(f"Enrollment: {enrollment or 'NOT FOUND (bridge runs dormant)'}")
    print(f"PG history rows loaded: {len(pg_history)}")
    print(f"ENABLE_COACHING_SCOPE_GATE={os.environ.get('ENABLE_COACHING_SCOPE_GATE')}")
    print("=" * 72)

    for i, user_text in enumerate(USER_TURNS, start=1):
        payload = prepare_response(state, user_text, profile)
        tr = TurnResult(
            turn=i,
            user=user_text,
            nate_response="",
            mode=payload.get("mode", ""),
            direct_response=bool(payload.get("direct_response")),
            bridge_register=None,
            bridge_audit=[],
            scope_labels=list(payload.get("signals", {}).keys()) if payload.get("signals") else [],
            live_ctx_turns=len(live_turns),
            pg_history_rows=len(pg_history),
            signals=dict(payload.get("signals") or {}),
        )
        for lbl in ("multi_topic_clinical_opening", "scope_gate_multi_topic", "scope_gate_continuation"):
            if payload.get("signals", {}).get(lbl):
                tr.scope_labels.append(lbl)

        system = BASE_SYSTEM
        addendum = payload.get("system_addendum") or ""
        if addendum:
            system = system + "\n\n---\n" + addendum
        if pg_block:
            system = system + "\n\n" + pg_block
        live_ctx = _format_live_turns(live_turns)
        if live_ctx:
            system = system + "\n\n" + live_ctx

        bridge_register = None
        bridge_audit: List[str] = []
        if db_pool:
            try:
                ttc = await prepare_therapeutic_context(
                    user_text=user_text,
                    user_id=USERNAME,
                    db_pool=db_pool,
                    base_system_prompt=system,
                    default_max_tokens=450,
                )
                system = ttc.get("enriched_system_prompt", system)
                meta = ttc.get("audit_metadata") or {}
                bridge_register = meta.get("register_directive") or meta.get("selected_register")
                if meta.get("sensitive_bridge_active"):
                    bridge_audit.append("sensitive_bridge_active")
                if meta.get("tmc_class"):
                    bridge_audit.append(f"tmc={meta.get('tmc_class')}")
            except Exception as e:
                bridge_audit.append(f"bridge_error:{type(e).__name__}")

        tr.bridge_register = bridge_register
        tr.bridge_audit = bridge_audit

        if payload.get("direct_response"):
            tr.nate_response = payload["direct_response"]
            tr.signals["provider"] = "scope_gate"
        else:
            try:
                text, provider = await generate_complete(
                    system,
                    user_text,
                    temperature=0.7,
                    max_tokens=450,
                    domain="clinical",
                )
                tr.nate_response = (text or "").strip()
                tr.signals["provider"] = provider
            except Exception as e:
                tr.nate_response = f"[LLM ERROR: {type(e).__name__}: {e}]"
                tr.signals["llm_error"] = str(e)

        record_assistant_turn(state, tr.nate_response)
        live_turns.append({"user_text": user_text, "ai_text": tr.nate_response})
        results.append(tr)

        print(f"\n--- TURN {i} ---")
        print(f"MAGICGUY72: {user_text}")
        print(f"Mode: {tr.mode} | direct={tr.direct_response} | live_ctx_turns={tr.live_ctx_turns}")
        if tr.scope_labels:
            print(f"Scope: {tr.scope_labels}")
        if tr.bridge_register or tr.bridge_audit:
            print(f"Bridge: register={tr.bridge_register} audit={tr.bridge_audit}")
        print(f"LITTLE NATE:\n{tr.nate_response}\n")

        await asyncio.sleep(0.1)

    if db_pool:
        await db_pool.close()
    return results


def _write_report(results: List[TurnResult], path: str) -> None:
    lines = [
        "# magicguy72 Sensitive Bridge Replay",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
        f"User: `{USERNAME}`",
        f"PG history rows: {results[0].pg_history_rows if results else 0}",
        "",
    ]
    for tr in results:
        lines.extend([
            f"## Turn {tr.turn}",
            "",
            "**magicguy72:**",
            f"> {tr.user}",
            "",
            f"- Prior live turns in prompt: **{tr.live_ctx_turns}**",
            f"- Mode: `{tr.mode}` | Scope gate direct: **{tr.direct_response}**",
            f"- Bridge register: `{tr.bridge_register}`",
            f"- Bridge audit: `{tr.bridge_audit}`",
            "",
            "**Little Nate:**",
            "",
            tr.nate_response,
            "",
            "---",
            "",
        ])
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


async def main() -> None:
    results = await run_replay()
    out_json = os.path.join(_REPO, "docs", "magicguy72_sensitive_bridge_replay.json")
    out_md = os.path.join(_REPO, "docs", "magicguy72_sensitive_bridge_replay.md")
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump([r.__dict__ for r in results], f, indent=2)
    _write_report(results, out_md)
    print(f"\nWrote {out_md}")
    print(f"Wrote {out_json}")


if __name__ == "__main__":
    asyncio.run(main())
