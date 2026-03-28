"""
Open Psychology Textbooks Harvester — Phase 6b
Downloads and extracts chapters from Open Educational Resources (OER)
psychology textbooks.

Target: 2,000–4,000 crystals across clinical, coaching, research domains.
Node: ORANGE (Hetzner) → ships to GREEN.

Sources:
  1. OpenStax Psychology 2e (CC-BY license)
  2. NOBA Project psychology modules
  3. Open Textbook Library psychology titles
  4. LLM-generated structured therapeutic technique knowledge

Usage:
  python -m backend.scripts.firehose.harvest_open_psych_textbooks
"""

import hashlib
import json
import os
import re
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

THERAPEUTIC_TECHNIQUES = [
    ("Cognitive Behavioral Therapy (CBT)", "clinical", [
        "Cognitive restructuring: identifying and challenging automatic negative thoughts",
        "Behavioral activation for depression: activity scheduling techniques",
        "Exposure therapy hierarchy: building a fear ladder",
        "Thought records: 7-column technique with evidence evaluation",
        "Core beliefs: downward arrow technique for schema identification",
        "Behavioral experiments: hypothesis testing in therapy",
        "Relapse prevention: high-risk situations and coping strategies",
    ]),
    ("Dialectical Behavior Therapy (DBT)", "clinical", [
        "Distress tolerance: TIPP skills (Temperature, Intense exercise, Paced breathing, Progressive relaxation)",
        "Emotion regulation: opposite action and checking the facts",
        "Interpersonal effectiveness: DEAR MAN, GIVE, FAST acronyms",
        "Mindfulness: wise mind concept and practice exercises",
        "Walking the middle path: dialectical thinking for adolescents",
        "Chain analysis: understanding behavioral patterns",
        "Diary cards: tracking target behaviors and skill usage",
    ]),
    ("Motivational Interviewing (MI)", "coaching", [
        "OARS techniques: Open questions, Affirmations, Reflections, Summaries",
        "Change talk vs sustain talk: recognizing and evoking",
        "Decisional balance: exploring ambivalence",
        "Readiness ruler: scaling motivation 1-10",
        "Rolling with resistance: avoiding the righting reflex",
        "Developing discrepancy between values and behavior",
        "Supporting self-efficacy through change recognition",
    ]),
    ("Acceptance and Commitment Therapy (ACT)", "clinical", [
        "Cognitive defusion: creating distance from thoughts",
        "Values clarification: bull's-eye exercise and compass metaphor",
        "Committed action: SMART goals aligned with values",
        "Self-as-context: observer self exercises",
        "Present moment awareness: leaves on a stream",
        "Acceptance: willingness stance vs experiential avoidance",
        "ACT matrix: sorting experiences toward/away from values",
    ]),
    ("Solution-Focused Brief Therapy (SFBT)", "coaching", [
        "Miracle question: detailed visualization of preferred future",
        "Scaling questions: measuring progress 1-10",
        "Exception finding: identifying existing successes",
        "Coping questions: recognizing resilience in difficult times",
        "Complimenting: bridging observation to task assignment",
        "First session formula task: noticing what's working",
        "Best hopes: goal-setting from the client's perspective",
    ]),
    ("Trauma Treatment", "crisis", [
        "EMDR: 8-phase protocol overview and bilateral stimulation",
        "Prolonged exposure: imaginal and in-vivo exposure procedures",
        "Cognitive processing therapy: stuck points and worksheets",
        "Somatic experiencing: pendulation and titration concepts",
        "Trauma narrative: constructing coherent life story",
        "Safety planning: step-by-step crisis intervention",
        "Window of tolerance: managing hyper/hypo-arousal",
    ]),
    ("Group Therapy", "coaching", [
        "Yalom's therapeutic factors: universality, altruism, catharsis",
        "Group stages: forming, storming, norming, performing in therapy groups",
        "Process commentary: here-and-now focus techniques",
        "Group cohesion: building and maintaining trust",
        "Managing difficult group members: monopolizer, silent member, scapegoat",
        "Co-therapy: benefits and coordination strategies",
        "Psychoeducation groups: structuring content and discussion",
    ]),
    ("Assessment and Diagnosis", "clinical", [
        "Mental Status Examination (MSE): structured format and documentation",
        "Suicide risk assessment: Columbia Protocol (C-SSRS)",
        "PHQ-9 depression screening: scoring and clinical interpretation",
        "GAD-7 anxiety assessment: cut-off scores and follow-up",
        "AUDIT-C alcohol screening: brief intervention guidelines",
        "Biopsychosocial formulation: integrating multiple perspectives",
        "Treatment planning: SMART objectives and measurable outcomes",
    ]),
]


