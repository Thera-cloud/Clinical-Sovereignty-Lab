"""
Firehose Orchestrator — Phase 7
Master runner for the entire Crystal Factory Firehose pipeline.
Executes harvest scripts in dependency order, tracks global progress,
and reports final statistics.

Architecture:
  ORANGE node (Hetzner CAX41) runs all harvests.
  Each harvest pushes crystals to GREEN (DigitalOcean) via REST API.
  GREEN runs Vectorize indexing, graph clustering, and meta-crystal synthesis.

Execution Order:
  Phase 1: Therapeutic Core (HuggingFace therapy datasets)
  Phase 2a: GitHub Deep (curated + trending repo parsing)
  Phase 2b: Stack Overflow (dump + API fallback)
  Phase 3: Legal (HIPAA, case law, federal register)
  Phase 4a: Business (SEC EDGAR, HF financial Q&A)
  Phase 4b: Accounting (GAAP patterns, IRS publications)
  Phase 5a: PMP (PMBOK knowledge areas, Agile patterns)
  Phase 5b: Machining (CNC, G-code, GD&T)
  Phase 5c: Teaching (pedagogy, ERIC research)
  Phase 6a: PubMed (therapy research abstracts)
  Phase 6b: Textbooks (therapeutic techniques, OER)

Usage:
  # Run everything:
  python -m backend.scripts.firehose.firehose_orchestrator

  # Run specific phases:
  python -m backend.scripts.firehose.firehose_orchestrator --phases 1,2

  # Status only:
  python -m backend.scripts.firehose.firehose_orchestrator --status

  # Resume from last checkpoint:
  python -m backend.scripts.firehose.firehose_orchestrator --resume
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

FIREHOSE_DIR = Path(__file__).parent
sys.path.insert(0, str(FIREHOSE_DIR))
from progress_tracker import ProgressTracker

PHASES = {
    1: {
        "name": "Therapeutic Core (HuggingFace)",
        "module": "harvest_huggingface_therapy",
        "function": "harvest_therapy",
        "target_crystals": "8,000–12,000",
        "domains": ["clinical", "crisis"],
        "deps": ["datasets"],
    },
    "2a": {
        "name": "GitHub Deep Repository Parsing",
        "module": "harvest_github_deep",
        "function": "harvest_github",
        "target_crystals": "5,000–10,000",
        "domains": ["coding"],
        "deps": ["requests"],
    },
    "2b": {
        "name": "Stack Overflow (Dump + API)",
        "module": "harvest_stackoverflow_dump",
        "function": "harvest_stackoverflow",
        "target_crystals": "4,000–8,000",
        "domains": ["coding"],
        "deps": ["requests"],
    },
    3: {
        "name": "Legal (HIPAA, Case Law, Federal Register)",
        "module": "harvest_legal_datasets",
        "function": "harvest_legal",
        "target_crystals": "3,000–5,000",
        "domains": ["legal"],
        "deps": ["requests", "datasets"],
    },
    "4a": {
        "name": "Business & Entrepreneurship",
        "module": "harvest_business_datasets",
        "function": "harvest_business",
        "target_crystals": "2,000–4,000",
        "domains": ["business"],
        "deps": ["requests", "datasets"],
    },
    "4b": {
        "name": "Accounting & Tax",
        "module": "harvest_accounting_datasets",
        "function": "harvest_accounting",
        "target_crystals": "1,500–3,000",
        "domains": ["accounting"],
        "deps": ["requests", "datasets"],
    },
    "5a": {
        "name": "PMP & Project Management",
        "module": "harvest_pmp_datasets",
        "function": "harvest_pmp",
        "target_crystals": "2,000–3,500",
        "domains": ["pmp"],
        "deps": ["requests"],
    },
    "5b": {
        "name": "Machining & CNC",
        "module": "harvest_machining_datasets",
        "function": "harvest_machining",
        "target_crystals": "1,500–3,000",
        "domains": ["machining"],
        "deps": ["requests"],
    },
    "5c": {
        "name": "Teaching & Pedagogy",
        "module": "harvest_teaching_datasets",
        "function": "harvest_teaching",
        "target_crystals": "2,000–3,500",
        "domains": ["teaching"],
        "deps": ["requests"],
    },
    "6a": {
        "name": "PubMed Therapy Research",
        "module": "harvest_pubmed_therapy",
        "function": "harvest_pubmed",
        "target_crystals": "3,000–5,000",
        "domains": ["clinical", "research", "crisis"],
        "deps": ["requests"],
    },
    "6b": {
        "name": "Open Psychology Textbooks",
        "module": "harvest_open_psych_textbooks",
        "function": "harvest_open_psych_textbooks",
        "target_crystals": "2,000–4,000",
        "domains": ["clinical", "coaching", "research"],
        "deps": ["requests"],
    },
}

PHASE_ORDER = [1, "2a", "2b", 3, "4a", "4b", "5a", "5b", "5c", "6a", "6b"]


def check_dependencies(phase_config: Dict) -> List[str]:
    """Check if required Python packages are installed."""
    missing = []
    for dep in phase_config.get("deps", []):
        try:
            __import__(dep)
        except ImportError:
            missing.append(dep)
    return missing


def run_phase(phase_key, tracker: ProgressTracker) -> Dict:
    """Execute a single harvest phase."""
    config = PHASES[phase_key]
    phase_name = config["name"]
    module_name = config["module"]
    func_name = config["function"]

    print(f"\n{'='*70}")
    print(f"  PHASE {phase_key}: {phase_name}")
    print(f"  Target: {config['target_crystals']} crystals")
    print(f"  Domains: {', '.join(config['domains'])}")
    print(f"{'='*70}")

    missing = check_dependencies(config)
    if missing:
        print(f"  SKIPPED — missing packages: {', '.join(missing)}")
        return {"phase": phase_key, "status": "skipped", "reason": f"missing: {missing}"}

    tracker.set_status("current_phase", str(phase_key))
    start = time.time()

    try:
        module = __import__(module_name)
        func = getattr(module, func_name)
        func()
        elapsed = time.time() - start
        print(f"\n  Phase {phase_key} completed in {elapsed:.0f}s")
        return {"phase": phase_key, "status": "completed", "elapsed_s": elapsed}
    except Exception as e:
        elapsed = time.time() - start
        print(f"\n  Phase {phase_key} FAILED after {elapsed:.0f}s: {e}")
        traceback.print_exc()
        return {"phase": phase_key, "status": "failed", "error": str(e), "elapsed_s": elapsed}


def show_status():
    """Display current firehose progress."""
    tracker = ProgressTracker()
    stats = tracker.get_stats()

    print(f"\n{'='*70}")
    print(f"  CRYSTAL FACTORY FIREHOSE — STATUS")
    print(f"{'='*70}")

    total_processed = 0
    total_passed = 0

    for s in stats:
        total_processed += s["processed"]
        total_passed += s["passed"]
        pass_rate = f"{s['passed']/s['processed']*100:.0f}%" if s["processed"] > 0 else "N/A"
        print(f"  {s['source']:35s}  processed: {s['processed']:>6d}  "
              f"passed: {s['passed']:>6d}  rate: {pass_rate:>5s}  "
              f"updated: {s['updated']}")

    print(f"\n  {'TOTAL':35s}  processed: {total_processed:>6d}  "
          f"passed: {total_passed:>6d}")
    print(f"\n  Current phase: {tracker.get_status('current_phase') or 'idle'}")
    print(f"  Current source: {tracker.get_status('current_source') or 'none'}")
    print(f"{'='*70}")

    tracker.close()


def parse_phase_arg(arg: str) -> List:
    """Parse phase selection like '1,2a,3' into a list."""
    phases = []
    for p in arg.split(","):
        p = p.strip()
        try:
            phases.append(int(p))
        except ValueError:
            phases.append(p)
    return phases


def main():
    parser = argparse.ArgumentParser(description="Crystal Factory Firehose Orchestrator")
    parser.add_argument("--phases", type=str, default="",
                        help="Comma-separated phase list (e.g., '1,2a,3'). Default: all.")
    parser.add_argument("--status", action="store_true",
                        help="Show current progress and exit.")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from the last incomplete phase.")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    tracker = ProgressTracker()
    phases_to_run = parse_phase_arg(args.phases) if args.phases else list(PHASE_ORDER)

    if args.resume:
        last_phase = tracker.get_status("last_completed_phase")
        if last_phase:
            try:
                idx = PHASE_ORDER.index(int(last_phase) if last_phase.isdigit() else last_phase)
                phases_to_run = PHASE_ORDER[idx + 1:]
                print(f"[ORCHESTRATOR] Resuming after phase {last_phase}")
            except (ValueError, IndexError):
                pass

    print(f"\n{'#'*70}")
    print(f"  CRYSTAL FACTORY FIREHOSE — FULL RUN")
    print(f"  Phases: {', '.join(str(p) for p in phases_to_run)}")
    print(f"  Start: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'#'*70}")

    results = []
    overall_start = time.time()

    for phase_key in phases_to_run:
        if phase_key not in PHASES:
            print(f"\n  Unknown phase: {phase_key} — skipping")
            continue

        result = run_phase(phase_key, tracker)
        results.append(result)

        if result["status"] == "completed":
            tracker.set_status("last_completed_phase", str(phase_key))

        tracker.write_status_json()

    overall_elapsed = time.time() - overall_start

    print(f"\n\n{'#'*70}")
    print(f"  FIREHOSE RUN COMPLETE")
    print(f"  Total time: {overall_elapsed/3600:.1f}h ({overall_elapsed:.0f}s)")
    print(f"{'#'*70}")

    for r in results:
        status_icon = "✅" if r["status"] == "completed" else "⏭️" if r["status"] == "skipped" else "❌"
        elapsed = f" ({r.get('elapsed_s', 0):.0f}s)" if "elapsed_s" in r else ""
        reason = f" — {r.get('reason', r.get('error', ''))}" if r["status"] != "completed" else ""
        print(f"  {status_icon} Phase {r['phase']}: {r['status']}{elapsed}{reason}")

    show_status()
    tracker.close()


if __name__ == "__main__":
    main()
