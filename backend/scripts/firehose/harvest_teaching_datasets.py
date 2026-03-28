"""
Teaching & Pedagogy Dataset Harvester — Phase 5c
Targets evidence-based teaching methods, classroom management,
curriculum design, and educational psychology for the Teacher DOJO.

Target: 2,000–3,500 crystals in teaching domain.
Node: ORANGE (Hetzner) → ships to GREEN.

Sources:
  1. LLM-generated structured pedagogy knowledge
  2. ERIC (Education Resources Information Center) API
  3. Open educational psychology resources

Usage:
  python -m backend.scripts.firehose.harvest_teaching_datasets
"""

import hashlib
import json
import os
import sys
import time
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

TEACHING_TOPICS = [
    "Bloom's Taxonomy: cognitive levels and action verbs for learning objectives",
    "Formative assessment strategies: exit tickets, think-pair-share, quick writes",
    "Differentiated instruction: tiered assignments and flexible grouping",
    "Backward design (Understanding by Design): stages and template",
    "Classroom management: positive behavioral interventions and supports (PBIS)",
    "Scaffolding techniques for English language learners (ELLs)",
    "Universal Design for Learning (UDL): engagement, representation, action/expression",
    "Socratic questioning: levels of questions and facilitation techniques",
    "Project-based learning (PBL): design principles and assessment rubrics",
    "Cooperative learning structures: jigsaw, think-pair-share, numbered heads",
    "Growth mindset: implementing Dweck's research in classroom practice",
    "Trauma-informed teaching: recognizing and responding to student trauma",
    "Restorative practices in education: circles, conferences, mediation",
    "Culturally responsive teaching: funds of knowledge approach",
    "Flipped classroom model: video creation, in-class activity design",
    "Standards-based grading: proficiency scales and evidence collection",
    "IEP goals: writing measurable objectives for special education",
    "504 accommodation plans: common accommodations and documentation",
    "Response to Intervention (RTI): three-tier model implementation",
    "Mastery learning: prerequisites, formative assessment, corrective instruction",
    "Gamification in education: point systems, badges, leaderboards",
    "Social-emotional learning (SEL): CASEL framework and integration",
    "Parent communication strategies: conferences, newsletters, digital tools",
    "De-escalation techniques for student behavioral crises",
    "Inquiry-based science teaching: 5E model (Engage, Explore, Explain, Elaborate, Evaluate)",
    "Reading comprehension strategies: reciprocal teaching, SQ3R, annotation",
    "Writing workshop model: mini-lessons, independent writing, conferencing",
    "Numeracy development: concrete-representational-abstract (CRA) sequence",
    "Assessment literacy: validity, reliability, bias in classroom assessments",
    "Teacher self-care and burnout prevention strategies",
]

ERIC_SEARCH_TERMS = [
    "evidence-based teaching strategies",
    "classroom management techniques research",
    "differentiated instruction effectiveness",
    "social emotional learning outcomes",
    "trauma-informed classroom practices",
    "culturally responsive pedagogy",
    "formative assessment techniques",
    "special education inclusion strategies",
    "technology integration classroom",
    "teacher professional development effectiveness",
]


def stage1_filter(text: str) -> Optional[int]:
    from common import stage1_ollama_score
    prompt = (
        f"Score this teaching/pedagogy fragment 1-10 for value as "
        f"crystallized knowledge for educators.\n"
        f"Consider: evidence base, practical applicability, specificity, "
        f"alignment with research-backed practices.\n"
        f"Respond with ONLY a number 1-10.\n\n{text[:1000]}"
    )
    return stage1_ollama_score(text, prompt)


def push_to_green(fragments: List[Dict]):
    from common import push_to_green_safe
    push_to_green_safe(
        fragments, domain_default="teaching", fallback_name="teaching",
        green_push_url=GREEN_PUSH_URL, green_auth_token=GREEN_AUTH_TOKEN or "",
        face_path_prefix="teaching",
    )


