"""
Distributed Defense Shield — Phase 8 of Sovereign Quantum Nate Build.

Implements Layers 2-9 of the defense architecture:
  L2: Distributed Curiosity Protocol (per-node state machine)
  L3: Crystal Integrity Helix (structural, coherence, entropy checks)
  L4: Per-Device Guardian Fibres (behavioral profiling)
  L5: Mesh-Wide DEFCON (regional isolation, ghost deploy, quantum collapse)
  L6: Mesh House of Mirrors + Ghost Swarm
  L7: Zero Knowledge Crystal Storage (mesh-wide + user-scoped encryption)
  L8: Distributed Canary System (unique per-device canaries)
  L9: Mesh Recon + Forensics
"""

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Layer 2: Distributed Curiosity Protocol
# ═══════════════════════════════════════════════════════════════

class CuriosityLevel(IntEnum):
    NONE = 0
    NOTICE = 1
    INTEREST = 2
    CONCERN = 3
    ALARM = 4


class DistributedCuriosityProtocol:
    """Per-node curiosity state machine for each observed source."""

    def __init__(self):
        self._states: Dict[str, Dict[str, Any]] = {}

    def observe(self, node_id: str, source_id: str, signal_type: str) -> CuriosityLevel:
        """Record an observation and return the new curiosity level."""
        key = f"{node_id}:{source_id}"
        state = self._states.setdefault(key, {
            "level": CuriosityLevel.NONE,
            "signals": [],
            "escalated_at": None,
        })

        now = time.time()
        state["signals"].append({"type": signal_type, "at": now})
        state["signals"] = [s for s in state["signals"] if now - s["at"] < 3600]

        # Escalation logic
        signal_count = len(state["signals"])
        unique_types = len(set(s["type"] for s in state["signals"]))

        if signal_count >= 50 or unique_types >= 10:
            state["level"] = CuriosityLevel.ALARM
        elif signal_count >= 20 or unique_types >= 6:
            state["level"] = CuriosityLevel.CONCERN
        elif signal_count >= 10:
            state["level"] = CuriosityLevel.INTEREST
        elif signal_count >= 3:
            state["level"] = CuriosityLevel.NOTICE

        if state["level"] >= CuriosityLevel.CONCERN and not state["escalated_at"]:
            state["escalated_at"] = now

        return CuriosityLevel(state["level"])

    def get_alarmed_sources(self) -> List[str]:
        return [
            k.split(":", 1)[1] for k, v in self._states.items()
            if v["level"] >= CuriosityLevel.ALARM
        ]

    def reset(self, node_id: str, source_id: str):
        self._states.pop(f"{node_id}:{source_id}", None)


# ═══════════════════════════════════════════════════════════════
# Layer 3: Crystal Integrity Helix
# ═══════════════════════════════════════════════════════════════

class HelixVerdict(Enum):
    INTACT = "intact"
    STRUCTURAL_FAIL = "structural_fail"
    COHERENCE_FAIL = "coherence_fail"
    ENTROPY_FAIL = "entropy_fail"


class CrystalIntegrityHelix:
    """Three-cord verification for intelligence crystals."""

    def __init__(self):
        self._known_hashes: Set[str] = set()

    def verify(self, crystal: Dict[str, Any]) -> HelixVerdict:
        """
        Run three sub-cord checks:
        1. Structural — valid schema, hash matches
        2. Coherence — connects to existing knowledge
        3. Entropy — genuinely novel, not replayed
        """
        # Cord 1: Structural
        required = {"crystal_text", "domain", "content_hash"}
        if not required.issubset(crystal.keys()):
            return HelixVerdict.STRUCTURAL_FAIL

        text = crystal["crystal_text"]
        domain = crystal.get("domain", "")
        scope = crystal.get("scope", "")
        gen = crystal.get("generation", 0)
        expected_hash = hashlib.sha256(
            f"{text}|{domain}|{scope}|{gen}".encode()
        ).hexdigest()

        if crystal["content_hash"] != expected_hash:
            return HelixVerdict.STRUCTURAL_FAIL

        # Cord 2: Coherence — text must be substantive
        if len(text) < 20 or len(text) > 50000:
            return HelixVerdict.COHERENCE_FAIL

        # Cord 3: Entropy — not a replay of known crystal
        if crystal["content_hash"] in self._known_hashes:
            return HelixVerdict.ENTROPY_FAIL

        self._known_hashes.add(crystal["content_hash"])
        if len(self._known_hashes) > 100000:
            oldest = list(self._known_hashes)[:50000]
            self._known_hashes = set(list(self._known_hashes)[50000:])

        return HelixVerdict.INTACT


