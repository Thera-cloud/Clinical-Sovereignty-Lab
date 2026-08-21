"""
PMB Report Governance API
Admin-gated Predictability Model of Behavior reports.

Coaches request PMB reports for their clients. Admin reviews with
PhD-level clinical consultation via Big Nate, then releases the
approved report with clinical guidance.

Includes:
- Geo-data endpoint (IP-to-location via ip-api.com batch, 24h cache)
- Company-wide PMB + Nevedal STATS aggregation with IDs + coach specialties
- 5-Layer Coherence Model computation (Individual/Family/Community/Cultural/Global)
- Wisdom feed (wisdom_extractions + community_wisdom)
"""

import json
import logging
import math
import os
import time as _time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Request

from app.services.api_server import get_current_user, require_admin, require_coach
from app.services.mfa_gate import enforce_mfa_recent

logger = logging.getLogger("pmb.reports")

router = APIRouter(prefix="/api/reports/pmb", tags=["pmb_reports"])

VAULT_ROOT = Path(os.environ.get("BRIDGE_DATA_DIR", "/app/bridge_data")) / "Vaults"

# ---------------------------------------------------------------------------
# Geo-IP cache (module-level, 24h TTL)
# ---------------------------------------------------------------------------
_geo_cache: Dict[str, dict] = {}
_geo_cache_ts: float = 0.0
_GEO_CACHE_TTL = 86400  # 24 hours

# ---------------------------------------------------------------------------
# Timezone → approximate coordinates (scalable fallback for any new user)
# ---------------------------------------------------------------------------
_TZ_COORDS = {
    "America/New_York": (40.71, -74.01), "America/Chicago": (41.88, -87.63),
    "America/Denver": (39.74, -104.99), "America/Los_Angeles": (34.05, -118.24),
    "America/Phoenix": (33.45, -112.07), "America/Anchorage": (61.22, -149.90),
    "Pacific/Honolulu": (21.31, -157.86), "America/Detroit": (42.33, -83.05),
    "America/Indiana/Indianapolis": (39.77, -86.16), "America/Kentucky/Louisville": (38.25, -85.76),
    "America/Boise": (43.62, -116.21), "America/Juneau": (58.30, -134.42),
    "America/Nome": (64.50, -165.41), "America/Adak": (51.88, -176.66),
    "America/Toronto": (43.65, -79.38), "America/Vancouver": (49.28, -123.12),
    "Europe/London": (51.51, -0.13), "Europe/Paris": (48.86, 2.35),
    "Europe/Berlin": (52.52, 13.41), "Asia/Tokyo": (35.68, 139.69),
    "Australia/Sydney": (-33.87, 151.21), "Asia/Shanghai": (31.23, 121.47),
    "Asia/Kolkata": (28.61, 77.21), "America/Sao_Paulo": (-23.55, -46.63),
    "Africa/Johannesburg": (-26.20, 28.04), "America/Mexico_City": (19.43, -99.13),
}

_US_STATES = {
    "AL": (32.36, -86.28), "AK": (63.59, -154.49), "AZ": (34.05, -111.09),
    "AR": (35.20, -91.83), "CA": (36.78, -119.42), "CO": (39.55, -105.78),
    "CT": (41.60, -72.76), "DE": (38.91, -75.53), "FL": (27.66, -81.52),
    "GA": (32.16, -82.90), "HI": (19.90, -155.58), "ID": (44.07, -114.74),
    "IL": (40.63, -89.40), "IN": (40.27, -86.13), "IA": (41.88, -93.10),
    "KS": (39.01, -98.48), "KY": (37.84, -84.27), "LA": (30.98, -91.96),
    "ME": (45.25, -69.45), "MD": (39.05, -76.64), "MA": (42.41, -71.38),
    "MI": (44.31, -85.60), "MN": (46.73, -94.69), "MS": (32.35, -89.40),
    "MO": (37.96, -91.83), "MT": (46.88, -110.36), "NE": (41.49, -99.90),
    "NV": (38.80, -116.42), "NH": (43.19, -71.57), "NJ": (40.06, -74.41),
    "NM": (34.52, -105.87), "NY": (43.30, -74.22), "NC": (35.76, -79.02),
    "ND": (47.55, -101.00), "OH": (40.42, -82.91), "OK": (35.47, -97.52),
    "OR": (43.80, -120.55), "PA": (41.20, -77.19), "RI": (41.58, -71.48),
    "SC": (33.84, -81.16), "SD": (43.97, -99.90), "TN": (35.52, -86.58),
    "TX": (31.97, -99.90), "UT": (39.32, -111.09), "VT": (44.56, -72.58),
    "VA": (37.43, -78.66), "WA": (47.75, -120.74), "WV": (38.60, -80.45),
    "WI": (43.78, -88.79), "WY": (43.08, -107.29), "DC": (38.91, -77.04),
}


def _deterministic_jitter(seed_str: str, radius: float = 1.5) -> tuple:
    """Deterministic lat/lng jitter from a string seed so positions are stable across reloads."""
    import hashlib
    h = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    angle = (h % 3600) / 3600.0 * 2 * math.pi
    r = ((h >> 12) % 1000) / 1000.0 * radius
    return (math.cos(angle) * r, math.sin(angle) * r)


def _resolve_location(profile: dict, ip_geo: dict, hardware_id: str) -> dict:
    """Multi-tier geolocation: IP > state > timezone > default with jitter."""
    if ip_geo.get("lat"):
        return {**ip_geo, "geo_source": "ip"}

    state = (profile.get("state") or "").strip().upper()
    if state in _US_STATES:
        lat, lng = _US_STATES[state]
        jlat, jlng = _deterministic_jitter(hardware_id)
        return {"lat": lat + jlat, "lng": lng + jlng, "city": "", "country": "US", "geo_source": "state"}

    tz = (profile.get("timezone") or "").strip()
    if tz in _TZ_COORDS:
        lat, lng = _TZ_COORDS[tz]
        jlat, jlng = _deterministic_jitter(hardware_id, radius=2.0)
        return {"lat": lat + jlat, "lng": lng + jlng, "city": "", "country": "", "geo_source": "timezone"}

    jlat, jlng = _deterministic_jitter(hardware_id, radius=4.0)
    return {"lat": 39.83 + jlat, "lng": -98.58 + jlng, "city": "", "country": "US", "geo_source": "default"}


