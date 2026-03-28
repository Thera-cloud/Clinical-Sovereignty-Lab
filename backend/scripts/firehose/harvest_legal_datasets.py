"""
Legal Dataset Harvester — Phase 3
Harvests HIPAA, FERPA, ADA, state licensing, malpractice case law,
and informed consent requirements for the Judge DOJO.

Target: 3,000–5,000 crystals in legal domain.
Node: ORANGE (Hetzner) → ships to GREEN.

Sources:
  1. HuggingFace legal datasets (pile-of-law subsets)
  2. CaseLaw Access Project (Harvard) API
  3. Federal Register API (HIPAA/ADA regulations)
  4. Open-access state licensing board data

Usage:
  pip install datasets requests
  python -m backend.scripts.firehose.harvest_legal_datasets
"""

import hashlib
import json
import os
import re
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

LEGAL_HF_DATASETS = [
    {
        "name": "pile-of-law/pile-of-law",
        "subset": "cfr",
        "domain": "legal",
        "source_type": "hf_cfr",
        "text_field": "text",
    },
    {
        "name": "pile-of-law/pile-of-law",
        "subset": "courtlistener_opinions",
        "domain": "legal",
        "source_type": "hf_courtlistener",
        "text_field": "text",
    },
]

FEDERAL_REGISTER_QUERIES = [
    {"term": "HIPAA", "agency": "hhs", "domain": "legal"},
    {"term": "mental health parity", "agency": "hhs", "domain": "legal"},
    {"term": "ADA accommodation", "domain": "legal"},
    {"term": "FERPA education records", "domain": "legal"},
    {"term": "informed consent mental health", "domain": "legal"},
    {"term": "telehealth regulations", "domain": "legal"},
    {"term": "counselor licensing requirements", "domain": "legal"},
    {"term": "malpractice mental health provider", "domain": "legal"},
]

CASELAW_QUERIES = [
    "HIPAA violation mental health",
    "therapist confidentiality breach",
    "informed consent psychotherapy",
    "counselor malpractice negligence",
    "duty to warn Tarasoff",
    "mandated reporting child abuse",
    "ADA reasonable accommodation mental health",
    "telehealth licensing interstate",
    "substance abuse records 42 CFR Part 2",
]


def stage1_filter(text: str, domain: str = "legal") -> Optional[int]:
    from common import stage1_ollama_score
    prompt = (
        f"Score this legal/regulatory fragment 1-10 for value as crystallized "
        f"knowledge for mental health professionals.\n"
        f"Consider: clarity, specificity, actionability for practitioners, "
        f"relevance to therapy/coaching practice.\n"
        f"Respond with ONLY a number 1-10.\n\n{text[:1000]}"
    )
    return stage1_ollama_score(text, prompt)


def push_to_green(fragments: List[Dict]):
    from common import push_to_green_safe
    push_to_green_safe(
        fragments, domain_default="legal", fallback_name="legal",
        green_push_url=GREEN_PUSH_URL, green_auth_token=GREEN_AUTH_TOKEN or "",
        face_path_prefix="legal",
    )


def harvest_huggingface_legal(tracker: ProgressTracker) -> int:
    """Harvest from HuggingFace legal datasets."""
    try:
        from datasets import load_dataset
    except ImportError:
        print("[LEGAL] pip install datasets required for HF harvest")
        return 0

    total_passed = 0
    push_buffer: List[Dict] = []

    for ds_config in LEGAL_HF_DATASETS:
        ds_name = ds_config["name"]
        subset = ds_config.get("subset")
        source_type = ds_config["source_type"]
        tracker.set_status("current_source", f"{ds_name}:{subset}")
        print(f"\n[LEGAL HF] Loading {ds_name} ({subset})...")

        try:
            if subset:
                dataset = load_dataset(ds_name, subset, streaming=True, trust_remote_code=True)
            else:
                dataset = load_dataset(ds_name, streaming=True, trust_remote_code=True)
        except Exception as e:
            print(f"[LEGAL HF] Failed to load {ds_name}: {e}")
            continue

        split_name = "train" if "train" in dataset else list(dataset.keys())[0]
        count = 0
        max_items = 5000

        for row in dataset[split_name]:
            count += 1
            if count > max_items:
                break

            item_id = f"{source_type}:{count}"
            if tracker.is_done(source_type, item_id):
                continue

            text = str(row.get(ds_config["text_field"], "")).strip()
            if len(text) < 100:
                tracker.mark_done(source_type, item_id, domain="legal", passed=False)
                continue

            fragment_text = f"[Legal Source: {source_type}]\n{text}"[:MAX_FRAGMENT_LEN]

            score = stage1_filter(fragment_text)
            passed = score is not None and score >= STAGE1_THRESHOLD
            tracker.mark_done(source_type, item_id, domain="legal", passed=passed)

            if passed:
                total_passed += 1
                push_buffer.append({
                    "text": fragment_text,
                    "source": f"legal_hf:{source_type}:{count}",
                    "domain": "legal",
                    "scope": "global",
                    "source_type": source_type,
                })

                if len(push_buffer) >= PUSH_BATCH_SIZE:
                    push_to_green(push_buffer)
                    push_buffer.clear()

            if count % 500 == 0:
                print(f"  [{source_type}] {count} processed, {total_passed} passed")

    if push_buffer:
        push_to_green(push_buffer)
    return total_passed


