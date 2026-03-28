"""
Machining & CNC Dataset Harvester — Phase 5b
Targets G-code patterns, tool selection, material science, tolerance
calculations, and safety protocols for the Machinist DOJO.

Target: 1,500–3,000 crystals in machining domain.
Node: ORANGE (Hetzner) → ships to GREEN.

Sources:
  1. LLM-generated structured machining knowledge
  2. Machinery's Handbook-style reference patterns
  3. G-code programming patterns

Usage:
  python -m backend.scripts.firehose.harvest_machining_datasets
"""

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

FIREHOSE_DIR = Path(__file__).parent
sys.path.insert(0, str(FIREHOSE_DIR))
from progress_tracker import ProgressTracker

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
GREEN_PUSH_URL = os.getenv("GREEN_PUSH_URL", "http://localhost:8000/api/admin/crystal-network/push")
GREEN_AUTH_TOKEN = os.getenv("GREEN_AUTH_TOKEN", "")

MAX_FRAGMENT_LEN = 2000
STAGE1_THRESHOLD = 6
PUSH_BATCH_SIZE = 50

MACHINING_TOPICS = [
    "Feeds and speeds calculation for aluminum 6061 on 3-axis CNC mill",
    "Surface finish (Ra) requirements and how cutting parameters affect them",
    "G-code: G41/G42 cutter compensation explanation and common pitfalls",
    "Thread milling vs single-point threading: when to use each",
    "Workholding: vise jaw design for thin-wall parts",
    "Tool deflection calculation and its effect on dimensional accuracy",
    "Coolant types: flood, mist, MQL — when to use each",
    "5-axis simultaneous machining: tool vector control fundamentals",
    "Carbide insert grade selection for stainless steel 316L",
    "CNC lathe: live tooling setup and programming (G12.1 polar interpolation)",
    "GD&T: position tolerance calculation with bonus tolerance (MMC)",
    "GD&T: profile of a surface vs profile of a line — datum reference",
    "Wire EDM: gap voltage, flush pressure, wire tension optimization",
    "Heat treatment: Rockwell hardness testing and implications for machining",
    "Chip load per tooth calculation and optimal chip thinning",
    "Trochoidal milling: tool path strategy for hard materials",
    "Bore interpolation (G12/G13) vs traditional boring bars",
    "Fixturing for production: quick-change pallets and zero-point systems",
    "Material properties: titanium Ti-6Al-4V machining best practices",
    "CNC program structure: safe start blocks, tool change routines",
    "In-process measurement: touch probes for automatic offset updates",
    "Thermal expansion compensation in precision machining",
    "Swiss-type lathe programming: guide bushing mechanics",
    "EDM sinker: electrode material selection (copper vs graphite)",
    "Statistical Process Control (SPC) for CNC: Cp, Cpk calculations",
    "Tap drill size calculation for various thread standards",
    "Power and torque requirements for heavy roughing operations",
    "Workpiece material identification: spark test, chemical analysis",
    "Machine alignment: laser interferometry and ballbar testing",
    "Additive manufacturing post-processing: machining 3D printed metal parts",
]


def stage1_filter(text: str) -> Optional[int]:
    from common import stage1_ollama_score
    prompt = (
        f"Score this machining/CNC fragment 1-10 for value as crystallized "
        f"knowledge for professional machinists.\n"
        f"Consider: technical accuracy, formula correctness, practical shop "
        f"applicability, safety awareness.\n"
        f"Respond with ONLY a number 1-10.\n\n{text[:1000]}"
    )
    return stage1_ollama_score(text, prompt)


def push_to_green(fragments: List[Dict]):
    from common import push_to_green_safe
    push_to_green_safe(
        fragments, domain_default="machining", fallback_name="machining",
        green_push_url=GREEN_PUSH_URL, green_auth_token=GREEN_AUTH_TOKEN or "",
        face_path_prefix="machining",
    )


def harvest_machining_knowledge(tracker: ProgressTracker) -> int:
    import requests

    total_passed = 0
    push_buffer: List[Dict] = []

    for topic in MACHINING_TOPICS:
        item_id = f"topic:{hashlib.sha256(topic.encode()).hexdigest()[:16]}"
        if tracker.is_done("machining", item_id):
            continue

        tracker.set_status("current_source", f"machining:{topic[:40]}")
        prompt = (
            f"Write a detailed machining knowledge crystal about: {topic}\n\n"
            f"Requirements:\n"
            f"1. Include specific formulas with units (SFM, IPM, IPT, etc.)\n"
            f"2. Provide worked numerical examples where applicable\n"
            f"3. Note common shop-floor mistakes and safety considerations\n"
            f"4. Reference relevant standards (ASME, ISO) when applicable\n"
            f"5. Keep to 300-500 words of dense, practitioner-level content"
        )

        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL, "prompt": prompt,
                    "system": "You are a master machinist and CNC programmer with 25 years of precision manufacturing experience. Provide accurate technical knowledge with real-world examples.",
                    "stream": False,
                },
                timeout=60,
            )
            if resp.status_code != 200:
                continue

            text = resp.json().get("response", "").strip()
            if len(text) < 100:
                continue

            fragment_text = f"[Machining Knowledge: {topic}]\n\n{text}"[:MAX_FRAGMENT_LEN]
            score = stage1_filter(fragment_text)
            passed = score is not None and score >= STAGE1_THRESHOLD
            tracker.mark_done("machining", item_id, domain="machining", passed=passed)

            if passed:
                total_passed += 1
                push_buffer.append({
                    "text": fragment_text,
                    "source": f"machining:{item_id}",
                    "domain": "machining",
                    "scope": "global",
                    "source_type": "machining_llm",
                })
                if len(push_buffer) >= PUSH_BATCH_SIZE:
                    push_to_green(push_buffer)
                    push_buffer.clear()

        except Exception as e:
            print(f"  [MACHINING] Error: {e}")

    if push_buffer:
        push_to_green(push_buffer)
    return total_passed


def harvest_machining():
    tracker = ProgressTracker()
    tracker.set_status("current_phase", "machining")

    total = harvest_machining_knowledge(tracker)

    tracker.set_status("current_source", "complete")
    tracker.write_status_json()
    print(f"\n[MACHINING] Complete — {total} fragments passed Stage 1")
    tracker.close()


if __name__ == "__main__":
    harvest_machining()
