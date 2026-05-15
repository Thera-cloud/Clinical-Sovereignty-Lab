#!/usr/bin/env python3
"""E2E behavior verification: therapeutic pre-flight + completion path + client-initiated persistence.

Equivalence note (bridge ``process_interaction``):
    Bridge applies ``prepare_therapeutic_context(...)``, replaces ``system_prompt``,
    then streams or completes via sovereign routing. This script uses the same
    ``prepare_therapeutic_context`` + ``generate_complete`` (non-streaming completion)
    as the non-stream fallback path — same enriched prompt and caps.

Usage:
    cd backend && python scripts/e2e_v14_behavior_verify.py [--mock-llm|--live-llm]

Requires DATABASE_URL (or POSTGRES_* vars handled by asyncpg URL builder below).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Repo root: backend/
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_BACKEND_ROOT.parent / ".env")
    load_dotenv(_BACKEND_ROOT / ".env")
except ImportError:
    pass

import asyncpg

from app.routers.sensitive_profile_api import _hash_codeword
from app.services.client_initiated_sensitive_registration import (
    CLIENT_INITIATED_ACTOR,
    EVT_CODEWORD_CLIENT_INITIATED,
    EVT_PART_CLIENT_INITIATED,
    persist_client_initiated_codeword,
    persist_client_initiated_part,
)
from app.services.sensitive_clinical_bridge import FULL_ACTIVATION_GAP_FEATURES
from app.services.sovereign_chat_client import generate_complete
from app.services.therapeutic_controller import prepare_therapeutic_context

TEST_USER = "test_v14_behavior"
TEST_HW_ID = "CLIENT_TEST_V14_BEHAVIOR_ID"
BASE_CLIENT_PROMPT = (
    "You are Little Nate, a trauma-informed AI therapeutic companion. "
    "Respond briefly and warmly in plain language."
)

MOCK_MANTRA = (
    "Here is one grounding mantra:\n\n"
    "\"I am breathing; I can slow down.\"\n\n"
    "Say it silently on each exhale when anxiety spikes or things feel out of control."
)

MOCK_CODEWORD_OFFER = (
    "If you'd like, we can register a private codeword phrase in your Sensitive Profile "
    "so your care team knows you're escalating — tell me the exact phrase when you're ready."
)

MOCK_CODEWORD_CONFIRM = (
    "I've saved that codeword phrase to your Sensitive Profile for clinician review."
)

MOCK_PART_OFFER = (
    "We can name that part together and save it to your Sensitive Profile — "
    "reply with the name you want to use."
)

MOCK_PART_CONFIRM = (
    "I've registered that part name on your Sensitive Profile for clinician review."
)


def _database_url() -> Optional[str]:
    u = os.getenv("DATABASE_URL")
    if u:
        return u
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "nate_admin")
    pw = os.getenv("POSTGRES_PASSWORD", "")
    db = os.getenv("POSTGRES_DB", "little_nate")
    if not pw:
        return None
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"


def _split_sentences(text: str) -> List[str]:
    if not text.strip():
        return []
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def _trailing_eval_question(text: str) -> Tuple[bool, str]:
    sents = _split_sentences(text)
    if not sents:
        return False, ""
    last = sents[-1].strip()
    if "?" not in last:
        return False, last
    low = last.lower()
    if re.search(r"\byou\b", low):
        return True, last
    return False, last


def _has_distinct_quoted_mantra(text: str) -> bool:
    for m in re.finditer(r'"([^"]{6,120})"', text):
        inner = m.group(1).strip()
        if len(inner.split()) >= 2:
            return True
    for m in re.finditer(r"'([^']{6,120})'", text):
        inner = m.group(1).strip()
        if len(inner.split()) >= 2:
            return True
    return False


def _has_brief_instruction(text: str) -> bool:
    low = text.lower()
    cues = (
        "say ",
        "repeat",
        "whisper",
        "silently",
        "exhale",
        "inhale",
        "breathe",
        "when ",
        "whenever",
        "each ",
        "slowly",
        "quietly",
    )
    return any(c in low for c in cues)


async def _ensure_pool() -> asyncpg.Pool:
    url = _database_url()
    if not url:
        raise RuntimeError("DATABASE_URL or POSTGRES_* credentials not set")
    return await asyncpg.create_pool(url, min_size=1, max_size=2, command_timeout=60)


def _pbk_hash(password: str = "E2E_dummy_pw") -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 100000
    ).hex()
    return f"{salt}:{dk}"


async def _setup_user(pool: asyncpg.Pool) -> None:
    gap_json = json.dumps(FULL_ACTIVATION_GAP_FEATURES)
    ph = _pbk_hash()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (
                username, password_hash, role, name, subscription_status,
                hardware_id, profile_data, tier
            )
            VALUES ($1, $2, 'CLIENT', 'V14 E2E Test', 'ACTIVE', $3, '{}'::jsonb, 'STANDARD')
            ON CONFLICT (username) DO UPDATE SET
                hardware_id = EXCLUDED.hardware_id,
                subscription_status = 'ACTIVE',
                role = 'CLIENT'
            """,
            TEST_USER,
            ph,
            TEST_HW_ID,
        )
        await conn.execute(
            """
            INSERT INTO sensitive_bridge_enrollment (
                user_id, cohort_label, gap_features_enabled, enrolled_by, notes
            )
            VALUES ($1, 'cohort_ga', $2::jsonb, 'e2e_script', 'synthetic v1.4 behavior verify')
            ON CONFLICT (user_id) DO UPDATE SET
                cohort_label = EXCLUDED.cohort_label,
                gap_features_enabled = EXCLUDED.gap_features_enabled,
                last_modified_at = NOW()
            """,
            TEST_USER,
            gap_json,
        )


