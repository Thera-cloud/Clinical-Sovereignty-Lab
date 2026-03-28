"""
HuggingFace Therapeutic Dataset Harvester — Phase 1
Downloads and extracts fragments from 6 therapeutic conversation datasets.

Target: 8,000–12,000 crystals across clinical + crisis domains.
Node: ORANGE (Hetzner) → ships to GREEN via crystal sync pipeline.

Datasets:
  1. nbertagnolli/counsel-chat         — Licensed counselor Q&A
  2. ShenLab/MentalChat16K             — 16K counseling Q&A pairs
  3. Amod/mental_health_counseling_conversations — MH conversations
  4. IINOVAII/therapy-conversations-combined — Combined therapy dialogues
  5. to-be/annomi-motivational-interviewing-therapy-conversations — Expert MI
  6. Psychotherapy-LLM/PsychoCounsel-Preference — Quality-ranked therapy

Usage:
  pip install datasets
  python harvest_huggingface_therapy.py
  python harvest_huggingface_therapy.py --dataset huggingface_counselchat --limit 5
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

FIREHOSE_DIR = Path(__file__).parent
sys.path.insert(0, str(FIREHOSE_DIR))
from progress_tracker import ProgressTracker

STAGE1_SCORE_THRESHOLD = 6
MAX_FRAGMENT_LEN = 2000
GREEN_PUSH_URL = os.getenv("GREEN_PUSH_URL", "http://localhost:8000/api/nate-agent/admin/crystal-network/push")
GREEN_AUTH_TOKEN = os.getenv("GREEN_AUTH_TOKEN", "")

THERAPY_DATASETS = [
    {
        "name": "nbertagnolli/counsel-chat",
        "domain": "clinical",
        "text_fields": [("answerText",)],
        "context_fields": [("questionTitle", "questionText")],
        "source_type": "huggingface_counselchat",
    },
    {
        "name": "ShenLab/MentalChat16K",
        "domain": "clinical",
        "text_fields": [("output",)],
        "context_fields": [("input",)],
        "source_type": "huggingface_mentalchat16k",
    },
    {
        "name": "Amod/mental_health_counseling_conversations",
        "domain": "clinical",
        "text_fields": [("Response",)],
        "context_fields": [("Context",)],
        "source_type": "huggingface_amod_mh",
    },
    {
        "name": "IINOVAII/therapy-conversations-combined",
        "domain": "clinical",
        "text_fields": [("text",)],
        "context_fields": [],
        "source_type": "huggingface_iinovaii",
    },
    {
        "name": "to-be/annomi-motivational-interviewing-therapy-conversations",
        "domain": "clinical",
        "text_fields": [],
        "context_fields": [],
        "source_type": "huggingface_annomi",
        "sharegpt": True,
    },
    {
        "name": "Psychotherapy-LLM/PsychoCounsel-Preference",
        "domain": "clinical",
        "text_fields": [("chosen",)],
        "context_fields": [("question",)],
        "source_type": "huggingface_psychocounsel",
    },
]


def build_fragment_text(row: dict, config: dict) -> str:
    if config.get("sharegpt"):
        convos = row.get("conversations", [])
        parts = []
        for turn in convos:
            role = "Therapist" if turn.get("from") == "gpt" else "Client"
            parts.append(f"{role}: {turn.get('value', '')}")
        text = "\n".join(parts)
        return text[:MAX_FRAGMENT_LEN] if text else ""

    parts = []
    for field_group in config.get("context_fields", []):
        if isinstance(field_group, tuple):
            for f in field_group:
                val = row.get(f, "")
                if val:
                    parts.append(str(val).strip())
        elif isinstance(field_group, str):
            val = row.get(field_group, "")
            if val:
                parts.append(str(val).strip())

    for field_group in config.get("text_fields", []):
        if isinstance(field_group, tuple):
            for f in field_group:
                val = row.get(f, "")
                if val:
                    parts.append(str(val).strip())
        elif isinstance(field_group, str):
            val = row.get(field_group, "")
            if val:
                parts.append(str(val).strip())

    text = "\n\n".join(parts)
    return text[:MAX_FRAGMENT_LEN] if text else ""


def stage1_filter(text: str, domain: str) -> Optional[int]:
    """Score fragment via Ollama 8B. Returns score 1-10 or None on failure."""
    from common import stage1_ollama_score
    prompt = (
        f"Score this fragment 1-10 for value as crystallized knowledge "
        f"in the domain of {domain}. Consider:\n"
        f"- Specificity (concrete patterns > vague principles)\n"
        f"- Actionability (problem+solution > theory alone)\n"
        f"- Relevance to professional coaching/counseling context\n"
        f"Respond with ONLY a number 1-10.\n\n"
        f"Fragment:\n{text[:1000]}"
    )
    return stage1_ollama_score(text, prompt)


def push_to_green(fragments: List[Dict]):
    """Ship Stage-1-passed fragments to GREEN production."""
    from common import push_to_green_safe
    push_to_green_safe(
        fragments, domain_default="clinical", fallback_name="therapy",
        green_push_url=GREEN_PUSH_URL, green_auth_token=GREEN_AUTH_TOKEN or "",
        face_path_prefix="therapy",
    )


def harvest_therapy(dataset_filter: Optional[str] = None, limit: Optional[int] = None):
    tracker = ProgressTracker()
    tracker.set_status("current_phase", "therapy")

    try:
        from datasets import load_dataset
    except ImportError:
        print("[THERAPY] pip install datasets required")
        return

    total_passed = 0
    push_buffer: List[Dict] = []
    PUSH_BATCH_SIZE = 50

    active_datasets = THERAPY_DATASETS
    if dataset_filter:
        active_datasets = [d for d in THERAPY_DATASETS if d["source_type"] == dataset_filter]
        if not active_datasets:
            print(f"[THERAPY] No dataset matching source_type '{dataset_filter}'")
            print(f"  Available: {', '.join(d['source_type'] for d in THERAPY_DATASETS)}")
            return

    for ds_config in active_datasets:
        ds_name = ds_config["name"]
        tracker.set_status("current_source", ds_name)
        print(f"\n[THERAPY] Processing {ds_name}...")

        try:
            dataset = load_dataset(ds_name)
        except Exception as e:
            print(f"[THERAPY] Failed to load {ds_name}: {e}")
            continue

        split_name = "train" if "train" in dataset else list(dataset.keys())[0]
        split_data = dataset[split_name]

        processed_this_ds = 0
        for idx, row in enumerate(split_data):
            if limit is not None and processed_this_ds >= limit:
                print(f"  [{ds_name}] reached limit of {limit} records")
                break

            item_id = f"{ds_name}:{idx}"
            if tracker.is_done(ds_config["source_type"], item_id):
                continue

            processed_this_ds += 1
            text = build_fragment_text(row, ds_config)
            if len(text) < 50:
                tracker.mark_done(ds_config["source_type"], item_id,
                                  domain=ds_config["domain"], passed=False)
                continue

            score = stage1_filter(text, ds_config["domain"])
            passed = score is not None and score >= STAGE1_SCORE_THRESHOLD

            tracker.mark_done(ds_config["source_type"], item_id,
                              domain=ds_config["domain"], passed=passed)

            if passed:
                total_passed += 1
                push_buffer.append({
                    "text": text,
                    "source": f"huggingface:{ds_name}:{idx}",
                    "domain": ds_config["domain"],
                    "scope": "global",
                    "source_type": ds_config["source_type"],
                    "quality_score": score,
                })

                if len(push_buffer) >= PUSH_BATCH_SIZE:
                    push_to_green(push_buffer)
                    push_buffer.clear()

            if idx % 500 == 0 and idx > 0:
                print(f"  [{ds_name}] processed {idx}, passed {total_passed}")
                tracker.write_status_json()

    if push_buffer:
        push_to_green(push_buffer)

    tracker.set_status("current_source", "complete")
    tracker.write_status_json()
    print(f"\n[THERAPY] Complete — {total_passed} fragments passed Stage 1")
    tracker.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HuggingFace Therapeutic Dataset Harvester")
    parser.add_argument("--dataset", type=str, default=None,
                        help="Run only this dataset source_type (e.g. huggingface_counselchat)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max records to process per dataset")
    args = parser.parse_args()
    harvest_therapy(dataset_filter=args.dataset, limit=args.limit)