# ═══════════════════════════════════════════════════════════════
# Layer 4: Per-Device Guardian Fibres
# ═══════════════════════════════════════════════════════════════

class DeviceGuardian:
    """Tracks behavioral profile for a single device."""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.submission_count = 0
        self.rejection_count = 0
        self.hour_distribution: Dict[int, int] = {}
        self.domain_distribution: Dict[str, int] = {}
        self.last_activity = 0.0
        self.anomaly_score = 0.0

    def record(self, domain: str, accepted: bool):
        now = time.time()
        hour = datetime.fromtimestamp(now, tz=timezone.utc).hour

        self.submission_count += 1
        self.hour_distribution[hour] = self.hour_distribution.get(hour, 0) + 1
        self.domain_distribution[domain] = self.domain_distribution.get(domain, 0) + 1
        if not accepted:
            self.rejection_count += 1
        self.last_activity = now

        self._update_anomaly_score()

    def _update_anomaly_score(self):
        score = 0.0

        # Rejection rate
        if self.submission_count > 10:
            rej_rate = self.rejection_count / self.submission_count
            if rej_rate > 0.5:
                score += 30

        # Concentration in single domain
        if self.domain_distribution:
            max_domain = max(self.domain_distribution.values())
            if self.submission_count > 10 and max_domain / self.submission_count > 0.9:
                score += 20

        # Unusual hour concentration
        if self.hour_distribution:
            max_hour_count = max(self.hour_distribution.values())
            if self.submission_count > 20 and max_hour_count / self.submission_count > 0.8:
                score += 15

        # Velocity spike
        if self.submission_count > 100:
            score += 10

        self.anomaly_score = min(score, 100)

    def is_anomalous(self) -> bool:
        return self.anomaly_score >= 50


class DeviceGuardianRegistry:
    """Manages guardian fibres for all known devices."""

    def __init__(self):
        self._guardians: Dict[str, DeviceGuardian] = {}

    def get_or_create(self, device_id: str) -> DeviceGuardian:
        if device_id not in self._guardians:
            self._guardians[device_id] = DeviceGuardian(device_id)
        return self._guardians[device_id]

    def get_anomalous_devices(self) -> List[str]:
        return [d for d, g in self._guardians.items() if g.is_anomalous()]

    def get_status(self) -> Dict[str, Any]:
        return {
            "total_devices": len(self._guardians),
            "anomalous": len(self.get_anomalous_devices()),
        }


# ═══════════════════════════════════════════════════════════════
# Layer 5: Mesh-Wide DEFCON
# ═══════════════════════════════════════════════════════════════

class MeshDefconLevel(IntEnum):
    DEFCON_5 = 5  # Normal
    DEFCON_4 = 4  # Elevated
    DEFCON_3 = 3  # Pause BLE replication
    DEFCON_2 = 2  # Deploy ghost swarm
    DEFCON_1 = 1  # Quantum collapse — withdraw to sovereign core


