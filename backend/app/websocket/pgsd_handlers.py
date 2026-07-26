"""
PGSD WebSocket router  # QUANTUM-CRYSTAL-ARCH

Self-contained dispatcher for the Planetary Galactic Scale Detector
(PGSD) message types. Wired into bridge_server.py behind the PGSD_ENABLED
feature flag so the production WebSocket backbone stays untouched if the
flag is off.

Handles:
    pgsd_compute_snapshot          (COACH/ADMIN)
    pgsd_get_history               (COACH/ADMIN)
    pgsd_get_trajectory            (COACH/ADMIN)
    pgsd_get_family_entanglement   (COACH/ADMIN)
    pgsd_get_zero_time_route       (COACH/ADMIN)
    pgsd_get_chat_timeline         (COACH/ADMIN) — ACCESS
    pgsd_get_discernment           (COACH/ADMIN) — ACCESS
    pgsd_get_cross_domain_series   (COACH/ADMIN) — ACCESS
    pgsd_get_trauma_wells          (COACH/ADMIN) — FIELD
    pgsd_get_ground_state          (COACH/ADMIN) — FIELD

Plus an auto-trigger entry point:
    schedule_for_user(user_id, source)
        — debounced, max one snapshot per hour per user.
        — call from crystallizer / multimodal-fusion / wisdom absorber.

This module is intentionally self-contained:
    * Only imports stdlib + app.services.pgsd_engine.PGSDEngine.
    * All DB access guarded by try/except — never raises into the bridge.
    * All replies are JSON-safe dicts; the bridge serializes + sends.
    * Role gating enforced inside every handler.
    * Backed by tables created in backend/migrations/191_pgsd_tables.sql.

Located in: backend/app/websocket/pgsd_handlers.py
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from app.services.pgsd_engine import PGSDEngine, SpatioTemporalComputer
except Exception:  # pragma: no cover — defensive
    PGSDEngine = None         # type: ignore[assignment]
    SpatioTemporalComputer = None  # type: ignore[assignment]


# Public set used by bridge_server.py to extend _SENTINEL_SKIP.
PGSD_MESSAGE_TYPES: frozenset = frozenset((
    "pgsd_compute_snapshot",
    "pgsd_get_history",
    "pgsd_get_trajectory",
    "pgsd_get_family_entanglement",
    "pgsd_get_zero_time_route",
    "pgsd_get_chat_timeline",
    "pgsd_get_discernment",
    "pgsd_get_cross_domain_series",
    "pgsd_get_trauma_wells",
    "pgsd_get_ground_state",
))


# Minimum seconds between auto-triggered snapshots for the same user.
_DEBOUNCE_SECONDS: int = 3600  # one per hour
_FAST_DEBOUNCE_SECONDS: int = 600  # live_activation / enroll


def _is_coach_or_admin(profile: Optional[Dict]) -> bool:
    if not profile:
        return False
    return profile.get("role") in ("COACH", "ADMIN")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PGSDWebSocketRouter:
    """Dispatcher + persistence for PGSD WebSocket messages."""

    def __init__(self, db_pool: Any = None):
        self.db = db_pool
        self.engine = PGSDEngine(db_pool=db_pool) if PGSDEngine else None
        self.spatial = SpatioTemporalComputer() if SpatioTemporalComputer else None

        # Debounce state: { user_id: last_unix_ts }
        self._last_compute: Dict[str, float] = {}
        # Background trigger tasks we keep references to so they aren't GC'd.
        self._bg_tasks: set = set()

    # ─── Public entry points ──────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self.engine is not None

    async def dispatch(
        self,
        t: str,
        data: Dict,
        current_profile: Optional[Dict],
    ) -> Optional[Dict]:
        """
        Handle one PGSD message. Returns the reply dict to send (or None
        if the message type is not ours). Never raises.
        """
        if t not in PGSD_MESSAGE_TYPES:
            return None
        if not self.enabled:
            return self._err(t, "PGSD engine unavailable")
        if not _is_coach_or_admin(current_profile):
            return self._err(t, "COACH or ADMIN role required", code="forbidden")

        try:
            if t == "pgsd_compute_snapshot":
                return await self._handle_compute_snapshot(data)
            if t == "pgsd_get_history":
                return await self._handle_get_history(data)
            if t == "pgsd_get_trajectory":
                return await self._handle_get_trajectory(data)
            if t == "pgsd_get_family_entanglement":
                return await self._handle_get_family_entanglement(data)
            if t == "pgsd_get_zero_time_route":
                return await self._handle_get_zero_time_route(data)
            if t == "pgsd_get_chat_timeline":
                return await self._handle_get_chat_timeline(data)
            if t == "pgsd_get_discernment":
                return await self._handle_get_discernment(data)
            if t == "pgsd_get_cross_domain_series":
                return await self._handle_get_cross_domain(data)
            if t == "pgsd_get_trauma_wells":
                return await self._handle_get_trauma_wells(data)
            if t == "pgsd_get_ground_state":
                return await self._handle_get_ground_state(data)
        except Exception as e:
            return self._err(t, f"internal: {e!s}")
        return None

    def schedule_for_user(
        self,
        user_id: str,
        source: str = "auto",
        debounce_seconds: Optional[int] = None,
    ) -> bool:
        """
        Fire-and-forget background snapshot. Debounced per-user.
        Returns True if a task was scheduled, False if debounced/disabled.
        Safe to call from sync or async code.
        """
        if not self.enabled or not user_id:
            return False
        source = (source or "auto").strip() if isinstance(source, str) else "auto"
        if not source:
            source = "auto"
        now = time.time()
        last = self._last_compute.get(user_id, 0.0)
        floor = debounce_seconds if debounce_seconds is not None else _DEBOUNCE_SECONDS
        if (now - last) < floor:
            return False
        self._last_compute[user_id] = now

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return False
        task = loop.create_task(self._bg_compute(user_id, source))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return True

    def schedule_for_user_fast(self, user_id: str, source: str = "live_activation") -> bool:
        """10-minute debounce path for enroll / live activation. # QUANTUM-CRYSTAL-ARCH"""
        return self.schedule_for_user(
            user_id, source=source, debounce_seconds=_FAST_DEBOUNCE_SECONDS
        )

    # ─── Handlers ─────────────────────────────────────────────────────

    async def _handle_compute_snapshot(self, data: Dict) -> Dict:
        client_id = (data.get("client_id") or "").strip()
        if not client_id:
            return self._err("pgsd_compute_snapshot", "client_id required")

        # QUANTUM-CRYSTAL-ARCH — resolve to hardware_id before persist + ACCESS/FIELD
        resolved = await self.engine.resolve_pgsd_subject(client_id)
        save_key = (resolved or {}).get("hardware_id") or client_id
        username = (resolved or {}).get("username") or ""

        prev = await self._load_latest_snapshot(save_key)

        pgsd = await self.engine.compute_full_pgsd(client_id)
        pgsd["computed_at"] = _utc_now_iso()
        pgsd["_trigger_source"] = "admin_compute"
        if username:
            pgsd["_username"] = username

        evolution = None
        route = None
        if prev:
            try:
                prev_density = (prev.get("full_pgsd") or {}).get(
                    "quantum_trace", {}).get("density_matrix", {})
                curr_density = pgsd.get("quantum_trace", {}).get("density_matrix", {})
                evolution = self.engine.trace.compute_lindblad_evolution(
                    curr_density, prev_density,
                    decoherence_events=0,
                    therapeutic_interventions=1,
                )
                route = self.engine.trace.compute_zero_time_route(
                    prev_density, curr_density)
            except Exception:
                evolution = None
                route = None

        snapshot_id = await self._save_snapshot(save_key, pgsd, evolution)
        self._last_compute[save_key] = time.time()
        # QUANTUM-CRYSTAL-ARCH — same ACCESS/FIELD follow-ups as auto-trigger path
        self._kick_access_field_followups(save_key, snapshot_id, "admin_compute")

        return {
            "type": "pgsd_snapshot",
            "ok": True,
            "snapshot_id": snapshot_id,
            "client_id": save_key,
            "pgsd": pgsd,
            "evolution_from_previous": evolution,
            "zero_time_route_from_previous": route,
        }

    async def _handle_get_history(self, data: Dict) -> Dict:
        client_id = (data.get("client_id") or "").strip()
        if not client_id:
            return self._err("pgsd_history", "client_id required")
        try:
            limit = int(data.get("limit", 20))
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(200, limit))

        rows = await self._fetch_history_rows(client_id, limit)
        snapshots: List[Dict] = []
        for r in rows:
            snapshots.append(self._row_to_summary(r))
        return {
            "type": "pgsd_history",
            "ok": True,
            "client_id": client_id,
            "count": len(snapshots),
            "snapshots": snapshots,
        }

    async def _handle_get_trajectory(self, data: Dict) -> Dict:
        client_id = (data.get("client_id") or "").strip()
        if not client_id:
            return self._err("pgsd_trajectory", "client_id required")

        rows = await self._fetch_history_rows(client_id, 10)
        # Oldest → newest for trajectory direction.
        rows = list(reversed(rows))

        coords: List[Dict] = []
        for r in rows:
            coords.append({
                "d1_valence": float(r.get("d1_valence") or 0),
                "d2_arousal": float(r.get("d2_arousal") or 0),
                "d3_relational": float(r.get("d3_relational") or 0),
                "d4_temporal_depth": float(r.get("d4_temporal_depth") or 0),
                "d5_integration": float(r.get("d5_integration") or 0),
                "magnitude": float(r.get("coordinate_magnitude") or 0),
            })

        if not self.spatial or len(coords) < 3:
            return {
                "type": "pgsd_trajectory",
                "ok": True,
                "client_id": client_id,
                "trajectory": {"trajectory": "insufficient_data"},
                "coordinate_count": len(coords),
            }

        traj = self.spatial.compute_latent_trajectory(coords, window=10)
        return {
            "type": "pgsd_trajectory",
            "ok": True,
            "client_id": client_id,
            "coordinate_count": len(coords),
            "trajectory": traj,
        }

    async def _handle_get_family_entanglement(self, data: Dict) -> Dict:
        family_id = (data.get("family_id") or "").strip()
        if not family_id:
            return self._err("pgsd_family_entanglement", "family_id required")

        members = await self._load_family_members(family_id)
        if not members:
            return {
                "type": "pgsd_family_entanglement",
                "ok": True,
                "family_id": family_id,
                "members": [],
                "couplings": [],
                "note": "no members or family lookup failed",
            }

        # Compute PGSD for each member.
        per_member: List[Dict] = []
        for uid in members:
            try:
                pgsd = await self.engine.compute_full_pgsd(uid)
                per_member.append({"user_id": uid, "pgsd": pgsd})
            except Exception:
                continue

        # Pairwise partial-trace coupling.
        couplings: List[Dict] = []
        n = len(per_member)
        for i in range(n):
            for j in range(i + 1, n):
                a = per_member[i]
                b = per_member[j]
                try:
                    a_density = a["pgsd"].get("quantum_trace", {}).get("density_matrix", {})
                    b_density = b["pgsd"].get("quantum_trace", {}).get("density_matrix", {})
                    partial = self.engine.trace.compute_partial_trace(
                        a_density, b_density)
                    coupling = float(partial.get("environmental_coupling", 0.0))
                    shared = self._shared_gravity_wells(a_density, b_density)
                    couplings.append({
                        "member_a": a["user_id"],
                        "member_b": b["user_id"],
                        "entanglement_strength": round(coupling, 4),
                        "coupling_coefficient": round(coupling, 4),
                        "shared_gravity_wells": shared,
                        "decoupled": bool(partial.get("decoupled", False)),
                    })
                    await self._save_family_entanglement(
                        family_id, a["user_id"], b["user_id"],
                        coupling, shared,
                    )
                except Exception:
                    continue

        return {
            "type": "pgsd_family_entanglement",
            "ok": True,
            "family_id": family_id,
            "members": [
                {
                    "user_id": m["user_id"],
                    "coordinate_5d": m["pgsd"].get("coordinate_5d", {}),
                    "fingerprint": m["pgsd"].get("emotional_fingerprint"),
                    "tduft": m["pgsd"].get("tduft", {}),
                    "timescape": m["pgsd"].get("timescape", {}),
                }
                for m in per_member
            ],
            "couplings": couplings,
        }

    async def _handle_get_zero_time_route(self, data: Dict) -> Dict:
        client_id = (data.get("client_id") or "").strip()
        try:
            origin_id = int(data.get("origin_snapshot_id"))
            dest_id = int(data.get("destination_snapshot_id"))
        except (TypeError, ValueError):
            return self._err(
                "pgsd_zero_time_route",
                "origin_snapshot_id and destination_snapshot_id required (int)",
            )
        if not client_id:
            return self._err("pgsd_zero_time_route", "client_id required")

        origin = await self._load_snapshot_by_id(origin_id)
        dest = await self._load_snapshot_by_id(dest_id)
        if not origin or not dest:
            return self._err("pgsd_zero_time_route", "snapshot(s) not found")

        try:
            o_density = (origin.get("full_pgsd") or {}).get(
                "quantum_trace", {}).get("density_matrix", {})
            d_density = (dest.get("full_pgsd") or {}).get(
                "quantum_trace", {}).get("density_matrix", {})
            route = self.engine.trace.compute_zero_time_route(o_density, d_density)
        except Exception as e:
            return self._err("pgsd_zero_time_route", f"compute failed: {e!s}")

        await self._save_trajectory(client_id, origin_id, dest_id, route)

        return {
            "type": "pgsd_zero_time_route",
            "ok": True,
            "client_id": client_id,
            "origin_snapshot_id": origin_id,
            "destination_snapshot_id": dest_id,
            "route": route,
        }

    # ─── ACCESS / FIELD read handlers ─────────────────────────────────

    async def _handle_get_chat_timeline(self, data: Dict) -> Dict:
        client_id = (data.get("client_id") or "").strip()
        if not client_id:
            return self._err("pgsd_get_chat_timeline", "client_id required")
        if not self.db:
            return self._err("pgsd_get_chat_timeline", "db unavailable")
        try:
            resolved = await self.engine.resolve_pgsd_subject(client_id)
            hw = (resolved or {}).get("hardware_id") or client_id
            limit = min(int(data.get("limit") or 40), 100)
            async with self.db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, snapshot_id, surface, session_id,
                           turn_created_at, text_prefix, created_at
                    FROM pgsd_chat_correlation
                    WHERE user_id = $1
                    ORDER BY COALESCE(turn_created_at, created_at) DESC
                    LIMIT $2
                    """,
                    hw,
                    limit,
                )
            turns = []
            for r in rows:
                turns.append(
                    {
                        "id": r["id"],
                        "snapshot_id": r["snapshot_id"],
                        "surface": r["surface"],
                        "session_id": r["session_id"],
                        "turn_created_at": r["turn_created_at"].isoformat()
                        if r.get("turn_created_at")
                        else None,
                        "text_prefix": r["text_prefix"],
                        "created_at": r["created_at"].isoformat()
                        if r.get("created_at")
                        else None,
                    }
                )
            return {
                "type": "pgsd_chat_timeline",
                "ok": True,
                "client_id": hw,
                "turns": turns,
            }
        except Exception as e:
            return self._err("pgsd_get_chat_timeline", f"{e!s}")

    async def _handle_get_discernment(self, data: Dict) -> Dict:
        client_id = (data.get("client_id") or "").strip()
        if not client_id:
            return self._err("pgsd_get_discernment", "client_id required")
        try:
            from app.services.pgsd_discernment_scorer import PGSDDiscernmentScorer

            scorer = PGSDDiscernmentScorer(db_pool=self.db)
            result = await scorer.score_user(client_id)
            return {
                "type": "pgsd_discernment",
                "ok": True,
                "client_id": result.get("user_id") or client_id,
                "scores": result,
            }
        except Exception as e:
            return self._err("pgsd_get_discernment", f"{e!s}")

    async def _handle_get_cross_domain(self, data: Dict) -> Dict:
        client_id = (data.get("client_id") or "").strip()
        if not client_id:
            return self._err("pgsd_get_cross_domain_series", "client_id required")
        try:
            from app.services.pgsd_correlation import compute_cross_domain_series

            days = min(int(data.get("days") or 30), 90)
            series = await compute_cross_domain_series(self.db, client_id, days=days)
            return {
                "type": "pgsd_cross_domain_series",
                "ok": True,
                "client_id": series.get("user_id") or client_id,
                "series": series,
            }
        except Exception as e:
            return self._err("pgsd_get_cross_domain_series", f"{e!s}")

    async def _handle_get_trauma_wells(self, data: Dict) -> Dict:
        client_id = (data.get("client_id") or "").strip()
        if not client_id:
            return self._err("pgsd_get_trauma_wells", "client_id required")
        if not self.db:
            return self._err("pgsd_get_trauma_wells", "db unavailable")
        try:
            from app.services.pgsd_trauma_wells import TraumaWellEngine

            eng = TraumaWellEngine(db_pool=self.db)
            await eng.refresh_wells(client_id)
            resolved = await self.engine.resolve_pgsd_subject(client_id)
            hw = (resolved or {}).get("hardware_id") or client_id
            async with self.db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, temporal_class, depth, source_tag, collapsed,
                           d1_valence, d2_arousal, d3_relational,
                           d4_temporal, d5_integration, created_at
                    FROM pgsd_trauma_wells
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT 40
                    """,
                    hw,
                )
            wells = [dict(r) for r in rows]
            for w in wells:
                if w.get("created_at"):
                    w["created_at"] = w["created_at"].isoformat()
            return {
                "type": "pgsd_trauma_wells",
                "ok": True,
                "client_id": hw,
                "wells": wells,
            }
        except Exception as e:
            return self._err("pgsd_get_trauma_wells", f"{e!s}")

    async def _handle_get_ground_state(self, data: Dict) -> Dict:
        client_id = (data.get("client_id") or "").strip()
        if not client_id:
            return self._err("pgsd_get_ground_state", "client_id required")
        try:
            from app.services.pgsd_field_engine import PGSDFieldEngine

            resolved = await self.engine.resolve_pgsd_subject(client_id)
            hw = (resolved or {}).get("hardware_id") or client_id
            field = PGSDFieldEngine(db_pool=self.db)
            await field.compute_spectrum([hw])
            ground = None
            if self.db:
                async with self.db.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT ground_energy, ground_coords, prior_energy,
                               relocation, computed_at
                        FROM pgsd_ground_states
                        WHERE user_id = $1
                        ORDER BY computed_at DESC
                        LIMIT 1
                        """,
                        hw,
                    )
                    if row:
                        ground = dict(row)
                        if ground.get("computed_at"):
                            ground["computed_at"] = ground["computed_at"].isoformat()
                        coords = ground.get("ground_coords")
                        if isinstance(coords, str):
                            try:
                                ground["ground_coords"] = json.loads(coords)
                            except Exception:
                                pass
            return {
                "type": "pgsd_ground_state",
                "ok": True,
                "client_id": hw,
                "ground": ground,
            }
        except Exception as e:
            return self._err("pgsd_get_ground_state", f"{e!s}")

    # ─── Background auto-trigger ──────────────────────────────────────

    async def _bg_compute(self, user_id: str, source: str) -> None:
        try:
            resolved = await self.engine.resolve_pgsd_subject(user_id)
            save_key = (resolved or {}).get("hardware_id") or user_id
            username = (resolved or {}).get("username") or ""
            prev = await self._load_latest_snapshot(save_key)
            pgsd = await self.engine.compute_full_pgsd(user_id)
            pgsd["computed_at"] = _utc_now_iso()
            pgsd["_trigger_source"] = source
            if username:
                pgsd["_username"] = username
            # QUANTUM-CRYSTAL-ARCH — Lindblad vs prior on auto-triggers too
            evolution = None
            if prev:
                try:
                    prev_density = (prev.get("full_pgsd") or {}).get(
                        "quantum_trace", {}
                    ).get("density_matrix", {})
                    curr_density = pgsd.get("quantum_trace", {}).get(
                        "density_matrix", {}
                    )
                    evolution = self.engine.trace.compute_lindblad_evolution(
                        curr_density,
                        prev_density,
                        decoherence_events=0,
                        therapeutic_interventions=1,
                    )
                except Exception:
                    evolution = None
            snapshot_id = await self._save_snapshot(save_key, pgsd, evolution)
            # QUANTUM-CRYSTAL-ARCH — ACCESS/FIELD follow-ups (shared with admin compute)
            self._kick_access_field_followups(save_key, snapshot_id, source)
        except Exception:
            # Auto-triggers must NEVER surface errors.
            return

    def _kick_access_field_followups(
        self,
        save_key: str,
        snapshot_id: Optional[int],
        source: str,
    ) -> None:
        """Fire-and-forget ACCESS + FIELD writers after a snapshot persist."""
        if not snapshot_id or not self.db or not save_key:
            return
        try:
            import os

            access_on = os.environ.get("ENABLE_PGSD_ACCESS", "").strip().lower() in (
                "1", "true", "yes", "on",
            )
            field_on = os.environ.get("ENABLE_PGSD_FIELD", "").strip().lower() in (
                "1", "true", "yes", "on",
            )
            master = os.environ.get("PGSD_ENABLED", "").strip().lower() in (
                "1", "true", "yes", "on",
            )
            if not master:
                return
            if access_on:
                from app.services.pgsd_correlation import (
                    compute_cross_domain_series,
                    correlate_recent_chat,
                )
                from app.services.pgsd_discernment_scorer import PGSDDiscernmentScorer

                asyncio.create_task(
                    correlate_recent_chat(self.db, save_key, snapshot_id, source)
                )
                asyncio.create_task(
                    PGSDDiscernmentScorer(db_pool=self.db).score_user(save_key)
                )
                asyncio.create_task(compute_cross_domain_series(self.db, save_key))
            if field_on:
                from app.services.pgsd_field_engine import PGSDFieldEngine
                from app.services.pgsd_trauma_wells import TraumaWellEngine

                asyncio.create_task(
                    TraumaWellEngine(db_pool=self.db).refresh_wells(save_key)
                )
                asyncio.create_task(
                    PGSDFieldEngine(db_pool=self.db).track_hamiltonian(
                        save_key, snapshot_id
                    )
                )
        except Exception:
            pass

    # ─── Persistence (all guarded; never raise) ───────────────────────

    async def _save_snapshot(
        self,
        user_id: str,
        pgsd: Dict,
        evolution: Optional[Dict],
    ) -> Optional[int]:
        if not self.db:
            return None
        try:
            tduft = pgsd.get("tduft", {}) or {}
            ts = pgsd.get("timescape", {}) or {}
            qt = pgsd.get("quantum_trace", {}) or {}
            coord = pgsd.get("coordinate_5d", {}) or {}
            dens = qt.get("density_matrix", {}) or {}
            partial = qt.get("partial_trace", {}) or {}
            evo = evolution or {}
            username = pgsd.get("_username") or ""
            # QUANTUM-CRYSTAL-ARCH — never persist NULL trigger_source (Tier-2 v2 packs)
            trigger_source = (pgsd.get("_trigger_source") or "auto")
            if isinstance(trigger_source, str):
                trigger_source = trigger_source.strip() or "auto"
            else:
                trigger_source = "auto"
            # Resolve username if missing (additive col from migration 283)
            if not username and self.engine:
                try:
                    resolved = await self.engine.resolve_pgsd_subject(user_id)
                    username = (resolved or {}).get("username") or ""
                except Exception:
                    username = ""
            async with self.db.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO pgsd_snapshots (
                        user_id, computed_at,
                        therapeutic_mass, pattern_gravity, therapeutic_energy,
                        velocity, time_density, noah_factor, active_dimensions,
                        void_fraction, time_dilation, session_region,
                        density_matrix, partial_trace, coherence, purity,
                        d1_valence, d2_arousal, d3_relational,
                        d4_temporal_depth, d5_integration, coordinate_magnitude,
                        emotional_fingerprint,
                        evolution_state, fidelity,
                        full_pgsd, source_metrics,
                        username, trigger_source
                    ) VALUES (
                        $1, NOW(),
                        $2, $3, $4,
                        $5, $6, $7, $8,
                        $9, $10, $11,
                        $12::jsonb, $13::jsonb, $14, $15,
                        $16, $17, $18,
                        $19, $20, $21,
                        $22,
                        $23, $24,
                        $25::jsonb, $26::jsonb,
                        $27, $28
                    )
                    RETURNING id
                    """,
                    user_id,
                    tduft.get("therapeutic_mass"),
                    tduft.get("pattern_gravity"),
                    tduft.get("therapeutic_energy"),
                    tduft.get("velocity"),
                    tduft.get("time_density"),
                    tduft.get("noah_factor"),
                    tduft.get("active_dimensions"),
                    ts.get("void_fraction"),
                    ts.get("time_dilation"),
                    ts.get("session_region"),
                    json.dumps(dens, default=str),
                    json.dumps(partial, default=str),
                    qt.get("coherence"),
                    qt.get("purity"),
                    coord.get("d1_valence"),
                    coord.get("d2_arousal"),
                    coord.get("d3_relational"),
                    coord.get("d4_temporal_depth"),
                    coord.get("d5_integration"),
                    coord.get("magnitude"),
                    pgsd.get("emotional_fingerprint"),
                    evo.get("evolution"),
                    evo.get("fidelity"),
                    json.dumps(pgsd, default=str),
                    json.dumps(pgsd.get("source_metrics", {}), default=str),
                    username or None,
                    trigger_source,
                )
                return int(row["id"]) if row else None
        except Exception:
            # Fallback without username cols if migration 283 not applied yet
            try:
                async with self.db.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO pgsd_snapshots (
                            user_id, computed_at,
                            therapeutic_mass, pattern_gravity, therapeutic_energy,
                            velocity, time_density, noah_factor, active_dimensions,
                            void_fraction, time_dilation, session_region,
                            density_matrix, partial_trace, coherence, purity,
                            d1_valence, d2_arousal, d3_relational,
                            d4_temporal_depth, d5_integration, coordinate_magnitude,
                            emotional_fingerprint,
                            evolution_state, fidelity,
                            full_pgsd, source_metrics
                        ) VALUES (
                            $1, NOW(),
                            $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                            $12::jsonb, $13::jsonb, $14, $15,
                            $16, $17, $18, $19, $20, $21, $22, $23, $24,
                            $25::jsonb, $26::jsonb
                        )
                        RETURNING id
                        """,
                        user_id,
                        tduft.get("therapeutic_mass"),
                        tduft.get("pattern_gravity"),
                        tduft.get("therapeutic_energy"),
                        tduft.get("velocity"),
                        tduft.get("time_density"),
                        tduft.get("noah_factor"),
                        tduft.get("active_dimensions"),
                        ts.get("void_fraction"),
                        ts.get("time_dilation"),
                        ts.get("session_region"),
                        json.dumps(dens, default=str),
                        json.dumps(partial, default=str),
                        qt.get("coherence"),
                        qt.get("purity"),
                        coord.get("d1_valence"),
                        coord.get("d2_arousal"),
                        coord.get("d3_relational"),
                        coord.get("d4_temporal_depth"),
                        coord.get("d5_integration"),
                        coord.get("magnitude"),
                        pgsd.get("emotional_fingerprint"),
                        evo.get("evolution"),
                        evo.get("fidelity"),
                        json.dumps(pgsd, default=str),
                        json.dumps(pgsd.get("source_metrics", {}), default=str),
                    )
                    return int(row["id"]) if row else None
            except Exception:
                return None

    async def _save_trajectory(
        self,
        user_id: str,
        origin_id: int,
        dest_id: int,
        route: Dict,
    ) -> None:
        if not self.db:
            return
        try:
            async with self.db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO pgsd_trajectories (
                        user_id, origin_snapshot_id, destination_snapshot_id,
                        route, dimensional_distance, estimated_sessions,
                        route_complexity
                    ) VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
                    """,
                    user_id, origin_id, dest_id,
                    json.dumps(route, default=str),
                    route.get("dimensional_distance"),
                    route.get("estimated_sessions"),
                    route.get("route_complexity"),
                )
        except Exception:
            return

    async def _save_family_entanglement(
        self,
        family_id: str,
        member_a: str,
        member_b: str,
        coupling: float,
        shared_wells: List[str],
    ) -> None:
        if not self.db:
            return
        try:
            async with self.db.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO pgsd_family_entanglement (
                        family_id, member_a_id, member_b_id,
                        entanglement_strength, shared_gravity_wells,
                        coupling_coefficient
                    ) VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                    """,
                    family_id, member_a, member_b,
                    float(coupling),
                    json.dumps(shared_wells, default=str),
                    float(coupling),
                )
        except Exception:
            return

    async def _load_latest_snapshot(self, user_id: str) -> Optional[Dict]:
        if not self.db:
            return None
        try:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, full_pgsd
                    FROM pgsd_snapshots
                    WHERE user_id = $1
                    ORDER BY computed_at DESC
                    LIMIT 1
                    """,
                    user_id,
                )
                if not row:
                    return None
                return {
                    "id": row["id"],
                    "full_pgsd": self._coerce_json(row["full_pgsd"]),
                }
        except Exception:
            return None

    async def _load_snapshot_by_id(self, snapshot_id: int) -> Optional[Dict]:
        if not self.db:
            return None
        try:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, user_id, full_pgsd
                    FROM pgsd_snapshots
                    WHERE id = $1
                    """,
                    int(snapshot_id),
                )
                if not row:
                    return None
                return {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "full_pgsd": self._coerce_json(row["full_pgsd"]),
                }
        except Exception:
            return None

    async def _fetch_history_rows(
        self, user_id: str, limit: int
    ) -> List[Dict]:
        if not self.db:
            return []
        try:
            async with self.db.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, computed_at,
                           therapeutic_mass, pattern_gravity, therapeutic_energy,
                           velocity, time_density, noah_factor, active_dimensions,
                           void_fraction, time_dilation, session_region,
                           coherence, purity,
                           d1_valence, d2_arousal, d3_relational,
                           d4_temporal_depth, d5_integration, coordinate_magnitude,
                           emotional_fingerprint, evolution_state, fidelity,
                           density_matrix, partial_trace, source_metrics
                    FROM pgsd_snapshots
                    WHERE user_id = $1
                    ORDER BY computed_at DESC
                    LIMIT $2
                    """,
                    user_id, int(limit),
                )
                return [dict(r) for r in rows]
        except Exception:
            return []

    async def _load_family_members(self, family_id: str) -> List[str]:
        if not self.db:
            return []
        try:
            async with self.db.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT DISTINCT user_id FROM family_members WHERE family_id = $1",
                    family_id,
                )
                return [r["user_id"] for r in rows if r.get("user_id")]
        except Exception:
            return []

    # ─── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _coerce_json(value: Any) -> Dict:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, (str, bytes)):
            try:
                return json.loads(value)
            except Exception:
                return {}
        return {}

    @staticmethod
    def _err(msg_type: str, error: str, code: str = "error") -> Dict:
        # Reply type derived from the request type (drop the trailing _request
        # if any, otherwise prefix with "pgsd_error_" for unknown shapes).
        reply_type = msg_type.replace("_compute_", "_").replace("_get_", "_")
        if not reply_type.startswith("pgsd_"):
            reply_type = "pgsd_error"
        return {
            "type": reply_type if reply_type != msg_type else "pgsd_error",
            "ok": False,
            "code": code,
            "error": error,
            "request_type": msg_type,
        }

    @staticmethod
    def _shared_gravity_wells(
        a_density: Dict, b_density: Dict, threshold: float = 0.15
    ) -> List[str]:
        """Dimensions where BOTH members have populations above threshold."""
        a_pops = (a_density or {}).get("populations", {}) or {}
        b_pops = (b_density or {}).get("populations", {}) or {}
        wells: List[str] = []
        for dim, a_val in a_pops.items():
            b_val = b_pops.get(dim, 0)
            try:
                if float(a_val) >= threshold and float(b_val) >= threshold:
                    wells.append(dim)
            except (TypeError, ValueError):
                continue
        return wells

    def row_to_summary(self, row: Dict) -> Dict:  # public alias
        return self._row_to_summary(row)

    @staticmethod
    def _row_to_summary(row: Dict) -> Dict:
        ca = row.get("computed_at")
        if isinstance(ca, datetime):
            ca = ca.isoformat()
        density = PGSDWebSocketRouter._coerce_json(row.get("density_matrix"))
        partial = PGSDWebSocketRouter._coerce_json(row.get("partial_trace"))
        source = PGSDWebSocketRouter._coerce_json(row.get("source_metrics"))
        return {
            "id": row.get("id"),
            "computed_at": ca,
            "tduft": {
                "therapeutic_mass": row.get("therapeutic_mass"),
                "pattern_gravity": row.get("pattern_gravity"),
                "therapeutic_energy": row.get("therapeutic_energy"),
                "velocity": row.get("velocity"),
                "time_density": row.get("time_density"),
                "noah_factor": row.get("noah_factor"),
                "active_dimensions": row.get("active_dimensions"),
            },
            "timescape": {
                "void_fraction": row.get("void_fraction"),
                "time_dilation": row.get("time_dilation"),
                "session_region": row.get("session_region"),
            },
            "quantum_trace": {
                "coherence": row.get("coherence"),
                "purity": row.get("purity"),
                # Full density-matrix populations + partial trace are loaded
                # so the dashboard heatmap renders on subject-select instead
                # of staying blank until the next manual Compute Now.
                "density_matrix": density,
                "partial_trace": partial,
            },
            "coordinate_5d": {
                "d1_valence": row.get("d1_valence"),
                "d2_arousal": row.get("d2_arousal"),
                "d3_relational": row.get("d3_relational"),
                "d4_temporal_depth": row.get("d4_temporal_depth"),
                "d5_integration": row.get("d5_integration"),
                "magnitude": row.get("coordinate_magnitude"),
            },
            "emotional_fingerprint": row.get("emotional_fingerprint"),
            "evolution": {
                "state": row.get("evolution_state"),
                "fidelity": row.get("fidelity"),
            },
            "source_metrics": source,
        }


__all__ = [
    "PGSDWebSocketRouter",
    "PGSD_MESSAGE_TYPES",
]
