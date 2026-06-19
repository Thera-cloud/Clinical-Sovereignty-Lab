#!/usr/bin/env python3
"""Replay Kristy (sweet2noend) smoke test JSON through current Little Nate pipeline.

Mirrors bridge: prepare_response → stance resolver → generate_complete → guard_generated_closer.
Optional PG lookup for original ai_text (2026-06-15 session) for before/after review.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO = os.path.abspath(os.path.join(_BACKEND, ".."))
for _root in (_BACKEND, "/app"):
    if _root and os.path.isdir(os.path.join(_root, "app", "services")):
        if _root not in sys.path:
            sys.path.insert(0, _root)
        break

from dotenv import load_dotenv

load_dotenv(os.path.join(_REPO, ".env"), override=False)

os.environ.setdefault("ENABLE_STANCE_RESOLVER", "true")
os.environ.setdefault("ENABLE_CLASSIFIER_LAYER", "false")
os.environ.setdefault("ENABLE_COACHING_SCOPE_GATE", "false")
os.environ.setdefault("ENABLE_ARC_MEMORY", "false")

_OUT_DIR = os.environ.get(
    "KRISTY_REPLAY_OUT_DIR",
    os.path.join(_REPO, "data") if len(_REPO) > 3 else "/app/data",
)
USERNAME = "sweet2noend@yahoo.com"
BASE_SYSTEM = """You are Little Nate — a warm, attuned therapeutic presence on Sovereign Sanctuary.
You are speaking with Kristy, a long-time client processing relationship pain, self-doubt, and
the need to be witnessed (not endlessly analyzed). Keep replies human and direct.
No diagnosis labels. Honor the mode instruction appended after --- if present."""

_FAIL_CLOSER = re.compile(
    r"which (part|perspective|framework|framing).*resonat|what feels most important",
    re.I,
)
_FAIL_MENU = re.compile(r"framings?|frameworks?", re.I)


@dataclass
class TurnResult:
    index: int
    intent_label: str
    user: str
    nate_response: str = ""
    original_response: str = ""
    stance_intent: str = ""
    stance_move: str = ""
    end_on_question: bool = True
    provider: str = ""
    mode: str = ""
    fail_flags: List[str] = field(default_factory=list)


def _format_live_turns(turns: List[Dict[str, str]], limit: int = 20) -> str:
    if not turns:
        return ""
    parts = ["LIVE SESSION CONTEXT (this replay session — same order as original):"]
    for t in turns[-limit:]:
        u = (t.get("user_text") or "")[:500]
        a = (t.get("ai_text") or "")[:500]
        if u:
            parts.append(f"Client: {u}")
        if a:
            parts.append(f"Nate: {a}")
    return "\n".join(parts)


def _score_failures(tr: TurnResult) -> None:
    text = tr.nate_response or ""
    intent = tr.intent_label
    flags: List[str] = []
    if intent in ("position", "meta") and text.rstrip().endswith("?"):
        flags.append("ends_on_question")
    if _FAIL_CLOSER.search(text):
        flags.append("closing_resonates_question")
    if intent == "meta" and _FAIL_MENU.search(text) and "framework" in text.lower():
        flags.append("meta_gave_framings")
    if intent == "low_weight" and len(text.split()) > 40:
        flags.append("low_weight_too_long")
    tr.fail_flags = flags


async def _load_original_responses(db_pool, turns: List[Dict]) -> Dict[int, str]:
    """Match production history rows to smoke-test turns by text prefix."""
    out: Dict[int, str] = {}
    if not db_pool:
        return out
    try:
        rows = await db_pool.fetch(
            """
            SELECT user_text, ai_text, created_at
            FROM conversation_history
            WHERE user_id = $1
              AND created_at >= '2026-06-15'::timestamptz
              AND created_at < '2026-06-19'::timestamptz
              AND LENGTH(COALESCE(user_text, '')) > 3
            ORDER BY created_at ASC
            """,
            USERNAME,
        )
    except Exception as e:
        print(f"[WARN] PG history load failed: {e}", file=sys.stderr)
        return out
    used: set = set()
    for turn in turns:
        idx = turn["index"]
        needle = (turn.get("text") or "").strip()[:80]
        if not needle:
            continue
        for i, row in enumerate(rows):
            if i in used:
                continue
            ut = (row["user_text"] or "").strip()
            if ut.startswith(needle[:40]) or needle[:40] in ut[:120]:
                out[idx] = (row["ai_text"] or "").strip()
                used.add(i)
                break
    return out


async def run_replay(json_path: str) -> List[TurnResult]:
    from app.services.little_nate_adaptive import SessionState, prepare_response, record_assistant_turn
    from app.services import ln_stance_resolver as stance
    from app.services.sovereign_chat_client import generate_complete

    with open(json_path, encoding="utf-8") as f:
        spec = json.load(f)
    turns = spec["turns"]

    db_pool = None
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        try:
            import asyncpg

            db_pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2, command_timeout=60)
        except Exception as e:
            print(f"[WARN] db_pool unavailable: {e}", file=sys.stderr)

    originals = await _load_original_responses(db_pool, turns)

    state = SessionState()
    stance_state = stance.StanceState()
    profile = {"hardware_id": "KRISTY_SMOKE", "name": "Kristy", "role": "CLIENT", "username": USERNAME}
    live_turns: List[Dict[str, str]] = []
    results: List[TurnResult] = []

    enable_stance = os.getenv("ENABLE_STANCE_RESOLVER", "false").lower() in ("true", "1", "yes")

    for turn in turns:
        idx = turn["index"]
        user_text = turn["text"]
        intent_label = turn.get("intent_label", "neutral")
        tr = TurnResult(index=idx, intent_label=intent_label, user=user_text)

        payload = prepare_response(state, user_text, profile)
        tr.mode = payload.get("mode", "")

        stance_dec = None
        if enable_stance and not payload.get("direct_response"):
            stance_dec = stance.resolve_stance(
                user_text,
                stance_state,
                payload.get("system_addendum", "") or "",
            )
            if stance_dec.move not in (stance.StanceMove.PASSTHROUGH, stance.StanceMove.REFLECT_AND_FRAME):
                payload["system_addendum"] = stance_dec.addendum
            tr.stance_intent = stance_dec.intent.value
            tr.stance_move = stance_dec.move.value
            tr.end_on_question = stance_dec.end_on_question

        if payload.get("direct_response"):
            tr.nate_response = payload["direct_response"]
            tr.provider = "direct_response"
        else:
            system = BASE_SYSTEM
            addendum = payload.get("system_addendum") or ""
            if addendum:
                system = system + "\n\n---\n" + addendum
            live_ctx = _format_live_turns(live_turns)
            if live_ctx:
                system = system + "\n\n" + live_ctx
            if len(system) > 30000:
                system = system[:30000] + "\n\n[Context truncated.]"

            try:
                text, provider = await generate_complete(
                    system,
                    user_text,
                    temperature=0.7,
                    max_tokens=500,
                    domain="clinical",
                    odpe_signal="TENSION" if intent_label in ("position", "meta") else "PROVISIONAL",
                )
                tr.nate_response = (text or "").strip()
                tr.provider = provider or ""
            except Exception as e:
                tr.nate_response = f"[LLM ERROR: {type(e).__name__}: {e}]"
                tr.provider = "error"

        if enable_stance and stance_dec and tr.nate_response and not tr.nate_response.startswith("[LLM"):
            tr.nate_response = stance.guard_generated_closer(tr.nate_response, stance_dec, stance_state)

        tr.original_response = originals.get(idx, "")
        _score_failures(tr)
        record_assistant_turn(state, tr.nate_response)
        live_turns.append({"user_text": user_text, "ai_text": tr.nate_response})
        results.append(tr)

        print(f"\n{'=' * 72}\nTURN {idx} | intent={intent_label} | stance={tr.stance_move} | mode={tr.mode}")
        print(f"KRISTY: {user_text[:300]}{'…' if len(user_text) > 300 else ''}")
        if tr.original_response:
            print(f"\n--- ORIGINAL (2026-06-15 prod) ---\n{tr.original_response[:1200]}{'…' if len(tr.original_response) > 1200 else ''}")
        print(f"\n--- NEW (build 157ca23 + stance) ---\n{tr.nate_response}")
        if tr.fail_flags:
            print(f"FAIL FLAGS: {', '.join(tr.fail_flags)}")

        await asyncio.sleep(0.15)

    if db_pool:
        await db_pool.close()
    return results


def _write_markdown(results: List[TurnResult], out_path: str, spec: Dict) -> None:
    lines = [
        "# Kristy Witness-Loop Smoke Replay",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
        f"Source: `{spec.get('smoke_test')}`",
        f"`ENABLE_STANCE_RESOLVER={os.environ.get('ENABLE_STANCE_RESOLVER')}`",
        "",
        "---",
        "",
    ]
    for tr in results:
        lines.extend([
            f"## Turn {tr.index} — expected `{tr.intent_label}`",
            "",
            f"**Stance:** `{tr.stance_move}` (classified `{tr.stance_intent}`) | "
            f"end_on_question={tr.end_on_question} | provider=`{tr.provider}` | mode=`{tr.mode}`",
            "",
            "**Kristy:**",
            "",
            tr.user,
            "",
        ])
        if tr.original_response:
            lines.extend([
                "**Original Little Nate (2026-06-15 production):**",
                "",
                tr.original_response,
                "",
            ])
        lines.extend([
            "**New Little Nate (current build):**",
            "",
            tr.nate_response,
            "",
        ])
        if tr.fail_flags:
            lines.append(f"*Fail flags:* {', '.join(tr.fail_flags)}")
            lines.append("")
        lines.append("---")
        lines.append("")

    pos_meta = [r for r in results if r.intent_label in ("position", "meta")]
    fails = [r for r in pos_meta if r.fail_flags]
    lines.extend([
        "## Summary",
        "",
        f"- Position/meta turns: {len(pos_meta)}",
        f"- Position/meta with fail flags: {len(fails)}",
        f"- Indices with fail flags: {[r.index for r in fails]}",
        "",
    ])
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


async def main() -> int:
    json_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_REPO, "data", "kristy_smoke_test.json")
    if not os.path.isfile(json_path):
        print(f"Missing JSON: {json_path}", file=sys.stderr)
        return 1
    with open(json_path, encoding="utf-8") as f:
        spec = json.load(f)
    results = await run_replay(json_path)
    out_md = os.path.join(_OUT_DIR, f"kristy_smoke_replay_{time.strftime('%Y%m%d_%H%M')}.md")
    out_json = out_md.replace(".md", ".json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump([r.__dict__ for r in results], f, indent=2, ensure_ascii=False)
    _write_markdown(results, out_md, spec)
    print(f"\nWrote {out_md}")
    print(f"Wrote {out_json}")
    fail_count = sum(1 for r in results if r.fail_flags)
    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