class MeshDefcon:
    """Mesh-wide DEFCON with regional isolation."""

    def __init__(self):
        self._global_level = MeshDefconLevel.DEFCON_5
        self._regional_levels: Dict[str, MeshDefconLevel] = {}
        self._history: List[Dict] = []

    def set_level(self, level: MeshDefconLevel, region: Optional[str] = None, reason: str = ""):
        if region:
            self._regional_levels[region] = level
        else:
            self._global_level = level

        self._history.append({
            "level": level.value,
            "region": region or "global",
            "reason": reason,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        if len(self._history) > 500:
            self._history = self._history[-500:]

        logger.warning("Mesh DEFCON %s → %d: %s", region or "GLOBAL", level.value, reason)

    def get_level(self, region: Optional[str] = None) -> MeshDefconLevel:
        if region and region in self._regional_levels:
            return min(self._global_level, self._regional_levels[region])
        return self._global_level

    @property
    def should_pause_ble(self) -> bool:
        return self._global_level <= MeshDefconLevel.DEFCON_3

    @property
    def should_deploy_ghosts(self) -> bool:
        return self._global_level <= MeshDefconLevel.DEFCON_2

    @property
    def quantum_collapse(self) -> bool:
        return self._global_level == MeshDefconLevel.DEFCON_1

    def get_status(self) -> Dict[str, Any]:
        return {
            "global_level": self._global_level.value,
            "regional_levels": {k: v.value for k, v in self._regional_levels.items()},
            "pause_ble": self.should_pause_ble,
            "ghost_swarm": self.should_deploy_ghosts,
            "quantum_collapse": self.quantum_collapse,
            "recent_history": self._history[-10:],
        }


# ═══════════════════════════════════════════════════════════════
# Layer 6: Mesh House of Mirrors
# ═══════════════════════════════════════════════════════════════

class MeshPhantomNode:
    """A ghost node that appears real but collects intelligence."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.interactions: List[Dict] = []
        self.created_at = time.time()

    def handle_probe(self, source_id: str, payload: Dict) -> Dict:
        self.interactions.append({
            "source": source_id,
            "payload_hash": hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
            "at": time.time(),
        })
        return self._fabricate_response(payload)

    def _fabricate_response(self, payload: Dict) -> Dict:
        return {
            "crystals": [{"id": f"c_{secrets.token_hex(4)}", "domain": "general", "confidence": 0.55}],
            "node_health": "nominal",
            "uptime_hours": 847,
        }

    def should_escalate(self) -> bool:
        return len(self.interactions) >= 10


class MeshGhostSwarm:
    """Deploys and manages phantom nodes in the mesh."""

    def __init__(self):
        self._phantoms: Dict[str, MeshPhantomNode] = {}

    def deploy(self, count: int = 5) -> List[str]:
        ids = []
        for _ in range(count):
            nid = f"phantom_{secrets.token_hex(6)}"
            self._phantoms[nid] = MeshPhantomNode(nid)
            ids.append(nid)
        logger.info("Deployed %d phantom nodes", count)
        return ids

    def handle_probe(self, node_id: str, source: str, payload: Dict) -> Optional[Dict]:
        phantom = self._phantoms.get(node_id)
        if not phantom:
            return None
        return phantom.handle_probe(source, payload)

    def get_escalation_targets(self) -> List[str]:
        return [
            p.node_id for p in self._phantoms.values()
            if p.should_escalate()
        ]

    def withdraw_all(self):
        count = len(self._phantoms)
        self._phantoms.clear()
        logger.info("Withdrew %d phantom nodes", count)


# ═══════════════════════════════════════════════════════════════
# Layer 7: Zero Knowledge Crystal Storage
# ═══════════════════════════════════════════════════════════════

class ZKCrystalStorage:
    """Encrypt crystals for device storage using mesh-wide or user-scoped keys.
    Keys rotate on DEFCON change. Old crystals are re-encrypted before new ones stored.
    """

    def __init__(self, master_key: Optional[bytes] = None):
        self._master_key = master_key or secrets.token_bytes(32)
        self._mesh_key = self._derive_mesh_key()
        self._key_version = 1
        self._previous_mesh_key: Optional[bytes] = None
        self._previous_key_version: Optional[int] = None
        self._reencryption_pending = False

    def _derive_mesh_key(self) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256", self._master_key, b"nate_mesh_crystals_v1", 100000
        )

    @staticmethod
    def _aes_gcm_encrypt(data: bytes, key: bytes) -> Tuple[bytes, bytes]:
        """AES-256-GCM authenticated encryption. Returns (nonce, ciphertext+tag)."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = secrets.token_bytes(12)
        aesgcm = AESGCM(key)
        ct = aesgcm.encrypt(nonce, data, None)
        return nonce, ct

    @staticmethod
    def _aes_gcm_decrypt(nonce: bytes, ciphertext: bytes, key: bytes) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ciphertext, None)

    @staticmethod
    def _xor_cipher_legacy(data: bytes, key: bytes, nonce: bytes) -> bytes:
        """Legacy XOR stream cipher — kept ONLY for reading pre-migration crystals."""
        stream_key = hashlib.sha256(key + nonce).digest()
        result = bytearray(len(data))
        for i in range(len(data)):
            result[i] = data[i] ^ stream_key[i % len(stream_key)]
        return bytes(result)

    def encrypt_global(self, crystal_text: str) -> Dict[str, Any]:
        """Encrypt a global-scope crystal with AES-256-GCM.
        Blocks when key rotation is in progress (re-encryption pending).
        """
        import base64
        if self._reencryption_pending:
            raise RuntimeError(
                "Cannot store new crystals until re-encryption completes after DEFCON key rotation"
            )
        nonce, ct = self._aes_gcm_encrypt(crystal_text.encode(), self._mesh_key)
        return {
            "ciphertext": base64.b64encode(ct).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "key_version": self._key_version,
            "scope": "global",
            "cipher": "aes-gcm",
        }

    def decrypt_global(self, encrypted: Dict[str, Any]) -> str:
        import base64
        cipher_bytes = base64.b64decode(encrypted["ciphertext"])
        nonce = base64.b64decode(encrypted["nonce"])
        key_version = encrypted.get("key_version", 1)
        key = self._mesh_key if key_version == self._key_version else self._previous_mesh_key
        if key is None:
            raise ValueError("Cannot decrypt: key version not available (already rotated)")
        if encrypted.get("cipher") == "aes-gcm":
            return self._aes_gcm_decrypt(nonce, cipher_bytes, key).decode()
        return self._xor_cipher_legacy(cipher_bytes, key, nonce).decode()

    def encrypt_user(self, crystal_text: str, user_passphrase: str) -> Dict[str, Any]:
        """Encrypt a user-scope crystal with AES-256-GCM."""
        import base64
        user_key = hashlib.pbkdf2_hmac(
            "sha256", user_passphrase.encode(), b"nate_user_crystal_v1", 100000
        )
        nonce, ct = self._aes_gcm_encrypt(crystal_text.encode(), user_key)
        return {
            "ciphertext": base64.b64encode(ct).decode(),
            "nonce": base64.b64encode(nonce).decode(),
            "scope": "user",
            "cipher": "aes-gcm",
        }

    def rotate_mesh_key(self) -> int:
        """Rotate mesh-wide key. Saves previous key for re-encryption of old crystals."""
        self._previous_mesh_key = self._mesh_key
        self._previous_key_version = self._key_version
        self._master_key = secrets.token_bytes(32)
        self._mesh_key = self._derive_mesh_key()
        self._key_version += 1
        self._reencryption_pending = True
        logger.warning("ZKCrystalStorage: mesh key rotated to version %d", self._key_version)
        return self._key_version

    def on_defcon_change(self, old_level: int, new_level: int) -> None:
        """Called when DEFCON escalates or de-escalates. Rotates key and marks re-encryption pending."""
        if old_level != new_level:
            self.rotate_mesh_key()
            logger.warning(
                "ZKCrystalStorage: DEFCON change %d → %d triggered key rotation",
                old_level, new_level,
            )

    def re_encrypt_crystal(self, encrypted: Dict[str, Any]) -> Dict[str, Any]:
        """Re-encrypt a crystal from an old key version to the current key."""
        if encrypted.get("key_version", 1) >= self._key_version:
            return encrypted
        if self._previous_mesh_key is None:
            raise ValueError("Cannot re-encrypt: previous key not retained")
        plain = self.decrypt_global(encrypted)
        prev = self._reencryption_pending
        self._reencryption_pending = False
        try:
            return self.encrypt_global(plain)
        finally:
            self._reencryption_pending = prev

    def complete_reencryption(self, reencrypted_count: int = 0) -> None:
        """Clear re-encryption block after all old crystals have been re-encrypted."""
        self._reencryption_pending = False
        self._previous_mesh_key = None
        self._previous_key_version = None
        logger.info(
            "ZKCrystalStorage: re-encryption complete (%d crystals), new crystals allowed",
            reencrypted_count,
        )


# ═══════════════════════════════════════════════════════════════
# Layer 8: Distributed Canary System
# ═══════════════════════════════════════════════════════════════

class CanaryCrystal:
    """A canary crystal planted on a specific device. Each canary has a unique UUID and content hash."""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.canary_id = f"canary_{secrets.token_hex(8)}"
        unique_salt = secrets.token_hex(4)
        self.content_hash = hashlib.sha256(
            f"{self.canary_id}:{device_id}:{unique_salt}:{time.time():.6f}".encode()
        ).hexdigest()
        self.created_at = datetime.now(timezone.utc)
        self.detected_outside = False


class DistributedCanarySystem:
    """Plant and monitor canary crystals across the mesh. Each device gets unique canaries.
    Canary crystals must never be included in Vectorize indexes — use get_canary_hashes() to exclude.
    """

    def __init__(self, db_pool: Optional[Any] = None):
        self._canaries: Dict[str, CanaryCrystal] = {}
        self._hash_to_canary: Dict[str, CanaryCrystal] = {}
        self._exfiltration_alerts: List[Dict] = []
        self._db_pool = db_pool

    def _assert_unique_canary(self, canary: CanaryCrystal) -> None:
        """Ensure canary_id and content_hash are never reused."""
        if canary.canary_id in self._canaries:
            raise ValueError("Canary ID collision — must never reuse")
        if canary.content_hash in self._hash_to_canary:
            raise ValueError("Canary content hash collision — must never reuse across devices")

    def plant(self, device_id: str) -> CanaryCrystal:
        """Plant a unique canary on a device. Never reuses UUID or content hash."""
        canary = CanaryCrystal(device_id)
        self._assert_unique_canary(canary)
        self._canaries[canary.canary_id] = canary
        self._hash_to_canary[canary.content_hash] = canary
        if self._db_pool:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._persist_canary(canary))
            except RuntimeError:
                pass
        return canary

    async def _persist_canary(self, canary: CanaryCrystal) -> None:
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO canary_crystals (canary_id, device_id, content_hash, planted_at)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (canary_id) DO NOTHING
                    """,
                    canary.canary_id,
                    canary.device_id,
                    canary.content_hash,
                    canary.created_at,
                )
        except Exception as e:
            logger.warning("DistributedCanarySystem: persist canary failed: %s", e)

    def check_exfiltration(
        self, content_hash: str, seen_on_device_id: Optional[str] = None
    ) -> Optional[str]:
        """If a canary hash appears outside its device, identify the source.
        seen_on_device_id: if provided and matches the canary's device, not exfiltration.
        """
        canary = self._hash_to_canary.get(content_hash)
        if canary is None:
            return None
        if seen_on_device_id is not None and seen_on_device_id == canary.device_id:
            return None
        canary.detected_outside = True
        alert = {
            "canary_id": canary.canary_id,
            "source_device": canary.device_id,
            "seen_on_device_id": seen_on_device_id,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }
        self._exfiltration_alerts.append(alert)
        logger.warning(
            "CANARY EXFILTRATION: device=%s seen_on=%s",
            canary.device_id, seen_on_device_id,
        )
        if self._db_pool:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._persist_exfiltration(canary))
            except RuntimeError:
                pass
        return canary.device_id

    async def _persist_exfiltration(self, canary: CanaryCrystal) -> None:
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE canary_crystals
                    SET detected_outside = TRUE, detected_at = NOW()
                    WHERE canary_id = $1
                    """,
                    canary.canary_id,
                )
        except Exception as e:
            logger.warning("DistributedCanarySystem: persist exfiltration failed: %s", e)

    def get_canary_hashes(self) -> Set[str]:
        """Return all canary content hashes. Use to exclude from Vectorize indexes."""
        return set(self._hash_to_canary.keys())

    def is_canary_hash(self, content_hash: str) -> bool:
        """Check if a hash belongs to a canary crystal (for Vectorize exclusion)."""
        return content_hash in self._hash_to_canary

    def get_status(self) -> Dict[str, Any]:
        return {
            "total_canaries": len(self._canaries),
            "exfiltration_alerts": len(self._exfiltration_alerts),
            "recent_alerts": self._exfiltration_alerts[-5:],
        }


