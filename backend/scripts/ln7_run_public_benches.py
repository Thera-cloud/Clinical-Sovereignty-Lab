#!/usr/bin/env python3
"""Run LN7 public benchmarks on ORANGE/BLUE (never GREEN for full mode).

Usage:
  # Smoke (default) — wiring proof against local Ollama
  LN7_PUBLIC_HARNESS_MODE=smoke PYTHONPATH=backend \\
    python backend/scripts/ln7_run_public_benches.py

  # Ingest-only scorecard from docs/ln7/public_results/*.json
  LN7_PUBLIC_HARNESS_MODE=ingest python backend/scripts/ln7_run_public_benches.py

  # Full official runners (requires LN7_PUBLIC_HARNESS_ROOT clones)
  LN7_PUBLIC_HARNESS_MODE=full LN7_PUBLIC_HARNESS_ROOT=/opt/ln7-harness \\
    python backend/scripts/ln7_run_public_benches.py --write

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


async def _main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", action="append", help="Benchmark id (repeatable)")
    ap.add_argument("--write", action="store_true", help="Write JSON under public_results/")
    ap.add_argument("--mode", default="", help="smoke|ingest|full (overrides env)")
    args = ap.parse_args()
    if args.mode:
        os.environ["LN7_PUBLIC_HARNESS_MODE"] = args.mode

    from app.services.ln7_public_harness import (
        PUBLIC_BENCHMARKS,
        run_public_benchmark,
        write_result,
    )

    names = args.bench or list(PUBLIC_BENCHMARKS)
    results = []
    for name in names:
        row = await run_public_benchmark(name)
        results.append(row)
        if args.write and row.get("status") == "ok":
            path = write_result(name, row)
            print(f"wrote {path}", file=sys.stderr)
        print(json.dumps(row, default=str))
    summary = {
        "ok": all(r.get("status") == "ok" for r in results),
        "n": len(results),
        "benchmarks": [r.get("benchmark") for r in results],
        "modes": list({r.get("mode") for r in results}),
        "report_only": True,
        "non_clinical_claim": True,
    }
    print(json.dumps(summary), file=sys.stderr)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