async def _load_pmb_snapshot(hardware_id: str, role: str = "CLIENT", db=None) -> dict:
    """Load PMB snapshot — PG client_metrics first, JSON fallback."""
    if db:
        try:
            async with db.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT crisis_perception, shame_profile, pmb,
                              c_emo, session_count, nevedal_state
                       FROM client_metrics WHERE hardware_id = $1""",
                    hardware_id
                )
                if row:
                    ns = row["nevedal_state"] or {}
                    if isinstance(ns, str):
                        ns = json.loads(ns)
                    cp = row["crisis_perception"] or {}
                    if isinstance(cp, str):
                        cp = json.loads(cp)
                    sp = row["shame_profile"] or {}
                    if isinstance(sp, str):
                        sp = json.loads(sp)
                    pmb = row["pmb"] or {}
                    if isinstance(pmb, str):
                        pmb = json.loads(pmb)
                    return {
                        "crisis_perception": cp,
                        "shame_profile": sp,
                        "pmb": pmb,
                        "C_emo": float(row["c_emo"] or 0),
                        "session_count": int(row["session_count"] or 0),
                        "mood_history_length": len(ns.get("mood_history", [])),
                        "cee_count": len(ns.get("cee_experiences", [])),
                        "snapshot_at": datetime.now(timezone.utc).isoformat(),
                    }
        except Exception as e:
            logger.warning("PG PMB snapshot failed for %s: %s", hardware_id, e)

    folder = "Clients" if role == "CLIENT" else "Coaches"
    metrics_path = VAULT_ROOT / folder / hardware_id / "metrics.json"
    if not metrics_path.exists():
        return {}
    try:
        with open(metrics_path, "r") as f:
            metrics = json.load(f)
        ns = metrics.get("nevedal_state", {})
        return {
            "crisis_perception": ns.get("crisis_perception", {}),
            "shame_profile": ns.get("shame_profile", {}),
            "pmb": ns.get("pmb", {}),
            "C_emo": ns.get("C_emo", 0),
            "session_count": len(metrics.get("history", [])),
            "mood_history_length": len(ns.get("mood_history", [])),
            "cee_count": len(ns.get("cee_experiences", [])),
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning("Failed to load PMB snapshot for %s: %s", hardware_id, e)
        return {}


async def _load_stats_snapshot(hardware_id: str, db=None) -> dict:
    """Load Nevedal STATS — PG client_metrics first, JSON fallback."""
    if db:
        try:
            async with db.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT c_emo, gap, quantum, anxiety_level, stress_level,
                              engagement, session_count, breakthrough_count
                       FROM client_metrics WHERE hardware_id = $1""",
                    hardware_id
                )
                if row:
                    return {
                        "c_emo": float(row["c_emo"] or 0),
                        "gap": float(row["gap"] or 0),
                        "quantum": float(row["quantum"] or 0),
                        "anxiety_level": float(row["anxiety_level"] or 0),
                        "stress_level": float(row["stress_level"] or 0),
                        "engagement": float(row["engagement"] or 0),
                        "session_count": int(row["session_count"] or 0),
                        "breakthrough_count": int(row["breakthrough_count"] or 0),
                    }
        except Exception as e:
            logger.warning("PG stats snapshot failed for %s: %s", hardware_id, e)

    metrics_path = VAULT_ROOT / "Clients" / hardware_id / "metrics.json"
    if not metrics_path.exists():
        return {}
    try:
        with open(metrics_path, "r") as f:
            metrics = json.load(f)
        ns = metrics.get("nevedal_state", {})
        return {
            "c_emo": ns.get("C_emo", 0),
            "gap": ns.get("GAP", 0),
            "quantum": ns.get("Quantum", 0),
            "anxiety_level": ns.get("anxiety_level", 0),
            "stress_level": ns.get("stress_level", 0),
            "engagement": ns.get("engagement", 0),
            "session_count": ns.get("session_count", 0),
            "breakthrough_count": ns.get("breakthrough_count", 0),
        }
    except Exception as e:
        logger.warning("Failed to load stats for %s: %s", hardware_id, e)
        return {}


