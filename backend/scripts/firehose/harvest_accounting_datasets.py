"""
Accounting Dataset Harvester — Phase 4b
Targets GAAP principles, QuickBooks patterns, practice accounting,
tax compliance, and nonprofit financial management for the CPA DOJO.

Target: 1,500–3,000 crystals in accounting domain.
Node: ORANGE (Hetzner) → ships to GREEN.

Sources:
  1. IRS publications (key publications for small business/nonprofit)
  2. FASB Codification excerpts (public summaries)
  3. HuggingFace accounting/finance datasets
  4. QuickBooks knowledge base patterns

Usage:
  python -m backend.scripts.firehose.harvest_accounting_datasets
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

IRS_PUBLICATIONS = [
    {"pub": "334", "title": "Tax Guide for Small Business"},
    {"pub": "535", "title": "Business Expenses"},
    {"pub": "557", "title": "Tax-Exempt Status for Your Organization"},
    {"pub": "583", "title": "Starting a Business and Keeping Records"},
    {"pub": "15", "title": "Employer's Tax Guide"},
    {"pub": "505", "title": "Tax Withholding and Estimated Tax"},
    {"pub": "463", "title": "Travel, Gift, and Car Expenses"},
    {"pub": "946", "title": "How To Depreciate Property"},
    {"pub": "598", "title": "Tax on Unrelated Business Income of Exempt Orgs"},
    {"pub": "1771", "title": "Charitable Contributions Substantiation"},
]

ACCOUNTING_PATTERNS = [
    "Revenue recognition ASC 606 for service businesses",
    "Chart of accounts best practices for therapy practice",
    "QuickBooks class tracking for multi-location practices",
    "Nonprofit fund accounting GAAP requirements",
    "Accrual vs cash basis for professional services",
    "Payroll tax compliance small business",
    "1099 contractor vs W-2 employee classification",
    "Subscription billing revenue recognition SaaS",
    "Tax deduction home office professional services",
    "Quarterly estimated tax calculation self-employed",
    "S-Corp reasonable compensation requirements",
    "Insurance billing reconciliation mental health",
    "Trust accounting requirements for client funds",
    "Financial statement preparation small business",
    "Year-end tax planning for practice owners",
    "Charitable donation receipt requirements 501c3",
    "Cost segregation study for practice real estate",
    "Employee retention credit eligibility criteria",
    "PPP loan forgiveness documentation requirements",
    "Practice valuation methods for acquisition",
]


def stage1_filter(text: str) -> Optional[int]:
    from common import stage1_ollama_score
    prompt = (
        f"Score this accounting/tax fragment 1-10 for value as crystallized "
        f"knowledge for CPA exam prep and practice management.\n"
        f"Consider: accuracy, specificity, GAAP compliance, practical applicability.\n"
        f"Respond with ONLY a number 1-10.\n\n{text[:1000]}"
    )
    return stage1_ollama_score(text, prompt)


def push_to_green(fragments: List[Dict]):
    from common import push_to_green_safe
    push_to_green_safe(
        fragments, domain_default="accounting", fallback_name="accounting",
        green_push_url=GREEN_PUSH_URL, green_auth_token=GREEN_AUTH_TOKEN or "",
        face_path_prefix="accounting",
    )


def harvest_llm_accounting_knowledge(tracker: ProgressTracker) -> int:
    """Use Ollama to generate structured accounting knowledge from patterns."""
    import requests

    total_passed = 0
    push_buffer: List[Dict] = []

    for pattern in ACCOUNTING_PATTERNS:
        item_id = f"pattern:{hashlib.sha256(pattern.encode()).hexdigest()[:16]}"
        if tracker.is_done("acct_patterns", item_id):
            continue

        tracker.set_status("current_source", f"acct_pattern:{pattern[:40]}")

        prompt = (
            f"Write a detailed, authoritative knowledge crystal about: {pattern}\n\n"
            f"Requirements:\n"
            f"1. Be precise and factual — cite specific GAAP standards, IRS "
            f"publications, or regulatory requirements where applicable\n"
            f"2. Include step-by-step procedures where relevant\n"
            f"3. Note common mistakes practitioners make\n"
            f"4. Keep to 200-400 words of dense, actionable content"
        )

        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "system": "You are a CPA and tax advisor with 20 years of experience in practice management. Provide precise, actionable accounting knowledge.",
                    "stream": False,
                },
                timeout=60,
            )
            if resp.status_code != 200:
                continue

            text = resp.json().get("response", "").strip()
            if len(text) < 100:
                tracker.mark_done("acct_patterns", item_id, domain="accounting", passed=False)
                continue

            fragment_text = f"[Accounting Knowledge: {pattern}]\n\n{text}"[:MAX_FRAGMENT_LEN]

            score = stage1_filter(fragment_text)
            passed = score is not None and score >= STAGE1_THRESHOLD
            tracker.mark_done("acct_patterns", item_id, domain="accounting", passed=passed)

            if passed:
                total_passed += 1
                push_buffer.append({
                    "text": fragment_text,
                    "source": f"acct_pattern:{item_id}",
                    "domain": "accounting",
                    "scope": "global",
                    "source_type": "acct_patterns",
                })
                if len(push_buffer) >= PUSH_BATCH_SIZE:
                    push_to_green(push_buffer)
                    push_buffer.clear()

        except Exception as e:
            print(f"  [ACCT] Pattern error: {e}")

    if push_buffer:
        push_to_green(push_buffer)
    return total_passed


def harvest_hf_accounting(tracker: ProgressTracker) -> int:
    try:
        from datasets import load_dataset
    except ImportError:
        return 0

    total_passed = 0
    push_buffer: List[Dict] = []
    ds_name = "virattt/financial-qa-10K"
    source_type = "hf_acct_qa"

    tracker.set_status("current_source", ds_name)
    try:
        dataset = load_dataset(ds_name, trust_remote_code=True)
    except Exception:
        return 0

    split = "train" if "train" in dataset else list(dataset.keys())[0]
    for idx, row in enumerate(dataset[split]):
        if idx > 3000:
            break
        item_id = f"{source_type}:{idx}"
        if tracker.is_done(source_type, item_id):
            continue

        answer = str(row.get("answer", "")).strip()
        question = str(row.get("question", "")).strip()
        text = f"[Financial Q&A]\nQ: {question}\nA: {answer}"[:MAX_FRAGMENT_LEN]

        if len(text) < 100:
            tracker.mark_done(source_type, item_id, domain="accounting", passed=False)
            continue

        score = stage1_filter(text)
        passed = score is not None and score >= STAGE1_THRESHOLD
        tracker.mark_done(source_type, item_id, domain="accounting", passed=passed)

        if passed:
            total_passed += 1
            push_buffer.append({
                "text": text, "source": f"hf_acct:{idx}",
                "domain": "accounting", "scope": "global",
                "source_type": source_type,
            })
            if len(push_buffer) >= PUSH_BATCH_SIZE:
                push_to_green(push_buffer)
                push_buffer.clear()

    if push_buffer:
        push_to_green(push_buffer)
    return total_passed


def harvest_accounting():
    tracker = ProgressTracker()
    tracker.set_status("current_phase", "accounting")

    patterns = harvest_llm_accounting_knowledge(tracker)
    hf = harvest_hf_accounting(tracker)

    tracker.set_status("current_source", "complete")
    tracker.write_status_json()
    print(f"\n[ACCOUNTING] Complete — Patterns: {patterns}, HF: {hf}")
    tracker.close()


if __name__ == "__main__":
    harvest_accounting()
