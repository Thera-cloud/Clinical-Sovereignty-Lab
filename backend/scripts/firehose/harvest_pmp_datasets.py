"""
PMP (Project Management Professional) Dataset Harvester — Phase 5a
Targets PMBOK knowledge areas, Agile/Scrum, risk management, and
earned value management for the PMP DOJO.

Target: 2,000–3,500 crystals in pmp domain.
Node: ORANGE (Hetzner) → ships to GREEN.

Sources:
  1. LLM-generated structured PMBOK knowledge (10 knowledge areas)
  2. PMI-adjacent open resources
  3. Agile/Scrum patterns from HuggingFace

Usage:
  python -m backend.scripts.firehose.harvest_pmp_datasets
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

PMBOK_KNOWLEDGE_AREAS = [
    "Integration Management",
    "Scope Management",
    "Schedule Management",
    "Cost Management",
    "Quality Management",
    "Resource Management",
    "Communications Management",
    "Risk Management",
    "Procurement Management",
    "Stakeholder Management",
]

PMP_TOPICS = [
    "Work Breakdown Structure (WBS) creation techniques",
    "Critical Path Method (CPM) calculation and application",
    "Earned Value Management (EVM): CPI, SPI, EAC, ETC formulas",
    "RACI matrix for stakeholder role assignment",
    "Monte Carlo simulation in project risk analysis",
    "Agile sprint planning and velocity estimation",
    "Kanban WIP limits and flow efficiency",
    "Change control board (CCB) process and documentation",
    "PERT estimation: optimistic, pessimistic, most likely",
    "Project charter elements and approval authority",
    "Risk register: identification, qualitative and quantitative analysis",
    "Procurement types: FFP, CPFF, T&M, CPIF contracts",
    "Scrum ceremonies: sprint planning, daily standup, retrospective, review",
    "SAFe (Scaled Agile Framework) PI planning",
    "Resource leveling vs resource smoothing",
    "Fast tracking vs crashing: schedule compression techniques",
    "Quality management: PDCA cycle, Six Sigma DMAIC",
    "Conflict resolution strategies: collaborate, compromise, force, smooth, withdraw",
    "Communication channels formula: n(n-1)/2",
    "Project closure: lessons learned, final report, procurement audit",
    "Benefits realization and project success criteria",
    "PMO types: supportive, controlling, directive",
    "Hybrid project management: waterfall-agile blending",
    "Predictive vs adaptive project life cycles",
    "Organizational project management maturity model (OPM3)",
    "Servant leadership in Agile project management",
    "Product backlog refinement and story point estimation",
    "Burndown and burnup chart interpretation",
    "Ishikawa (fishbone) diagram for root cause analysis",
    "Decision tree analysis for project risk quantification",
]


def stage1_filter(text: str) -> Optional[int]:
    from common import stage1_ollama_score
    prompt = (
        f"Score this project management fragment 1-10 for value as "
        f"crystallized PMP exam and practice knowledge.\n"
        f"Consider: PMBOK alignment, formula accuracy, actionability, "
        f"real-world applicability.\n"
        f"Respond with ONLY a number 1-10.\n\n{text[:1000]}"
    )
    return stage1_ollama_score(text, prompt)


def push_to_green(fragments: List[Dict]):
    from common import push_to_green_safe
    push_to_green_safe(
        fragments, domain_default="pmp", fallback_name="pmp",
        green_push_url=GREEN_PUSH_URL, green_auth_token=GREEN_AUTH_TOKEN or "",
        face_path_prefix="pmp",
    )


def harvest_pmp_knowledge(tracker: ProgressTracker) -> int:
    import requests

    total_passed = 0
    push_buffer: List[Dict] = []

    for ka in PMBOK_KNOWLEDGE_AREAS:
        item_id = f"ka:{hashlib.sha256(ka.encode()).hexdigest()[:16]}"
        if tracker.is_done("pmp_ka", item_id):
            continue

        tracker.set_status("current_source", f"pmp_ka:{ka}")
        prompt = (
            f"Write a comprehensive knowledge crystal about PMBOK Knowledge Area: {ka}\n\n"
            f"Include:\n"
            f"1. Key processes within this knowledge area and their process groups\n"
            f"2. Essential tools and techniques with brief explanations\n"
            f"3. Inputs and outputs of the most important processes\n"
            f"4. Common PMP exam traps related to this area\n"
            f"5. Real-world application tips\n"
            f"Keep to 300-500 words of dense, exam-relevant content."
        )

        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL, "prompt": prompt,
                    "system": "You are a PMP-certified project manager and exam instructor. Provide precise PMBOK-aligned knowledge.",
                    "stream": False,
                },
                timeout=60,
            )
            if resp.status_code != 200:
                continue

            text = resp.json().get("response", "").strip()
            if len(text) < 100:
                continue

            fragment_text = f"[PMP Knowledge Area: {ka}]\n\n{text}"[:MAX_FRAGMENT_LEN]
            score = stage1_filter(fragment_text)
            passed = score is not None and score >= STAGE1_THRESHOLD
            tracker.mark_done("pmp_ka", item_id, domain="pmp", passed=passed)

            if passed:
                total_passed += 1
                push_buffer.append({
                    "text": fragment_text, "source": f"pmp_ka:{ka}",
                    "domain": "pmp", "scope": "global", "source_type": "pmp_ka",
                })
                if len(push_buffer) >= PUSH_BATCH_SIZE:
                    push_to_green(push_buffer)
                    push_buffer.clear()

        except Exception as e:
            print(f"  [PMP] KA error: {e}")

    for topic in PMP_TOPICS:
        item_id = f"topic:{hashlib.sha256(topic.encode()).hexdigest()[:16]}"
        if tracker.is_done("pmp_topics", item_id):
            continue

        tracker.set_status("current_source", f"pmp_topic:{topic[:40]}")
        prompt = (
            f"Write a detailed knowledge crystal about: {topic}\n\n"
            f"Be precise with any formulas, include worked examples where "
            f"applicable, and note common misconceptions.\n"
            f"Keep to 200-400 words."
        )

        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL, "prompt": prompt,
                    "system": "You are a PMP exam prep instructor. Provide precise, testable knowledge with formulas and examples.",
                    "stream": False,
                },
                timeout=60,
            )
            if resp.status_code != 200:
                continue

            text = resp.json().get("response", "").strip()
            if len(text) < 100:
                continue

            fragment_text = f"[PMP Topic: {topic}]\n\n{text}"[:MAX_FRAGMENT_LEN]
            score = stage1_filter(fragment_text)
            passed = score is not None and score >= STAGE1_THRESHOLD
            tracker.mark_done("pmp_topics", item_id, domain="pmp", passed=passed)

            if passed:
                total_passed += 1
                push_buffer.append({
                    "text": fragment_text, "source": f"pmp_topic:{item_id}",
                    "domain": "pmp", "scope": "global", "source_type": "pmp_topics",
                })
                if len(push_buffer) >= PUSH_BATCH_SIZE:
                    push_to_green(push_buffer)
                    push_buffer.clear()

        except Exception as e:
            print(f"  [PMP] Topic error: {e}")

    if push_buffer:
        push_to_green(push_buffer)
    return total_passed


def harvest_pmp():
    tracker = ProgressTracker()
    tracker.set_status("current_phase", "pmp")

    total = harvest_pmp_knowledge(tracker)

    tracker.set_status("current_source", "complete")
    tracker.write_status_json()
    print(f"\n[PMP] Complete — {total} fragments passed Stage 1")
    tracker.close()


if __name__ == "__main__":
    harvest_pmp()