async def _batch_geolocate(ips: List[str]) -> Dict[str, dict]:
    """Resolve up to 100 IPs to lat/lng via ip-api.com/batch (free, no key)."""
    global _geo_cache, _geo_cache_ts
    now = _time.time()
    if now - _geo_cache_ts > _GEO_CACHE_TTL:
        _geo_cache.clear()
        _geo_cache_ts = now

    unknown = [ip for ip in ips if ip not in _geo_cache and ip]
    if not unknown:
        return _geo_cache

    for batch_start in range(0, len(unknown), 100):
        batch = unknown[batch_start:batch_start + 100]
        try:
            async with aiohttp.ClientSession() as session:
                payload = [
                    {"query": ip, "fields": "lat,lon,city,country,query,status"}
                    for ip in batch
                ]
                async with session.post(
                    "https://ip-api.com/batch", json=payload, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        results = await resp.json()
                        for r in results:
                            if r.get("status") == "success" and r.get("lat"):
                                _geo_cache[r["query"]] = {
                                    "lat": r["lat"],
                                    "lng": r["lon"],
                                    "city": r.get("city", ""),
                                    "country": r.get("country", ""),
                                }
        except Exception as e:
            logger.warning("ip-api.com batch failed: %s", e)

    return _geo_cache


def _parse_profile(row) -> dict:
    """Safely parse profile_data from asyncpg row."""
    profile = row.get("profile_data") or {}
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except Exception as e:
            logger.warning("_parse_profile: failed to parse profile_data for %s: %s",
                           row.get("username", "?"), e)
            profile = {}
    return profile


def _safe_int(val, default: int = 0) -> int:
    """Convert profile_data values (may be str or int or None) to int safely."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


# ===========================================================================
# GEO-DATA ENDPOINT
# ===========================================================================

@router.get("/geo-data", dependencies=[Depends(require_admin)])
async def geo_data(request: Request):
    """Per-client geo-located PMB + STATS data for globe visualization."""
    db = request.app.state.db_pool

    async with db.acquire() as conn:
        client_rows = await conn.fetch(
            "SELECT username, hardware_id, profile_data FROM users WHERE role = 'CLIENT'"
        )
        coach_rows = await conn.fetch(
            "SELECT username, hardware_id, profile_data FROM users WHERE role = 'COACH'"
        )

        ip_rows = await conn.fetch("""
            SELECT DISTINCT ON (identifier) identifier, ip_address
            FROM login_attempts
            WHERE success = true AND ip_address IS NOT NULL AND ip_address != ''
            ORDER BY identifier, created_at DESC
        """)

        group_rows = await conn.fetch("""
            SELECT user_id, array_agg(DISTINCT group_name) as groups
            FROM community_attendance_records
            WHERE group_name IS NOT NULL AND group_name != ''
            GROUP BY user_id
        """)

    ip_map = {r["identifier"]: str(r["ip_address"]) for r in ip_rows}
    group_map = {r["user_id"]: [g for g in (r["groups"] or []) if g] for r in group_rows}

    all_ips = list(set(ip_map.values()))
    geo_lookup = await _batch_geolocate(all_ips)

    clients = []
    for r in client_rows:
        hw_id = r["hardware_id"]
        if not hw_id:
            continue
        profile = _parse_profile(r)
        ip = ip_map.get(r["username"], "")
        ip_geo = geo_lookup.get(ip, {})
        loc = _resolve_location(profile, ip_geo, hw_id)

        pmb_snap = await _load_pmb_snapshot(hw_id, db=db)
        stats_snap = await _load_stats_snapshot(hw_id, db=db)

        token_usage = _safe_int(profile.get("token_usage_month"))
        login_count = _safe_int(profile.get("login_count"))
        last_login_str = profile.get("last_login", "")
        days_since = None
        if last_login_str:
            try:
                last_dt = datetime.fromisoformat(str(last_login_str).replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                days_since = (datetime.now(timezone.utc) - last_dt).days
            except Exception as e:
                logger.debug("geo_data: last_login parse failed for %s: %s", r["username"], e)
        recency = max(0.0, 1.0 - (days_since or 30) / 30.0) if days_since is not None else 0.0
        u_score = min(1.0, token_usage / 50000.0) if token_usage else 0.0
        l_score = min(1.0, login_count / 10.0) if login_count else 0.0
        eng_score = round(0.4 * u_score + 0.3 * recency + 0.3 * l_score, 3)

        if stats_snap:
            stats_snap["engagement"] = eng_score
        else:
            stats_snap = {
                "c_emo": 0, "gap": 0, "quantum": 0,
                "anxiety_level": 0, "stress_level": 0, "engagement": eng_score,
                "session_count": _safe_int(profile.get("total_sessions_count")),
                "breakthrough_count": 0,
            }

        pmb_data = {
            "reactivity_type": "MIXED",
            "reconsolidation_readiness": 0,
            "crisis_baseline": "CALIBRATING",
            "shame_index": 0,
            "legacy_count": 0,
        }
        if pmb_snap and pmb_snap.get("pmb"):
            pmb_data = {
                "reactivity_type": (pmb_snap["pmb"].get("reactivity_type", "MIXED") or "MIXED"),
                "reconsolidation_readiness": pmb_snap["pmb"].get("reconsolidation_readiness", 0),
                "crisis_baseline": (pmb_snap.get("crisis_perception", {}).get("perception_baseline", "CALIBRATING") or "CALIBRATING"),
                "shame_index": pmb_snap.get("shame_profile", {}).get("shame_index", 0),
                "legacy_count": len(pmb_snap["pmb"].get("legacy_patterns", [])),
            }

        clients.append({
            "username": r["username"],
            "name": profile.get("name") or r["username"],
            "hardware_id": hw_id,
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
            "city": loc.get("city", ""),
            "country": loc.get("country", ""),
            "geo_source": loc.get("geo_source", "none"),
            "family_id": profile.get("family_id"),
            "company_id": profile.get("company_id"),
            "coach_id": profile.get("coach_id"),
            "coach_name": profile.get("assigned_coach"),
            "group_names": group_map.get(r["username"], []),
            "tier": profile.get("tier", "TRIAL"),
            "pmb": pmb_data,
            "stats": stats_snap,
            "has_pmb": bool(pmb_snap and pmb_snap.get("pmb")),
            "engagement": {
                "engagement_score": eng_score,
                "tokens_used": token_usage,
                "login_count": login_count,
                "days_since_last_login": days_since,
            },
        })

    coaches = []
    for r in coach_rows:
        profile = _parse_profile(r)
        ip = ip_map.get(r["username"], "")
        ip_geo = geo_lookup.get(ip, {})
        loc = _resolve_location(profile, ip_geo, r["hardware_id"])
        coaches.append({
            "username": r["username"],
            "name": profile.get("name") or r["username"],
            "hardware_id": r["hardware_id"],
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
            "city": loc.get("city", ""),
            "country": loc.get("country", ""),
            "geo_source": loc.get("geo_source", "none"),
            "specialty": profile.get("specialty") or profile.get("specializations") or "",
        })

    return {"clients": clients, "coaches": coaches}


# ===========================================================================
# COMPANY-STATS ENDPOINT (expanded)
# ===========================================================================

@router.get("/company-stats", dependencies=[Depends(require_admin)])
async def company_stats(request: Request):
    """Aggregate PMB + STATS statistics across all clients."""
    db = request.app.state.db_pool

    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT username, hardware_id, profile_data FROM users WHERE role = 'CLIENT'"
        )
        coach_rows = await conn.fetch(
            "SELECT username, hardware_id, profile_data FROM users WHERE role = 'COACH'"
        )
        group_rows = await conn.fetch("""
            SELECT user_id, array_agg(DISTINCT group_name) as groups
            FROM community_attendance_records
            WHERE group_name IS NOT NULL AND group_name != ''
            GROUP BY user_id
        """)

    group_map = {r["user_id"]: [g for g in (r["groups"] or []) if g] for r in group_rows}

    total_clients = len(rows)
    clients_with_pmb = 0
    baseline_dist = {"MINIMIZER": 0, "AMPLIFIER": 0, "NORMALIZER": 0, "CALIBRATED": 0, "CALIBRATING": 0}
    reactivity_dist = {"FIGHT": 0, "FLIGHT": 0, "FREEZE": 0, "FAWN": 0, "MIXED": 0}
    legacy_categories: Dict[str, int] = {}
    total_reconsolidation = 0.0
    total_shame = 0.0
    clients_with_legacy = 0
    stats_totals = {"c_emo": 0.0, "gap": 0.0, "quantum": 0.0, "anxiety": 0.0, "stress": 0.0, "engagement": 0.0, "breakthroughs": 0}
    stats_count = 0
    client_list = []

    for r in rows:
        hw_id = r["hardware_id"]
        if not hw_id:
            continue
        profile = _parse_profile(r)
        snap = await _load_pmb_snapshot(hw_id, db=db)
        stats = await _load_stats_snapshot(hw_id, db=db)

        token_usage = _safe_int(profile.get("token_usage_month"))
        login_count = _safe_int(profile.get("login_count"))
        last_login_str = profile.get("last_login", "")
        days_since = None
        if last_login_str:
            try:
                last_dt = datetime.fromisoformat(str(last_login_str).replace("Z", "+00:00"))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                days_since = (datetime.now(timezone.utc) - last_dt).days
            except Exception as e:
                logger.debug("company_stats: last_login parse failed for %s: %s", r["username"], e)
        recency = max(0.0, 1.0 - (days_since or 30) / 30.0) if days_since is not None else 0.0
        u_score = min(1.0, token_usage / 50000.0) if token_usage else 0.0
        l_score = min(1.0, login_count / 10.0) if login_count else 0.0
        eng_score = round(0.4 * u_score + 0.3 * recency + 0.3 * l_score, 3)

        if stats:
            stats["engagement"] = eng_score
        else:
            stats = {
                "c_emo": 0, "gap": 0, "quantum": 0,
                "anxiety_level": 0, "stress_level": 0, "engagement": eng_score,
                "session_count": _safe_int(profile.get("total_sessions_count")),
                "breakthrough_count": 0,
            }

        entry = {
            "username": r["username"],
            "name": profile.get("name") or r["username"],
            "hardware_id": hw_id,
            "family_id": profile.get("family_id"),
            "company_id": profile.get("company_id"),
            "coach_id": profile.get("coach_id"),
            "coach_name": profile.get("assigned_coach"),
            "group_names": group_map.get(r["username"], []),
            "has_pmb": False,
            "stats": stats,
            "engagement": {
                "engagement_score": eng_score,
                "tokens_used": token_usage,
                "login_count": login_count,
                "days_since_last_login": days_since,
            },
        }

        if stats:
            stats_count += 1
            stats_totals["c_emo"] += stats.get("c_emo", 0) or 0
            stats_totals["gap"] += stats.get("gap", 0) or 0
            stats_totals["quantum"] += stats.get("quantum", 0) or 0
            stats_totals["anxiety"] += stats.get("anxiety_level", 0) or 0
            stats_totals["stress"] += stats.get("stress_level", 0) or 0
            stats_totals["engagement"] += stats.get("engagement", 0) or 0
            stats_totals["breakthroughs"] += stats.get("breakthrough_count", 0) or 0

        if not snap or not snap.get("pmb"):
            client_list.append(entry)
            continue

        clients_with_pmb += 1
        cp = snap.get("crisis_perception", {})
        sp = snap.get("shame_profile", {})
        pmb = snap.get("pmb", {})

        bl = (cp.get("perception_baseline", "CALIBRATING") or "CALIBRATING").upper()
        if bl in baseline_dist:
            baseline_dist[bl] += 1
        else:
            baseline_dist["CALIBRATING"] += 1

        rt = (pmb.get("reactivity_type", "MIXED") or "MIXED").upper()
        if rt in reactivity_dist:
            reactivity_dist[rt] += 1
        else:
            reactivity_dist["MIXED"] += 1

        recon = pmb.get("reconsolidation_readiness", 0) or 0
        total_reconsolidation += recon
        shame_idx = sp.get("shame_index", 0) or 0
        total_shame += shame_idx

        legacy = pmb.get("legacy_patterns", [])
        if legacy:
            clients_with_legacy += 1
            for lp in legacy:
                if isinstance(lp, dict):
                    cat = lp.get("pattern", "unknown")
                    legacy_categories[cat] = legacy_categories.get(cat, 0) + 1

        entry.update({
            "has_pmb": True,
            "baseline": bl,
            "reactivity_type": rt,
            "reconsolidation_readiness": recon,
            "shame_index": shame_idx,
            "legacy_count": len(legacy),
            "session_count": snap.get("session_count", 0),
        })
        client_list.append(entry)

    avg_reconsolidation = total_reconsolidation / max(clients_with_pmb, 1)
    avg_shame = total_shame / max(clients_with_pmb, 1)
    top_legacy = sorted(legacy_categories.items(), key=lambda x: x[1], reverse=True)[:8]

    sc = max(stats_count, 1)
    avg_stats = {
        "avg_c_emo": round(stats_totals["c_emo"] / sc, 4),
        "avg_gap": round(stats_totals["gap"] / sc, 4),
        "avg_quantum": round(stats_totals["quantum"] / sc, 4),
        "avg_anxiety": round(stats_totals["anxiety"] / sc, 4),
        "avg_stress": round(stats_totals["stress"] / sc, 4),
        "avg_engagement": round(stats_totals["engagement"] / sc, 4),
        "total_breakthroughs": stats_totals["breakthroughs"],
        "clients_with_stats": stats_count,
    }

    coach_list = []
    for cr in coach_rows:
        cp = _parse_profile(cr)
        coach_list.append({
            "username": cr["username"],
            "name": cp.get("name") or cr["username"],
            "hardware_id": cr["hardware_id"],
            "specialty": cp.get("specialty") or cp.get("specializations") or "",
        })

    return {
        "total_clients": total_clients,
        "clients_with_pmb": clients_with_pmb,
        "baseline_distribution": baseline_dist,
        "reactivity_distribution": reactivity_dist,
        "avg_reconsolidation_readiness": round(avg_reconsolidation, 4),
        "avg_shame_index": round(avg_shame, 4),
        "clients_with_legacy": clients_with_legacy,
        "top_legacy_categories": [{"pattern": p, "count": c} for p, c in top_legacy],
        "avg_stats": avg_stats,
        "clients": client_list,
        "coaches": coach_list,
    }


# ===========================================================================
# 5-LAYER COHERENCE MODEL
# ===========================================================================

@router.get("/coherence-layers", dependencies=[Depends(require_admin)])
async def coherence_layers(request: Request):
    """Compute the 5-Layer Coherence Model from live client data.

    Layer 1 (Individual): C_emo per client
    Layer 2 (Family): mean coherence, system resonance, pattern transmission, interruption efficacy
    Layer 3 (Community): aggregated across community mesh group_name groupings
    Layer 4 (Cultural): internal therapeutic state vs external SkyEye sentiment
    Layer 5 (Global): weighted synthesis
    """
    db = request.app.state.db_pool

    async with db.acquire() as conn:
        client_rows = await conn.fetch(
            "SELECT id, username, hardware_id, profile_data FROM users WHERE role = 'CLIENT'"
        )
        group_rows = await conn.fetch("""
            SELECT user_id, array_agg(DISTINCT group_name) as groups
            FROM community_attendance_records
            WHERE group_name IS NOT NULL AND group_name != ''
            GROUP BY user_id
        """)
        sentiment_row = await conn.fetchrow("""
            SELECT AVG(
                CASE
                    WHEN content::text ILIKE '%positive%' THEN 0.7
                    WHEN content::text ILIKE '%negative%' THEN 0.3
                    ELSE 0.5
                END
            ) as avg_sentiment
            FROM skyeye_activity
            WHERE type IN ('post_published', 'content_generated')
              AND created_at > NOW() - INTERVAL '7 days'
        """)

    group_map: Dict[str, List[str]] = {}
    for r in group_rows:
        for g in (r["groups"] or []):
            if g:
                group_map.setdefault(g, []).append(r["user_id"])

    # --- Layer 1: Individual coherence (from coherence_measurements + metrics.json) ---
    individual_scores: Dict[str, float] = {}
    family_map: Dict[str, List[str]] = defaultdict(list)
    user_uuid_map: Dict[str, str] = {}

    for r in client_rows:
        hw_id = r["hardware_id"]
        if not hw_id:
            continue
        profile = _parse_profile(r)
        user_uuid_map[r["username"]] = str(r.get("id", "")) if r.get("id") else ""

        stats = await _load_stats_snapshot(hw_id, db=db)
        c_emo = stats.get("c_emo", 0.5) if stats else 0.5
        individual_scores[r["username"]] = c_emo

        fam_id = profile.get("family_id")
        if fam_id:
            family_map[fam_id].append(r["username"])

    async with db.acquire() as conn:
        db_coherence = await conn.fetch("""
            SELECT DISTINCT ON (user_id) user_id, score
            FROM coherence_measurements
            WHERE layer = 'individual' AND user_id IS NOT NULL
            ORDER BY user_id, measured_at DESC
        """)
        for row in db_coherence:
            uid = str(row["user_id"])
            for uname, uuid_str in user_uuid_map.items():
                if uuid_str == uid:
                    individual_scores[uname] = float(row["score"])
                    break

    all_s1 = list(individual_scores.values()) or [0.5]
    avg_s1 = sum(all_s1) / len(all_s1)

    # --- Layer 2: Family coherence ---
    family_scores: Dict[str, dict] = {}
    all_s2 = []
    for fam_id, members in family_map.items():
        member_scores = [individual_scores.get(m, 0.5) for m in members]
        if not member_scores:
            continue
        mean_c = sum(member_scores) / len(member_scores)
        variance = sum((s - mean_c) ** 2 for s in member_scores) / max(len(member_scores), 1)
        resonance = 1.0 / (1.0 + variance)
        s2 = 0.35 * mean_c + 0.30 * resonance + 0.20 * mean_c + 0.15 * mean_c
        family_scores[fam_id] = {
            "family_id": fam_id,
            "s2": round(s2, 4),
            "mean_coherence": round(mean_c, 4),
            "resonance": round(resonance, 4),
            "member_count": len(members),
            "members": members,
        }
        all_s2.append(s2)

    avg_s2 = sum(all_s2) / max(len(all_s2), 1) if all_s2 else avg_s1

    # --- Layer 3: Community coherence ---
    community_scores: Dict[str, dict] = {}
    all_s3 = []
    for group_name, member_usernames in group_map.items():
        member_fam_ids = set()
        member_s1 = []
        for uname in member_usernames:
            if uname in individual_scores:
                member_s1.append(individual_scores[uname])
            for fam_id, fam_members in family_map.items():
                if uname in fam_members:
                    member_fam_ids.add(fam_id)

        fam_s2_list = [family_scores[fid]["s2"] for fid in member_fam_ids if fid in family_scores]
        if not fam_s2_list:
            fam_s2_list = member_s1 if member_s1 else [0.5]

        mean_s2 = sum(fam_s2_list) / len(fam_s2_list)
        std_s2 = math.sqrt(sum((v - mean_s2) ** 2 for v in fam_s2_list) / max(len(fam_s2_list), 1))
        s3 = 0.60 * mean_s2 + 0.40 * (1.0 - min(1.0, 3.0 * std_s2))

        community_scores[group_name] = {
            "group_name": group_name,
            "s3": round(s3, 4),
            "mean_family_coherence": round(mean_s2, 4),
            "std_family_coherence": round(std_s2, 4),
            "family_count": len(member_fam_ids),
            "member_count": len(member_usernames),
        }
        all_s3.append(s3)

    avg_s3 = sum(all_s3) / max(len(all_s3), 1) if all_s3 else avg_s2

    # --- Layer 4: Cultural coherence ---
    s_internal = avg_s1
    s_external = float(sentiment_row["avg_sentiment"]) if sentiment_row and sentiment_row["avg_sentiment"] else 0.5
    s4 = 1.0 - abs(s_internal - s_external)

    # --- Layer 5: Global coherence (prefer DB briefing if available) ---
    s5 = 0.20 * avg_s1 + 0.25 * avg_s2 + 0.30 * avg_s3 + 0.25 * s4

    async with db.acquire() as conn:
        briefing = await conn.fetchrow(
            "SELECT global_coherence_index, layer_summaries, trending_themes, "
            "gap_analysis_summary, notable_changes, recommendations, generated_at "
            "FROM coherence_briefings ORDER BY generated_at DESC LIMIT 1"
        )
        db_global = await conn.fetch(
            "SELECT score, measured_at FROM coherence_measurements "
            "WHERE layer = 'global' ORDER BY measured_at DESC LIMIT 10"
        )

    if briefing and briefing["global_coherence_index"] is not None:
        s5 = float(briefing["global_coherence_index"])

    global_trend = [{"score": float(r["score"]), "at": r["measured_at"].isoformat()} for r in (db_global or [])]

    briefing_info = None
    if briefing:
        briefing_info = {
            "global_coherence_index": briefing["global_coherence_index"],
            "layer_summaries": briefing["layer_summaries"] if isinstance(briefing["layer_summaries"], dict) else {},
            "trending_themes": list(briefing["trending_themes"] or []),
            "gap_analysis": briefing["gap_analysis_summary"] or "",
            "notable_changes": list(briefing["notable_changes"] or []),
            "recommendations": list(briefing["recommendations"] or []),
            "generated_at": briefing["generated_at"].isoformat() if briefing["generated_at"] else None,
        }

    return {
        "layers": [
            {"level": 1, "name": "Individual", "score": round(avg_s1, 4), "weight": 0.20, "client_count": len(all_s1)},
            {"level": 2, "name": "Family", "score": round(avg_s2, 4), "weight": 0.25, "family_count": len(family_scores)},
            {"level": 3, "name": "Community", "score": round(avg_s3, 4), "weight": 0.30, "group_count": len(community_scores)},
            {"level": 4, "name": "Cultural", "score": round(s4, 4), "weight": 0.25,
             "components": {"internal": round(s_internal, 4), "external": round(s_external, 4)}},
            {"level": 5, "name": "Global", "score": round(s5, 4), "weight": 1.0},
        ],
        "families": list(family_scores.values()),
        "communities": list(community_scores.values()),
        "global_score": round(s5, 4),
        "global_trend": global_trend,
        "latest_briefing": briefing_info,
    }


# ===========================================================================
# WISDOM FEED
# ===========================================================================

@router.get("/wisdom-feed", dependencies=[Depends(require_admin)])
async def wisdom_feed(request: Request):
    """Aggregated wisdom from therapy extractions, Little Nate's insight journal,
    and community convergence — the full lived learning pipeline."""
    db = request.app.state.db_pool
    extractions = []
    journal_items = []
    community = []

    async with db.acquire() as conn:
        try:
            ext_rows = await conn.fetch("""
                SELECT id, insight_type, content, source, effectiveness_score, extracted_at
                FROM wisdom_extractions
                ORDER BY extracted_at DESC NULLS LAST
                LIMIT 30
            """)
            extractions = [
                {
                    "id": str(r["id"]),
                    "type": "extraction",
                    "insight_type": r["insight_type"],
                    "content": (r["content"] or "")[:300],
                    "source": r["source"],
                    "effectiveness_score": float(r["effectiveness_score"]) if r["effectiveness_score"] else None,
                    "timestamp": r["extracted_at"].isoformat() if r["extracted_at"] else None,
                }
                for r in ext_rows
            ]
        except Exception as e:
            logger.warning("wisdom_extractions query failed: %s", e)

        try:
            journal_rows = await conn.fetch("""
                SELECT id, insight_type, category, title, content,
                       coherence_score, impact_score, applied,
                       source_systems, created_at
                FROM sovereign_insight_journal
                ORDER BY created_at DESC NULLS LAST
                LIMIT 30
            """)
            journal_items = [
                {
                    "id": r["id"],
                    "type": "nate_insight",
                    "insight_type": r["insight_type"],
                    "category": r["category"],
                    "title": r["title"],
                    "content": (r["content"] or "")[:300],
                    "coherence_score": float(r["coherence_score"]) if r["coherence_score"] else None,
                    "impact_score": float(r["impact_score"]) if r["impact_score"] else None,
                    "applied": r["applied"],
                    "source_systems": list(r["source_systems"] or []),
                    "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in journal_rows
            ]
        except Exception as e:
            logger.warning("sovereign_insight_journal query failed: %s", e)

        try:
            com_rows = await conn.fetch("""
                SELECT id, topic, insight_text, convergence_count,
                       source_session_count, location_name, created_at
                FROM community_wisdom
                ORDER BY created_at DESC NULLS LAST
                LIMIT 20
            """)
            community = [
                {
                    "id": r["id"],
                    "type": "community_convergence",
                    "topic": r["topic"],
                    "content": (r["insight_text"] or "")[:300],
                    "convergence_count": r["convergence_count"],
                    "source_session_count": r["source_session_count"],
                    "location_name": r["location_name"],
                    "timestamp": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in com_rows
            ]
        except Exception as e:
            logger.warning("community_wisdom query failed: %s", e)

    combined = extractions + journal_items + community
    combined.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "feed": combined[:60],
        "extraction_count": len(extractions),
        "journal_count": len(journal_items),
        "community_count": len(community),
    }


# ===========================================================================
# CLIENT PMB ENDPOINT
# ===========================================================================

@router.get("/client/{hardware_id}")
async def get_client_pmb(hardware_id: str, request: Request, admin: Dict = Depends(require_admin)):
    """Get full PMB data for a specific client, pulling from all live DB sources."""
    db = request.app.state.db_pool
    # gap-fix-e: PHI read requires fresh MFA (no-op when ENABLE_PHI_MFA_GATE is off)
    await enforce_mfa_recent(db, admin)

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, profile_data FROM users WHERE hardware_id = $1 AND role = 'CLIENT'",
            hardware_id,
        )
        if not row:
            raise HTTPException(404, "Client not found")

        profile = _parse_profile(row)
        user_uuid = row["id"]

        coherence_row = await conn.fetchrow(
            "SELECT score, confidence, measured_at FROM coherence_measurements "
            "WHERE user_id = $1 ORDER BY measured_at DESC LIMIT 1",
            user_uuid,
        )

        global_coherence = await conn.fetchrow(
            "SELECT score, measured_at FROM coherence_measurements "
            "WHERE layer = 'global' ORDER BY measured_at DESC LIMIT 1"
        )

        wisdom_rows = await conn.fetch(
            "SELECT id, insight_type, content, source, effectiveness_score "
            "FROM wisdom_extractions WHERE user_id = $1 ORDER BY extracted_at DESC LIMIT 5",
            user_uuid,
        )

        coach_row = await conn.fetchrow(
            "SELECT username, profile_data FROM users WHERE hardware_id = $1",
            profile.get("coach_id", ""),
        )

        db_session_count = await conn.fetchval(
            "SELECT COUNT(*) FROM sessions WHERE user_id = $1", user_uuid,
        ) or 0

        nevedal_rows = await conn.fetch(
            "SELECT c_emo, cee_window, cee_duration_seconds, biometrics, recorded_at "
            "FROM nevedal_metrics WHERE user_id = $1 ORDER BY recorded_at DESC LIMIT 50",
            user_uuid,
        )

        mood_count = await conn.fetchval(
            "SELECT COUNT(*) FROM nevedal_metrics WHERE user_id = $1 AND biometrics IS NOT NULL",
            user_uuid,
        ) or 0

    snap = await _load_pmb_snapshot(hardware_id, db=db)
    stats = await _load_stats_snapshot(hardware_id, db=db)

    token_usage = _safe_int(profile.get("token_usage_month"))
    token_balance = _safe_int(profile.get("token_balance"))
    login_count = _safe_int(profile.get("login_count"))
    total_sessions = max(db_session_count, _safe_int(profile.get("total_sessions_count")))

    cee_count = sum(1 for r in nevedal_rows if r["cee_window"])
    latest_c_emo = 0.0
    if nevedal_rows:
        latest_c_emo = float(nevedal_rows[0]["c_emo"]) if nevedal_rows[0]["c_emo"] else 0.0

    last_login_str = profile.get("last_login", "")
    days_since_login = None
    if last_login_str:
        try:
            last_dt = datetime.fromisoformat(str(last_login_str).replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            days_since_login = (datetime.now(timezone.utc) - last_dt).days
        except Exception as e:
            logger.debug("client detail: last_login parse failed for %s: %s", hardware_id, e)

    recency_score = max(0.0, 1.0 - (days_since_login or 30) / 30.0) if days_since_login is not None else 0.0
    usage_score = min(1.0, token_usage / 50000.0) if token_usage else 0.0
    login_score = min(1.0, login_count / 10.0) if login_count else 0.0
    engagement_score = round(0.4 * usage_score + 0.3 * recency_score + 0.3 * login_score, 3)

    c_emo_db = float(coherence_row["score"]) if coherence_row else latest_c_emo
    c_emo_global = float(global_coherence["score"]) if global_coherence else 0.0

    if not snap:
        snap = {
            "crisis_perception": {
                "perception_baseline": "CALIBRATING",
                "distress_discrepancy": 0,
                "minimization_score": 0,
                "sensitivity_score": 0,
                "normalization_index": 0,
            },
            "shame_profile": {
                "shame_index": 0,
                "shame_baseline": 0,
                "shame_masking_pattern": "UNKNOWN",
                "core_beliefs": [],
            },
            "pmb": {
                "reactivity_type": "MIXED",
                "reactivity_indicators": {"fight": 0, "flight": 0, "freeze": 0, "fawn": 0},
                "reconsolidation_readiness": 0,
                "legacy_patterns": [],
            },
            "C_emo": c_emo_db or c_emo_global,
            "session_count": total_sessions,
            "mood_history_length": mood_count,
            "cee_count": cee_count,
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
            "data_status": "awaiting_first_session" if total_sessions == 0 else "active",
        }

    if nevedal_rows:
        c_emo_values = [float(r["c_emo"]) for r in nevedal_rows if r["c_emo"]]
        if c_emo_values:
            snap["C_emo"] = c_emo_values[0]
            snap["pmb"]["reconsolidation_readiness"] = round(
                sum(c_emo_values) / len(c_emo_values), 4
            )

    if stats:
        snap["stats"] = stats
    else:
        snap["stats"] = {
            "c_emo": c_emo_db or c_emo_global,
            "gap": 0,
            "quantum": 0,
            "anxiety_level": 0,
            "stress_level": 0,
            "engagement": engagement_score,
            "session_count": total_sessions,
            "breakthrough_count": 0,
        }

    snap["engagement"] = {
        "engagement_score": engagement_score,
        "tokens_used": token_usage,
        "token_balance": token_balance,
        "login_count": login_count,
        "days_since_last_login": days_since_login,
        "last_login": last_login_str or None,
        "onboarding_completed": profile.get("onboarding_completed") == "true" or profile.get("onboarding_completed") is True,
    }

    snap["subscription"] = {
        "plan": profile.get("subscription_plan", ""),
        "status": profile.get("subscription_status", ""),
        "tier": profile.get("tier", ""),
        "trial_end": profile.get("trial_end_date", ""),
    }

    snap["coach"] = {
        "coach_id": profile.get("coach_id", ""),
        "coach_name": _parse_profile(coach_row).get("name", "") if coach_row else "",
        "coach_username": coach_row["username"] if coach_row else "",
    }

    snap["family"] = {
        "family_id": profile.get("family_id", ""),
        "family_role": profile.get("family_role", ""),
    }

    snap["global_coherence"] = {
        "score": c_emo_global,
        "measured_at": global_coherence["measured_at"].isoformat() if global_coherence else None,
    }

    if wisdom_rows:
        snap["wisdom"] = [
            {
                "insight_type": r["insight_type"],
                "content": (r["content"] or "")[:200],
                "source": r["source"],
                "effectiveness": float(r["effectiveness_score"]) if r["effectiveness_score"] else None,
            }
            for r in wisdom_rows
        ]

    return snap


# ===========================================================================
# REPORT GOVERNANCE ENDPOINTS (unchanged from original)
# ===========================================================================

@router.post("/request")
async def request_pmb_report(
    request: Request,
    user: Dict = Depends(require_coach),
):
    """Coach requests a PMB report for one of their assigned clients."""
    body = await request.json()
    client_username = body.get("client_username", "").strip()
    urgency = body.get("urgency", "ROUTINE").upper()
    urgency_reason = body.get("urgency_reason", "")

    if not client_username:
        raise HTTPException(400, "client_username is required")
    if urgency not in ("ROUTINE", "PRE_SESSION", "URGENT"):
        raise HTTPException(400, "urgency must be ROUTINE, PRE_SESSION, or URGENT")

    db = request.app.state.db_pool
    coach_username = user.get("username", "")

    async with db.acquire() as conn:
        client = await conn.fetchrow(
            "SELECT username, hardware_id, role, profile_data->>'name' as name, "
            "profile_data->>'coach_id' as coach_id, "
            "profile_data->>'assigned_coach' as assigned_coach "
            "FROM users WHERE LOWER(username) = LOWER($1) AND role = 'CLIENT'",
            client_username,
        )
        if not client:
            raise HTTPException(404, f"Client '{client_username}' not found")

        is_admin = user.get("role") == "ADMIN"
        coach_hw = user.get("hardware_id", "")
        client_coach_id = client["coach_id"] or ""
        client_assigned = client["assigned_coach"] or ""
        if not is_admin and coach_hw != client_coach_id and coach_username.lower() != client_assigned.lower():
            raise HTTPException(403, "You are not assigned to this client")

        pending = await conn.fetchval(
            "SELECT COUNT(*) FROM pmb_report_requests "
            "WHERE client_username = $1 AND status IN ('PENDING', 'IN_REVIEW')",
            client["username"],
        )
        if pending and pending > 0:
            raise HTTPException(409, "A PMB report request is already pending for this client")

        snapshot = await _load_pmb_snapshot(client["hardware_id"], db=db)
        if not snapshot:
            raise HTTPException(
                422, "No PMB data available for this client yet. More sessions are needed."
            )

        row = await conn.fetchrow(
            """INSERT INTO pmb_report_requests
               (client_username, client_hardware_id, client_name,
                requested_by, urgency, urgency_reason, pmb_snapshot)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               RETURNING id, status, requested_at""",
            client["username"],
            client["hardware_id"],
            client["name"] or client["username"],
            coach_username,
            urgency,
            urgency_reason or None,
            json.dumps(snapshot),
        )

    logger.info(
        "PMB report requested: client=%s coach=%s urgency=%s id=%s",
        client_username, coach_username, urgency, row["id"],
    )
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "urgency": urgency,
        "requested_at": row["requested_at"].isoformat(),
        "message": "Request submitted for clinical review.",
    }


@router.get("/pending", dependencies=[Depends(require_admin)])
async def list_pending_reports(request: Request):
    """Admin queue: pending PMB reports sorted by urgency."""
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, client_username, client_name, requested_by,
                      urgency, urgency_reason, status, requested_at,
                      pmb_snapshot
               FROM pmb_report_requests
               WHERE status IN ('PENDING', 'IN_REVIEW')
               ORDER BY
                   CASE urgency
                       WHEN 'URGENT' THEN 0
                       WHEN 'PRE_SESSION' THEN 1
                       WHEN 'ROUTINE' THEN 2
                   END,
                   requested_at ASC""",
        )
    return [
        {
            "id": str(r["id"]),
            "client_username": r["client_username"],
            "client_name": r["client_name"],
            "requested_by": r["requested_by"],
            "urgency": r["urgency"],
            "urgency_reason": r["urgency_reason"],
            "status": r["status"],
            "requested_at": r["requested_at"].isoformat(),
            "pmb_summary": _build_pmb_summary(r["pmb_snapshot"]),
        }
        for r in rows
    ]


