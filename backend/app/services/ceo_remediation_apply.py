"""CEO APPROVE → allowlisted remediations + smoke + Dual-COO/LLM reflect.

Phase A kinds: ln7_fuel_volume_burst, trust_reprobe
Phase B: post-run smoke, Queens fact report, fallback LLM reflection

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nate.ceo_remediation_apply")

FUEL_BURST_COOLDOWN_S = 12 * 3600
FUEL_BURST_DEFAULT_LIMIT = 0  # all non-heldout packs

# Label (Trust Enforcer) → (app.state attr, activity type for latest score)
AUDITOR_REPROBE_MAP: Dict[str, Tuple[str, str]] = {
    "Defense Health": ("defense_auditor", "defense_audit_sent"),
    "AI Pipeline": ("ai_pipeline_auditor", "ai_pipeline_audit_sent"),
    "Hardware Security": ("hw_security_auditor", "hw_security_audit_sent"),
    "System Integrity": ("system_integrity_auditor", "system_integrity_audit_sent"),
    "WebSocket Flows": ("ws_flow_auditor", "ws_flow_audit_sent"),
    "Tier Gating": ("tier_gating_auditor", "tier_gating_audit_sent"),
    "SkyEye Dashboard": ("skyeye_tab_auditor", "skyeye_tab_audit_sent"),
    "Sovereign Command": ("command_tab_auditor", "command_tab_audit_sent"),
    "Billing Pipeline": ("billing_auditor", "billing_audit_sent"),
    "Coach & DOJO": ("coach_dojo_auditor", "coach_dojo_audit_sent"),
    "Token Lab": ("token_lab_auditor", "token_lab_audit_sent"),
    "QuickBooks Sync": ("quickbooks_auditor", "quickbooks_audit_sent"),
    "CEO Dual-COO": ("ceo_dual_coo_auditor", "ceo_dual_coo_audit_sent"),
}


def _resolve_app_state():
    try:
        import app.main as main_mod

        app = getattr(main_mod, "app", None)
        return getattr(app, "state", None) if app is not None else None
    except Exception:
        return None


def _redis():
    try:
        from app.websocket.cli_dual_coo import _redis as _r

        return _r()
    except Exception:
        return None


def _env_prefix() -> str:
    env = (os.getenv("ENVIRONMENT") or "production").strip() or "production"
    return f"nate:{env}:ceo_remediation"


async def apply_ceo_remediation(
    db_pool,
    payload: Dict[str, Any],
    *,
    approved_by: str = "ceo",
) -> Dict[str, Any]:
    """Dispatch allowlisted remediation, then Phase B smoke + reflect."""
    kind = str((payload or {}).get("kind") or "").strip()
    if kind not in ("ln7_fuel_volume_burst", "trust_reprobe"):
        return {"ok": False, "skipped": True, "reason": "not_remediation_kind"}

    exec_result: Dict[str, Any]
    if kind == "ln7_fuel_volume_burst":
        exec_result = await _run_fuel_burst(db_pool, payload, approved_by=approved_by)
    else:
        exec_result = await _run_trust_reprobe(db_pool, payload, approved_by=approved_by)

    smoke = await _collect_smoke(db_pool, kind=kind, exec_result=exec_result)
    queens = _queens_fact_report(kind=kind, exec_result=exec_result, smoke=smoke)
    llm = await _fallback_llm_reflect(queens)

    report = {
        "ok": bool(exec_result.get("ok")),
        "kind": kind,
        "approved_by": approved_by,
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "execution": exec_result,
        "smoke": smoke,
        "queens_report": queens,
        "llm_reflection": llm,
        "summary_text": _format_report_email(kind, exec_result, smoke, queens, llm),
    }
    await _log_remediation(db_pool, report)
    return report


async def _run_fuel_burst(
    db_pool, payload: Dict[str, Any], *, approved_by: str
) -> Dict[str, Any]:
    c = _redis()
    cooldown_key = f"{_env_prefix()}:fuel_burst"
    if c:
        try:
            if c.get(cooldown_key):
                return {
                    "ok": False,
                    "skipped": True,
                    "reason": "cooldown_12h",
                    "detail": "Fuel volume burst already ran within 12h — inbox cleared, no re-run.",
                }
        except Exception as e:
            logger.debug("fuel cooldown check: %s", e)

    apply = payload.get("apply") if isinstance(payload.get("apply"), dict) else {}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    volume = str(apply.get("volume") or f"ceo_{stamp}")[:40]
    limit = int(apply.get("limit") if apply.get("limit") is not None else FUEL_BURST_DEFAULT_LIMIT)
    digest = bool(apply.get("digest", True))

    from app.services.ln7_fuel_volume import run_fuel_volume_burst

    out = await run_fuel_volume_burst(
        db_pool, volume=volume, limit=limit, digest=digest
    )
    out["approved_by"] = approved_by
    out["domain_hint"] = payload.get("domain") or "coding"
    if out.get("ok") and c:
        try:
            c.setex(cooldown_key, FUEL_BURST_COOLDOWN_S, volume)
        except Exception as e:
            logger.debug("fuel cooldown set: %s", e)
    return out


async def _run_trust_reprobe(
    db_pool, payload: Dict[str, Any], *, approved_by: str
) -> Dict[str, Any]:
    auditor = str(payload.get("auditor") or "").strip()
    category = str(payload.get("category") or "").strip()
    state = _resolve_app_state()
    mapping = AUDITOR_REPROBE_MAP.get(auditor)
    if not mapping:
        # Fuzzy: title fragment
        for label, m in AUDITOR_REPROBE_MAP.items():
            if label.lower() in auditor.lower() or auditor.lower() in label.lower():
                mapping = m
                auditor = label
                break
    if not mapping:
        return {
            "ok": False,
            "skipped": True,
            "reason": "auditor_not_mapped",
            "auditor": auditor,
            "detail": "No reprobe handler for this auditor — acknowledge only; fix via ops.",
        }
    attr, activity_type = mapping
    inst = getattr(state, attr, None) if state is not None else None
    if inst is None:
        return {
            "ok": False,
            "skipped": True,
            "reason": "auditor_not_running",
            "auditor": auditor,
            "attr": attr,
        }

    trusted = total = None
    results_summary: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    try:
        # Prefer _build_and_send (single audit + skyeye_activity) — avoid double _audit_all
        if hasattr(inst, "_build_and_send"):
            try:
                await inst._build_and_send(now)
            except TypeError:
                await inst._build_and_send()
            if db_pool:
                async with db_pool.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT content FROM skyeye_activity
                        WHERE type = $1
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        activity_type,
                    )
                    if row and row["content"]:
                        m = re.search(r"(\d+)\s*/\s*(\d+)\s*TRUSTED", str(row["content"]))
                        if m:
                            trusted, total = int(m.group(1)), int(m.group(2))
        elif hasattr(inst, "_audit_all"):
            results = await inst._audit_all()
            if isinstance(results, list):
                total = len(results)
                trusted = sum(
                    1 for r in results if str((r or {}).get("status") or "") == "TRUSTED"
                )
                results_summary = [
                    {
                        "name": (r or {}).get("name") or (r or {}).get("check") or "?",
                        "status": (r or {}).get("status"),
                    }
                    for r in results[:20]
                    if (r or {}).get("status") != "TRUSTED"
                ]
        else:
            return {
                "ok": False,
                "skipped": True,
                "reason": "no_reprobe_method",
                "auditor": auditor,
            }
    except Exception as e:
        logger.warning("trust_reprobe %s failed: %s", auditor, e)
        return {
            "ok": False,
            "auditor": auditor,
            "category": category,
            "error": str(e)[:300],
        }

    return {
        "ok": True,
        "auditor": auditor,
        "category": category,
        "activity_type": activity_type,
        "trusted": trusted,
        "total": total,
        "failures": results_summary,
        "approved_by": approved_by,
        "note": "Reprobe only — does not auto-patch failing endpoints.",
    }


async def _collect_smoke(
    db_pool, *, kind: str, exec_result: Dict[str, Any]
) -> Dict[str, Any]:
    smoke: Dict[str, Any] = {"checks": []}
    # API health
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://localhost:8000/health", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                body = await resp.text()
                smoke["checks"].append(
                    {
                        "name": "api_health",
                        "ok": resp.status == 200 and "healthy" in body.lower(),
                        "detail": f"status={resp.status}",
                    }
                )
    except Exception as e:
        smoke["checks"].append(
            {"name": "api_health", "ok": False, "detail": str(e)[:120]}
        )

    # Schema-error scan via recent backend is hard from here — check fuel/coding
    if kind == "ln7_fuel_volume_burst" and db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT trainable FROM ln7_fuel_snapshots
                    WHERE domain_tag = 'coding'
                    ORDER BY snap_date DESC LIMIT 1
                    """
                )
                trainable = int(row["trainable"]) if row else None
                smoke["checks"].append(
                    {
                        "name": "coding_fuel",
                        "ok": trainable is not None,
                        "detail": f"trainable={trainable}",
                    }
                )
        except Exception as e:
            smoke["checks"].append(
                {"name": "coding_fuel", "ok": False, "detail": str(e)[:120]}
            )
        gauge = (exec_result or {}).get("gauge") or {}
        smoke["checks"].append(
            {
                "name": "fuel_gauge",
                "ok": bool(gauge.get("ok")),
                "detail": str(gauge.get("digest") or gauge.get("error") or "")[:200],
            }
        )

    if kind == "trust_reprobe":
        t, tot = exec_result.get("trusted"), exec_result.get("total")
        smoke["checks"].append(
            {
                "name": "auditor_score",
                "ok": bool(exec_result.get("ok")) and t is not None,
                "detail": f"{t}/{tot}" if t is not None else exec_result.get("reason") or "n/a",
            }
        )

    smoke["all_ok"] = all(bool(c.get("ok")) for c in smoke["checks"]) if smoke["checks"] else False
    return smoke


