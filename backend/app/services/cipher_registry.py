"""Data-class-aware cipher registry (Slice 6b of Bee HIV+ privacy plan).

Splits encryption keys by data class so a single key compromise does not
unlock everything. Keeps the existing ``TokenCipher`` untouched (that is
the OAuth cipher) and adds per-class keys for PII and sensitive clinical
data.

Data classes
------------
======  =======================================  =========================
class   scope                                    env var
======  =======================================  =========================
oauth   3rd-party OAuth tokens (QB/Stripe/CF)    SKYEYE_TOKEN_ENCRYPTION_KEY
pii     user PII (email, phone, address)         SKYEYE_TOKEN_ENCRYPTION_KEY_PII
clinical sensitive clinical fields (trauma etc.) SKYEYE_TOKEN_ENCRYPTION_KEY_CLINICAL
======  =======================================  =========================

Fallback policy
---------------
1. By default, if a class-specific key is absent, the registry falls back
   to the ``oauth`` key. This preserves backward compatibility — nothing
   breaks when only the master key is configured.
2. If ``ENCRYPTION_STRICT_KEY_SPLIT=true``, a missing class-specific key
   raises ``CipherKeyMissing``. Set this once every production key is
   deployed to catch regressions.
3. In non-strict mode without any key, ``encrypt`` returns plaintext with
   a warning (matches legacy ``TokenCipher`` behavior).
4. ``decrypt`` transparently passes through legacy plaintext values
   (Fernet ciphertext always starts with ``gAAAAA``).

Rotation
--------
Rotation is a per-column backfill, out of scope for this slice. The
registry provides the seam: once each class has its own key, rotation
means re-encrypting rows in that class alone — no touching OAuth tokens
or clinical data if only PII keys are rotating.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:  # pragma: no cover - cryptography is a production dep
    from cryptography.fernet import Fernet, InvalidToken  # type: ignore
except Exception:  # pragma: no cover
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore

DATA_CLASS_OAUTH = "oauth"
DATA_CLASS_PII = "pii"
DATA_CLASS_CLINICAL = "clinical"
_VALID_CLASSES = (DATA_CLASS_OAUTH, DATA_CLASS_PII, DATA_CLASS_CLINICAL)

_ENV_BY_CLASS: Dict[str, str] = {
    DATA_CLASS_OAUTH: "SKYEYE_TOKEN_ENCRYPTION_KEY",
    DATA_CLASS_PII: "SKYEYE_TOKEN_ENCRYPTION_KEY_PII",
    DATA_CLASS_CLINICAL: "SKYEYE_TOKEN_ENCRYPTION_KEY_CLINICAL",
}

_ENV_STRICT_SPLIT = "ENCRYPTION_STRICT_KEY_SPLIT"
_ENV_STRICT = "ENCRYPTION_STRICT"
_ENV_ENVIRONMENT = "ENVIRONMENT"


class CipherKeyMissing(RuntimeError):
    """Raised when a class-specific key is required but not configured."""


class CipherRegistry:
    """Registry of per-data-class Fernet ciphers.

    Prefer :func:`get_registry` to obtain the process-wide singleton.
    """

    _instance: Optional["CipherRegistry"] = None

    # keyed by data_class -> Fernet or None
    _ciphers: Dict[str, Optional[Any]]
    _strict: bool = False
    _strict_split: bool = False
    _warned: Dict[str, bool]

    def __init__(self) -> None:
        self._ciphers = {}
        self._warned = {}
        self._load_flags()

    # ------------------------------------------------------------------
    # public accessors
    # ------------------------------------------------------------------
    @classmethod
    def get(cls) -> "CipherRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Test helper: drop the singleton so a new env is picked up."""
        cls._instance = None

    def encrypt(self, plaintext: str, data_class: str = DATA_CLASS_OAUTH) -> str:
        """Encrypt a value under the cipher for ``data_class``.

        Non-strict mode with no key: returns plaintext with a warning.
        Strict mode with no key: raises :class:`CipherKeyMissing`.
        """
        if not plaintext:
            return plaintext
        fernet = self._get_fernet(data_class)
        if fernet is None:
            if self._strict or self._strict_split:
                raise CipherKeyMissing(
                    f"CipherRegistry.encrypt: no key for data_class={data_class!r}"
                )
            return plaintext
        try:
            return fernet.encrypt(plaintext.encode()).decode()
        except Exception as exc:
            if self._strict or self._strict_split:
                raise CipherKeyMissing(
                    f"CipherRegistry.encrypt failed for {data_class}: {exc}"
                ) from exc
            logger.error("CipherRegistry.encrypt failed (%s): %s", data_class, exc)
            return plaintext

    def decrypt(self, ciphertext: str, data_class: str = DATA_CLASS_OAUTH) -> str:
        """Decrypt a value under the cipher for ``data_class``.

        Legacy plaintext (values that don't start with ``gAAAAA``) pass
        through unchanged, matching the historical ``TokenCipher``
        behavior. This is required so rows encrypted before the split
        keep working.
        """
        if data_class not in _VALID_CLASSES:
            raise ValueError(
                f"Unknown data_class={data_class!r}; expected one of {_VALID_CLASSES}"
            )
        if not ciphertext:
            return ciphertext
        if not ciphertext.startswith("gAAAAA"):
            return ciphertext
        fernet = self._get_fernet(data_class)
        if fernet is None:
            # Ciphertext-shaped input but no key. Never expose raw bytes;
            # return the input untouched and let callers detect via ==.
            return ciphertext
        try:
            return fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            logger.warning(
                "CipherRegistry.decrypt: InvalidToken for %s — wrong key or "
                "legacy value; returning raw",
                data_class,
            )
            return ciphertext
        except Exception as exc:
            logger.error("CipherRegistry.decrypt failed (%s): %s", data_class, exc)
            return ciphertext

    def has_key(self, data_class: str = DATA_CLASS_OAUTH) -> bool:
        """True iff a Fernet is available for this data class."""
        return self._get_fernet(data_class) is not None

    def is_strict(self) -> bool:
        return bool(self._strict or self._strict_split)

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------
    def _load_flags(self) -> None:
        env = (os.getenv(_ENV_ENVIRONMENT) or "").strip().lower()
        override = (os.getenv(_ENV_STRICT) or "").strip().lower()
        if override in ("true", "1", "yes", "on"):
            self._strict = True
        elif override in ("false", "0", "no", "off"):
            self._strict = False
        else:
            self._strict = env == "production"
        split = (os.getenv(_ENV_STRICT_SPLIT) or "").strip().lower()
        self._strict_split = split in ("true", "1", "yes", "on")

    def _get_fernet(self, data_class: str) -> Optional[Any]:
        if data_class not in _VALID_CLASSES:
            raise ValueError(
                f"Unknown data_class={data_class!r}; expected one of {_VALID_CLASSES}"
            )
        if data_class in self._ciphers:
            return self._ciphers[data_class]
        fernet = self._build_fernet(data_class)
        self._ciphers[data_class] = fernet
        return fernet

    def _build_fernet(self, data_class: str) -> Optional[Any]:
        if Fernet is None:
            if not self._warned.get("_lib"):
                logger.warning("CipherRegistry: cryptography not installed")
                self._warned["_lib"] = True
            return None
        env_name = _ENV_BY_CLASS[data_class]
        raw = (os.getenv(env_name) or "").strip()
        if not raw and data_class != DATA_CLASS_OAUTH:
            # Fallback to OAuth master key unless strict-split forbids it.
            if self._strict_split:
                if not self._warned.get(data_class):
                    logger.error(
                        "CipherRegistry: %s unset and strict-split enabled — "
                        "no fallback to oauth key",
                        env_name,
                    )
                    self._warned[data_class] = True
                return None
            raw = (os.getenv(_ENV_BY_CLASS[DATA_CLASS_OAUTH]) or "").strip()
            if raw and not self._warned.get(data_class):
                logger.info(
                    "CipherRegistry: %s falling back to oauth master key",
                    data_class,
                )
                self._warned[data_class] = True
        if not raw:
            return None
        try:
            return Fernet(raw.encode() if isinstance(raw, str) else raw)
        except Exception as exc:
            logger.error(
                "CipherRegistry: invalid key for %s (%s): %s",
                data_class,
                env_name,
                exc,
            )
            return None


def get_registry() -> CipherRegistry:
    """Convenience accessor for the singleton."""
    return CipherRegistry.get()