@router.get("/history", dependencies=[Depends(require_admin)])
async def report_history(request: Request):
    """Admin: all PMB reports with status history."""
    db = request.app.state.db_pool
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, client_username, client_name, requested_by,
                      urgency, status, requested_at, reviewed_by,
                      reviewed_at, released_at, expires_at, deny_reason
               FROM pmb_report_requests
               ORDER BY requested_at DESC
               LIMIT 100""",
        )
    return [
        {
            "id": str(r["id"]),
            "client_username": r["client_username"],
            "client_name": r["client_name"],
            "requested_by": r["requested_by"],
            "urgency": r["urgency"],
            "status": r["status"],
            "requested_at": r["requested_at"].isoformat(),
            "reviewed_by": r["reviewed_by"],
            "reviewed_at": r["reviewed_at"].isoformat() if r["reviewed_at"] else None,
            "released_at": r["released_at"].isoformat() if r["released_at"] else None,
            "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
            "deny_reason": r["deny_reason"],
        }
        for r in rows
    ]


@router.get("/my-requests")
async def my_requests(request: Request, user: Dict = Depends(require_coach)):
    """Coach: list own submitted PMB report requests."""
    db = request.app.state.db_pool
    coach = user.get("username", "")
    async with db.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, client_username, client_name, urgency, status,
                      requested_at, released_at, deny_reason, expires_at
               FROM pmb_report_requests
               WHERE requested_by = $1
               ORDER BY requested_at DESC
               LIMIT 50""",
            coach,
        )
    return [
        {
            "id": str(r["id"]),
            "client_username": r["client_username"],
            "client_name": r["client_name"],
            "urgency": r["urgency"],
            "status": r["status"],
            "requested_at": r["requested_at"].isoformat(),
            "released_at": r["released_at"].isoformat() if r["released_at"] else None,
            "deny_reason": r["deny_reason"],
            "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
        }
        for r in rows
    ]