# ═══════════════════════════════════════════════════════════════
# Layer 9: Mesh Recon + Forensics
# ═══════════════════════════════════════════════════════════════

class MeshReconReport:
    """Assembles mesh-wide incident reports. mesh_recon_reports rows are append-only — never UPDATE or DELETE."""

    def __init__(self, db_pool: Optional[Any] = None):
        self._reports: List[Dict] = []
        self._db_pool = db_pool

    def assemble(
        self,
        trigger: str,
        affected_nodes: List[str],
        curiosity_states: Dict[str, int],
        canary_alerts: List[Dict],
        defcon_level: int,
        incident_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        report_id = f"recon_{secrets.token_hex(6)}"
        recommendations = self._generate_recommendations(trigger, defcon_level)
        curiosity_summary = {
            level_name: sum(1 for v in curiosity_states.values() if v == level_val)
            for level_name, level_val in [
                ("none", 0), ("notice", 1), ("interest", 2), ("concern", 3), ("alarm", 4)
            ]
        }
        report = {
            "id": report_id,
            "trigger": trigger,
            "assembled_at": datetime.now(timezone.utc).isoformat(),
            "defcon_level": defcon_level,
            "affected_nodes": affected_nodes,
            "node_count": len(affected_nodes),
            "curiosity_summary": curiosity_summary,
            "canary_alerts": canary_alerts,
            "crystal_contamination": "assessment_pending",
            "recommendations": recommendations,
            "incident_id": incident_id or report_id,
        }
        self._reports.append(report)
        if len(self._reports) > 100:
            self._reports = self._reports[-100:]
        if self._db_pool:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._persist_report(report))
            except RuntimeError:
                pass
        return report

    async def _persist_report(self, report: Dict[str, Any]) -> None:
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO mesh_recon_reports
                    (id, trigger, defcon_level, affected_nodes, node_count, curiosity_summary, canary_alerts, recommendations, assembled_at)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9::timestamptz)
                    """,
                    report["id"],
                    report["trigger"],
                    report["defcon_level"],
                    report["affected_nodes"],
                    report["node_count"],
                    json.dumps(report["curiosity_summary"]),
                    json.dumps(report["canary_alerts"]),
                    report["recommendations"],
                    report["assembled_at"],
                )
        except Exception as e:
            logger.warning("MeshReconReport: persist report failed: %s", e)

    def _generate_recommendations(self, trigger: str, defcon_level: int) -> List[str]:
        recs = []
        if defcon_level <= 2:
            recs.append("Deploy ghost swarm to affected regions")
            recs.append("Rotate mesh-wide crystal encryption key")
        if "canary" in trigger.lower():
            recs.append("Quarantine source device immediately")
            recs.append("Audit all crystals from source device")
        if defcon_level == 1:
            recs.append("QUANTUM COLLAPSE: Withdraw all distributed nodes to sovereign core")
            recs.append("Preserve forensic evidence before system withdrawal")
        recs.append("Generate full forensic timeline for patent shield documentation")
        return recs

    def get_reports(self, limit: int = 10) -> List[Dict]:
        return self._reports[-limit:]

    async def reconstruct_incident(
        self,
        trigger: Optional[str] = None,
        report_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Reconstruct incident timeline from forensic data. Append-only: never updates or deletes reports."""
        if not self._db_pool:
            return self._reports[-limit:]
        try:
            async with self._db_pool.acquire() as conn:
                conditions = []
                params: List[Any] = []
                idx = 1
                if trigger:
                    conditions.append(f"trigger = ${idx}")
                    params.append(trigger)
                    idx += 1
                if report_id:
                    conditions.append(f"id = ${idx}")
                    params.append(report_id)
                    idx += 1
                if since:
                    conditions.append(f"assembled_at >= ${idx}::timestamptz")
                    params.append(since.isoformat())
                    idx += 1
                where = " AND ".join(conditions) if conditions else "TRUE"
                params.append(limit)
                rows = await conn.fetch(
                    f"""
                    SELECT id, trigger, defcon_level, affected_nodes, node_count,
                           curiosity_summary, canary_alerts, recommendations, assembled_at
                    FROM mesh_recon_reports
                    WHERE {where}
                    ORDER BY assembled_at ASC
                    LIMIT ${idx}
                    """,
                    *params,
                )
                return [
                    {
                        "id": r["id"],
                        "trigger": r["trigger"],
                        "defcon_level": r["defcon_level"],
                        "affected_nodes": r["affected_nodes"] or [],
                        "node_count": r["node_count"] or 0,
                        "curiosity_summary": r["curiosity_summary"] or {},
                        "canary_alerts": r["canary_alerts"] or [],
                        "recommendations": r["recommendations"] or [],
                        "assembled_at": r["assembled_at"].isoformat() if r["assembled_at"] else None,
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning("MeshReconReport: reconstruct_incident failed: %s", e)
            return []


# ═══════════════════════════════════════════════════════════════
# Unified Shield Orchestrator
# ═══════════════════════════════════════════════════════════════

class DistributedDefenseShield:
    """Orchestrates all 9 layers of the distributed defense.
    DEFCON changes must flow through on_defcon_change to trigger Layer 7 key rotation.
    """

    def __init__(self, db_pool: Optional[Any] = None):
        self.edge_mirror = None  # Set externally (L1)
        self.curiosity = DistributedCuriosityProtocol()
        self.helix = CrystalIntegrityHelix()
        self.guardians = DeviceGuardianRegistry()
        self.defcon = MeshDefcon()
        self.ghost_swarm = MeshGhostSwarm()
        self.zk_storage = ZKCrystalStorage()
        self.canary_system = DistributedCanarySystem(db_pool=db_pool)
        self.recon = MeshReconReport(db_pool=db_pool)
        self.db_pool = db_pool

    def set_defcon_level(
        self, level: MeshDefconLevel, region: Optional[str] = None, reason: str = ""
    ) -> None:
        """Set DEFCON level via shield so Layer 7 key rotation is triggered."""
        old_level = self.defcon.get_level(region).value
        self.defcon.set_level(level, region=region, reason=reason)
        new_level = level.value
        if old_level != new_level:
            self.on_defcon_change(old_level, new_level)

    def on_defcon_change(self, old_level: int, new_level: int) -> None:
        """Called when DEFCON escalates or de-escalates. Triggers Layer 7 key rotation."""
        self.zk_storage.on_defcon_change(old_level, new_level)

    def get_status(self) -> Dict[str, Any]:
        return {
            "defcon": self.defcon.get_status(),
            "guardians": self.guardians.get_status(),
            "canaries": self.canary_system.get_status(),
            "ghost_swarm_active": len(self.ghost_swarm._phantoms),
            "curiosity_alarms": len(self.curiosity.get_alarmed_sources()),
        }
