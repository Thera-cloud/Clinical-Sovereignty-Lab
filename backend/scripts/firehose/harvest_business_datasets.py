"""
Business & Entrepreneurship Dataset Harvester — Phase 4a
Targets business strategy, startup operations, SaaS metrics, and
practice management for the Entrepreneur DOJO.

Target: 2,000–4,000 crystals in business domain.
Node: ORANGE (Hetzner) → ships to GREEN.

Sources:
  1. SEC EDGAR company filings (10-K management discussion excerpts)
  2. YCombinator/Startup School open resources
  3. HuggingFace business datasets
  4. SBA.gov small business resources

Usage:
  python -m backend.scripts.firehose.harvest_business_datasets
"""

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

GREEN_PUSH_URL = os.getenv("GREEN_PUSH_URL", "http://localhost:8000/api/admin/crystal-network/push")
GREEN_AUTH_TOKEN = os.getenv("GREEN_AUTH_TOKEN", "")

MAX_FRAGMENT_LEN = 2000
STAGE1_THRESHOLD = 6
PUSH_BATCH_SIZE = 50

SBA_TOPICS = [
    "starting-managing/starting-business",
    "starting-managing/managing-business",
    "funding-financing",
    "marketing-sales",
    "business-operations",
]

BUSINESS_HF_DATASETS = [
    {
        "name": "virattt/financial-qa-10K",
        "domain": "business",
        "text_field": "answer",
        "context_field": "question",
        "source_type": "hf_financial_qa",
    },
]

SEC_SECTORS = [
    "Healthcare", "Technology", "Services",
]


def stage1_filter(text: str) -> Optional[int]:
    from common import stage1_ollama_score
    prompt = (
        f"Score this business/entrepreneurship fragment 1-10 for value as "
        f"crystallized knowledge for practice owners and entrepreneurs.\n"
        f"Consider: actionability, specificity, relevance to small business "
        f"or professional practice management.\n"
        f"Respond with ONLY a number 1-10.\n\n{text[:1000]}"
    )
    return stage1_ollama_score(text, prompt)


def push_to_green(fragments: List[Dict]):
    from common import push_to_green_safe
    push_to_green_safe(
        fragments, domain_default="business", fallback_name="business",
        green_push_url=GREEN_PUSH_URL, green_auth_token=GREEN_AUTH_TOKEN or "",
        face_path_prefix="business",
    )


def harvest_hf_business(tracker: ProgressTracker) -> int:
    try:
        from datasets import load_dataset
    except ImportError:
        return 0

    total_passed = 0
    push_buffer: List[Dict] = []

    for ds in BUSINESS_HF_DATASETS:
        name = ds["name"]
        tracker.set_status("current_source", name)
        print(f"\n[BIZ HF] Loading {name}...")
        try:
            dataset = load_dataset(name, trust_remote_code=True)
        except Exception as e:
            print(f"[BIZ HF] Failed: {e}")
            continue

        split = "train" if "train" in dataset else list(dataset.keys())[0]
        for idx, row in enumerate(dataset[split]):
            item_id = f"{ds['source_type']}:{idx}"
            if tracker.is_done(ds["source_type"], item_id):
                continue

            answer = str(row.get(ds["text_field"], "")).strip()
            question = str(row.get(ds.get("context_field", ""), "")).strip()

            text = f"[Business Q&A]\nQ: {question}\nA: {answer}"[:MAX_FRAGMENT_LEN]
            if len(text) < 80:
                tracker.mark_done(ds["source_type"], item_id, domain="business", passed=False)
                continue

            score = stage1_filter(text)
            passed = score is not None and score >= STAGE1_THRESHOLD
            tracker.mark_done(ds["source_type"], item_id, domain="business", passed=passed)

            if passed:
                total_passed += 1
                push_buffer.append({
                    "text": text, "source": f"hf_biz:{name}:{idx}",
                    "domain": "business", "scope": "global",
                    "source_type": ds["source_type"],
                })
                if len(push_buffer) >= PUSH_BATCH_SIZE:
                    push_to_green(push_buffer)
                    push_buffer.clear()

            if idx > 5000:
                break

    if push_buffer:
        push_to_green(push_buffer)
    return total_passed


def harvest_sec_edgar(tracker: ProgressTracker) -> int:
    """Fetch 10-K MD&A sections from SEC EDGAR full-text search."""
    import requests

    total_passed = 0
    push_buffer: List[Dict] = []

    for sector in SEC_SECTORS:
        if tracker.is_done("sec_edgar", f"sector:{sector}"):
            continue

        tracker.set_status("current_source", f"sec_edgar:{sector}")
        print(f"  [SEC] Searching sector: {sector}")

        try:
            resp = requests.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={
                    "q": f"{sector} management discussion analysis",
                    "dateRange": "custom",
                    "startdt": "2023-01-01",
                    "enddt": "2026-01-01",
                    "forms": "10-K",
                },
                headers={"User-Agent": "SovereignSanctuary research@sovereignsanctuary.net"},
                timeout=30,
            )
            if resp.status_code != 200:
                continue

            hits = resp.json().get("hits", {}).get("hits", [])
            for hit in hits[:30]:
                doc_id = hit.get("_id", "")
                did = f"sec:{doc_id}"
                if tracker.is_done("sec_edgar", did):
                    continue

                source = hit.get("_source", {})
                company = source.get("display_names", ["Unknown"])[0] if source.get("display_names") else "Unknown"
                text_content = source.get("file_description", "")

                text = f"[SEC 10-K: {company}]\n{text_content}"[:MAX_FRAGMENT_LEN]
                if len(text) < 120:
                    continue

                score = stage1_filter(text)
                passed = score is not None and score >= STAGE1_THRESHOLD
                tracker.mark_done("sec_edgar", did, domain="business", passed=passed)

                if passed:
                    total_passed += 1
                    push_buffer.append({
                        "text": text, "source": f"sec_edgar:{doc_id}",
                        "domain": "business", "scope": "global",
                        "source_type": "sec_edgar",
                    })
                    if len(push_buffer) >= PUSH_BATCH_SIZE:
                        push_to_green(push_buffer)
                        push_buffer.clear()

            time.sleep(1)
        except Exception as e:
            print(f"  [SEC] Error: {e}")

        tracker.mark_done("sec_edgar", f"sector:{sector}", domain="business")

    if push_buffer:
        push_to_green(push_buffer)
    return total_passed


def harvest_business():
    tracker = ProgressTracker()
    tracker.set_status("current_phase", "business")

    hf = harvest_hf_business(tracker)
    sec = harvest_sec_edgar(tracker)

    tracker.set_status("current_source", "complete")
    tracker.write_status_json()
    print(f"\n[BUSINESS] Complete — HF: {hf}, SEC: {sec}")
    tracker.close()


if __name__ == "__main__":
    harvest_business()
