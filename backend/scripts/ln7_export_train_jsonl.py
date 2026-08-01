#!/usr/bin/env python3
"""Export CLEAN LN7 train JSONL for offline QLoRA — BLUE/ops only.

Rules (optimal train half):
  - Include sandbox passed=true rows with real unified-diff patch_text
  - Include reject→fix preference pairs when a failed + passed pack share a key
  - Drop hash stubs, dry_run noise, heldout pack env_redis_prefix
  - Cap prompt/assistant to ~4k (pack-scale), not generic long-context

Also seeds train packs' golden.patch when --include-goldens (offline-safe).

Usage:
  DATABASE_URL=... PYTHONPATH=backend \\
    python backend/scripts/ln7_export_train_jsonl.py --out data/ln7_train.jsonl
  python backend/scripts/ln7_export_train_jsonl.py --out data/ln7_train.jsonl --goldens-only

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

def _resolve_root() -> Path:
    here = Path(__file__).resolve()
    # Repo checkout: .../backend/scripts/<this>
    if len(here.parents) >= 3 and (here.parents[2] / "backend" / "app").is_dir():
        return here.parents[2]
    # nate_backend bind: /app/scripts/<this>, code at /app/app
    if (Path("/app") / "app").is_dir():
        return Path("/app")
    env = os.environ.get("LN7_REPO_ROOT")
    if env and Path(env).is_dir():
        return Path(env)
    return here.parents[2] if len(here.parents) >= 3 else here.parent


ROOT = _resolve_root()
for _p in (ROOT / "backend", ROOT, Path("/app")):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _packs_root() -> Path:
    for cand in (
        ROOT / "backend" / "app" / "data" / "ln_sandbox_ci_packs",
        ROOT / "app" / "data" / "ln_sandbox_ci_packs",
    ):
        if cand.is_dir():
            return cand
    return ROOT / "backend" / "app" / "data" / "ln_sandbox_ci_packs"


MAX_CHARS = int(os.getenv("LN7_EXPORT_MAX_CHARS", "4000") or "4000")
try:
    # Phase D: single source of truth is packs_index.json's "heldout" list,
    # shared with ln7_train_queue.py — never hardcode a second copy here.
    from app.services.ln7_heldout_registry import heldout_packs as _heldout_packs

    HELDOUT_PACKS = _heldout_packs()
except Exception:
    HELDOUT_PACKS = frozenset({"env_redis_prefix"})
# Fallback if packs_index missing; preferred: all packs with golden.patch minus heldout
TRAIN_GOLDEN_PACKS = ("asyncpg_cast", "catch_all_routes")
_STUB_RE = re.compile(r"^\[patch_hash=", re.I)
_DIFF_MARK = re.compile(r"(?m)^(diff --git |--- |\+\+\+ |@@ )")
PARAPHRASE_N = int(os.getenv("LN7_EXPORT_PARAPHRASE_N", "16") or "16")


def _train_golden_pack_names() -> List[str]:
    root = _packs_root()
    names: List[str] = []
    idx = root / "packs_index.json"
    if idx.is_file():
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
            names = [n for n in (data.get("packs") or []) if n not in HELDOUT_PACKS]
        except Exception:
            names = []
    if not names:
        names = [n for n in TRAIN_GOLDEN_PACKS if n not in HELDOUT_PACKS]
    return [n for n in names if (root / n / "golden.patch").is_file()]


def _paraphrase_prompts(prompt: str) -> List[str]:
    """Same assistant patch, varied user phrasing — expands thin unique-diff sets."""
    base = (prompt or "").strip()
    variants = [
        base,
        f"Engineering task: {base}",
        f"Return a unified diff only. {base}",
        f"Sandbox CI pack failure — fix it. {base}",
        f"Produce a minimal correct patch. {base}",
        f"Little Nate 7 train sample — patch only. {base}",
        f"Fix the broken file; pytest must pass. {base}",
        f"Sovereign CI: emit unified diff, no prose. {base}",
        f"Apply the smallest correct change. {base}",
        f"Repo hygiene task — diff only. {base}",
        f"Milestone A fast-tier sample. {base}",
        f"QLoRA preference row — assistant is the golden patch. {base}",
        f"Do not explain; patch only. {base}",
        f"CI red: restore green with a unified diff. {base}",
        f"Clinical Sovereignty Lab coding pack. {base}",
        f"Adapter train example (user→golden.diff). {base}",
    ]
    n = max(1, min(PARAPHRASE_N, len(variants)))
    return variants[:n]


def _cap(s: str, n: int = MAX_CHARS) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n]


def _is_real_diff(text: str) -> bool:
    if not text or _STUB_RE.match(text.strip()):
        return False
    if "dry_run_stub" in text or "method\": \"dry_run" in text:
        return False
    return bool(_DIFF_MARK.search(text)) or (
        text.count("\n+") + text.count("\n-") >= 2 and "@@" in text
    )


def _pack_from_meta(meta: Any) -> str:
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return str((meta or {}).get("pack") or "")


def _row_messages(prompt: str, assistant: str, rejected: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "prompt": _cap(prompt),
        "messages": [
            {"role": "user", "content": _cap(prompt)},
            {"role": "assistant", "content": _cap(assistant)},
        ],
    }
    if rejected and _is_real_diff(rejected):
        out["rejected"] = _cap(rejected)
        out["preference"] = True
    return out


def golden_rows() -> List[Dict[str, Any]]:
    """Train-eligible golden.patch rows (heldout pack excluded) + prompt paraphrases."""
    from app.websocket.ln7_harness import build_pack_prompt

    packs_root = _packs_root()
    out: List[Dict[str, Any]] = []
    for pack in _train_golden_pack_names():
        gpath = packs_root / pack / "golden.patch"
        if not gpath.is_file():
            continue
        gdiff = gpath.read_text(encoding="utf-8")
        if not _is_real_diff(gdiff):
            continue
        prompt0 = build_pack_prompt(pack) or f"Fix pack {pack}. Return a unified diff."
        ph = hashlib.sha256(gdiff.encode()).hexdigest()[:32]
        for i, prompt in enumerate(_paraphrase_prompts(prompt0)):
            base = {
                "outcome_id": f"golden:{pack}:p{i}",
                "task_id": None,
                "revision_id": "LN7-golden",
                "patch_hash": f"{ph}:p{i}",
                "harness_mode": "golden",
                "split": "train",
                "spdx_license": "MIT",
                "pack": pack,
                "source": "golden.patch" if i == 0 else "golden.paraphrase",
                "clean": True,
            }
            base.update(_row_messages(prompt, gdiff))
            out.append(base)
    return out

async def export_rows(
    limit: int = 500,
    *,
    include_goldens: bool = True,
    goldens_only: bool = False,
    domain: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    stats = {
        "from_db_passed": 0,
        "from_db_pairs": 0,
        "from_goldens": 0,
        "dropped_stub": 0,
        "dropped_heldout": 0,
        "dropped_no_diff": 0,
        "domain": domain,
    }
    out: List[Dict[str, Any]] = []
    seen_ph: set = set()

    if goldens_only:
        g = golden_rows()
        stats["from_goldens"] = len(g)
        return g[:limit], stats

    if not goldens_only:
        import asyncpg

        dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
        if not dsn:
            host = os.getenv("POSTGRES_HOST", "localhost")
            user = os.getenv("POSTGRES_USER", "nate_admin")
            pw = os.getenv("POSTGRES_PASSWORD", "")
            db = os.getenv("POSTGRES_DB", "little_nate")
            dsn = f"postgresql://{user}:{pw}@{host}:5432/{db}"

        try:
            conn = await asyncpg.connect(dsn)
        except Exception as exc:
            stats["db_error"] = str(exc)[:200]
            g = golden_rows() if include_goldens else []
            stats["from_goldens"] = len(g)
            return g[:limit], stats

        try:
            has_patch = await conn.fetchval(
                """
                SELECT EXISTS (
                  SELECT 1 FROM information_schema.columns
                  WHERE table_name = 'ln7_coding_outcomes' AND column_name = 'patch_text'
                )
                """
            )
            patch_col = "o.patch_text" if has_patch else "NULL::text AS patch_text"
            # Phase D — SQL-level hard-block: heldout-split rows never leave the
            # query at all. Pack-name-based HELDOUT_PACKS filtering below is a
            # second, independent layer for CI packs without a ln7_tasks.split
            # row (defense in depth, not a substitute for this WHERE clause).
            rows = await conn.fetch(
                f"""
                SELECT o.id, o.task_id, o.patch_hash, o.revision_id, o.harness_mode,
                       o.metrics_json, o.diff_lines, o.tokens, o.passed,
                       {patch_col},
                       t.split, t.spdx_license, t.prompt_summary, t.task_hash
                FROM ln7_coding_outcomes o
                LEFT JOIN ln7_tasks t ON t.task_id = o.task_id
                WHERE o.generator IN ('ln7', 'ln7_golden')
                  AND (t.split IS NULL OR t.split = 'train')
                ORDER BY o.created_at DESC
                LIMIT $1
                """,
                max(limit * 4, 200),
            )
            try:
                stats["dropped_heldout_sql"] = int(
                    await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM ln7_coding_outcomes o
                        LEFT JOIN ln7_tasks t ON t.task_id = o.task_id
                        WHERE o.generator IN ('ln7', 'ln7_golden') AND t.split = 'heldout'
                        """
                    )
                    or 0
                )
            except Exception:
                stats["dropped_heldout_sql"] = None
        finally:
            await conn.close()

        # Group by pack for reject→fix pairing
        by_pack: Dict[str, Dict[str, List[Any]]] = {}
        for r in rows:
            d = dict(r)
            pack = _pack_from_meta(d.get("metrics_json"))
            if pack in HELDOUT_PACKS:
                stats["dropped_heldout"] += 1
                continue
            if d.get("split") == "heldout":
                # Phase D hard-block: held-out never trains
                stats["dropped_heldout"] += 1
                continue
            if domain:
                meta = d.get("metrics_json") or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                row_dom = (
                    (meta.get("domain_tag") or meta.get("domain") or "")
                    if isinstance(meta, dict)
                    else ""
                )
                if str(row_dom).lower() != str(domain).lower():
                    continue
            body = (d.get("patch_text") or "") if isinstance(d.get("patch_text"), str) else ""
            # Re-assert heldout never enters train JSONL
            assert d.get("split") != "heldout", "heldout hard-block violated"
            if not _is_real_diff(body):
                stats["dropped_no_diff"] += 1
                continue
            key = pack or (d.get("task_id") or f"id:{d.get('id')}")
            bucket = by_pack.setdefault(key, {"pass": [], "fail": []})
            bucket["pass" if d.get("passed") else "fail"].append(d)

        for key, bucket in by_pack.items():
            fails = bucket["fail"]
            passes = bucket["pass"]
            for p in passes:
                ph = p.get("patch_hash") or ""
                if ph in seen_ph:
                    continue
                seen_ph.add(ph)
                body = p.get("patch_text") or ""
                if _STUB_RE.match((body or "").strip()):
                    stats["dropped_stub"] += 1
                    continue
                pack = _pack_from_meta(p.get("metrics_json")) or key
                prompt = (
                    p.get("prompt_summary")
                    or f"Fix pack {pack}. Return a unified diff that makes pytest pass."
                )
                rejected = None
                if fails:
                    # Prefer most recent fail with real diff
                    rejected = fails[0].get("patch_text")
                    stats["from_db_pairs"] += 1
                else:
                    stats["from_db_passed"] += 1
                rec = {
                    "outcome_id": str(p.get("id")),
                    "task_id": p.get("task_id"),
                    "revision_id": p.get("revision_id"),
                    "patch_hash": ph,
                    "harness_mode": p.get("harness_mode"),
                    "split": p.get("split") or "train",
                    "spdx_license": p.get("spdx_license") or "unknown",
                    "pack": pack,
                    "source": "db_passed" if not rejected else "db_preference",
                    "clean": True,
                }
                rec.update(_row_messages(prompt, body, rejected))
                out.append(rec)
                if len(out) >= limit:
                    break
            if len(out) >= limit:
                break

    if include_goldens and len(out) < limit:
        for g in golden_rows():
            ph = g.get("patch_hash") or ""
            if ph in seen_ph:
                continue
            seen_ph.add(ph)
            out.append(g)
            stats["from_goldens"] += 1
            if len(out) >= limit:
                break

    return out[:limit], stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--limit",
        type=int,
        default=int(os.getenv("LN7_EXPORT_LIMIT", "2000") or "2000"),
    )
    ap.add_argument("--include-goldens", action="store_true", default=True)
    ap.add_argument("--no-goldens", action="store_true")
    ap.add_argument("--goldens-only", action="store_true")
    ap.add_argument(
        "--domain",
        default=None,
        help="Filter export to domain_tag (W9 / B3)",
    )
    args = ap.parse_args()
    include = not args.no_goldens
    rows, stats = asyncio.run(
        export_rows(
            args.limit,
            include_goldens=include,
            goldens_only=args.goldens_only,
            domain=args.domain,
        )
    )
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
    min_rows = int(os.getenv("LN7_QLORA_MIN_ROWS", "2") or "2")
    ok = len(rows) >= min_rows
    print(json.dumps({"ok": ok, "n": len(rows), "path": str(path), "stats": stats, "min_rows": min_rows}))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