def _queens_fact_report(
    *, kind: str, exec_result: Dict[str, Any], smoke: Dict[str, Any]
) -> Dict[str, Any]:
    """Dual-COO structured facts (no speculation)."""
    return {
        "author": "dual_coo_queens",
        "kind": kind,
        "execution_ok": bool(exec_result.get("ok")),
        "skipped": bool(exec_result.get("skipped")),
        "reason": exec_result.get("reason") or exec_result.get("error"),
        "facts": {
            "pass": exec_result.get("pass"),
            "fail": exec_result.get("fail"),
            "packs": exec_result.get("packs"),
            "volume": exec_result.get("volume"),
            "auditor": exec_result.get("auditor"),
            "trusted": exec_result.get("trusted"),
            "total": exec_result.get("total"),
            "failures": exec_result.get("failures") or [],
        },
        "smoke_all_ok": bool(smoke.get("all_ok")),
        "smoke_checks": smoke.get("checks") or [],
    }


async def _fallback_llm_reflect(queens: Dict[str, Any]) -> Dict[str, Any]:
    """Second opinion via inference router (Workers/Grok/Azure fallback). Fail-open."""
    prompt = (
        "You are a production ops reviewer. Given this JSON remediation report, "
        "reply with JSON only: "
        '{"confidence":0-1,"regressions":["..."],"risks":["..."],"verdict":"ok|watch|fail",'
        '"one_line":"..."}. Be conservative. Do not invent metrics.\n\n'
        + json.dumps(queens, default=str)[:3500]
    )
    try:
        state = _resolve_app_state()
        router = getattr(state, "inference_router", None) or getattr(
            state, "nate_inference_router", None
        )
        if router is None:
            from app.services.nate_inference_router import NateInferenceRouter

            router = NateInferenceRouter()
        result = await router.generate(
            prompt=prompt,
            system="Ops reflection only. JSON response. No code changes.",
            tier="utility",
            temperature=0.2,
            max_tokens=400,
            domain="defense",
            odpe_signal="LOCKED",
        )
        text = (result or {}).get("text") or ""
        parsed = _extract_json_obj(text)
        return {
            "ok": True,
            "provider": (result or {}).get("provider"),
            "parsed": parsed,
            "raw": text[:800],
        }
    except Exception as e:
        logger.warning("ceo remediation LLM reflect failed: %s", e)
        return {"ok": False, "error": str(e)[:200], "parsed": None}


