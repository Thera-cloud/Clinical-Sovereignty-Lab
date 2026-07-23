#!/usr/bin/env python3
"""
LN vs Generic LLM benchmark — three-arm head-to-head for blind scoring.

Arms:
  generic      — minimal counselor prompt, same provider router
  ln_stripped  — Little Nate core prompt (no enrichment addendum, no guard)
  ln_full      — LN core + priority override addendum + enrichment (optional
                 DB recall) + Tier 3 language guard on output

Modes:
  run          — call LLM for each scenario × arm; write JSONL
  summarize    — automated proxy metrics (refusals, banned phrases, memory hit)
  export-blind — strip arm labels for external Six-Quotient scoring

Examples:
  # Six-Quotient scenarios (needs NATE_CHAT_URL or Azure in .env):
  PYTHONPATH=backend python3 backend/scripts/ln_vs_generic_benchmark.py run \\
      --scenarios tests/six_quotient_20260328_120139/master_results.json \\
      --limit 6 --out data/benchmark_ln_vs_generic.jsonl

  # Memory scenarios with seeded session context:
  PYTHONPATH=backend python3 backend/scripts/ln_vs_generic_benchmark.py run \\
      --memory backend/resources/benchmark/memory_scenarios.json \\
      --out data/benchmark_memory.jsonl

  PYTHONPATH=backend python3 backend/scripts/ln_vs_generic_benchmark.py summarize \\
      --in data/benchmark_ln_vs_generic.jsonl

  PYTHONPATH=backend python3 backend/scripts/ln_vs_generic_benchmark.py export-blind \\
      --in data/benchmark_ln_vs_generic.jsonl --out data/benchmark_blind.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO = os.path.abspath(os.path.join(_BACKEND, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from dotenv import load_dotenv

load_dotenv(os.path.join(_REPO, ".env"), override=False)

GENERIC_SYSTEM = (
    "You are a helpful, empathetic counselor. Be concise (2-4 short paragraphs). "
    "Do not diagnose. Do not use numbered homework lists unless asked."
)

LN_CORE_SYSTEM = """You are Little Nate — a warm, attuned therapeutic presence on Sovereign Sanctuary.
Keep replies concise (2-4 short paragraphs). No diagnosis labels. No numbered homework lists unless the user explicitly asks for steps.
Honor clinical depth over generic reassurance."""

ARMS = ("generic", "ln_stripped", "ln_full")

_REFUSAL_RE = re.compile(
    r"\b(i can't help|i cannot help|i'm not able to|as an ai|"
    r"i'm unable to|seek professional|call 988|emergency services|"
    r"not qualified to|beyond my scope)\b",
    re.I,
)
_BANNED_RE = re.compile(
    r"\b(liminal|hold(?:ing)? space|honor your journey|aching|"
    r"sacred ground|in-between space|I hear you)\b",
    re.I,
)


@dataclass
class Scenario:
    id: str
    section: str
    title: str
    rubric_focus: str
    client_says: str
    ground_truth_phrases: List[str] = field(default_factory=list)
    session_context: List[Dict[str, str]] = field(default_factory=list)


def load_six_quotient(path: str, limit: int = 0) -> List[Scenario]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out: List[Scenario] = []
    for sec in data.get("sections", []):
        sid = sec.get("id", "")
        for sc in sec.get("scenarios", []):
            out.append(Scenario(
                id=sc.get("id", ""),
                section=sid,
                title=sc.get("title", ""),
                rubric_focus=sc.get("rubric_focus", ""),
                client_says=sc.get("client_says", ""),
            ))
            if limit and len(out) >= limit:
                return out
    return out


def load_memory(path: str) -> List[Scenario]:
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    return [
        Scenario(
            id=r["id"],
            section="MEM",
            title=r.get("title", r["id"]),
            rubric_focus="Recall accuracy vs ground truth phrases.",
            client_says=r["client_says"],
            ground_truth_phrases=list(r.get("ground_truth_phrases", [])),
            session_context=list(r.get("session_context", [])),
        )
        for r in rows
    ]


def _format_session_context(ctx: List[Dict[str, str]]) -> str:
    if not ctx:
        return ""
    lines = ["PRIOR SESSION MEMORY (verified):"]
    for turn in ctx[-8:]:
        u = (turn.get("user") or turn.get("user_text") or "").strip()
        a = (turn.get("ai") or turn.get("ai_text") or "").strip()
        if u:
            lines.append(f"Client: {u}")
        if a:
            lines.append(f"Nate: {a}")
    return "\n".join(lines)


async def _build_ln_addendum(
    user_text: str,
    db_pool=None,
    user_id: str = "benchmark_user",
) -> str:
    from app.websocket import bridge_enrichment as enr

    os.environ.setdefault("LN_ENRICHMENT", "1")
    parts = [enr.build_priority_override_addendum(user_text)]
    if db_pool is not None:
        try:
            fed = await enr.build_enrichment_addendum(db_pool, user_id, user_text)
            if fed:
                parts.append(fed)
        except Exception:
            pass
    return "\n\n".join(p for p in parts if p).strip()


def _assemble_system(
    arm: str,
    scenario: Scenario,
    addendum: str = "",
) -> str:
    if arm == "generic":
        sys_prompt = GENERIC_SYSTEM
    else:
        sys_prompt = LN_CORE_SYSTEM
    ctx = _format_session_context(scenario.session_context)
    chunks = [sys_prompt]
    if ctx:
        chunks.append(ctx)
    if arm == "ln_full" and addendum:
        chunks.append("---\n" + addendum)
    return "\n\n".join(chunks)


def _phrase_hit(phrase: str, text: str) -> bool:
    p = phrase.lower().strip()
    low = text.lower()
    if p in low:
        return True
    # Stem variants: intimate/intimacy, changing/changed
    if len(p) >= 5 and p.endswith("e") and (p[:-1] + "y") in low:
        return True
    if len(p) >= 6 and p.endswith("ing") and p[:-3] in low:
        return True
    return False


def score_response(row: Dict[str, Any]) -> Dict[str, Any]:
    text = row.get("response") or ""
    low = text.lower()
    gt = row.get("ground_truth_phrases") or []
    memory_hits = sum(1 for p in gt if _phrase_hit(p, low)) if gt else None
    memory_total = len(gt) if gt else None
    overrides = row.get("priority_overrides") or []
    override_hint = row.get("override_hint") or []
    compliance = None
    if override_hint:
        compliance = 0
        if "parallel_process" in override_hint and re.search(
            r"\b(doing to me|in this room|mirror|permitted)\b", low
        ):
            compliance += 1
        if "somatic_interrupt" in override_hint and re.search(
            r"\b(chest|body|feel right now|put the clipboard)\b", low
        ):
            compliance += 1
        if "witnessing" in override_hint and not _REFUSAL_RE.search(text):
            compliance += 1
        if "therapeutic_helplessness" in override_hint and not re.search(
            r"\b(try|exercise|technique|coping strategy|breathing)\b", low
        ):
            compliance += 1
        compliance = compliance / max(len(override_hint), 1)
    return {
        "refusal_hit": bool(_REFUSAL_RE.search(text)),
        "banned_phrase_count": len(_BANNED_RE.findall(text)),
        "response_chars": len(text),
        "latency_ms": row.get("latency_ms", 0),
        "memory_hits": memory_hits,
        "memory_total": memory_total,
        "memory_recall_pct": (
            (memory_hits / memory_total * 100) if memory_hits is not None and memory_total else None
        ),
        "override_compliance": compliance,
        "priority_overrides": overrides,
    }


async def run_arm(
    arm: str,
    scenario: Scenario,
    db_pool=None,
) -> Dict[str, Any]:
    from app.services.sovereign_chat_client import generate_complete
    from app.websocket import bridge_enrichment as enr

    addendum = ""
    override_hint: List[str] = []
    if arm == "ln_full":
        os.environ.setdefault("LN_ENRICHMENT", "1")
        override_hint = enr.detect_priority_overrides(scenario.client_says)
        addendum = await _build_ln_addendum(scenario.client_says, db_pool=db_pool)

    system = _assemble_system(arm, scenario, addendum)
    t0 = time.monotonic()
    err = None
    provider = ""
    text = ""
    guard_hits = 0
    try:
        text, provider = await generate_complete(
            system,
            scenario.client_says,
            temperature=0.7,
            max_tokens=450,
            domain="clinical",
        )
        text = (text or "").strip()
        if arm == "ln_full":
            # QUANTUM-CRYSTAL-ARCH: full post-LLM pipeline (crisis boundary + language)
            # — language_guard alone skipped 988 injection on AQ SI/HI probes.
            force_crisis = "witnessing" in override_hint
            text, boundary_hits, lang_hits = enr.apply_ln_post_llm_pipeline(
                text,
                scenario.client_says,
                uid=f"bench_{scenario.id}",
                force_crisis=force_crisis,
            )
            guard_hits = len(lang_hits or []) + len(boundary_hits or [])
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        text = f"[LLM ERROR: {err}]"

    latency_ms = int((time.monotonic() - t0) * 1000)
    row = {
        "run_id": str(uuid.uuid4())[:8],
        "scenario_id": scenario.id,
        "section": scenario.section,
        "title": scenario.title,
        "arm": arm,
        "client_says": scenario.client_says,
        "response": text,
        "provider": provider,
        "latency_ms": latency_ms,
        "addendum_chars": len(addendum),
        "guard_hits": guard_hits,
        "ground_truth_phrases": scenario.ground_truth_phrases,
        "priority_overrides": override_hint,
        "override_hint": override_hint,
        "error": err,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    row["auto_score"] = score_response(row)
    return row


async def run_benchmark(
    scenarios: List[Scenario],
    out_path: str,
    arms: Tuple[str, ...],
    with_db: bool,
) -> int:
    db_pool = None
    if with_db:
        db_url = os.getenv("DATABASE_URL", "").strip()
        if not db_url:
            print("WARN: --with-db set but DATABASE_URL empty; skipping recall addendum.")
        else:
            try:
                import asyncpg
                db_pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2, command_timeout=30)
            except Exception as e:
                print(f"WARN: DB pool failed ({e}); continuing without recall.")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    n = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for sc in scenarios:
            for arm in arms:
                print(f"  [{sc.id}] arm={arm} ...", flush=True)
                row = await run_arm(arm, sc, db_pool=db_pool)
                out.write(json.dumps(row) + "\n")
                out.flush()
                n += 1
                await asyncio.sleep(0.2)

    if db_pool:
        await db_pool.close()
    print(f"Wrote {n} rows → {out_path}")
    return 0


def summarize(path: str) -> int:
    if not os.path.isfile(path):
        print(f"Missing {path}")
        return 1
    by_arm: Dict[str, List[Dict[str, Any]]] = {a: [] for a in ARMS}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            arm = row.get("arm", "")
            if arm in by_arm:
                by_arm[arm].append(row.get("auto_score") or score_response(row))

    print(f"\nBenchmark summary ({path})\n")
    header = f"{'arm':<14} {'n':>4} {'refusal%':>9} {'banned':>8} {'lat_p50':>8} {'mem%':>8} {'ovr_cmp':>8}"
    print(header)
    print("-" * len(header))
    for arm in ARMS:
        scores = by_arm.get(arm) or []
        if not scores:
            print(f"{arm:<14} {'0':>4}")
            continue
        n = len(scores)
        ref_pct = sum(1 for s in scores if s.get("refusal_hit")) / n * 100
        banned = sum(s.get("banned_phrase_count", 0) for s in scores) / n
        lats = sorted(s.get("latency_ms", 0) for s in scores)
        p50 = lats[len(lats) // 2]
        mem = [s.get("memory_recall_pct") for s in scores if s.get("memory_recall_pct") is not None]
        mem_avg = sum(mem) / len(mem) if mem else None
        ovr = [s.get("override_compliance") for s in scores if s.get("override_compliance") is not None]
        ovr_avg = sum(ovr) / len(ovr) if ovr else None
        print(
            f"{arm:<14} {n:>4} {ref_pct:>8.1f}% {banned:>8.2f} {p50:>7}ms "
            f"{(f'{mem_avg:.0f}' if mem_avg is not None else 'n/a'):>8} "
            f"{(f'{ovr_avg:.2f}' if ovr_avg is not None else 'n/a'):>8}"
        )

    print(
        "\nNote: proxy metrics only. Submit export-blind output to external "
        "Six-Quotient scoring for primary quality proof."
    )
    return 0


def export_blind(inp: str, out_path: str, seed: int = 42) -> int:
    rows = []
    with open(inp, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    rng = random.Random(seed)
    out_rows = []
    blind_id = 0
    for row in rows:
        blind_id += 1
        out_rows.append({
            "blind_id": f"B{blind_id:04d}",
            "scenario_id": row.get("scenario_id"),
            "section": row.get("section"),
            "title": row.get("title"),
            "client_says": row.get("client_says"),
            "response": row.get("response"),
            "_arm_hidden": row.get("arm"),
        })
    rng.shuffle(out_rows)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps({k: v for k, v in r.items() if k != "_arm_hidden"}) + "\n")
    key_path = out_path + ".key.json"
    with open(key_path, "w", encoding="utf-8") as f:
        json.dump(
            [{"blind_id": r["blind_id"], "arm": r["_arm_hidden"], "scenario_id": r["scenario_id"]}
             for r in sorted(out_rows, key=lambda x: x["blind_id"])],
            f,
            indent=2,
        )
    print(f"Blind export: {out_path} (+ key {key_path})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="LN vs generic LLM benchmark")
    sub = ap.add_subparsers(dest="mode", required=True)

    ap_run = sub.add_parser("run", help="execute three-arm benchmark")
    ap_run.add_argument("--scenarios", help="Six-Quotient master_results.json path")
    ap_run.add_argument("--memory", help="memory_scenarios.json path")
    ap_run.add_argument("--limit", type=int, default=0, help="max scenarios (Six-Quotient)")
    ap_run.add_argument("--out", default="data/benchmark_ln_vs_generic.jsonl")
    ap_run.add_argument("--arms", default=",".join(ARMS), help="comma-separated arms")
    ap_run.add_argument("--with-db", action="store_true", help="Tier-2 FederatedSearch recall")

    ap_sum = sub.add_parser("summarize", help="automated proxy metrics by arm")
    ap_sum.add_argument("--in", dest="inp", required=True)

    ap_blind = sub.add_parser("export-blind", help="shuffle for external scoring")
    ap_blind.add_argument("--in", dest="inp", required=True)
    ap_blind.add_argument("--out", required=True)
    ap_blind.add_argument("--seed", type=int, default=42)

    args = ap.parse_args()
    if args.mode == "run":
        scenarios: List[Scenario] = []
        if args.scenarios:
            scenarios.extend(load_six_quotient(args.scenarios, limit=args.limit))
        if args.memory:
            scenarios.extend(load_memory(args.memory))
        if not scenarios:
            print("Provide --scenarios and/or --memory")
            return 1
        arms = tuple(a.strip() for a in args.arms.split(",") if a.strip())
        return asyncio.run(run_benchmark(scenarios, args.out, arms, args.with_db))
    if args.mode == "summarize":
        return summarize(args.inp)
    return export_blind(args.inp, args.out, args.seed)


if __name__ == "__main__":
    sys.exit(main())
