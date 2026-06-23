#!/usr/bin/env python3
"""Replay LetsGoLisa action-step requests through Sensitive Bridge + audit repair.

Uses isolated session_id prefix replay_test_letsgolisa_* — deleted on exit.
Does NOT load real conversation_history (live turns only in replay).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO = os.path.abspath(os.path.join(_BACKEND, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from dotenv import load_dotenv

load_dotenv(os.path.join(_REPO, ".env"), override=False)

USERNAME = "LetsGoLisa"
HARDWARE_ID = "CLIENT_LETSGOLISA_ID"
SESSION_PREFIX = "replay_test_letsgolisa_"

# Lisa Jun 22 session — turns that failed direct delivery (with minimal context)
CONTEXT_TURN = (
    "Little Nate, could you generate a bullet list of my progress over the past "
    "2 weeks please? It can be posted here on the screen."
)

FAILING_TURNS: List[str] = [
    "It feels complete. Thank you. Could we also take this list and generate "
    "some good action steps for me to consider?",
    "Yes, I am hopeful and I'd like to continue the integration. Perhaps you "
    "could suggest 2-3 action steps that you believe would be helpful with my "
    "current process?",
    "So in keeping with my list above, do you have 2-3 prospective action "
    "steps that emerge?",
    "You are asking me questions instead of suggesting. Are you holding back "
    "for a particular reason?",
    "Thank you. Do you have any others to add from your HUGE database of wisdom? "
    "I like hearing your suggestions.",
    "I welcome you to offer one.",
]

BASE_SYSTEM = """You are Little Nate — warm, attuned coaching presence on Sovereign Sanctuary.
You are speaking with Lisa (LetsGoLisa). Honor clinical boundaries in appended blocks."""


@dataclass
class TurnResult:
    turn: int
    user: str
    nate_response: str
    direct_action_kind: Optional[str]
    audit_passed: Optional[bool]
    violations: List[str] = field(default_factory=list)
    list_items: int = 0
    bridge_register: Optional[str] = None


def _format_live(turns: List[Dict[str, str]]) -> str:
    if not turns:
        return ""
    lines = ["LIVE SESSION CONTEXT (this replay only):"]
    for t in turns[-12:]:
        if t.get("user_text"):
            lines.append(f"Client: {t['user_text'][:400]}")
        if t.get("ai_text"):
            lines.append(f"Nate: {t['ai_text'][:400]}")
    return "\n".join(lines)


async def _delete_test_rows(db_pool, session_id: str) -> int:
    async with db_pool.acquire() as conn:
        n = await conn.execute(
            "DELETE FROM conversation_history WHERE session_id = $1",
            session_id,
        )
    # asyncpg returns 'DELETE n'
    try:
        return int(str(n).split()[-1])
    except Exception:
        return 0


async def _insert_test_row(
    db_pool, session_id: str, user_text: str, ai_text: str,
) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO conversation_history
                (session_id, user_id, user_text, ai_text, created_at)
            VALUES ($1, $2, $3, $4, NOW())
            """,
            session_id,
            USERNAME,
            user_text,
            ai_text,
        )