def harvest_teaching_knowledge(tracker: ProgressTracker) -> int:
    import requests

    total_passed = 0
    push_buffer: List[Dict] = []

    for topic in TEACHING_TOPICS:
        item_id = f"topic:{hashlib.sha256(topic.encode()).hexdigest()[:16]}"
        if tracker.is_done("teaching_topics", item_id):
            continue

        tracker.set_status("current_source", f"teaching:{topic[:40]}")
        prompt = (
            f"Write a detailed teaching knowledge crystal about: {topic}\n\n"
            f"Requirements:\n"
            f"1. Reference specific research or theoretical frameworks\n"
            f"2. Include step-by-step implementation instructions\n"
            f"3. Provide a concrete classroom example\n"
            f"4. Note common implementation mistakes\n"
            f"5. Include assessment/evaluation criteria\n"
            f"Keep to 300-500 words."
        )

        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL, "prompt": prompt,
                    "system": "You are a master teacher and educational researcher with 20 years of K-12 and higher education experience. Provide evidence-based, practical pedagogy.",
                    "stream": False,
                },
                timeout=60,
            )
            if resp.status_code != 200:
                continue

            text = resp.json().get("response", "").strip()
            if len(text) < 100:
                continue

            fragment_text = f"[Teaching Knowledge: {topic}]\n\n{text}"[:MAX_FRAGMENT_LEN]
            score = stage1_filter(fragment_text)
            passed = score is not None and score >= STAGE1_THRESHOLD
            tracker.mark_done("teaching_topics", item_id, domain="teaching", passed=passed)

            if passed:
                total_passed += 1
                push_buffer.append({
                    "text": fragment_text, "source": f"teaching:{item_id}",
                    "domain": "teaching", "scope": "global",
                    "source_type": "teaching_llm",
                })
                if len(push_buffer) >= PUSH_BATCH_SIZE:
                    push_to_green(push_buffer)
                    push_buffer.clear()

        except Exception as e:
            print(f"  [TEACHING] Topic error: {e}")

    if push_buffer:
        push_to_green(push_buffer)
    return total_passed


def harvest_eric(tracker: ProgressTracker) -> int:
    """Fetch research abstracts from ERIC API."""
    import requests

    total_passed = 0
    push_buffer: List[Dict] = []

    for term in ERIC_SEARCH_TERMS:
        tkey = f"eric:{term.replace(' ', '_')}"
        if tracker.is_done("eric_api", tkey):
            continue

        tracker.set_status("current_source", f"eric:{term}")
        print(f"  [ERIC] Searching: {term}")

        try:
            resp = requests.get(
                "https://api.ies.ed.gov/eric/",
                params={
                    "search": term,
                    "rows": 30,
                    "format": "json",
                    "fields": "title,description,subject",
                },
                timeout=30,
            )
            if resp.status_code != 200:
                continue

            docs = resp.json().get("response", {}).get("docs", [])
            for doc in docs:
                doc_id = doc.get("id", "")
                did = f"eric:{doc_id}"
                if tracker.is_done("eric_api", did):
                    continue

                title = doc.get("title", "")
                description = doc.get("description", "")
                subjects = ", ".join(doc.get("subject", [])[:5])

                text = (
                    f"[ERIC Research: {title}]\n"
                    f"Subjects: {subjects}\n\n"
                    f"{description}"
                )[:MAX_FRAGMENT_LEN]

                if len(text) < 120:
                    continue

                score = stage1_filter(text)
                passed = score is not None and score >= STAGE1_THRESHOLD
                tracker.mark_done("eric_api", did, domain="teaching", passed=passed)

                if passed:
                    total_passed += 1
                    push_buffer.append({
                        "text": text, "source": f"eric:{doc_id}",
                        "domain": "teaching", "scope": "global",
                        "source_type": "eric_api",
                    })
                    if len(push_buffer) >= PUSH_BATCH_SIZE:
                        push_to_green(push_buffer)
                        push_buffer.clear()

            time.sleep(1)
        except Exception as e:
            print(f"  [ERIC] Error: {e}")

        tracker.mark_done("eric_api", tkey, domain="teaching")

    if push_buffer:
        push_to_green(push_buffer)
    return total_passed


def harvest_teaching():
    tracker = ProgressTracker()
    tracker.set_status("current_phase", "teaching")

    topics = harvest_teaching_knowledge(tracker)
    eric = harvest_eric(tracker)

    tracker.set_status("current_source", "complete")
    tracker.write_status_json()
    print(f"\n[TEACHING] Complete — Topics: {topics}, ERIC: {eric}")
    tracker.close()


if __name__ == "__main__":
    harvest_teaching()