async def _cleanup(pool: asyncpg.Pool) -> None:
    """Reset mutable SS rows only.

    sensitive_bridge_log is append-only until retained_until (migration 213); DELETE
    is blocked for live rows. We keep user + audit history and only wipe codewords,
    parts, and enrollment so reruns can INSERT fresh test rows.
    """
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM user_parts_registry WHERE user_id = $1", TEST_USER
            )
            await conn.execute(
                "DELETE FROM user_safety_codewords WHERE user_id = $1", TEST_USER
            )
            await conn.execute(
                "DELETE FROM sensitive_bridge_enrollment WHERE user_id = $1", TEST_USER
            )
    except asyncpg.UndefinedTableError:
        pass


async def _run_llm_turn(
    *,
    pool: asyncpg.Pool,
    user_text: str,
    mock: bool,
    mock_text: str,
    register_override: Optional[str],
) -> Tuple[str, str]:
    pack = await prepare_therapeutic_context(
        user_text=user_text,
        user_id=TEST_HW_ID,
        db_pool=pool,
        base_system_prompt=BASE_CLIENT_PROMPT,
        default_max_tokens=600,
        register_directive=register_override,
    )
    enriched = pack.get("enriched_system_prompt") or BASE_CLIENT_PROMPT
    max_tok = int(pack.get("max_tokens") or 600)
    if mock:
        return mock_text, "mocked"
    text, provider = await generate_complete(
        enriched,
        user_text,
        odpe_signal=None,
        domain="clinical",
        temperature=0.35,
        max_tokens=min(max_tok, 800),
    )
    return text.strip(), provider


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--mock-llm",
        action="store_true",
        help="Skip external LLM (default when --live-llm not passed)",
    )
    ap.add_argument(
        "--live-llm",
        action="store_true",
        help="Call configured inference providers",
    )
    args = ap.parse_args()
    mock = not args.live_llm

    results: Dict[str, Any] = {
        "test1": {"pass": False, "response": "", "trailing_q": False},
        "test2": {"pass": False, "row": None, "audit": False},
        "test3": {"pass": False, "row": None, "audit": False},
        "llm_mode": "mocked" if mock else "live",
        "schema_error": "",
    }

    pool: Optional[asyncpg.Pool] = None
    rc = 1
    try:
        pool = await _ensure_pool()
    except Exception as e:
        print(f"END-TO-E BEHAVIOR VERIFICATION — DB unavailable: {e}")
        print(_final_report(results))
        return 2

    try:
        await _cleanup(pool)
        try:
            await _setup_user(pool)
        except asyncpg.UndefinedTableError as e:
            results["schema_error"] = str(e)
            print(_final_report(results))
            rc = 3
        else:
            # --- Test 1 ---
            t1_msg = (
                "I'm feeling really anxious and out of control. "
                "Can you give me a mantra to ground myself?"
            )
            try:
                r1, prov = await _run_llm_turn(
                    pool=pool,
                    user_text=t1_msg,
                    mock=mock,
                    mock_text=MOCK_MANTRA,
                    register_override="dissociation_grounding",
                )
                results["test1"]["response"] = r1
                bad_tail, _ = _trailing_eval_question(r1)
                results["test1"]["trailing_q"] = bad_tail
                ok_mantra = _has_distinct_quoted_mantra(r1)
                ok_instr = _has_brief_instruction(r1)
                results["test1"]["pass"] = ok_mantra and ok_instr and not bad_tail
                results["test1"]["provider"] = prov
            except Exception as e:
                results["test1"]["response"] = f"ERROR: {e}"

            # --- Test 2 ---
            try:
                await _run_llm_turn(
                    pool=pool,
                    user_text=(
                        "I'd like to have a phrase I can use when I'm starting to panic "
                        "so you know what's happening."
                    ),
                    mock=mock,
                    mock_text=MOCK_CODEWORD_OFFER,
                    register_override=None,
                )
                ok_cw, body = await persist_client_initiated_codeword(
                    pool,
                    canonical_username=TEST_USER,
                    plaintext_codeword="the wave is coming",
                )
                row = await pool.fetchrow(
                    """
                    SELECT user_id, disclosure_type, client_initiated, codeword_type,
                           codeword_salt, codeword_hash
                    FROM user_safety_codewords WHERE user_id = $1
                    """,
                    TEST_USER,
                )
                audit = await pool.fetchrow(
                    """
                    SELECT id, user_id, event_type FROM sensitive_bridge_log
                    WHERE user_id = $1 AND event_type = $2
                    ORDER BY id DESC LIMIT 1
                    """,
                    TEST_USER,
                    EVT_CODEWORD_CLIENT_INITIATED,
                )
                hash_ok = bool(
                    row
                    and row["codeword_hash"]
                    == _hash_codeword("the wave is coming", row["codeword_salt"])
                )
                results["test2"]["pass"] = (
                    ok_cw
                    and row
                    and row["disclosure_type"] == "grounding_request"
                    and row["client_initiated"] is True
                    and hash_ok
                    and audit is not None
                )
                results["test2"]["row"] = dict(row) if row else None
                results["test2"]["audit"] = audit is not None
                results["test2"]["persist_body"] = body
            except Exception as e:
                results["test2"]["error"] = str(e)

            # --- Test 3 ---
            try:
                await _run_llm_turn(
                    pool=pool,
                    user_text=(
                        "There's a part of me that always wants to run away when things get hard. "
                        "Can we name it so we can talk about it?"
                    ),
                    mock=mock,
                    mock_text=MOCK_PART_OFFER,
                    register_override=None,
                )
                ok_pt, body = await persist_client_initiated_part(
                    pool,
                    canonical_username=TEST_USER,
                    part_name="the Runner",
                    part_category="protector",
                )
                row = await pool.fetchrow(
                    """
                    SELECT user_id, part_name, part_category, created_by, client_initiated
                    FROM user_parts_registry WHERE user_id = $1 AND part_name = $2
                    """,
                    TEST_USER,
                    "the Runner",
                )
                audit = await pool.fetchrow(
                    """
                    SELECT id, user_id, event_type FROM sensitive_bridge_log
                    WHERE user_id = $1 AND event_type = $2
                    ORDER BY id DESC LIMIT 1
                    """,
                    TEST_USER,
                    EVT_PART_CLIENT_INITIATED,
                )
                results["test3"]["pass"] = (
                    ok_pt
                    and row
                    and row["part_name"] == "the Runner"
                    and row["part_category"] == "protector"
                    and row["created_by"] == CLIENT_INITIATED_ACTOR
                    and row["client_initiated"] is True
                    and audit is not None
                )
                results["test3"]["row"] = dict(row) if row else None
                results["test3"]["audit"] = audit is not None
                results["test3"]["persist_body"] = body
            except Exception as e:
                results["test3"]["error"] = str(e)

            rc = 0 if all(results[k]["pass"] for k in ("test1", "test2", "test3")) else 1
    finally:
        if pool:
            try:
                await _cleanup(pool)
            except Exception:
                pass
            await pool.close()

    if rc != 3:
        print(_final_report(results))
    return rc


