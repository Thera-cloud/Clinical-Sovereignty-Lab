"""
PGSD field engine — TFIM-like Hamiltonian spectrum + fidelity tracking.  # QUANTUM-CRYSTAL-ARCH

Gated by ENABLE_PGSD_FIELD. Never raises into callers; 5s soft timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_MAX_SITES = 8
_PURE_EIG_MAX = 6
_SOFT_TIMEOUT_S = 5.0


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def field_enabled() -> bool:
    return _env_true("PGSD_ENABLED") and _env_true("ENABLE_PGSD_FIELD")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _eigh_symmetric_pure(h: Sequence[Sequence[float]]) -> Tuple[List[float], List[List[float]]]:
    """
    Symmetric eigendecomposition for N<=6 via Jacobi rotations.
    Returns (eigenvalues ascending, eigenvectors as columns in orthonormal matrix).
    """
    n = len(h)
    if n == 0:
        return [], []
    a = [[float(h[i][j]) for j in range(n)] for i in range(n)]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]

    for _ in range(max(20, 4 * n * n)):
        p, q = 0, 1
        max_off = abs(a[p][q])
        for i in range(n):
            for j in range(i + 1, n):
                if abs(a[i][j]) > max_off:
                    max_off = abs(a[i][j])
                    p, q = i, j
        if max_off < 1e-10:
            break
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        if abs(apq) < 1e-14:
            continue
        phi = 0.5 * __import__("math").atan2(2.0 * apq, aqq - app)
        c, s = __import__("math").cos(phi), __import__("math").sin(phi)
        for i in range(n):
            if i not in (p, q):
                aip, aiq = a[i][p], a[i][q]
                a[i][p] = c * aip - s * aiq
                a[p][i] = a[i][p]
                a[i][q] = s * aip + c * aiq
                a[q][i] = a[i][q]
        app2 = c * c * app - 2 * s * c * apq + s * s * aqq
        aqq2 = s * s * app + 2 * s * c * apq + c * c * aqq
        a[p][p], a[q][q] = app2, aqq2
        a[p][q] = a[q][p] = 0.0
        for i in range(n):
            vip, viq = v[i][p], v[i][q]
            v[i][p] = c * vip - s * viq
            v[i][q] = s * vip + c * viq

    evals = [a[i][i] for i in range(n)]
    pairs = sorted(enumerate(evals), key=lambda x: x[1])
    order = [p[0] for p in pairs]
    evals_sorted = [p[1] for p in pairs]
    vectors = [[v[i][j] for i in range(n)] for j in order]
    return evals_sorted, vectors


def _eigh_symmetric(h: Sequence[Sequence[float]]) -> Tuple[List[float], List[List[float]]]:
    n = len(h)
    if n <= _PURE_EIG_MAX:
        try:
            import numpy as np

            mat = np.array([[float(h[i][j]) for j in range(n)] for i in range(n)])
            w, vecs = np.linalg.eigh(mat)
            return [float(x) for x in w.tolist()], [list(map(float, col)) for col in vecs.T]
        except Exception:
            pass
    return _eigh_symmetric_pure(h)


def _build_site_hamiltonian(
    coord: Dict[str, Any],
    j_coupling: float,
    h_drive: float,
) -> List[List[float]]:
    """Local field + drive on diagonal; coupling encoded at spectrum build time."""
    h0 = (
        _safe_float(coord.get("d1_valence"), 0.0) * 0.2
        + _safe_float(coord.get("d2_arousal"), 0.0) * 0.15
        + _safe_float(coord.get("d3_relational"), 0.0) * 0.2
        + _safe_float(coord.get("d4_temporal_depth"), 0.0) * 0.15
        + _safe_float(coord.get("d5_integration"), 0.0) * 0.3
    )
    local = h0 + h_drive
    return [[local, -abs(j_coupling)], [-abs(j_coupling), local]]


def _tfim_chain_hamiltonian(
    locals_h: List[float],
    j_values: List[float],
) -> List[List[float]]:
    """Open-chain TFIM-like H on N spins (Pauli-Z basis energy levels)."""
    n = len(locals_h)
    dim = 1 << n
    h_mat = [[0.0] * dim for _ in range(dim)]

    def bit(state: int, i: int) -> int:
        return (state >> i) & 1

    for state in range(dim):
        energy = 0.0
        for i in range(n):
            s = 1.0 if bit(state, i) else -1.0
            energy += locals_h[i] * s
        for i in range(n - 1):
            si = 1.0 if bit(state, i) else -1.0
            sj = 1.0 if bit(state, i + 1) else -1.0
            energy += j_values[i] * si * sj
        h_mat[state][state] = energy
    return h_mat


class PGSDFieldEngine:
    def __init__(self, db_pool: Any = None):
        self.db_pool = db_pool

    async def _load_member_coords(self, user_ids: List[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not self.db_pool:
            return out
        async with self.db_pool.acquire() as conn:
            for uid in user_ids:
                row = await conn.fetchrow(
                    """
                    SELECT s.user_id, s.username,
                           u.profile_data->>'family_id' AS family_id,
                           s.d1_valence, s.d2_arousal, s.d3_relational,
                           s.d4_temporal_depth, s.d5_integration, s.coherence
                    FROM pgsd_snapshots s
                    LEFT JOIN users u ON u.hardware_id = s.user_id
                    WHERE s.user_id = $1
                    ORDER BY s.computed_at DESC
                    LIMIT 1
                    """,
                    uid,
                )
                if row:
                    out.append(dict(row))
        return out

    async def _rank_by_coupling(
        self, members: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if len(members) <= _MAX_SITES:
            return members
        scored = []
        for m in members:
            j_eff = abs(_safe_float(m.get("d3_relational"), 0.0))
            scored.append((j_eff, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:_MAX_SITES]]

    def _assemble_hamiltonian(self, members: List[Dict[str, Any]]) -> Tuple[List[List[float]], Dict[str, Any]]:
        n = len(members)
        if n == 0:
            return [[0.0]], {"n_sites": 0}
        if n == 1:
            c = members[0]
            loc = _safe_float(c.get("d5_integration"), 0.5) - 0.5
            return [[loc]], {"n_sites": 1, "g_control": 0.0}

        locals_h: List[float] = []
        j_values: List[float] = []
        g_control = 0.0
        for i, m in enumerate(members):
            coh = _safe_float(m.get("coherence"), 0.5)
            h_drive = (coh - 0.5) * 0.4
            local = (
                _safe_float(m.get("d1_valence"), 0.0) * 0.15
                + _safe_float(m.get("d5_integration"), 0.0) * 0.35
                + h_drive
            )
            locals_h.append(local)
            g_control += h_drive
            if i < n - 1:
                j = _safe_float(m.get("d3_relational"), 0.0) * _safe_float(
                    members[i + 1].get("d3_relational"), 0.0
                )
                j_values.append(j)

        if n <= _PURE_EIG_MAX:
            h_mat = _tfim_chain_hamiltonian(locals_h, j_values)
        else:
            # Fallback: tridiagonal approximation
            h_mat = [[0.0] * n for _ in range(n)]
            for i in range(n):
                h_mat[i][i] = locals_h[i]
                if i + 1 < n:
                    h_mat[i][i + 1] = j_values[i] if i < len(j_values) else 0.0
                    h_mat[i + 1][i] = h_mat[i][i + 1]

        meta = {
            "n_sites": n,
            "locals_h": locals_h,
            "j_values": j_values,
            "g_control": round(g_control / max(n, 1), 4),
        }
        return h_mat, meta

    async def compute_spectrum(self, user_ids: List[str]) -> Dict[str, Any]:
        """Compute field spectrum for up to 8 members; persist spectrum + ground state."""
        result: Dict[str, Any] = {"enabled": field_enabled(), "user_ids": user_ids}
        try:
            if not field_enabled() or not self.db_pool or not user_ids:
                return result

            async def _inner() -> Dict[str, Any]:
                members = await self._load_member_coords(list(user_ids))
                members = await self._rank_by_coupling(members)
                if not members:
                    return result
                h_mat, meta = self._assemble_hamiltonian(members)
                evals, _vecs = await asyncio.to_thread(_eigh_symmetric, h_mat)
                ground = float(evals[0]) if evals else 0.0
                gap = float(evals[1] - evals[0]) if len(evals) > 1 else 0.0
                family_id = members[0].get("family_id")
                primary = members[0]
                hw = primary.get("user_id")
                username = primary.get("username") or ""
                ground_coords = {
                    "d1": primary.get("d1_valence"),
                    "d2": primary.get("d2_arousal"),
                    "d3": primary.get("d3_relational"),
                    "d4": primary.get("d4_temporal_depth"),
                    "d5": primary.get("d5_integration"),
                }

                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO pgsd_field_spectrum (
                            user_id, family_id, eigenvalues,
                            ground_energy, gap, g_control, meta_json
                        ) VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7::jsonb)
                        """,
                        hw,
                        family_id,
                        json.dumps([round(float(e), 6) for e in evals]),
                        ground,
                        gap,
                        meta.get("g_control"),
                        json.dumps(meta),
                    )
                    prior = await conn.fetchrow(
                        """
                        SELECT ground_energy FROM pgsd_ground_states
                        WHERE user_id = $1
                        ORDER BY computed_at DESC
                        LIMIT 1
                        """,
                        hw,
                    )
                    prior_e = _safe_float((prior or {}).get("ground_energy"), ground)
                    relocation = abs(ground - prior_e)
                    await conn.execute(
                        """
                        INSERT INTO pgsd_ground_states (
                            user_id, username, ground_energy, ground_coords,
                            prior_energy, relocation
                        ) VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                        """,
                        hw,
                        username or None,
                        ground,
                        json.dumps(ground_coords),
                        prior_e,
                        relocation,
                    )

                result.update(
                    {
                        "ground_energy": ground,
                        "gap": gap,
                        "eigenvalues": evals,
                        "meta": meta,
                    }
                )
                return result

            return await asyncio.wait_for(_inner(), timeout=_SOFT_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.debug("PGSDFieldEngine.compute_spectrum timed out")
            result["timeout"] = True
            return result
        except Exception as e:
            logger.debug("PGSDFieldEngine.compute_spectrum failed: %s", e)
            return result

    async def track_hamiltonian(
        self,
        user_id: str,
        snapshot_id: Optional[int],
    ) -> Dict[str, Any]:
        """Fidelity vs prior snapshot Hamiltonian parameters."""
        out: Dict[str, Any] = {"user_id": user_id, "snapshot_id": snapshot_id}
        try:
            if not field_enabled() or not self.db_pool or not user_id:
                return out

            async def _inner() -> Dict[str, Any]:
                async with self.db_pool.acquire() as conn:
                    curr = await conn.fetchrow(
                        """
                        SELECT id, user_id, username,
                               d1_valence, d2_arousal, d3_relational,
                               d4_temporal_depth, d5_integration, coherence, fidelity
                        FROM pgsd_snapshots
                        WHERE user_id = $1
                        ORDER BY computed_at DESC
                        LIMIT 1
                        """,
                        user_id,
                    )
                    prior = await conn.fetchrow(
                        """
                        SELECT id, d1_valence, d2_arousal, d3_relational,
                               d4_temporal_depth, d5_integration, coherence, fidelity
                        FROM pgsd_snapshots
                        WHERE user_id = $1 AND id <> COALESCE($2, -1)
                        ORDER BY computed_at DESC
                        LIMIT 1
                        """,
                        user_id,
                        snapshot_id,
                    )
                    if not curr:
                        return out
                    fid_qt = _safe_float(curr.get("fidelity"), 1.0)
                    if prior:
                        diffs = [
                            abs(
                                _safe_float(curr.get(k), 0.0)
                                - _safe_float(prior.get(k), 0.0)
                            )
                            for k in (
                                "d1_valence",
                                "d2_arousal",
                                "d3_relational",
                                "d4_temporal_depth",
                                "d5_integration",
                            )
                        ]
                        coord_fid = max(0.0, 1.0 - sum(diffs) / max(len(diffs), 1))
                    else:
                        coord_fid = 1.0
                    fidelity = round(0.6 * fid_qt + 0.4 * coord_fid, 4)
                    tau_delta = round(1.0 - fidelity, 4)
                    h_params = {
                        "coord_fidelity": coord_fid,
                        "qt_fidelity": fid_qt,
                        "snapshot_id": snapshot_id or curr.get("id"),
                    }
                    await conn.execute(
                        """
                        INSERT INTO pgsd_hamiltonian_track (
                            user_id, username, snapshot_id,
                            fidelity, tau_delta, h_params
                        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                        """,
                        user_id,
                        curr.get("username"),
                        snapshot_id or curr.get("id"),
                        fidelity,
                        tau_delta,
                        json.dumps(h_params),
                    )
                    out.update(
                        {
                            "fidelity": fidelity,
                            "tau_delta": tau_delta,
                            "h_params": h_params,
                        }
                    )
                    return out

            return await asyncio.wait_for(_inner(), timeout=_SOFT_TIMEOUT_S)
        except asyncio.TimeoutError:
            out["timeout"] = True
            return out
        except Exception as e:
            logger.debug("PGSDFieldEngine.track_hamiltonian failed: %s", e)
            return out


__all__ = [
    "PGSDFieldEngine",
    "_eigh_symmetric",
    "_eigh_symmetric_pure",
    "_build_site_hamiltonian",
    "field_enabled",
]
