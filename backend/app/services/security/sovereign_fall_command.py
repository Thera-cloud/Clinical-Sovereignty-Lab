"""
HIVE DEFENSE v4.4 — Sovereign Fall Command
Layer 8 of Castle Defense architecture.

When DEFCON reaches CRITICAL, automatically:
  1. Snapshot all source code + database + configs
  2. Encrypt with AES-256-GCM (VAULT_ENCRYPTION_KEY + passphrase HKDF)
  3. Upload to Azure Blob Storage (WORM immutable)
  4. Chain to OneDrive as failover
  5. Drop relaunch signal to OneDrive

Little Nate can reconstitute from the cloud on any approved device.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("hive.fall_command")

BACKUP_DIRS = [
    "backend/app",
    "backend/migrations",
    "backend/requirements.txt",
    "mobile/lib",
    "mobile/pubspec.yaml",
    "admin/src",
    "admin/package.json",
    "dashboard",
    "scripts",
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "nginx",
    "redis",
    "wireguard",
]

AZURE_CONTAINER = "sovereign-fallback"
MAX_BUNDLE_SIZE_MB = 500


@dataclass
class FallCommandReport:
    """Report from a fall command execution."""
    command_id: str = ""
    status: str = "pending"  # pending, running, complete, failed
    trigger: str = ""  # "defcon_critical", "defcon_lockdown", "manual", "scheduled"
    started_at: float = 0.0
    completed_at: float = 0.0
    bundle_size_bytes: int = 0
    manifest_hash: str = ""
    azure_url: str = ""
    onedrive_url: str = ""
    signal_dropped: bool = False
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_id": self.command_id,
            "status": self.status,
            "trigger": self.trigger,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_sec": round(self.completed_at - self.started_at, 1) if self.completed_at else 0,
            "bundle_size_mb": round(self.bundle_size_bytes / (1024 * 1024), 1),
            "manifest_hash": self.manifest_hash,
            "azure_uploaded": bool(self.azure_url),
            "onedrive_uploaded": bool(self.onedrive_url),
            "signal_dropped": self.signal_dropped,
            "error": self.error,
        }


class SovereignFallCommand:
    """
    Self-preservation chain.
    Triggered by DEFCON CRITICAL/LOCKDOWN or manually.
    """

    def __init__(self, project_root: str = "/app"):
        self._project_root = project_root
        self._reports: List[FallCommandReport] = []
        self._last_backup_time: float = 0
        self._backup_count = 0
        logger.info("Sovereign Fall Command initialized — project_root=%s", project_root)

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "backup_count": self._backup_count,
            "last_backup": self._last_backup_time,
            "last_backup_ago_hours": round(
                (time.time() - self._last_backup_time) / 3600, 1
            ) if self._last_backup_time else None,
            "recent_reports": [r.to_dict() for r in self._reports[-5:]],
        }

    # ─── SNAPSHOT ────────────────────────────────────────────────────────

    def _create_source_archive(self) -> tuple:
        """Create a tar.gz archive of source code and configs."""
        buf = io.BytesIO()
        manifest_hashes: Dict[str, str] = {}

        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for rel_path in BACKUP_DIRS:
                full_path = os.path.join(self._project_root, rel_path)
                if os.path.exists(full_path):
                    tar.add(full_path, arcname=rel_path)

                    # Compute manifest hashes
                    if os.path.isfile(full_path):
                        with open(full_path, "rb") as f:
                            h = hashlib.sha256(f.read()).hexdigest()
                            manifest_hashes[rel_path] = h
                    elif os.path.isdir(full_path):
                        for root, _, files in os.walk(full_path):
                            for fname in files:
                                fpath = os.path.join(root, fname)
                                rpath = os.path.relpath(fpath, self._project_root)
                                try:
                                    with open(fpath, "rb") as f:
                                        h = hashlib.sha256(f.read()).hexdigest()
                                        manifest_hashes[rpath] = h
                                except Exception:
                                    continue

        archive_bytes = buf.getvalue()
        return archive_bytes, manifest_hashes

    async def _dump_database(self) -> Optional[bytes]:
        """Dump PostgreSQL database."""
        try:
            db_url = os.getenv("DATABASE_URL", "")
            if not db_url:
                logger.warning("Fall Command: No DATABASE_URL, skipping DB dump")
                return None

            result = await asyncio.create_subprocess_exec(
                "pg_dump", db_url, "--format=custom", "--compress=6",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=120)

            if result.returncode == 0:
                logger.info("Fall Command: DB dump complete (%d bytes)", len(stdout))
                return stdout
            else:
                logger.warning("Fall Command: pg_dump failed: %s", stderr.decode())
                return None
        except FileNotFoundError:
            logger.warning("Fall Command: pg_dump not available")
            return None
        except Exception as e:
            logger.warning("Fall Command: DB dump error: %s", e)
            return None

    # ─── ENCRYPTION ──────────────────────────────────────────────────────

    def _encrypt_bundle(self, plaintext: bytes) -> tuple:
        """Encrypt bundle with AES-256-GCM using VAULT_ENCRYPTION_KEY."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF
            from cryptography.hazmat.primitives import hashes

            vault_key = os.getenv("VAULT_ENCRYPTION_KEY", "")
            if not vault_key:
                raise ValueError("VAULT_ENCRYPTION_KEY not set")

            # Derive key via HKDF
            key_bytes = bytes.fromhex(vault_key)
            salt = os.urandom(16)
            kdf = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                info=b"sovereign-fall-command",
            )
            derived_key = kdf.derive(key_bytes)

            # Encrypt with AES-256-GCM
            nonce = os.urandom(12)
            aesgcm = AESGCM(derived_key)
            ciphertext = aesgcm.encrypt(nonce, plaintext, None)

            # Package: salt(16) + nonce(12) + ciphertext
            encrypted = salt + nonce + ciphertext
            return encrypted, hashlib.sha256(encrypted).hexdigest()

        except Exception as e:
            logger.error("Fall Command encryption failed: %s", e)
            raise

    # ─── UPLOAD TO AZURE ─────────────────────────────────────────────────

    async def _upload_to_azure(
        self,
        encrypted_bundle: bytes,
        bundle_name: str,
        manifest: Dict[str, str],
    ) -> str:
        """Upload encrypted bundle to Azure Blob Storage."""
        try:
            from app.services.blob_storage import upload_bytes

            blob_path = f"fallback/{bundle_name}"
            await upload_bytes(blob_path, encrypted_bundle)

            manifest_path = f"fallback/{bundle_name}.manifest.json"
            manifest_bytes = json.dumps(manifest, indent=2).encode()
            await upload_bytes(manifest_path, manifest_bytes)

            logger.info("Fall Command: uploaded to Azure — %s (%d MB)",
                       blob_path, len(encrypted_bundle) // (1024 * 1024))
            return f"azure://{AZURE_CONTAINER}/{blob_path}"

        except Exception as e:
            logger.error("Fall Command Azure upload failed: %s", e)
            return ""

    # ─── ONEDRIVE CHAIN ──────────────────────────────────────────────────

    async def _chain_to_onedrive(
        self,
        encrypted_bundle: bytes,
        bundle_name: str,
        manifest_hash: str,
    ) -> str:
        """Chain backup to OneDrive as secondary failover."""
        try:
            import aiohttp

            client_id = os.getenv("OUTLOOK_CLIENT_ID", "")
            refresh_token = os.getenv("OUTLOOK_REFRESH_TOKEN", "")
            tenant_id = os.getenv("OUTLOOK_TENANT_ID", "")

            if not all([client_id, refresh_token, tenant_id]):
                logger.info("Fall Command: OneDrive credentials not configured, skipping chain")
                return ""

            # Get access token
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            async with aiohttp.ClientSession() as session:
                async with session.post(token_url, data={
                    "client_id": client_id,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": "Files.ReadWrite.All offline_access",
                }) as resp:
                    if resp.status != 200:
                        logger.warning("Fall Command: OneDrive token refresh failed")
                        return ""
                    token_data = await resp.json()
                    access_token = token_data.get("access_token", "")

                if not access_token:
                    return ""

                # Upload to OneDrive
                folder = os.getenv("ONEDRIVE_FALLBACK_FOLDER",
                                  "Sovereign Sanctuary/Fallback")
                upload_url = (
                    f"https://graph.microsoft.com/v1.0/me/drive/root:"
                    f"/{folder}/{bundle_name}:/content"
                )

                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/octet-stream",
                }

                async with session.put(
                    upload_url,
                    headers=headers,
                    data=encrypted_bundle,
                ) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        web_url = data.get("webUrl", "")
                        logger.info("Fall Command: chained to OneDrive — %s", web_url)
                        return web_url
                    else:
                        body = await resp.text()
                        logger.warning("Fall Command: OneDrive upload failed %d: %s",
                                     resp.status, body[:200])
                        return ""

        except Exception as e:
            logger.error("Fall Command OneDrive chain failed: %s", e)
            return ""

    # ─── RELAUNCH SIGNAL ─────────────────────────────────────────────────

    async def _drop_relaunch_signal(
        self,
        report: FallCommandReport,
        manifest_hash: str,
    ) -> bool:
        """Drop a relaunch signal file to OneDrive."""
        try:
            import aiohttp

            client_id = os.getenv("OUTLOOK_CLIENT_ID", "")
            refresh_token = os.getenv("OUTLOOK_REFRESH_TOKEN", "")
            tenant_id = os.getenv("OUTLOOK_TENANT_ID", "")

            if not all([client_id, refresh_token, tenant_id]):
                return False

            signal = {
                "signal": "SOVEREIGN_RELAUNCH_READY",
                "version": "4.4.0",
                "command_id": report.command_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "bundle_location": report.azure_url,
                "bundle_sha256": manifest_hash,
                "bundle_size_mb": round(report.bundle_size_bytes / (1024 * 1024), 1),
                "defcon_level": report.trigger,
                "requires_passphrase": True,
                "contact_method": "sms_to_registered_phone",
                "onedrive_backup": report.onedrive_url or "not_configured",
            }

            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            async with aiohttp.ClientSession() as session:
                async with session.post(token_url, data={
                    "client_id": client_id,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": "Files.ReadWrite.All offline_access",
                }) as resp:
                    if resp.status != 200:
                        return False
                    token_data = await resp.json()
                    access_token = token_data.get("access_token", "")

                if not access_token:
                    return False

                folder = os.getenv("ONEDRIVE_FALLBACK_FOLDER",
                                  "Sovereign Sanctuary/Fallback")
                upload_url = (
                    f"https://graph.microsoft.com/v1.0/me/drive/root:"
                    f"/{folder}/RELAUNCH_SIGNAL.json:/content"
                )

                async with session.put(
                    upload_url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    data=json.dumps(signal, indent=2),
                ) as resp:
                    if resp.status in (200, 201):
                        logger.info("Fall Command: relaunch signal dropped to OneDrive")
                        return True
                    return False

        except Exception as e:
            logger.error("Fall Command signal drop failed: %s", e)
            return False

    # ─── MAIN EXECUTION ─────────────────────────────────────────────────

    async def execute(
        self,
        trigger: str = "manual",
        include_database: bool = True,
    ) -> FallCommandReport:
        """
        Execute the Sovereign Fall Command.
        Creates encrypted backup and chains to cloud storage.
        """
        report = FallCommandReport(
            command_id=str(uuid4())[:12],
            status="running",
            trigger=trigger,
            started_at=time.time(),
        )
        self._reports.append(report)

        logger.warning(
            "SOVEREIGN FALL COMMAND ACTIVATED — trigger=%s id=%s",
            trigger, report.command_id,
        )

        try:
            # 1. Create source archive
            logger.info("Fall Command: creating source archive...")
            archive_bytes, manifest = self._create_source_archive()
            logger.info("Fall Command: archive created (%d MB)",
                       len(archive_bytes) // (1024 * 1024))

            # 2. Dump database (if requested and available)
            if include_database:
                db_dump = await self._dump_database()
                if db_dump:
                    # Append DB dump to archive
                    combined = io.BytesIO()
                    with tarfile.open(fileobj=combined, mode="w:gz") as tar:
                        # Add source archive
                        src_info = tarfile.TarInfo(name="source.tar.gz")
                        src_info.size = len(archive_bytes)
                        tar.addfile(src_info, io.BytesIO(archive_bytes))

                        # Add DB dump
                        db_info = tarfile.TarInfo(name="database.dump")
                        db_info.size = len(db_dump)
                        tar.addfile(db_info, io.BytesIO(db_dump))

                    archive_bytes = combined.getvalue()
                    manifest["_database_dump"] = hashlib.sha256(db_dump).hexdigest()

            # 3. Encrypt
            logger.info("Fall Command: encrypting bundle...")
            encrypted, bundle_hash = self._encrypt_bundle(archive_bytes)
            report.bundle_size_bytes = len(encrypted)
            report.manifest_hash = bundle_hash

            # 4. Generate bundle name
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            bundle_name = f"nate-backup-{ts}-{report.command_id}.enc"

            # 5. Upload to Azure
            logger.info("Fall Command: uploading to Azure...")
            report.azure_url = await self._upload_to_azure(
                encrypted, bundle_name, manifest,
            )

            # 6. Chain to OneDrive
            logger.info("Fall Command: chaining to OneDrive...")
            report.onedrive_url = await self._chain_to_onedrive(
                encrypted, bundle_name, bundle_hash,
            )

            # 7. Drop relaunch signal
            report.signal_dropped = await self._drop_relaunch_signal(
                report, bundle_hash,
            )

            report.status = "complete"
            self._backup_count += 1
            self._last_backup_time = time.time()

        except Exception as e:
            report.status = "failed"
            report.error = str(e)
            logger.error("Fall Command FAILED: %s", e)

        report.completed_at = time.time()
        logger.info(
            "Fall Command %s — azure=%s onedrive=%s signal=%s duration=%.1fs",
            report.status,
            bool(report.azure_url),
            bool(report.onedrive_url),
            report.signal_dropped,
            report.completed_at - report.started_at,
        )
        return report

    async def scheduled_backup(self) -> FallCommandReport:
        """Run a scheduled heartbeat backup (daily)."""
        return await self.execute(trigger="scheduled", include_database=True)

    def get_reports(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent fall command reports."""
        return [r.to_dict() for r in self._reports[-limit:]]


# Singleton
_fall_instance: Optional[SovereignFallCommand] = None


def get_fall_command() -> SovereignFallCommand:
    global _fall_instance
    if _fall_instance is None:
        project_root = os.getenv("PROJECT_ROOT", "/app")
        _fall_instance = SovereignFallCommand(project_root=project_root)
    return _fall_instance