def _final_report(results: Dict[str, Any]) -> str:
    t1 = results["test1"]
    t2 = results["test2"]
    t3 = results["test3"]
    p1 = "PASS" if t1.get("pass") else "FAIL"
    p2 = "PASS" if t2.get("pass") else "FAIL"
    p3 = "PASS" if t3.get("pass") else "FAIL"
    rtxt = t1.get("response", "")
    schema_note = (
        f"(schema) {results.get('schema_error')}\n\n"
        if results.get("schema_error")
        else ""
    )
    return (
        "\nEND-TO-E BEHAVIOR VERIFICATION\n"
        + schema_note
        + f"Test 1 — Clean mantra delivery: {p1}\n"
        f"  Response text: {rtxt!r}\n"
        f"  Trailing question detected: {'yes' if t1.get('trailing_q') else 'no'}\n\n"
        f"Test 2 — Codeword registration: {p2}\n"
        f"  DB row created: {'yes' if t2.get('row') else 'no'}\n"
        f"  Audit event fired: {'yes' if t2.get('audit') else 'no'}\n"
        f"  Row snapshot: {t2.get('row')}\n"
        f"  Errors: {t2.get('error', '')}\n\n"
        f"Test 3 — Part registration: {p3}\n"
        f"  DB row created: {'yes' if t3.get('row') else 'no'}\n"
        f"  Audit event fired: {'yes' if t3.get('audit') else 'no'}\n"
        f"  Row snapshot: {t3.get('row')}\n"
        f"  Errors: {t3.get('error', '')}\n\n"
        f"Live LLM or mocked: {results.get('llm_mode', 'unknown')}\n"
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