def _parse_report_uuid(report_id: str) -> UUID:
    try:
        return UUID(report_id)
    except (ValueError, AttributeError):
        raise HTTPException(422, f"Invalid report ID format: {report_id}")


@router.post("/deep-dive/{report_id}")
async def deep_dive(report_id: str, request: Request, admin: Dict = Depends(require_admin)):
    """Admin: get full PMB data for clinical consultation with Big Nate."""
    rid = _parse_report_uuid(report_id)
    db = request.app.state.db_pool
    # gap-fix-e: PHI read requires fresh MFA (no-op when ENABLE_PHI_MFA_GATE is off)
    await enforce_mfa_recent(db, admin)
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM pmb_report_requests WHERE id = $1",
            rid,
        )
        if not row:
            raise HTTPException(404, "Report request not found")

        if row["status"] == "PENDING":
            await conn.execute(
                "UPDATE pmb_report_requests SET status = 'IN_REVIEW' WHERE id = $1",
                rid,
            )

    snapshot = row["pmb_snapshot"] if isinstance(row["pmb_snapshot"], dict) else json.loads(row["pmb_snapshot"] or "{}")

    return {
        "id": str(row["id"]),
        "client_username": row["client_username"],
        "client_name": row["client_name"],
        "requested_by": row["requested_by"],
        "urgency": row["urgency"],
        "urgency_reason": row["urgency_reason"],
        "status": "IN_REVIEW",
        "requested_at": row["requested_at"].isoformat(),
        "pmb_snapshot": snapshot,
        "pmb_formatted": _format_pmb_for_consultation(snapshot),
    }


