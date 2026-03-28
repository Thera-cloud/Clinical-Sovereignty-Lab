"""
Stack Overflow Data Dump Harvester — Phase 2b
Processes the official SO data dump (XML) OR falls back to API for
high-score answers in targeted tags.

Target: 4,000–8,000 crystals in coding domain.
Node: ORANGE (Hetzner) → ships to GREEN.

Data dump: download Posts.xml from archive.org/details/stackexchange
Fallback: uses SO public API (rate limited, 300 requests/day without key).

Usage:
  # With data dump:
  STACKOVERFLOW_DUMP_PATH=/data/stackoverflow/Posts.xml python -m backend.scripts.firehose.harvest_stackoverflow_dump
  # API fallback:
  python -m backend.scripts.firehose.harvest_stackoverflow_dump
"""

import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

FIREHOSE_DIR = Path(__file__).parent
sys.path.insert(0, str(FIREHOSE_DIR))
from progress_tracker import ProgressTracker

GREEN_PUSH_URL = os.getenv("GREEN_PUSH_URL", "http://localhost:8000/api/admin/crystal-network/push")
GREEN_AUTH_TOKEN = os.getenv("GREEN_AUTH_TOKEN", "")
SO_API_KEY = os.getenv("SO_API_KEY", "")
SO_DUMP_PATH = os.getenv("STACKOVERFLOW_DUMP_PATH", "")

MAX_FRAGMENT_LEN = 2000
STAGE1_THRESHOLD = 6
PUSH_BATCH_SIZE = 50

TARGET_TAGS = [
    "python", "fastapi", "asyncio", "postgresql", "redis",
    "docker", "kubernetes", "websocket", "security",
    "machine-learning", "pytorch", "transformers",
    "flutter", "dart", "react", "typescript",
    "cloudflare-workers", "wasm", "rust",
    "nginx", "ssl", "cors", "oauth-2.0",
    "stripe-payments", "twilio",
]