def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _format_report_email(
    kind: str,
    exec_result: Dict[str, Any],
    smoke: Dict[str, Any],
    queens: Dict[str, Any],
    llm: Dict[str, Any],
) -> str:
    lines = [
        "EXECUTION REPORT (Phase A+B)",
        f"Kind: {kind}",
        f"Execution ok: {exec_result.get('ok')} skipped={exec_result.get('skipped')}",
    ]
    if exec_result.get("reason") or exec_result.get("detail"):
        lines.append(
            f"Reason: {exec_result.get('reason') or ''} "
            f"{exec_result.get('detail') or ''}".strip()
        )
    if kind == "ln7_fuel_volume_burst" and not exec_result.get("skipped"):
        lines.append(
            f"Fuel forks: pass={exec_result.get('pass')} fail={exec_result.get('fail')} "
            f"skip={exec_result.get('skip')} packs={exec_result.get('packs')} "
            f"volume={exec_result.get('volume')}"
        )
        digest = exec_result.get("gauge") or {}
        if digest.get("digest"):
            lines.append("Gauge: " + "; ".join(str(x) for x in digest["digest"][:6]))
    if kind == "trust_reprobe":
        lines.append(
            f"Auditor: {exec_result.get('auditor')} "
            f"{exec_result.get('trusted')}/{exec_result.get('total')} TRUSTED"
        )
        for f in (exec_result.get("failures") or [])[:8]:
            lines.append(f"  FAIL: {f.get('name')} → {f.get('status')}")
    lines.append("Smoke:")
    for c in smoke.get("checks") or []:
        lines.append(f"  [{'OK' if c.get('ok') else 'FAIL'}] {c.get('name')}: {c.get('detail')}")
    lines.append(f"Queens smoke_all_ok: {queens.get('smoke_all_ok')}")
    parsed = (llm or {}).get("parsed") or {}
    if parsed:
        lines.append(
            f"LLM reflect ({(llm or {}).get('provider')}): "
            f"verdict={parsed.get('verdict')} confidence={parsed.get('confidence')} "
            f"— {parsed.get('one_line')}"
        )
        for r in (parsed.get("risks") or [])[:5]:
            lines.append(f"  risk: {r}")
        for r in (parsed.get("regressions") or [])[:5]:
            lines.append(f"  regression: {r}")
    elif llm.get("error"):
        lines.append(f"LLM reflect unavailable: {llm.get('error')}")
    lines.append(
        "Note: APPROVE ran the allowlisted remediation only — not an open-ended code rewrite."
    )
    return "\n".join(lines)


async def _log_remediation(db_pool, report: Dict[str, Any]) -> None:
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO skyeye_activity (type, content, platform)
                VALUES ('ceo_remediation_executed', $1, 'ceo')
                """,
                json.dumps(
                    {
                        "kind": report.get("kind"),
                        "ok": report.get("ok"),
                        "smoke_all_ok": (report.get("smoke") or {}).get("all_ok"),
                        "at_utc": report.get("at_utc"),
                        "summary": (report.get("summary_text") or "")[:1500],
                    },
                    default=str,
                )[:4000],
            )
    except Exception as e:
        logger.warning("ceo_remediation log: %s", e)