@router.post("/approve/{report_id}")
async def approve_report(report_id: str, request: Request, admin: Dict = Depends(require_admin)):
    """Admin approves a PMB report with clinical analysis and guidance."""
    rid = _parse_report_uuid(report_id)
    # gap-fix-e: clinical write requires fresh MFA (no-op when flag off)
    await enforce_mfa_recent(request.app.state.db_pool, admin)
    body = await request.json()
    clinical_analysis = body.get("clinical_analysis", {})
    admin_notes = body.get("admin_notes", "")
    risk_flags = body.get("risk_flags", [])
    contraindications = body.get("contraindications", "")
    consultation_thread_id = body.get("consultation_thread_id", "")

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status FROM pmb_report_requests WHERE id = $1",
            rid,
        )
        if not row:
            raise HTTPException(404, "Report request not found")
        if row["status"] in ("APPROVED", "DENIED"):
            raise HTTPException(409, f"Report already {row['status'].lower()}")

        now = datetime.now(timezone.utc)
        await conn.execute(
            """UPDATE pmb_report_requests SET
                   status = 'APPROVED',
                   clinical_analysis = $2,
                   admin_notes = $3,
                   risk_flags = $4,
                   contraindications = $5,
                   reviewed_by = 'DrNevedal1',
                   reviewed_at = $6,
                   released_at = $6,
                   consultation_thread_id = $7
               WHERE id = $1""",
            rid,
            json.dumps(clinical_analysis),
            admin_notes or None,
            json.dumps(risk_flags),
            contraindications or None,
            now,
            consultation_thread_id or None,
        )

    logger.info("PMB report approved: id=%s", report_id)
    return {"id": report_id, "status": "APPROVED", "released_at": now.isoformat()}