def clean_html_body(body: str) -> str:
    text = html.unescape(body)
    text = re.sub(r"<code>(.+?)</code>", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"<pre>(.+?)</pre>", r"\n```\n\1\n```\n", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def harvest_from_dump(tracker: ProgressTracker) -> int:
    """Parse Posts.xml from the official SO data dump."""
    if not SO_DUMP_PATH or not os.path.exists(SO_DUMP_PATH):
        return 0

    print(f"[SO DUMP] Parsing {SO_DUMP_PATH} ...")
    total_passed = 0
    push_buffer: List[Dict] = []

    for event, elem in ET.iterparse(SO_DUMP_PATH, events=("end",)):
        if elem.tag != "row":
            continue

        post_type = elem.get("PostTypeId", "")
        score = int(elem.get("Score", "0"))

        if post_type != "2" or score < 10:
            elem.clear()
            continue

        post_id = elem.get("Id", "")
        item_id = f"dump:{post_id}"
        if tracker.is_done("so_dump", item_id):
            elem.clear()
            continue

        body = elem.get("Body", "")
        tags = elem.get("Tags", "")
        parent_id = elem.get("ParentId", "")

        text = clean_html_body(body)
        if len(text) < 80:
            tracker.mark_done("so_dump", item_id, domain="coding", passed=False)
            elem.clear()
            continue

        tag_str = tags.replace("<", " ").replace(">", " ").strip()
        fragment_text = (
            f"[Stack Overflow Answer (score: {score})]\n"
            f"Tags: {tag_str}\n\n"
            f"{text}"
        )[:MAX_FRAGMENT_LEN]

        s1 = stage1_filter(fragment_text)
        passed = s1 is not None and s1 >= STAGE1_THRESHOLD
        tracker.mark_done("so_dump", item_id, domain="coding", passed=passed)

        if passed:
            total_passed += 1
            push_buffer.append({
                "text": fragment_text,
                "source": f"stackoverflow:dump:{post_id}",
                "domain": "coding",
                "scope": "global",
                "quality_score": s1,
                "source_type": "so_dump",
            })

            if len(push_buffer) >= PUSH_BATCH_SIZE:
                push_to_green(push_buffer)
                push_buffer.clear()

        elem.clear()

        if total_passed % 100 == 0 and total_passed > 0:
            print(f"  [SO DUMP] {total_passed} fragments passed")
            tracker.write_status_json()

    if push_buffer:
        push_to_green(push_buffer)

    return total_passed


def harvest_from_api(tracker: ProgressTracker) -> int:
    """Fall back to SO public API for high-score answers."""
    import requests

    total_passed = 0
    push_buffer: List[Dict] = []

    for tag in TARGET_TAGS:
        if tracker.is_done("so_api", f"tag:{tag}"):
            continue

        tracker.set_status("current_source", f"so_api:{tag}")
        print(f"  [SO API] Fetching tag: {tag}")

        page = 1
        tag_passed = 0
        while page <= 5:
            params = {
                "order": "desc",
                "sort": "votes",
                "tagged": tag,
                "filter": "withbody",
                "pagesize": 100,
                "page": page,
                "site": "stackoverflow",
            }
            if SO_API_KEY:
                params["key"] = SO_API_KEY

            try:
                resp = requests.get(
                    "https://api.stackexchange.com/2.3/questions",
                    params=params,
                    timeout=30,
                )
                if resp.status_code != 200:
                    break

                data = resp.json()
                questions = data.get("items", [])
                if not questions:
                    break

                for q in questions:
                    if not q.get("is_answered"):
                        continue

                    q_id = str(q.get("question_id", ""))
                    item_id = f"api:{q_id}"
                    if tracker.is_done("so_api", item_id):
                        continue

                    q_title = q.get("title", "")
                    q_tags = ", ".join(q.get("tags", []))

                    a_resp = requests.get(
                        f"https://api.stackexchange.com/2.3/questions/{q_id}/answers",
                        params={
                            "order": "desc", "sort": "votes",
                            "filter": "withbody", "site": "stackoverflow",
                            **({"key": SO_API_KEY} if SO_API_KEY else {}),
                        },
                        timeout=30,
                    )
                    if a_resp.status_code != 200:
                        continue

                    answers = a_resp.json().get("items", [])
                    for ans in answers[:2]:
                        a_score = ans.get("score", 0)
                        if a_score < 5:
                            continue

                        body = clean_html_body(ans.get("body", ""))
                        if len(body) < 80:
                            continue

                        text = (
                            f"[Stack Overflow Q&A (score: {a_score})]\n"
                            f"Q: {q_title}\n"
                            f"Tags: {q_tags}\n\n"
                            f"A: {body}"
                        )[:MAX_FRAGMENT_LEN]

                        s1 = stage1_filter(text)
                        passed = s1 is not None and s1 >= STAGE1_THRESHOLD
                        a_item = f"api:{q_id}:{ans.get('answer_id', '')}"
                        tracker.mark_done("so_api", a_item, domain="coding", passed=passed)

                        if passed:
                            total_passed += 1
                            tag_passed += 1
                            push_buffer.append({
                                "text": text,
                                "source": f"stackoverflow:api:{q_id}",
                                "domain": "coding",
                                "scope": "global",
                                "quality_score": s1,
                                "source_type": "so_api",
                            })

                            if len(push_buffer) >= PUSH_BATCH_SIZE:
                                push_to_green(push_buffer)
                                push_buffer.clear()

                    time.sleep(0.5)

                if data.get("has_more") is False:
                    break
                page += 1
                time.sleep(1)

            except Exception as e:
                print(f"  [SO API] Error on tag {tag}: {e}")
                break

        tracker.mark_done("so_api", f"tag:{tag}", domain="coding")
        print(f"  [SO API] tag={tag}: {tag_passed} passed")

    if push_buffer:
        push_to_green(push_buffer)

    return total_passed


def stage1_filter(text: str) -> Optional[int]:
    from common import stage1_ollama_score
    prompt = (
        f"Score this code Q&A fragment 1-10 for value as crystallized knowledge.\n"
        f"Consider: specificity, pattern reusability, debug insight, security.\n"
        f"Respond with ONLY a number 1-10.\n\n{text[:1000]}"
    )
    return stage1_ollama_score(text, prompt)


def push_to_green(fragments: List[Dict]):
    from common import push_to_green_safe
    push_to_green_safe(
        fragments, domain_default="coding", fallback_name="stackoverflow",
        green_push_url=GREEN_PUSH_URL, green_auth_token=GREEN_AUTH_TOKEN or "",
        face_path_prefix="stackoverflow",
    )


def harvest_stackoverflow():
    tracker = ProgressTracker()
    tracker.set_status("current_phase", "stackoverflow")

    dump_count = harvest_from_dump(tracker)
    api_count = harvest_from_api(tracker)

    tracker.set_status("current_source", "complete")
    tracker.write_status_json()
    print(f"\n[SO] Complete — dump: {dump_count}, api: {api_count}")
    tracker.close()


if __name__ == "__main__":
    harvest_stackoverflow()
