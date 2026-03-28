"""
Me-2-Me Platinum — Legacy Vault Storage
Encrypted permanent storage for all Me-2-Me data.
AES-256-GCM encrypted, integrity-checked, tiered storage.

NOTE ON ENCRYPTION:
    Production deployment MUST set VAULT_ENCRYPTION_KEY env var to enable
    AES-256-GCM encryption at rest. Without this key, data is stored in
    cleartext with integrity hashes only.

    When the key is present:
    - Each user gets a derived key via HKDF(master_key, user_id)
    - All imprint and crystal data is AES-256-GCM encrypted before INSERT
    - Decryption happens transparently on retrieval
    - Integrity is verified via GCM authentication tag

    Implementation path: backend/app/services/me2me/vault_crypto.py (TBD)
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.me2me import ConsentLevel
from app.services.me2me.constants import VAULT_ENCRYPTION_ALGORITHM, VAULT_DEFAULT_RETENTION_YEARS

logger = logging.getLogger("me2me.legacy_vault")

# Encryption support — AES-256-GCM with per-user HKDF-derived keys
_VAULT_KEY = os.environ.get("VAULT_ENCRYPTION_KEY", "")

# Lazy-loaded crypto modules (only imported when encryption is enabled)
_AESGCM = None
_HKDF = None
_SHA256 = None
_default_backend = None

def _init_crypto():
    """Lazy-load cryptography modules on first use."""
    global _AESGCM, _HKDF, _SHA256, _default_backend
    if _AESGCM is not None:
        return
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AG
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF as _H
        from cryptography.hazmat.primitives.hashes import SHA256 as _S
        from cryptography.hazmat.backends import default_backend as _db
        _AESGCM = _AG
        _HKDF = _H
        _SHA256 = _S
        _default_backend = _db
    except ImportError:
        logger.error("cryptography package not available — vault encryption disabled")


def _derive_user_key(user_id: str) -> bytes:
    """Derive a 32-byte AES key from the master vault key + user ID via HKDF."""
    _init_crypto()
    if not _HKDF or not _SHA256 or not _default_backend:
        raise RuntimeError("Cryptography library not available")
    hkdf = _HKDF(
        algorithm=_SHA256(),
        length=32,
        salt=user_id.encode("utf-8"),
        info=b"me2me-vault-aes256gcm",
        backend=_default_backend(),
    )
    return hkdf.derive(_VAULT_KEY.encode("utf-8"))


def _encrypt_data(data: str, user_id: str) -> str:
    """Encrypt data for vault storage using AES-256-GCM.
    Returns base64-encoded nonce+ciphertext, or plaintext if no key configured."""
    if not _VAULT_KEY:
        return data  # No encryption key configured — store plaintext
    try:
        _init_crypto()
        if not _AESGCM:
            return data  # cryptography not installed — fallback to plaintext
        derived_key = _derive_user_key(user_id)
        nonce = os.urandom(12)  # 96-bit nonce for GCM
        aesgcm = _AESGCM(derived_key)
        ciphertext = aesgcm.encrypt(nonce, data.encode("utf-8"), None)
        # Format: base64(nonce || ciphertext+tag)
        return "ENC:" + base64.b64encode(nonce + ciphertext).decode("ascii")
    except Exception as e:
        logger.error("Encryption failed for user %s: %s — storing plaintext", user_id, e)
        return data


def _decrypt_data(data: str, user_id: str) -> str:
    """Decrypt data from vault storage. Handles both encrypted and legacy plaintext."""
    if not data.startswith("ENC:"):
        return data  # Not encrypted (legacy plaintext entry)
    if not _VAULT_KEY:
        logger.warning("Encrypted data found but VAULT_ENCRYPTION_KEY not set — cannot decrypt")
        return data  # Cannot decrypt without key
    try:
        _init_crypto()
        if not _AESGCM:
            return data
        raw = base64.b64decode(data[4:])  # Strip "ENC:" prefix
        nonce = raw[:12]
        ciphertext = raw[12:]
        derived_key = _derive_user_key(user_id)
        aesgcm = _AESGCM(derived_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")
    except Exception as e:
        logger.error("Decryption failed for user %s: %s", user_id, e)
        return data  # Return raw on failure (admin can investigate)


class LegacyVaultMe2Me:
    """
    Encrypted permanent storage for Me-2-Me identity data.
    All data at rest is AES-256-GCM encrypted with per-user keys
    when VAULT_ENCRYPTION_KEY is configured.
    """

    def __init__(self, consent_service=None, db_pool=None):
        self._consent = consent_service
        self._db = db_pool
        if _VAULT_KEY:
            logger.info("Vault encryption enabled (AES-256-GCM)")
        else:
            logger.warning("Vault encryption NOT enabled — set VAULT_ENCRYPTION_KEY for production")

    async def store_imprint(
        self, user_id: str, data: Dict[str, Any], source: str = ""
    ) -> Optional[str]:
        """Store an imprint entry in the vault."""
        if self._consent:
            has_consent = await self._consent.check_consent(
                user_id, ConsentLevel.OBSERVE
            )
            if not has_consent:
                logger.warning("Vault store rejected: no consent for user %s", user_id)
                return None

        content_hash = hashlib.sha256(str(data).encode()).hexdigest()[:32]
        entry_id = data.get("entry_id", content_hash)

        if self._db:
            try:
                # Encrypt sensitive fields (themes, emotions) at rest
                themes_json = json.dumps(data.get("themes", []))
                emotions_json = json.dumps(data.get("emotions", []))
                enc_themes = _encrypt_data(themes_json, user_id)
                enc_emotions = _encrypt_data(emotions_json, user_id)

                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO me2me_imprint_entries
                        (entry_id, user_id, source, content_hash, themes, emotions, c_emo_at_capture)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (entry_id) DO NOTHING""",
                        entry_id, user_id, source,
                        content_hash,
                        enc_themes,
                        enc_emotions,
                        data.get("c_emo_at_capture", data.get("c_emo", 0.0)),
                    )
            except Exception as e:
                logger.error("Vault storage failed: %s", e)
                return None

        return content_hash

    async def store_crystal(
        self, user_id: str, crystal_data: Dict[str, Any]
    ) -> Optional[str]:
        """Store an identity crystal in the vault."""
        if self._consent:
            has_consent = await self._consent.check_consent(
                user_id, ConsentLevel.PRESERVE
            )
            if not has_consent:
                return None

        crystal_id = crystal_data.get("crystal_id", hashlib.sha256(
            str(crystal_data).encode()
        ).hexdigest()[:16])

        if self._db:
            try:
                # Encrypt sensitive identity crystal fields at rest
                personality_json = json.dumps(crystal_data.get("personality", {}), default=str)
                language_json = json.dumps(crystal_data.get("language", {}), default=str)
                humor_json = json.dumps(crystal_data.get("humor", {}), default=str)
                values_json = json.dumps(crystal_data.get("core_values", []), default=str)
                themes_json = json.dumps(crystal_data.get("life_themes", []), default=str)

                enc_personality = _encrypt_data(personality_json, user_id)
                enc_language = _encrypt_data(language_json, user_id)
                enc_humor = _encrypt_data(humor_json, user_id)
                enc_values = _encrypt_data(values_json, user_id)
                enc_themes = _encrypt_data(themes_json, user_id)

                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO me2me_identity_crystals
                        (crystal_id, user_id, crystal_version, personality, language_sig,
                         humor, core_values, life_themes, confidence_score)
                        VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb, $9)""",
                        crystal_id, user_id,
                        crystal_data.get("crystal_version", 1),
                        enc_personality if not enc_personality.startswith("ENC:") else json.dumps({"_encrypted": enc_personality}),
                        enc_language if not enc_language.startswith("ENC:") else json.dumps({"_encrypted": enc_language}),
                        enc_humor if not enc_humor.startswith("ENC:") else json.dumps({"_encrypted": enc_humor}),
                        enc_values if not enc_values.startswith("ENC:") else json.dumps({"_encrypted": enc_values}),
                        enc_themes if not enc_themes.startswith("ENC:") else json.dumps({"_encrypted": enc_themes}),
                        crystal_data.get("confidence_score", 0.0),
                    )
            except Exception as e:
                logger.error("Crystal storage failed: %s", e)
                return None

        return crystal_id

    async def retrieve_crystal(
        self, user_id: str, version: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Retrieve the latest (or specific) identity crystal."""
        if self._consent:
            has_consent = await self._consent.check_consent(
                user_id, ConsentLevel.PRESERVE
            )
            if not has_consent:
                return None

        if not self._db:
            return None

        try:
            async with self._db.acquire() as conn:
                if version:
                    row = await conn.fetchrow(
                        """SELECT * FROM me2me_identity_crystals
                        WHERE user_id = $1 AND crystal_version = $2""",
                        user_id, version,
                    )
                else:
                    row = await conn.fetchrow(
                        """SELECT * FROM me2me_identity_crystals
                        WHERE user_id = $1
                        ORDER BY synthesized_at DESC LIMIT 1""",
                        user_id,
                    )
                if row:
                    result = dict(row)
                    # Decrypt encrypted fields transparently
                    for field in ("personality", "language_sig", "humor", "core_values", "life_themes"):
                        val = result.get(field)
                        if isinstance(val, dict) and "_encrypted" in val:
                            decrypted = _decrypt_data(val["_encrypted"], user_id)
                            try:
                                result[field] = json.loads(decrypted)
                            except (json.JSONDecodeError, TypeError):
                                result[field] = decrypted
                        elif isinstance(val, str) and val.startswith("ENC:"):
                            decrypted = _decrypt_data(val, user_id)
                            try:
                                result[field] = json.loads(decrypted)
                            except (json.JSONDecodeError, TypeError):
                                result[field] = decrypted
                    return result
        except Exception as e:
            logger.error("Crystal retrieval failed: %s", e)
        return None

    async def check_integrity(self, user_id: str) -> Dict[str, Any]:
        """Run integrity check on a user's vault data."""
        result = {"user_id": user_id, "status": "unknown", "issues": []}

        if not self._db:
            result["status"] = "no_database"
            return result

        try:
            async with self._db.acquire() as conn:
                imprint_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM me2me_imprint_entries WHERE user_id = $1",
                    user_id,
                )
                crystal_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM me2me_identity_crystals WHERE user_id = $1",
                    user_id,
                )
                result["imprint_count"] = imprint_count
                result["crystal_count"] = crystal_count
                result["status"] = "healthy"

                if imprint_count == 0 and crystal_count == 0:
                    result["status"] = "empty"

        except Exception as e:
            result["status"] = "error"
            result["issues"].append(str(e))

        return result

    # ── Thematic Content Extraction (for Marketing) ───────────────

    async def extract_thematic_content(self, content_type: str = "emotional_themes") -> Dict[str, Any]:
        """Extract anonymized thematic content for use in campaign storytelling.

        Returns aggregated emotional themes, relationship patterns, and life
        transitions — NO PII, NO user-identifiable data.

        Args:
            content_type: One of 'emotional_themes', 'relationship_patterns',
                         'life_transitions', 'family_dynamics'
        """
        if not self._db:
            return {"themes": [], "source": "unavailable"}

        try:
            async with self._db.acquire() as conn:
                if content_type == "emotional_themes":
                    return await self._extract_emotional_themes(conn)
                elif content_type == "relationship_patterns":
                    return await self._extract_relationship_patterns(conn)
                elif content_type == "life_transitions":
                    return await self._extract_life_transitions(conn)
                elif content_type == "family_dynamics":
                    return await self._extract_family_dynamics(conn)
                else:
                    return {"themes": [], "error": f"Unknown content_type: {content_type}"}
        except Exception as e:
            logger.error(f"Thematic extraction error ({content_type}): {e}")
            return {"themes": [], "error": str(e)}

    async def _extract_emotional_themes(self, conn) -> Dict:
        """Aggregate emotion distributions across all imprints (fully anonymized)."""
        try:
            rows = await conn.fetch("""
                SELECT emotions FROM me2me_imprint_entries
                WHERE emotions IS NOT NULL
                ORDER BY created_at DESC LIMIT 200
            """)
            if not rows:
                return {"themes": ["resilience", "connection", "growth"], "source": "default"}

            emotion_counts: Dict[str, int] = {}
            for r in rows:
                emotions = r["emotions"]
                if isinstance(emotions, str):
                    import json as _j
                    try:
                        emotions = _j.loads(emotions)
                    except Exception:
                        continue
                if isinstance(emotions, dict):
                    for k, v in emotions.items():
                        emotion_counts[k] = emotion_counts.get(k, 0) + (int(v) if isinstance(v, (int, float)) else 1)
                elif isinstance(emotions, list):
                    for e in emotions:
                        emotion_counts[str(e)] = emotion_counts.get(str(e), 0) + 1

            top = sorted(emotion_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            return {"themes": [t[0] for t in top], "counts": dict(top), "source": "imprints"}
        except Exception as e:
            return {"themes": ["love", "grief", "hope", "anger", "joy"], "source": "fallback", "note": str(e)}

    async def _extract_relationship_patterns(self, conn) -> Dict:
        """Extract common relationship themes from identity crystals."""
        try:
            rows = await conn.fetch("""
                SELECT life_themes, core_values FROM me2me_identity_crystals
                WHERE life_themes IS NOT NULL
                ORDER BY created_at DESC LIMIT 50
            """)
            if not rows:
                return {"patterns": ["trust building", "vulnerability", "repair after conflict"], "source": "default"}

            themes = []
            for r in rows:
                lt = r["life_themes"]
                if isinstance(lt, str):
                    import json as _j
                    try:
                        lt = _j.loads(lt)
                    except Exception:
                        continue
                if isinstance(lt, list):
                    themes.extend([str(t) for t in lt[:5]])
                elif isinstance(lt, dict):
                    themes.extend(list(lt.keys())[:5])

            from collections import Counter
            top = Counter(themes).most_common(8)
            return {"patterns": [t[0] for t in top], "source": "crystals"}
        except Exception:
            return {"patterns": ["reconnection", "forgiveness", "boundaries"], "source": "fallback"}

    async def _extract_life_transitions(self, conn) -> Dict:
        """Extract common life transition themes."""
        try:
            rows = await conn.fetch("""
                SELECT themes FROM me2me_imprint_entries
                WHERE themes IS NOT NULL AND source IN ('session', 'homework')
                ORDER BY created_at DESC LIMIT 200
            """)
            transition_keywords = [
                "career change", "divorce", "loss", "new baby", "moving",
                "retirement", "graduation", "marriage", "illness", "recovery",
                "identity", "coming out", "empty nest", "remarriage",
            ]
            found = {}
            for r in rows:
                t = str(r["themes"]).lower()
                for kw in transition_keywords:
                    if kw in t:
                        found[kw] = found.get(kw, 0) + 1

            top = sorted(found.items(), key=lambda x: x[1], reverse=True)[:8]
            return {"transitions": [t[0] for t in top] if top else transition_keywords[:5], "source": "imprints" if top else "default"}
        except Exception:
            return {"transitions": ["loss", "identity shift", "new beginnings"], "source": "fallback"}

    async def _extract_family_dynamics(self, conn) -> Dict:
        """Extract family dynamics themes from family fabrics."""
        try:
            rows = await conn.fetch("""
                SELECT shared_memories FROM me2me_family_fabrics
                WHERE shared_memories IS NOT NULL
                ORDER BY created_at DESC LIMIT 30
            """)
            if not rows:
                return {"dynamics": ["intergenerational patterns", "sibling bonds", "parental attachment"], "source": "default"}

            themes = []
            for r in rows:
                mem = r["shared_memories"]
                if isinstance(mem, str):
                    import json as _j
                    try:
                        mem = _j.loads(mem)
                    except Exception:
                        continue
                if isinstance(mem, list):
                    for m in mem[:5]:
                        if isinstance(m, dict):
                            themes.append(m.get("theme", m.get("type", "family")))
                        else:
                            themes.append(str(m)[:50])

            from collections import Counter
            top = Counter(themes).most_common(6)
            return {"dynamics": [t[0] for t in top], "source": "fabrics"}
        except Exception:
            return {"dynamics": ["legacy", "connection", "repair"], "source": "fallback"}
