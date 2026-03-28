"""Shared utilities for all firehose harvest scripts.

Provides:
- stage1_filter_with_retry(): Ollama scoring with configurable retries
- push_to_green_safe(): GREEN push with JSONL fallback on failure
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

FIREHOSE_DIR = Path(os.environ.get("FIREHOSE_DATA_DIR", "")).resolve() if os.environ.get("FIREHOSE_DATA_DIR") else Path(__file__).resolve().parent / "data"
FIREHOSE_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct-q4_K_M")


def stage1_ollama_score(
    text: str,
    prompt_template: str,
    *,
    max_retries: int = 2,
    timeout: int = 30,
) -> Optional[int]:
    """Score a fragment via Ollama with retry on transient failures.

    Args:
        text: Fragment text (truncated to 1000 chars for prompt)
        prompt_template: Full prompt string (must include the fragment text)
        max_retries: Number of retry attempts (default 2 = up to 3 total)
        timeout: HTTP timeout per attempt
    """
    import requests

    for attempt in range(1 + max_retries):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt_template, "stream": False},
                timeout=timeout,
            )
            if resp.status_code == 200:
                answer = resp.json().get("response", "").strip()
                for token in answer.split():
                    try:
                        s = int(token)
                        if 1 <= s <= 10:
                            return s
                    except ValueError:
                        continue
                return None
            if resp.status_code >= 500 and attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            return None
        except (requests.ConnectionError, requests.Timeout):
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            return None
        except Exception:
            return None
    return None


def push_to_green_safe(
    fragments: List[Dict],
    *,
    domain_default: str = "general",
    fallback_name: str = "fragments",
    green_push_url: str = "",
    green_auth_token: str = "",
    face_path_prefix: str = "firehose",
):
    """Push crystals to GREEN with JSONL fallback on any failure.

    On success, also drains any pending JSONL buffer from previous failures.
    If the push fails (network error, 4xx, 5xx), fragments are written
    to a local JSONL file so they can be retried later.
    """
    import requests as _requests

    crystals = []
    for f in fragments:
        crystals.append({
            "crystal_text": f["text"],
            "domain": f.get("domain", domain_default),
            "confidence": 0.60,
            "content_hash": hashlib.sha256(f["text"].encode()).hexdigest(),
            "face_path": f"firehose:{f.get('source_type', face_path_prefix)}",
            "scope": "global",
        })

    if not green_auth_token or not green_push_url:
        _write_jsonl_fallback(crystals, fallback_name, "no_token")
        return

    try:
        resp = _requests.post(
            green_push_url,
            json={"crystals": crystals, "node_id": "ORANGE_hetzner"},
            headers={"Authorization": f"Bearer {green_auth_token}"},
            timeout=60,
        )
        if resp.status_code in (200, 201):
            print(f"[{fallback_name.upper()}] Pushed {len(crystals)} crystals to GREEN: {resp.status_code}")
            _retry_jsonl_buffer(fallback_name, green_push_url, green_auth_token)
        else:
            print(f"[{fallback_name.upper()}] GREEN push returned {resp.status_code} — saving to JSONL fallback")
            _write_jsonl_fallback(crystals, fallback_name, f"http_{resp.status_code}")
    except Exception as e:
        print(f"[{fallback_name.upper()}] GREEN push failed ({e}) — saving to JSONL fallback")
        _write_jsonl_fallback(crystals, fallback_name, str(type(e).__name__))


def _retry_jsonl_buffer(name: str, green_push_url: str, green_auth_token: str):
    """Drain any pending JSONL buffer from previous push failures."""
    import requests as _requests

    buf_path = FIREHOSE_DIR / f"{name}_buffer.jsonl"
    if not buf_path.exists() or buf_path.stat().st_size == 0:
        return

    try:
        pending: List[Dict] = []
        with open(buf_path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    pending.append(json.loads(line))

        if not pending:
            buf_path.unlink(missing_ok=True)
            return

        batch_size = 50
        shipped = 0
        failed_crystals: List[Dict] = []

        for i in range(0, len(pending), batch_size):
            batch = pending[i:i + batch_size]
            try:
                resp = _requests.post(
                    green_push_url,
                    json={"crystals": batch, "node_id": "ORANGE_hetzner"},
                    headers={"Authorization": f"Bearer {green_auth_token}"},
                    timeout=60,
                )
                if resp.status_code in (200, 201):
                    shipped += len(batch)
                else:
                    failed_crystals.extend(batch)
                    break
            except Exception:
                failed_crystals.extend(batch)
                failed_crystals.extend(pending[i + batch_size:])
                break

        if failed_crystals:
            with open(buf_path, "w") as fh:
                for c in failed_crystals:
                    fh.write(json.dumps(c) + "\n")
            print(f"[{name.upper()}] JSONL retry: shipped {shipped}, {len(failed_crystals)} still pending")
        else:
            buf_path.unlink(missing_ok=True)
            print(f"[{name.upper()}] JSONL retry: drained all {shipped} buffered crystals")
    except Exception as e:
        print(f"[{name.upper()}] JSONL retry failed: {e}")


def _write_jsonl_fallback(crystals: List[Dict], name: str, reason: str):
    out = FIREHOSE_DIR / f"{name}_buffer.jsonl"
    with open(out, "a") as fh:
        for c in crystals:
            fh.write(json.dumps(c) + "\n")
    print(f"[{name.upper()}] Buffered {len(crystals)} crystals to {out} (reason: {reason})")