@router.post("/deny/{report_id}")
async def deny_report(report_id: str, request: Request, admin: Dict = Depends(require_admin)):
    """Admin denies a PMB report request with reason."""
    rid = _parse_report_uuid(report_id)
    # gap-fix-e: clinical write requires fresh MFA (no-op when flag off)
    await enforce_mfa_recent(request.app.state.db_pool, admin)
    body = await request.json()
    reason = body.get("reason", "")

    db = request.app.state.db_pool
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status FROM pmb_report_requests WHERE id = $1",
            rid,
        )
        if not row:
            raise HTTPException(404, "Report request not found")
        if row["status"] in ("APPROVED", "DENIED"):
            raise HTTPException(409, f"Report already {row['status'].lower()}")

        now = datetime.now(timezone.utc)
        await conn.execute(
            """UPDATE pmb_report_requests SET
                   status = 'DENIED',
                   deny_reason = $2,
                   reviewed_by = 'DrNevedal1',
                   reviewed_at = $3
               WHERE id = $1""",
            rid,
            reason or "Insufficient data for clinical report at this time.",
            now,
        )

    logger.info("PMB report denied: id=%s reason=%s", report_id, reason)
    return {"id": report_id, "status": "DENIED", "reason": reason}


@router.get("/{report_id}")
async def get_report(report_id: str, request: Request, user: Dict = Depends(get_current_user)):
    """Get a specific PMB report. Coaches only see APPROVED reports for their clients."""
    rid = _parse_report_uuid(report_id)
    db = request.app.state.db_pool
    # gap-fix-e: PHI read requires fresh MFA for both admin + coach callers (no-op when flag off)
    await enforce_mfa_recent(db, user)
    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM pmb_report_requests WHERE id = $1",
            rid,
        )
    if not row:
        raise HTTPException(404, "Report not found")

    is_admin = user.get("role") == "ADMIN"

    if not is_admin:
        if row["requested_by"] != user.get("username", ""):
            raise HTTPException(403, "Access denied")
        if row["status"] != "APPROVED":
            raise HTTPException(403, "Report not yet released")

    snapshot = row["pmb_snapshot"] if isinstance(row["pmb_snapshot"], dict) else json.loads(row["pmb_snapshot"] or "{}")
    clinical = row["clinical_analysis"] if isinstance(row["clinical_analysis"], dict) else json.loads(row["clinical_analysis"] or "{}")
    flags = row["risk_flags"] if isinstance(row["risk_flags"], list) else json.loads(row["risk_flags"] or "[]")

    result = {
        "id": str(row["id"]),
        "client_username": row["client_username"],
        "client_name": row["client_name"],
        "requested_by": row["requested_by"],
        "urgency": row["urgency"],
        "status": row["status"],
        "requested_at": row["requested_at"].isoformat(),
        "pmb_snapshot": snapshot,
        "clinical_analysis": clinical,
        "admin_notes": row["admin_notes"],
        "risk_flags": flags,
        "contraindications": row["contraindications"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
        "released_at": row["released_at"].isoformat() if row["released_at"] else None,
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
    }

    if row["status"] == "DENIED":
        result["deny_reason"] = row["deny_reason"]

    return result


# ===========================================================================
# HELPERS
# ===========================================================================

def _build_pmb_summary(snapshot) -> dict:
    """Build a compact summary for the queue view."""
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except Exception as e:
            logger.warning("_build_pmb_summary: failed to parse snapshot JSON: %s", e)
            return {}
    if not isinstance(snapshot, dict):
        return {}

    pmb = snapshot.get("pmb", {})
    cp = snapshot.get("crisis_perception", {})
    sp = snapshot.get("shame_profile", {})

    return {
        "reactivity_type": pmb.get("reactivity_type", "MIXED"),
        "reconsolidation_readiness": pmb.get("reconsolidation_readiness", 0),
        "crisis_baseline": cp.get("perception_baseline", "CALIBRATING"),
        "shame_index": sp.get("shame_index", 0),
        "legacy_count": len(pmb.get("legacy_patterns", [])),
        "session_count": snapshot.get("session_count", 0),
    }


def _format_pmb_for_consultation(snapshot: dict) -> str:
    """Format PMB data as readable text for Big Nate clinical consultation."""
    if not snapshot:
        return "No PMB data available."

    lines = ["=== PREDICTABILITY MODEL OF BEHAVIOR -- CLINICAL DATA ===\n"]

    cp = snapshot.get("crisis_perception", {})
    if cp:
        lines.append("--- CRISIS PERCEPTION ---")
        lines.append(f"Baseline: {cp.get('perception_baseline', 'CALIBRATING')}")
        lines.append(f"Distress Discrepancy: {cp.get('distress_discrepancy', 0):.1%}")
        lines.append(f"Minimization Score: {cp.get('minimization_score', 0):.1%}")
        lines.append(f"Sensitivity Score: {cp.get('sensitivity_score', 0):.1%}")
        lines.append(f"Normalization Index: {cp.get('normalization_index', 0):.1%}")
        lines.append(f"Calibration Count: {cp.get('calibration_count', 0)}")
        lines.append("")

    sp = snapshot.get("shame_profile", {})
    if sp:
        lines.append("--- SHAME PROFILE ---")
        lines.append(f"Shame Index: {sp.get('shame_index', 0):.1%}")
        lines.append(f"Shame Baseline: {sp.get('shame_baseline', 0):.1%}")
        lines.append(f"Masking Pattern: {sp.get('shame_masking_pattern', 'UNKNOWN')}")
        beliefs = sp.get("core_beliefs", [])
        if beliefs:
            lines.append("Core Beliefs:")
            for b in beliefs[:5]:
                if isinstance(b, dict):
                    lines.append(f"  - \"{b.get('belief', '')}\" (frequency: {b.get('frequency', 0)}, confidence: {b.get('confidence', 0):.2f})")
        lines.append("")

    pmb = snapshot.get("pmb", {})
    if pmb:
        lines.append("--- REACTIVITY PROFILE ---")
        lines.append(f"Dominant Type: {pmb.get('reactivity_type', 'MIXED')}")
        ri = pmb.get("reactivity_indicators", {})
        for rt in ("fight", "flight", "freeze", "fawn"):
            lines.append(f"  {rt.upper()}: {ri.get(rt, 0):.1%}")
        lines.append("")

        lines.append("--- RECONSOLIDATION READINESS ---")
        lines.append(f"Score: {pmb.get('reconsolidation_readiness', 0):.1%}")
        lines.append("")

        legacy = pmb.get("legacy_patterns", [])
        if legacy:
            lines.append("--- TRANSGENERATIONAL LEGACY ---")
            for lp in legacy:
                if isinstance(lp, dict):
                    reflected = "REFLECTED IN CLIENT" if lp.get("reflected_in_client") else "observed only"
                    lines.append(f"  - {lp.get('source', 'unknown').upper()} -> {lp.get('pattern', '')}: {reflected}")
            lines.append("")

    lines.append(f"Session count: {snapshot.get('session_count', 0)}")
    lines.append(f"Current C_emo: {snapshot.get('C_emo', 0):.3f}")

    return "\n".join(lines)