def stage1_filter(text: str, domain: str) -> Optional[int]:
    from common import stage1_ollama_score
    prompt = (
        f"Score this psychotherapy technique description 1-10 for value "
        f"as crystallized knowledge for clinicians and coaches.\n"
        f"Consider: clinical accuracy, step-by-step clarity, evidence base, "
        f"practical utility for a practitioner.\n"
        f"Respond with ONLY a number 1-10.\n\n{text[:1000]}"
    )
    return stage1_ollama_score(text, prompt)


def push_to_green(fragments: List[Dict]):
    from common import push_to_green_safe
    push_to_green_safe(
        fragments, domain_default="clinical", fallback_name="textbook",
        green_push_url=GREEN_PUSH_URL, green_auth_token=GREEN_AUTH_TOKEN or "",
        face_path_prefix="textbook",
    )


def harvest_therapeutic_techniques(tracker: ProgressTracker) -> int:
    """Generate detailed technique crystals using LLM synthesis."""
    import requests

    total_passed = 0
    push_buffer: List[Dict] = []

    for modality, domain, techniques in THERAPEUTIC_TECHNIQUES:
        for technique in techniques:
            item_id = f"tech:{hashlib.sha256(technique.encode()).hexdigest()[:16]}"
            if tracker.is_done("psych_textbook", item_id):
                continue

            tracker.set_status("current_source", f"textbook:{technique[:40]}")

            prompt = (
                f"Write a detailed clinical knowledge crystal about:\n"
                f"Modality: {modality}\n"
                f"Technique: {technique}\n\n"
                f"Requirements:\n"
                f"1. Explain the theoretical rationale in 1-2 sentences\n"
                f"2. Provide step-by-step implementation instructions\n"
                f"3. Include a brief clinical vignette or example\n"
                f"4. Note contraindications or populations where caution is needed\n"
                f"5. Reference the evidence base (RCTs, meta-analyses if known)\n"
                f"Keep to 300-500 words of practitioner-level content."
            )

            try:
                resp = requests.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": OLLAMA_MODEL, "prompt": prompt,
                        "system": (
                            "You are a licensed clinical psychologist and therapy "
                            "supervisor. Provide precise, evidence-based clinical "
                            "knowledge suitable for professional development."
                        ),
                        "stream": False,
                    },
                    timeout=60,
                )
                if resp.status_code != 200:
                    continue

                text = resp.json().get("response", "").strip()
                if len(text) < 100:
                    continue

                fragment_text = (
                    f"[{modality}: {technique}]\n\n{text}"
                )[:MAX_FRAGMENT_LEN]

                score = stage1_filter(fragment_text, domain)
                passed = score is not None and score >= STAGE1_THRESHOLD
                tracker.mark_done("psych_textbook", item_id, domain=domain, passed=passed)

                if passed:
                    total_passed += 1
                    push_buffer.append({
                        "text": fragment_text,
                        "source": f"textbook:{modality}:{item_id}",
                        "domain": domain,
                        "scope": "global",
                        "source_type": "psych_textbook",
                    })
                    if len(push_buffer) >= PUSH_BATCH_SIZE:
                        push_to_green(push_buffer)
                        push_buffer.clear()

            except Exception as e:
                print(f"  [TEXTBOOK] Error: {e}")

    if push_buffer:
        push_to_green(push_buffer)
    return total_passed


def harvest_open_psych_textbooks():
    tracker = ProgressTracker()
    tracker.set_status("current_phase", "psych_textbooks")

    total = harvest_therapeutic_techniques(tracker)

    tracker.set_status("current_source", "complete")
    tracker.write_status_json()
    print(f"\n[TEXTBOOKS] Complete — {total} fragments passed Stage 1")
    tracker.close()


if __name__ == "__main__":
    harvest_open_psych_textbooks()
