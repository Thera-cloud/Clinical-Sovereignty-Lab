"""LN7 revision readiness for Dual-COO / CEO promote asks.

# QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_revision_readiness")

_MIN_PACK_TASKS = 3


def _parse_notes_blob(notes: str) -> Dict[str, Any]:
    text = (notes or "").strip()
    if not text:
        return {}
    # Prefer trailing JSON object in notes
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    m = re.search(r"\{[\s\S]*\}\s*$", text)
    if m:
        try:
            parsed = json.loads(m.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _extract_adapter_path(
    harness: Dict[str, Any],
    notes: str,
    notes_json: Dict[str, Any],
) -> str:
    for key in ("adapter_path", "adapter", "lora_path", "peft_adapter"):
        val = harness.get(key) or notes_json.get(key)
        if val:
            return str(val).strip()
    # Free-text path hints
    for pat in (
        r"adapter[_ ]path[=:\s]+(\S+)",
        r"(/opt/ln7/adapters/\S+)",
        r"(\.ln7-adapters/\S+)",
    ):
        m = re.search(pat, notes or "", re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip(")`,'\"")
    return ""


def _extract_peft_url(harness: Dict[str, Any], notes: str, notes_json: Dict[str, Any]) -> str:
    for key in ("peft_url", "serve_url", "openai_base_url"):
        val = harness.get(key) or notes_json.get(key)
        if val:
            return str(val).strip().rstrip("/")
    env = (os.getenv("LN7_PEFT_URL") or "").strip().rstrip("/")
    if env:
        return env
    m = re.search(r"(https?://[^\s]+?:11435)", notes or "")
    if m:
        return m.group(1).rstrip("/")
    m = re.search(r"(http://10\.13\.13\.5:11435)", notes or "")
    if m:
        return m.group(1).rstrip("/")
    return ""


def _model_card_exists(revision_id: str, stored_path: Optional[str] = None) -> bool:
    candidates: List[Path] = []
    if stored_path:
        candidates.append(Path(stored_path))
    try:
        from app.services.little_nate_7 import model_card_path

        rel = model_card_path(revision_id)
        candidates.append(Path(rel))
        candidates.append(Path(__file__).resolve().parents[3] / rel)
    except Exception:
        pass
    name = f"LN7_{revision_id}.md"
    candidates.extend(
        [
            Path(__file__).resolve().parents[3] / "docs" / "ln7" / name,
            Path("/app/data/ln7/model_cards") / name,
            Path("docs/ln7") / name,
        ]
    )
    for p in candidates:
        try:
            if p.is_file() and p.stat().st_size > 20:
                return True
        except OSError:
            continue
    return revision_id == "LN7-baseline"


async def _probe_peft(peft_url: str) -> Dict[str, Any]:
    if not peft_url:
        return {"ok": False, "reason": "no_peft_url"}
    timeout = float(os.getenv("LN7_PEFT_PROBE_TIMEOUT_S", "2.5") or 2.5)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as client:
            for path in ("/health", "/v1/models", "/"):
                try:
                    resp = await client.get(f"{peft_url}{path}")
                    if resp.status_code < 500:
                        return {
                            "ok": True,
                            "status_code": resp.status_code,
                            "path": path,
                        }
                except Exception:
                    continue
        return {"ok": False, "reason": "unreachable"}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)[:120]}


async def assess_revision_readiness(
    db_pool,
    revision_id: str,
    *,
    force_class: Optional[str] = None,
) -> Dict[str, Any]:
    """Best-effort readiness dict. ready=true only when adapter+PEFT+packs+canary gate ok."""
    rid = (revision_id or "").strip()
    checks: Dict[str, Any] = {}
    if not rid:
        return {
            "ready": False,
            "reason": "missing_revision_id",
            "checks": checks,
            "revision_id": rid,
            "readiness_class": "premature",
        }
    if not db_pool:
        return {
            "ready": False,
            "reason": "no_db",
            "checks": {"db": False},
            "revision_id": rid,
            "readiness_class": "premature",
            "status": "unknown",
            "base_checkpoint": "",
            "adapter_path": "",
            "peft_url": "",
        }

    row = None
    pack_n = 0
    pack_passes = 0
    canary_status = ""
    canary_gate: Dict[str, Any] = {}
    train_adapter = ""
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT revision_id, base_checkpoint, quantization, status, active,
                       notes, harness_config_json, model_card_path
                FROM ln7_revisions WHERE revision_id = $1
                """,
                rid,
            )
            pack_n = int(
                await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM ln7_coding_outcomes
                    WHERE revision_id = $1 AND generator = 'ln7'
                      AND (metrics_json->>'pack') IS NOT NULL
                      AND COALESCE(metrics_json->>'invalidated', '') = ''
                    """,
                    rid,
                )
                or 0
            )
            pack_passes = int(
                await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM ln7_coding_outcomes
                    WHERE revision_id = $1 AND generator = 'ln7'
                      AND passed = TRUE
                      AND (metrics_json->>'pack') IS NOT NULL
                      AND COALESCE(metrics_json->>'invalidated', '') = ''
                    """,
                    rid,
                )
                or 0
            )
            canary = await conn.fetchrow(
                "SELECT status, pass_rate_json FROM ln7_canary_state WHERE revision_id = $1",
                rid,
            )
            if canary:
                canary_status = str(canary["status"] or "")
                raw_gate = canary["pass_rate_json"]
                if isinstance(raw_gate, str):
                    try:
                        canary_gate = json.loads(raw_gate)
                    except Exception:
                        canary_gate = {}
                elif isinstance(raw_gate, dict):
                    canary_gate = dict(raw_gate)
            train_adapter = (
                await conn.fetchval(
                    """
                    SELECT adapter_path FROM ln7_train_jobs
                    WHERE revision_id = $1 AND adapter_path IS NOT NULL AND adapter_path != ''
                    ORDER BY id DESC LIMIT 1
                    """,
                    rid,
                )
                or ""
            )
    except Exception as exc:
        logger.warning("ln7 readiness query: %s", exc)
        return {
            "ready": False,
            "reason": f"db_error:{str(exc)[:80]}",
            "checks": checks,
            "revision_id": rid,
            "readiness_class": "premature",
        }

    if not row:
        return {
            "ready": False,
            "reason": "revision_not_found",
            "checks": {"revision_row": False},
            "revision_id": rid,
            "readiness_class": "premature",
        }

    harness = row["harness_config_json"] or {}
    if isinstance(harness, str):
        try:
            harness = json.loads(harness)
        except Exception:
            harness = {}
    if not isinstance(harness, dict):
        harness = {}
    notes = str(row["notes"] or "")
    notes_json = _parse_notes_blob(notes)
    adapter_path = _extract_adapter_path(harness, notes, notes_json) or str(train_adapter or "")
    peft_url = _extract_peft_url(harness, notes, notes_json)
    card_ok = _model_card_exists(rid, str(row["model_card_path"] or "") or None)

    peft_probe = await _probe_peft(peft_url)
    packs_ok = pack_n >= _MIN_PACK_TASKS
    gate_ok = bool(canary_gate.get("ok"))
    gate_reason = str(canary_gate.get("reason") or "")
    canary_blocked = canary_status in ("rolled_back",) or gate_reason in (
        "insufficient_tasks",
        "forgetting_monitor_drift",
    )
    canary_ready = gate_ok and canary_status in ("active", "promoted", "") and not canary_blocked
    # Path-only is NOT enough — need PEFT smoke + packs + canary
    adapter_ok = bool(adapter_path)
    peft_ok = bool(peft_probe.get("ok"))

    checks = {
        "revision_row": True,
        "model_card": card_ok,
        "adapter_path": adapter_ok,
        "adapter_path_value": adapter_path[:200],
        "peft_url": bool(peft_url),
        "peft_url_value": peft_url[:200],
        "peft_probe": peft_ok,
        "peft_probe_detail": peft_probe,
        "private_pack_n": pack_n,
        "private_pack_passes": pack_passes,
        "private_packs_ok": packs_ok,
        "canary_status": canary_status or "none",
        "canary_gate_ok": gate_ok,
        "canary_gate_reason": gate_reason,
        "canary_ready": canary_ready,
        "status": str(row["status"] or ""),
        "active": bool(row["active"]),
        "base_checkpoint": str(row["base_checkpoint"] or ""),
    }

    ready = bool(
        card_ok and adapter_ok and peft_ok and packs_ok and canary_ready and not row["active"]
    )
    if force_class == "ready" and card_ok and adapter_ok and peft_ok and packs_ok and gate_ok:
        ready = True
        checks["force_class"] = "ready"

    if row["active"]:
        reason = "already_active"
        ready = False
    elif not card_ok:
        reason = "model_card_missing"
    elif not adapter_ok:
        reason = "adapter_path_missing"
    elif not peft_ok:
        reason = "peft_unreachable"
    elif not packs_ok:
        reason = "insufficient_private_pack_outcomes"
    elif not canary_ready:
        reason = gate_reason or canary_status or "canary_not_ready"
    else:
        reason = "ready_for_ceo_activate" if ready else "blocked"

    readiness_class = "ready" if ready else "premature"
    return {
        "ready": ready,
        "reason": reason,
        "checks": checks,
        "revision_id": rid,
        "readiness_class": readiness_class,
        "status": str(row["status"] or ""),
        "base_checkpoint": str(row["base_checkpoint"] or ""),
        "adapter_path": adapter_path,
        "peft_url": peft_url,
        "pack_n": pack_n,
        "pack_passes": pack_passes,
        "canary_status": canary_status,
        "canary_gate": canary_gate,
    }


def checklist_one_liner(readiness: Dict[str, Any]) -> str:
    c = readiness.get("checks") or {}
    parts = [
        f"card={'ok' if c.get('model_card') else 'fail'}",
        f"adapter={'ok' if c.get('adapter_path') else 'fail'}",
        f"peft={'ok' if c.get('peft_probe') else 'fail'}",
        f"packs={c.get('private_pack_n', 0)}/{_MIN_PACK_TASKS}",
        f"canary={'ok' if c.get('canary_ready') else c.get('canary_status') or 'none'}",
    ]
    return " · ".join(parts)