async def run_replay(persist: bool, write_db: bool) -> List[TurnResult]:
    from app.services.little_nate_clinical_output_policy import (
        classify_direct_action_request,
        count_deliverable_list_items,
    )
    from app.services.sovereign_chat_client import generate_complete
    from app.services.therapeutic_controller import (
        audit_therapeutic_response,
        prepare_therapeutic_context,
    )

    db_pool = None
    db_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if not db_url:
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        user = os.getenv("POSTGRES_USER", "nate_admin")
        password = os.getenv("POSTGRES_PASSWORD", "")
        database = os.getenv("POSTGRES_DB", "little_nate")
        if password:
            db_url = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    session_id = SESSION_PREFIX + uuid.uuid4().hex[:12]

    if db_url:
        import asyncpg

        db_pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3, command_timeout=60)
        if write_db:
            await _delete_test_rows(db_pool, session_id)

    live: List[Dict[str, str]] = []
    results: List[TurnResult] = []
    sequence = [CONTEXT_TURN] + FAILING_TURNS

    print(f"Session: {session_id}")
    print(f"User: {USERNAME} | persist={persist} write_db={write_db}")
    print("=" * 72)

    for i, user_text in enumerate(sequence, start=1):
        system = BASE_SYSTEM
        live_ctx = _format_live(live)
        if live_ctx:
            system = system + "\n\n" + live_ctx

        direct_kind = classify_direct_action_request(user_text)
        bridge_register = None
        meta: Dict[str, Any] = {}

        if db_pool:
            ttc = await prepare_therapeutic_context(
                user_text=user_text,
                user_id=HARDWARE_ID,
                db_pool=db_pool,
                base_system_prompt=system,
                default_max_tokens=450,
                session_id=session_id,
            )
            system = ttc.get("enriched_system_prompt", system)
            meta = dict(ttc.get("audit_metadata") or {})
            bridge_register = meta.get("register_directive") or meta.get("register_default")
            _len_cap = ttc.get("max_tokens", 450)
        else:
            _len_cap = 450

        text, provider = await generate_complete(
            system,
            user_text,
            temperature=0.7,
            max_tokens=_len_cap,
            domain="clinical",
        )
        nate = (text or "").strip()
        audit_passed: Optional[bool] = None
        violations: List[str] = []

        if meta and db_pool:
            audited = await audit_therapeutic_response(
                response_text=nate,
                audit_metadata=meta,
                user_id=HARDWARE_ID,
                db_pool=db_pool,
            )
            nate = (audited.get("response_text") or nate).strip()
            audit_passed = audited.get("audit_passed")
            violations = list(audited.get("violations") or [])

        items = count_deliverable_list_items(nate)
        tr = TurnResult(
            turn=i,
            user=user_text,
            nate_response=nate,
            direct_action_kind=direct_kind or meta.get("direct_action_request_kind"),
            audit_passed=audit_passed,
            violations=violations,
            list_items=items,
            bridge_register=bridge_register,
        )
        results.append(tr)
        live.append({"user_text": user_text, "ai_text": nate})

        if write_db and db_pool:
            await _insert_test_row(db_pool, session_id, user_text, nate)

        ok = (
            "PASS"
            if (not tr.direct_action_kind or items >= 2 or (tr.direct_action_kind != "action_steps" and items >= 1))
            else "FAIL"
        )
        if tr.direct_action_kind in ("single_suggestion", "teaching") and len(nate) >= 80 and not nate.strip().endswith("?"):
            ok = "PASS"

        print(f"\n--- TURN {i} [{ok}] ---")
        print(f"LISA: {user_text[:120]}...")
        print(f"direct_action={tr.direct_action_kind} register={bridge_register} items={items} audit={audit_passed}")
        if violations:
            print(f"violations={violations}")
        print(f"NATE:\n{nate}\n")

        await asyncio.sleep(0.05)

    if db_pool and not persist:
        deleted = await _delete_test_rows(db_pool, session_id)
        print(f"\nDeleted {deleted} replay rows (session_id={session_id})")
        await db_pool.close()
    elif db_pool:
        await db_pool.close()
        print(f"\nLeft {len(sequence)} rows under session_id={session_id} (persist mode)")

    passed = sum(
        1
        for r in results
        if r.turn > 1
        and (
            not r.direct_action_kind
            or r.list_items >= 2
            or (
                r.direct_action_kind in ("single_suggestion", "teaching")
                and len(r.nate_response) >= 80
                and not r.nate_response.strip().endswith("?")
            )
        )
    )
    actionable = [r for r in results if r.turn > 1 and r.direct_action_kind]
    print(f"\nSUMMARY: {passed}/{len(actionable)} actionable turns delivered substance")

    return results


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--persist", action="store_true", help="Keep DB rows after run")
    p.add_argument("--write-db", action="store_true", help="Write rows during replay (still deleted unless --persist)")
    args = p.parse_args()
    asyncio.run(run_replay(persist=args.persist, write_db=args.write_db))


if __name__ == "__main__":
    main()
