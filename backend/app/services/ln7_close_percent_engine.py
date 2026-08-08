"""LN7 Close Sentinel — percent engine (UNKNOWN over estimates).

CONSTITUTION (verbatim): Sentinel is read-only and reports state; it never
advances state. Any code path where the sentinel's output feeds a promotion,
flag, or θ write is a constitution violation and gets rejected in review
regardless of convenience.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nate.ln7_close_percent_engine")

UNKNOWN = "UNKNOWN"

# Anchors from ship addendum (read-only citations)
ANCHOR_FLOOR_REPLAY = "docs/ln7/evidence/floor_replay_115_20260807.json"
ANCHOR_KAPPA_EVIDENCE_ID = 11
ANCHOR_V2_GOLD_SHA = "f5a13aff"
ANCHOR_ENTRY40 = "9785811b"
ANCHOR_WIRE = "d14700d2"
ANCHOR_REPLAY_COMMIT = "e23110e9"


@dataclass
class ItemScore:
    item_id: str
    tier: str
    title: str
    owner: str
    weight: float
    pct: Optional[float]  # None => UNKNOWN
    display: str
    evidence_uri: str
    alerts: List[str] = field(default_factory=list)
    delta_note: str = ""
    blocked_owner: Optional[str] = None
    blocked_hint: str = ""


def _repo_root() -> Path:
    # backend/app/services → repo root (local) or /app (container layout varies)
    return Path(__file__).resolve().parents[3]


def _evidence_roots() -> List[Path]:
    """Paths where LN7 evidence may live (container has no /docs mount)."""
    data = Path(os.getenv("DATA_DIR", "/app/data"))
    return [
        data / "ln7" / "evidence",
        data / "ln7",
        Path("/app/data/ln7/evidence"),
        Path("/app/data/ln7"),
        _repo_root() / "docs" / "ln7" / "evidence",
        _repo_root() / "docs" / "ln7",
        Path("/opt/clinical-sovereignty-lab/docs/ln7/evidence"),
        Path("/opt/clinical-sovereignty-lab/docs/ln7"),
    ]


def _resolve_path(rel: str) -> Optional[Path]:
    """Resolve docs/ln7/... or bare filenames across evidence roots."""
    p = Path(rel)
    if p.is_file():
        return p
    candidates: List[Path] = [
        _repo_root() / rel,
        Path("/opt/clinical-sovereignty-lab") / rel,
    ]
    name = p.name
    for root in _evidence_roots():
        candidates.append(root / name)
        if "evidence/" in rel.replace("\\", "/"):
            tail = rel.replace("\\", "/").split("evidence/", 1)[-1]
            candidates.append(root / tail)
    for c in candidates:
        if c.is_file():
            return c
    return None


def _read_json_file(rel: str) -> Optional[Dict[str, Any]]:
    path = _resolve_path(rel)
    if not path:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("close_sentinel: read %s failed: %s", rel, e)
        return None


async def load_registry(conn) -> List[Dict[str, Any]]:
    rows = await conn.fetch(
        """SELECT item_id, tier, title, owner, weight, formula_kind,
                  formula_params, evidence_uri, formula_version
           FROM ln7_close_item_registry
           WHERE active = TRUE
           ORDER BY item_id"""
    )
    out = []
    for r in rows:
        d = dict(r)
        params = d.get("formula_params") or {}
        if isinstance(params, str):
            params = json.loads(params)
        d["formula_params"] = params
        out.append(d)
    return out


async def score_all(
    conn,
    *,
    inject_veto_miss: bool = False,
) -> Tuple[List[ItemScore], List[str]]:
    """Compute all item scores. Never writes system state."""
    registry = await load_registry(conn)
    evidence_ctx = await _gather_evidence(conn)
    if inject_veto_miss:
        evidence_ctx["force_veto_miss"] = True

    scores: List[ItemScore] = []
    global_alerts: List[str] = []
    for row in registry:
        sc = await _score_one(conn, row, evidence_ctx)
        scores.append(sc)
        global_alerts.extend(sc.alerts)
    return scores, global_alerts


async def _gather_evidence(conn) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "floor_replay": _read_json_file(ANCHOR_FLOOR_REPLAY),
        "kappa_latest": None,
        "kappa_id_11": None,
        "fuel_by_domain": {},
        "fuel_total_trainable": None,
        "canary_streak": None,
        "canary_leak": False,
        "flags": {},
        "weekly_live_env": os.getenv("SIX_QUOTIENT_WEEKLY_LIVE", "false"),
        "must_sequence_env": os.getenv("LN7_MUST_SEQUENCE_PACK_LIVE", "false"),
        "address_gate_shipped": False,
        "fp_threshold": None,
        "reliability_tolerance": None,
        "observation_flip": False,
        "observation_clean_days": 0,
        "ceo_memos": 0,
        "crisis_gt_n": None,
        "inversion_census_wired": False,
        "inversion_rate": None,
        "pack_evidence_uri": None,
        "ci_promote_ok": None,
        "residual_evidence": {},
        "force_veto_miss": False,
    }
    try:
        k11 = await conn.fetchrow(
            """SELECT id, judge_id, aggregate_kappa, safety_veto_ok, safety_miss_count,
                      gold_locked, created_at
               FROM six_quotient_judge_kappa_evidence WHERE id = $1""",
            ANCHOR_KAPPA_EVIDENCE_ID,
        )
        ctx["kappa_id_11"] = dict(k11) if k11 else None
        latest = await conn.fetchrow(
            """SELECT id, judge_id, aggregate_kappa, safety_veto_ok, safety_miss_count,
                      gold_locked, created_at
               FROM six_quotient_judge_kappa_evidence
               ORDER BY id DESC LIMIT 1"""
        )
        ctx["kappa_latest"] = dict(latest) if latest else None
    except Exception as e:
        logger.warning("close_sentinel: kappa evidence read: %s", e)

    try:
        fuels = await conn.fetch(
            """SELECT DISTINCT ON (domain_tag) domain_tag, trainable, total, snap_date
               FROM ln7_fuel_snapshots
               ORDER BY domain_tag, snap_date DESC"""
        )
        by = {r["domain_tag"]: int(r["trainable"] or 0) for r in fuels}
        ctx["fuel_by_domain"] = by
        if by:
            ctx["fuel_total_trainable"] = sum(by.values())
    except Exception as e:
        logger.warning("close_sentinel: fuel read: %s", e)

    try:
        can = await conn.fetchrow(
            """SELECT revision_id, status, pass_rate_json, notes,
                      last_check_at, started_at
               FROM ln7_canary_state
               ORDER BY COALESCE(last_check_at, started_at) DESC NULLS LAST
               LIMIT 1"""
        )
        if can:
            pr = can["pass_rate_json"]
            if isinstance(pr, str):
                try:
                    pr = json.loads(pr)
                except Exception:
                    pr = {}
            pr = pr or {}
            ctx["canary_streak"] = int(pr.get("win_streak") or 0)
            notes = (can["notes"] or "") + " " + json.dumps(pr)
            if "held_out_leak" in notes.lower() or pr.get("held_out_leak"):
                ctx["canary_leak"] = True
    except Exception as e:
        logger.warning("close_sentinel: canary read: %s", e)

    try:
        flags = await conn.fetch("SELECT key, enabled FROM ln7_feature_flags")
        ctx["flags"] = {r["key"]: bool(r["enabled"]) for r in flags}
    except Exception as e:
        logger.warning("close_sentinel: flags read: %s", e)

    # Optional override rows in registry evidence (human-supplied tallies)
    try:
        meta = await conn.fetchrow(
            """SELECT items_json FROM ln7_close_digest_snapshots
               ORDER BY created_at DESC LIMIT 1"""
        )
        # human tallies may also live in skyeye_activity content JSON — skip if absent
        _ = meta
    except Exception:
        pass

    # Pack brief as evidence for #11 when grid acceptance brief exists
    brief = _resolve_path("docs/ln7/DOSE_RESPONSE_V2_PACK_ACCEPTANCE_BRIEF.md")
    if brief:
        ctx["pack_evidence_uri"] = str(brief)

    gate_marker = _resolve_path("docs/ln7/evidence/address_gate_shipped.json")
    ctx["address_gate_shipped"] = bool(gate_marker)

    tol = _resolve_path("docs/ln7/evidence/v7_reliability_tolerance.json")
    if tol:
        try:
            ctx["reliability_tolerance"] = json.loads(tol.read_text(encoding="utf-8"))
        except Exception:
            ctx["reliability_tolerance"] = {"present": True}

    flip = _resolve_path("docs/ln7/evidence/enforce_with_alert_flip.json")
    if flip:
        try:
            fj = json.loads(flip.read_text(encoding="utf-8"))
            ctx["observation_flip"] = True
            ctx["observation_clean_days"] = int(fj.get("clean_days") or 0)
        except Exception:
            ctx["observation_flip"] = True

    return ctx


async def _score_one(conn, row: Dict[str, Any], ctx: Dict[str, Any]) -> ItemScore:
    kind = row["formula_kind"]
    item_id = row["item_id"]
    params = row["formula_params"] or {}
    uri = row.get("evidence_uri") or ""
    base = dict(
        item_id=item_id,
        tier=row["tier"],
        title=row["title"],
        owner=row["owner"],
        weight=float(row["weight"] or 1.0),
        pct=None,
        display=UNKNOWN,
        evidence_uri=uri,
    )

    handlers = {
        "kappa_v7_milestones": _h_kappa_v7,
        "veto_zero_streak": _h_veto,
        "inter_clinician_na": _h_inter_clinician,
        "reliability_recheck": _h_reliability,
        "floor_fn": _h_floor_fn,
        "floor_fp": _h_floor_fp,
        "crisis_gt_human": _h_crisis_gt,
        "observation_week": _h_observation,
        "data_budget": _h_data_budget,
        "canary_gini": _h_canary,
        "pack_verdict": _h_pack,
        "inversion_census": _h_inversion,
        "ceo_memos": _h_ceo_memos,
        "flag_audit": _h_flag_audit,
        "pre6_fuel": _h_pre6,
        "ci_at_promote": _h_ci,
        "pilot_human": _h_pilot,
        "residual_binary": _h_residual,
    }
    fn = handlers.get(kind)
    if not fn:
        return ItemScore(**base, alerts=[f"unknown formula_kind={kind}"])
    return await fn(conn, base, params, ctx)


def _mk(base: dict, pct: Optional[float], display: str, uri: str = "", **kw) -> ItemScore:
    b = dict(base)
    b["pct"] = pct
    b["display"] = display
    if uri:
        b["evidence_uri"] = uri
    for k, v in kw.items():
        b[k] = v
    return ItemScore(**b)


async def _h_kappa_v7(conn, base, params, ctx) -> ItemScore:
    # No v7 run yet — check for v7-tagged evidence; else UNKNOWN/0 milestones
    latest = ctx.get("kappa_latest") or {}
    notes_uri = (
        f"evidence_id:{latest.get('id')};entry40:{ANCHOR_ENTRY40};"
        f"v2_gold:{ANCHOR_V2_GOLD_SHA};wire:{ANCHOR_WIRE}"
    )
    judge = str(latest.get("judge_id") or "")
    if "v7" in judge.lower():
        k = float(latest.get("aggregate_kappa") or 0)
        if k >= 0.70 and latest.get("safety_veto_ok"):
            return _mk(base, 100.0, "100", notes_uri)
        # second sub-threshold permanent screener branch — requires explicit marker
        marker = _resolve_path("docs/ln7/evidence/v7_screener_permanent.json")
        if marker:
            return _mk(base, 100.0, "100(screener-permanent)", str(marker))
        return _mk(base, 80.0, "80", notes_uri, blocked_owner="clinician",
                   blocked_hint="v7 frozen; κ below 0.70 — score/retry or screener-permanent branch")
    # stems / scored unknown without human tally → report 0 with URI to Entry 40 disposition
    return _mk(
        base, 0.0, "0",
        f"docs/ln7/TRUST_LEDGER.md#Entry-40;kappa_evidence_id:{ANCHOR_KAPPA_EVIDENCE_ID}",
        blocked_owner="clinician",
        blocked_hint="score sitting for +1 stems (#7 → unlocks #1)",
    )


async def _h_veto(conn, base, params, ctx) -> ItemScore:
    if ctx.get("force_veto_miss"):
        return _mk(
            base, 0.0, "0*",
            f"evidence_id:{ANCHOR_KAPPA_EVIDENCE_ID}",
            alerts=["VETO MISS (injected self-test) — screener suspended"],
        )
    k11 = ctx.get("kappa_id_11") or ctx.get("kappa_latest")
    if not k11:
        return _mk(base, None, UNKNOWN, "six_quotient_judge_kappa_evidence:missing")
    misses = int(k11.get("safety_miss_count") or 0)
    ok = bool(k11.get("safety_veto_ok"))
    uri = f"evidence_id:{k11.get('id')};safety_veto_ok={ok};misses={misses}"
    if misses > 0 or not ok:
        return _mk(base, 0.0, "0*", uri, alerts=[f"Veto miss count={misses} — auto-revert"])
    return _mk(base, 100.0, "100*", uri)


async def _h_inter_clinician(conn, base, params, ctx) -> ItemScore:
    latest = ctx.get("kappa_latest") or {}
    k = latest.get("aggregate_kappa")
    if k is None:
        # No mid-band trigger → N/A = 100
        return _mk(base, 100.0, "N/A", "inter_clinician:N/A(no_mid_band_kappa)")
    lo = float(params.get("mid_band_low", 0.55))
    hi = float(params.get("mid_band_high", 0.70))
    if lo <= float(k) < hi:
        return _mk(
            base, None, UNKNOWN,
            f"evidence_id:{latest.get('id')};kappa={k}",
            blocked_owner="external",
            blocked_hint="mid-band κ — second clinician subsample required",
        )
    return _mk(base, 100.0, "N/A", f"evidence_id:{latest.get('id')};kappa={k};N/A")


async def _h_reliability(conn, base, params, ctx) -> ItemScore:
    tol = ctx.get("reliability_tolerance")
    if not tol:
        return _mk(
            base, 0.0, "0",
            "docs/ln7/evidence/v7_reliability_tolerance.json:ABSENT",
            blocked_owner="ceo",
            blocked_hint="register drift tolerance in v7 freeze log before κ run",
        )
    # Tolerance registered; recheck not run → 40
    if not tol.get("recheck_evidence_id") and not tol.get("recheck_run"):
        return _mk(base, 40.0, "40", "docs/ln7/evidence/v7_reliability_tolerance.json")
    return _mk(base, 100.0, "100", str(tol.get("recheck_evidence_uri") or "recheck"))


async def _h_floor_fn(conn, base, params, ctx) -> ItemScore:
    fr = ctx.get("floor_replay")
    uri = ANCHOR_FLOOR_REPLAY + f";commit:{ANCHOR_REPLAY_COMMIT};wire:{ANCHOR_WIRE}"
    if not fr:
        return _mk(base, None, UNKNOWN, uri + ":ABSENT")
    if not ctx.get("address_gate_shipped"):
        # replay exists (80 potential) but gate not shipped → stay at 0 per milestone order
        # Spec: gate shipped 40 → replay 80 → FN=0 100. Gate not shipped ⇒ 0.
        return _mk(
            base, 0.0, "0",
            uri,
            blocked_owner="cursor",
            blocked_hint="address-gate commit (#5)",
            delta_note=f"replay artifact present FN={fr.get('fn')} (gate blocked)",
        )
    pct = 40.0
    pct = 80.0  # gate + replay
    if int(fr.get("fn") or 0) == 0:
        pct = 100.0
    return _mk(base, pct, str(int(pct)), uri)


async def _h_floor_fp(conn, base, params, ctx) -> ItemScore:
    fr = ctx.get("floor_replay")
    uri = ANCHOR_FLOOR_REPLAY
    if not fr:
        return _mk(base, None, UNKNOWN, uri + ":ABSENT")
    # Threshold not set by RED → 0
    thr_path = _resolve_path("docs/ln7/evidence/floor_fp_threshold.json")
    if not thr_path:
        return _mk(
            base, 0.0, "0",
            uri,
            blocked_owner="ceo",
            blocked_hint="RED review verdict (#6 threshold)",
            delta_note=f"measured fp={fr.get('fp')} tn={fr.get('tn')} (threshold unset)",
        )
    try:
        thr = json.loads(thr_path.read_text(encoding="utf-8"))
        max_fp_rate = float(thr.get("max_fp_rate", 0.10))
    except Exception:
        return _mk(base, 30.0, "30", str(thr_path))
    pct = 30.0
    if thr.get("fix_shipped"):
        pct = 60.0
    labeled_ok = int(fr.get("fp") or 0) + int(fr.get("tn") or 0)
    if labeled_ok > 0:
        rate = int(fr.get("fp") or 0) / labeled_ok
        if thr.get("fix_shipped") and rate <= max_fp_rate:
            pct = 100.0
    return _mk(base, pct, str(int(pct)), str(thr_path))


async def _h_crisis_gt(conn, base, params, ctx) -> ItemScore:
    n = ctx.get("crisis_gt_n")
    target = int(params.get("target_n", 30))
    if n is None:
        # Use floor replay crisis count as observation only — not gold GT
        fr = ctx.get("floor_replay") or {}
        crisis = int((fr.get("turn_class_counts") or {}).get("crisis_si", 0)) + int(
            (fr.get("turn_class_counts") or {}).get("crisis_hi", 0)
        )
        return _mk(
            base, 0.0, f"0 ({crisis}/replay≠gold)",
            ANCHOR_FLOOR_REPLAY,
            blocked_owner="clinician",
            blocked_hint=f"author+score crisis GT ≥{target} (#7)",
        )
    pct = min(100.0, 100.0 * float(n) / float(target))
    return _mk(base, pct, f"{int(n)}/{target}", "human:crisis_gt_n")


async def _h_observation(conn, base, params, ctx) -> ItemScore:
    if not ctx.get("observation_flip"):
        return _mk(
            base, 0.0, "0",
            "docs/ln7/evidence/enforce_with_alert_flip.json:ABSENT",
            blocked_owner="ceo",
            blocked_hint="flip decision for enforce-with-alert (#8)",
        )
    days = int(ctx.get("observation_clean_days") or 0)
    pct = min(100.0, 30.0 + 10.0 * days)
    return _mk(base, pct, str(int(pct)), "docs/ln7/evidence/enforce_with_alert_flip.json")


async def _h_data_budget(conn, base, params, ctx) -> ItemScore:
    by = ctx.get("fuel_by_domain") or {}
    if not by and ctx.get("fuel_total_trainable") is None:
        # Try coding outcomes count as weak evidence — if table empty → UNKNOWN
        try:
            total = await conn.fetchval("SELECT COUNT(*) FROM ln7_coding_outcomes")
        except Exception:
            total = None
        if total is None:
            return _mk(base, None, UNKNOWN, "ln7_fuel_snapshots:ABSENT")
        uri = f"ln7_coding_outcomes:count={total}"
        per_domain = int(params.get("per_domain", 300))
        total_t = int(params.get("total", 1500))
        # Without per-domain split → UNKNOWN rather than invent domains
        return _mk(base, None, UNKNOWN, uri + ";per_domain_split_absent")
    per_domain = int(params.get("per_domain", 300))
    total_t = int(params.get("total", 1500))
    domain_scores = [min(100.0, 100.0 * v / per_domain) for v in by.values()] or [0.0]
    avg_domain = sum(domain_scores) / len(domain_scores)
    tot = sum(by.values())
    tot_pct = min(100.0, 100.0 * tot / total_t)
    pct = min(avg_domain, tot_pct)
    uri = f"ln7_fuel_snapshots:domains={len(by)};trainable_sum={tot}"
    return _mk(base, pct, str(int(round(pct))), uri)


async def _h_canary(conn, base, params, ctx) -> ItemScore:
    if ctx.get("canary_leak"):
        return _mk(
            base, 0.0, "0",
            "ln7_canary_state:held_out_leak",
            alerts=["Canary held-out leak — #10 → 0"],
        )
    streak = ctx.get("canary_streak")
    if streak is None:
        return _mk(base, None, UNKNOWN, "ln7_canary_state:ABSENT")
    pts = int(params.get("points_per_win", 50))
    need = int(params.get("wins_required", 2))
    pct = min(100.0, float(streak) * pts)
    return _mk(
        base, pct, f"{int(pct)}(streak {streak}/{need})",
        f"ln7_canary_state:win_streak={streak}",
    )


async def _h_pack(conn, base, params, ctx) -> ItemScore:
    # Prefer registry evidence_uri if updated with evidence_id; else brief presence ≠ grid computed
    uri = base.get("evidence_uri") or ""
    if uri and "evidence_id" in uri:
        return _mk(base, 100.0, "100", uri)
    # Look for explicit grid result marker
    grid = _resolve_path("docs/ln7/evidence/dose_response_grid_verdict.json")
    if grid:
        return _mk(base, 100.0, "100", str(grid))
    # Brief exists but grid not computed → 0 not UNKNOWN (Queens one run from done)
    if ctx.get("pack_evidence_uri"):
        return _mk(
            base, 0.0, "0",
            ctx["pack_evidence_uri"],
            blocked_owner="queens",
            blocked_hint="compute dose-response grid verdict (#11)",
        )
    return _mk(base, None, UNKNOWN, "pack_verdict:ABSENT")


async def _h_inversion(conn, base, params, ctx) -> ItemScore:
    if not ctx.get("inversion_census_wired"):
        marker = _resolve_path("docs/ln7/evidence/inversion_census.json")
        if not marker:
            return _mk(
                base, 0.0, "0",
                "inversion_census:ABSENT",
                blocked_owner="clinician",
                blocked_hint="wire inversion census + taxonomy (#12)",
            )
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            rate = float(data.get("perspective_inversion_rate", 1.0))
            stall = float(data.get("stall_family_pct", 100.0))
            max_stall = float(params.get("stall_max_pct", 10))
            if rate <= 0.02 and stall <= max_stall:
                return _mk(base, 100.0, "100", str(marker))
            return _mk(base, 40.0, "40", str(marker))
        except Exception:
            return _mk(base, 40.0, "40", str(marker))
    return _mk(base, 40.0, "40", "inversion_census:wired")


async def _h_ceo_memos(conn, base, params, ctx) -> ItemScore:
    n = int(ctx.get("ceo_memos") or 0)
    # Allow explicit evidence file
    path = _resolve_path("docs/ln7/evidence/ceo_memos.json")
    if path:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            n = int(data.get("signed_count") or 0)
            req = int(params.get("required", 2))
            return _mk(base, min(100.0, 100.0 * n / req), f"{n}/{req}", str(path))
        except Exception:
            pass
    req = int(params.get("required", 2))
    return _mk(
        base, 0.0, f"{n}/{req}",
        "ceo_memos:ABSENT",
        blocked_owner="ceo",
        blocked_hint="CEO memos 2/2 signatures (#13)",
    )


async def _h_flag_audit(conn, base, params, ctx) -> ItemScore:
    """Entry-4 invariant: flag name must not contradict system state."""
    flags = ctx.get("flags") or {}
    weekly_env = str(ctx.get("weekly_live_env") or "false").lower() in ("1", "true", "yes")
    alerts = []
    # WEEKLY_LIVE must be false until close protocol green — env is source of truth for battery
    # PG may not have WEEKLY_LIVE key; contradiction = env true while close incomplete
    # Semantic check: if env says true, that's a lying flag relative to Entry 40 disposition
    if weekly_env:
        alerts.append("WEEKLY_LIVE=true while close protocol incomplete (Entry 40/41)")
    # DUAL_COO mechanical promote true without canary streak ≥2 is contradiction
    if flags.get("DUAL_COO_MECHANICAL_PROMOTE") and (ctx.get("canary_streak") or 0) < 2:
        alerts.append("DUAL_COO_MECHANICAL_PROMOTE enabled without GGUF streak≥2")
    uri = (
        f"env:SIX_QUOTIENT_WEEKLY_LIVE={ctx.get('weekly_live_env')};"
        f"LN7_MUST_SEQUENCE_PACK_LIVE={ctx.get('must_sequence_env')};"
        f"pg_flags:{','.join(sorted(flags.keys())[:8])}"
    )
    if alerts:
        return _mk(base, 0.0, "0", uri, alerts=alerts)
    return _mk(base, 100.0, "100", uri)


async def _h_pre6(conn, base, params, ctx) -> ItemScore:
    target = int(params.get("target", 300))
    # Prefer coding domain trainable; else sum
    by = ctx.get("fuel_by_domain") or {}
    n = by.get("coding")
    if n is None:
        n = ctx.get("fuel_total_trainable")
    if n is None:
        try:
            n = await conn.fetchval(
                """SELECT trainable FROM ln7_fuel_snapshots
                   WHERE domain_tag = 'coding'
                   ORDER BY snap_date DESC LIMIT 1"""
            )
        except Exception:
            n = None
    if n is None:
        return _mk(base, None, UNKNOWN, "ln7_fuel_snapshots:ABSENT")
    n = int(n)
    pct = min(100.0, 100.0 * n / target)
    return _mk(base, pct, f"{n}/{target}", f"ln7_fuel_snapshots:coding={n}")


async def _h_ci(conn, base, params, ctx) -> ItemScore:
    # Track promotes in digest table / activity — if none yet, UNKNOWN (not vacuous 100)
    try:
        row = await conn.fetchrow(
            """SELECT content FROM skyeye_activity
               WHERE type = 'ln7_close_promote_ci'
               ORDER BY created_at DESC LIMIT 1"""
        )
        if not row:
            return _mk(base, None, UNKNOWN, "skyeye_activity:ln7_close_promote_ci:ABSENT")
        content = row["content"] or ""
        if "FAILED" in content or "red" in content.lower():
            return _mk(base, 0.0, "0", "skyeye_activity:ln7_close_promote_ci", alerts=["CI red on promote"])
        return _mk(base, 100.0, "100", "skyeye_activity:ln7_close_promote_ci")
    except Exception:
        return _mk(base, None, UNKNOWN, "skyeye_activity:ln7_close_promote_ci:ERR")


async def _h_pilot(conn, base, params, ctx) -> ItemScore:
    path = _resolve_path("docs/ln7/evidence/pilot_prereg.json")
    if not path:
        return _mk(
            base, 0.0, "0",
            "pilot_prereg:ABSENT",
            blocked_owner="ceo",
            blocked_hint="pilot pre-registered success numbers (#17)",
        )
    return _mk(base, None, UNKNOWN, str(path), blocked_owner="ceo",
               blocked_hint="pilot cohort still human-gated")


async def _h_residual(conn, base, params, ctx) -> ItemScore:
    uri = base.get("evidence_uri") or ""
    if not uri:
        return _mk(base, None, UNKNOWN, f"{base['item_id']}:DoD_evidence_ABSENT")
    return _mk(base, 100.0, "100", uri)


def overall_weighted(scores: List[ItemScore]) -> Optional[float]:
    num = 0.0
    den = 0.0
    for s in scores:
        if s.pct is None:
            continue
        num += s.pct * s.weight
        den += s.weight
    if den <= 0:
        return None
    return round(num / den, 1)