def harvest_federal_register(tracker: ProgressTracker) -> int:
    """Fetch regulatory documents from the Federal Register API."""
    import requests

    total_passed = 0
    push_buffer: List[Dict] = []

    for query_cfg in FEDERAL_REGISTER_QUERIES:
        term = query_cfg["term"]
        item_key = f"fedreg:{term.replace(' ', '_')}"
        if tracker.is_done("federal_register", item_key):
            continue

        tracker.set_status("current_source", f"fedreg:{term}")
        print(f"  [FEDREG] Searching: {term}")

        params = {
            "conditions[term]": term,
            "per_page": 20,
            "order": "relevance",
        }
        if "agency" in query_cfg:
            params["conditions[agencies][]"] = query_cfg["agency"]

        try:
            resp = requests.get(
                "https://www.federalregister.gov/api/v1/documents.json",
                params=params,
                timeout=30,
            )
            if resp.status_code != 200:
                continue

            results = resp.json().get("results", [])
            for doc in results:
                doc_id = str(doc.get("document_number", ""))
                did = f"fedreg:{doc_id}"
                if tracker.is_done("federal_register", did):
                    continue

                title = doc.get("title", "")
                abstract = doc.get("abstract", "")
                body = doc.get("body_html_url", "")

                text = (
                    f"[Federal Register: {term}]\n"
                    f"Title: {title}\n"
                    f"Abstract: {abstract}\n"
                )[:MAX_FRAGMENT_LEN]

                if len(text) < 100:
                    continue

                score = stage1_filter(text)
                passed = score is not None and score >= STAGE1_THRESHOLD
                tracker.mark_done("federal_register", did, domain="legal", passed=passed)

                if passed:
                    total_passed += 1
                    push_buffer.append({
                        "text": text,
                        "source": f"federal_register:{doc_id}",
                        "domain": "legal",
                        "scope": "global",
                        "source_type": "federal_register",
                    })

                    if len(push_buffer) >= PUSH_BATCH_SIZE:
                        push_to_green(push_buffer)
                        push_buffer.clear()

            time.sleep(1)
        except Exception as e:
            print(f"  [FEDREG] Error: {e}")

        tracker.mark_done("federal_register", item_key, domain="legal")

    if push_buffer:
        push_to_green(push_buffer)
    return total_passed


def harvest_caselaw(tracker: ProgressTracker) -> int:
    """Fetch case law from Case Law Access Project (Harvard)."""
    import requests

    total_passed = 0
    push_buffer: List[Dict] = []
    cap_api = "https://api.case.law/v1"

    for query in CASELAW_QUERIES:
        qkey = f"caselaw:{query.replace(' ', '_')}"
        if tracker.is_done("caselaw", qkey):
            continue

        tracker.set_status("current_source", f"caselaw:{query}")
        print(f"  [CASELAW] Searching: {query}")

        try:
            resp = requests.get(
                f"{cap_api}/cases/",
                params={"search": query, "page_size": 20, "ordering": "-decision_date"},
                timeout=30,
            )
            if resp.status_code != 200:
                tracker.mark_done("caselaw", qkey, domain="legal", passed=False)
                continue

            cases = resp.json().get("results", [])
            for case in cases:
                case_id = str(case.get("id", ""))
                cid = f"caselaw:{case_id}"
                if tracker.is_done("caselaw", cid):
                    continue

                name = case.get("name_abbreviation", case.get("name", ""))
                court = case.get("court", {}).get("name", "")
                date = case.get("decision_date", "")

                opinions = case.get("casebody", {}).get("data", {}).get("opinions", [])
                opinion_text = ""
                if opinions:
                    opinion_text = opinions[0].get("text", "")[:1200]

                text = (
                    f"[Case Law: {name}]\n"
                    f"Court: {court}\n"
                    f"Date: {date}\n\n"
                    f"{opinion_text}"
                )[:MAX_FRAGMENT_LEN]

                if len(text) < 150:
                    continue

                score = stage1_filter(text)
                passed = score is not None and score >= STAGE1_THRESHOLD
                tracker.mark_done("caselaw", cid, domain="legal", passed=passed)

                if passed:
                    total_passed += 1
                    push_buffer.append({
                        "text": text,
                        "source": f"caselaw:{case_id}",
                        "domain": "legal",
                        "scope": "global",
                        "source_type": "caselaw",
                    })

                    if len(push_buffer) >= PUSH_BATCH_SIZE:
                        push_to_green(push_buffer)
                        push_buffer.clear()

            time.sleep(1)
        except Exception as e:
            print(f"  [CASELAW] Error: {e}")

        tracker.mark_done("caselaw", qkey, domain="legal")

    if push_buffer:
        push_to_green(push_buffer)
    return total_passed


def harvest_legal():
    tracker = ProgressTracker()
    tracker.set_status("current_phase", "legal")

    hf = harvest_huggingface_legal(tracker)
    fr = harvest_federal_register(tracker)
    cl = harvest_caselaw(tracker)

    tracker.set_status("current_source", "complete")
    tracker.write_status_json()
    print(f"\n[LEGAL] Complete — HF: {hf}, FedReg: {fr}, CaseLaw: {cl}")
    tracker.close()


if __name__ == "__main__":
    harvest_legal()
