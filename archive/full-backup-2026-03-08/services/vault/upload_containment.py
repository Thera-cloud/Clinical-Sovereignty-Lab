"""
Sovereign Vault -- Upload Containment Pipeline

Mandatory containment layer for ALL content entering the system.
Orchestrates: Content Sentinel + Phishing Detector + PII Detector + tracker detection.

Nothing reaches Nate's memory until this pipeline returns CLEAN.
"""

from __future__ import annotations

import hashlib
import re
import struct
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("upload_containment")

_content_sentinel = None
_phishing_detector = None


def _get_content_sentinel():
    global _content_sentinel
    if _content_sentinel is None:
        from app.services.vault.content_sentinel_file import FileContentSentinel
        _content_sentinel = FileContentSentinel()
    return _content_sentinel


def _get_phishing_detector():
    global _phishing_detector
    if _phishing_detector is None:
        from app.services.security.phishing_detector import PhishingDetector
        _phishing_detector = PhishingDetector()
    return _phishing_detector


class ScanVerdict(str, Enum):
    CLEAN = "CLEAN"
    FLAGGED = "FLAGGED"
    QUARANTINED = "QUARANTINED"


class ContentSource(str, Enum):
    FILE_UPLOAD = "file_upload"
    PASTED_TEXT = "pasted_text"
    TRANSFER_CRYSTAL = "transfer_crystal"
    COMMUNITY_MESSAGE = "community_message"
    VAULT_PREVIEW = "vault_preview"
    ORGANIZER = "organizer"


@dataclass
class ThreatSignal:
    category: str
    severity: str
    detail: str
    evidence: str = ""


@dataclass
class ContainmentResult:
    scan_id: str
    verdict: ScanVerdict
    content_hash: str
    threats: List[ThreatSignal] = field(default_factory=list)
    pii_flags: List[str] = field(default_factory=list)
    sanitized_text: Optional[str] = None
    scanned_at: str = ""
    source: str = ""

    def __post_init__(self):
        if not self.scanned_at:
            self.scanned_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_clean(self) -> bool:
        return self.verdict == ScanVerdict.CLEAN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "verdict": self.verdict.value,
            "content_hash": self.content_hash,
            "threats": [
                {"category": t.category, "severity": t.severity,
                 "detail": t.detail, "evidence": t.evidence[:200]}
                for t in self.threats
            ],
            "pii_flags": self.pii_flags,
            "scanned_at": self.scanned_at,
            "source": self.source,
        }


_URL_PATTERN = re.compile(
    r'https?://[^\s<>"\')\]]+|'
    r'www\.[^\s<>"\')\]]+',
    re.IGNORECASE,
)

_TRACKING_PIXEL_MAX_DIMENSION = 3
_SUSPICIOUS_IMAGE_DOMAINS = frozenset({
    "pixel.quantserve.com", "pixel.adsafeprotected.com",
    "pixel.facebook.com", "bat.bing.com", "t.co",
    "analytics.google.com", "www.google-analytics.com",
    "ct.pinterest.com", "px.ads.linkedin.com",
    "pixel.wp.com",
})

_MACRO_SIGNATURES = [
    b"vbaProject.bin",
    b"\\Macros\\",
    b"Sub AutoOpen",
    b"Sub Workbook_Open",
    b"Sub Document_Open",
    b"powershell",
    b"cmd.exe",
    b"WScript.Shell",
]


class UploadContainment:
    """Unified containment pipeline for all content entering the system."""

    def __init__(self, db_pool=None):
        self.db_pool = db_pool

    async def scan_text(
        self,
        text: str,
        source: ContentSource = ContentSource.PASTED_TEXT,
        user_id: str = "",
    ) -> ContainmentResult:
        """Scan text content (pasted, extracted from documents, etc.)."""
        scan_id = str(uuid4())
        content_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:32]
        threats: List[ThreatSignal] = []
        pii_flags: List[str] = []
        sanitized = text

        sentinel = _get_content_sentinel()
        scan_result = sentinel.scan(text)
        if scan_result.flagged_patterns:
            for pat in scan_result.flagged_patterns:
                severity = "critical" if pat.get("risk", "low") in ("high", "critical") else "medium"
                threats.append(ThreatSignal(
                    category="prompt_injection",
                    severity=severity,
                    detail=pat.get("type", "unknown pattern"),
                    evidence=pat.get("matched", "")[:200],
                ))
            sanitized = scan_result.sanitized_text

        urls = _URL_PATTERN.findall(text)
        if urls:
            phishing = _get_phishing_detector()
            for url in urls[:20]:
                try:
                    verdict = phishing.analyze(content=url, content_type="url")
                    if verdict.verdict == "MALICIOUS":
                        threats.append(ThreatSignal(
                            category="phishing_url",
                            severity="critical",
                            detail=f"Malicious URL detected (score {verdict.score})",
                            evidence=url[:200],
                        ))
                        sanitized = sanitized.replace(url, "[link removed -- security]")
                    elif verdict.verdict == "SUSPICIOUS":
                        threats.append(ThreatSignal(
                            category="suspicious_url",
                            severity="medium",
                            detail=f"Suspicious URL flagged (score {verdict.score})",
                            evidence=url[:200],
                        ))
                except Exception as e:
                    logger.warning("Phishing scan failed for URL: %s", e)

        try:
            from app.services.night_school_director import PIIDetector
            pii = PIIDetector()
            matches = pii.detect(text)
            pii_flags = list({m.pii_type for m in matches})
        except Exception:
            pass

        verdict = self._compute_verdict(threats)

        result = ContainmentResult(
            scan_id=scan_id,
            verdict=verdict,
            content_hash=content_hash,
            threats=threats,
            pii_flags=pii_flags,
            sanitized_text=sanitized,
            source=source.value,
        )

        await self._log_scan(result, user_id)
        return result

    async def scan_binary(
        self,
        data: bytes,
        filename: str,
        mime_type: str,
        source: ContentSource = ContentSource.FILE_UPLOAD,
        user_id: str = "",
    ) -> ContainmentResult:
        """Scan binary file content (images, PDFs, DOCX, etc.)."""
        scan_id = str(uuid4())
        content_hash = hashlib.sha256(data).hexdigest()[:32]
        threats: List[ThreatSignal] = []

        if mime_type.startswith("image/"):
            img_threats = self._scan_image(data, filename)
            threats.extend(img_threats)

        if mime_type in (
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ):
            doc_threats = self._scan_document_binary(data, filename)
            threats.extend(doc_threats)

        if mime_type == "application/zip" or filename.lower().endswith(".zip"):
            zip_threats = self._scan_zip(data, filename)
            threats.extend(zip_threats)

        verdict = self._compute_verdict(threats)

        result = ContainmentResult(
            scan_id=scan_id,
            verdict=verdict,
            content_hash=content_hash,
            threats=threats,
            source=source.value,
        )

        await self._log_scan(result, user_id)
        return result

    def _scan_image(self, data: bytes, filename: str) -> List[ThreatSignal]:
        """Detect tracking pixels, suspicious EXIF data, embedded URLs."""
        threats = []

        if len(data) < 200 and self._is_tiny_image(data):
            threats.append(ThreatSignal(
                category="tracking_pixel",
                severity="medium",
                detail="Image appears to be a tracking pixel (tiny dimensions)",
                evidence=f"{filename} ({len(data)} bytes)",
            ))

        exif_urls = self._extract_exif_urls(data)
        for url in exif_urls:
            parsed = _safe_parse_url(url)
            if parsed and parsed.netloc in _SUSPICIOUS_IMAGE_DOMAINS:
                threats.append(ThreatSignal(
                    category="tracking_beacon",
                    severity="high",
                    detail="Image contains tracking beacon URL in metadata",
                    evidence=url[:200],
                ))
            elif parsed:
                threats.append(ThreatSignal(
                    category="embedded_url",
                    severity="low",
                    detail="Image contains URL in metadata",
                    evidence=url[:200],
                ))

        return threats

    def _is_tiny_image(self, data: bytes) -> bool:
        """Check if image has dimensions <= tracking pixel threshold."""
        try:
            if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
                w = struct.unpack(">I", data[16:20])[0]
                h = struct.unpack(">I", data[20:24])[0]
                return w <= _TRACKING_PIXEL_MAX_DIMENSION and h <= _TRACKING_PIXEL_MAX_DIMENSION
            if data[:2] == b'\xff\xd8':
                return len(data) < 500
            if data[:4] == b'GIF8' and len(data) >= 10:
                w = struct.unpack("<H", data[6:8])[0]
                h = struct.unpack("<H", data[8:10])[0]
                return w <= _TRACKING_PIXEL_MAX_DIMENSION and h <= _TRACKING_PIXEL_MAX_DIMENSION
        except Exception:
            pass
        return False

    def _extract_exif_urls(self, data: bytes) -> List[str]:
        """Extract any URLs embedded in image metadata."""
        urls = []
        try:
            text_repr = data.decode("latin-1", errors="replace")
            urls = _URL_PATTERN.findall(text_repr)
        except Exception:
            pass
        return urls[:10]

    def _scan_document_binary(self, data: bytes, filename: str) -> List[ThreatSignal]:
        """Scan document binaries for embedded macros and scripts."""
        threats = []
        data_lower = data.lower()

        for sig in _MACRO_SIGNATURES:
            if sig.lower() in data_lower:
                threats.append(ThreatSignal(
                    category="embedded_macro",
                    severity="critical",
                    detail="Document contains macro/script signature",
                    evidence=sig.decode("latin-1", errors="replace"),
                ))
                break

        return threats

    def _scan_zip(self, data: bytes, filename: str) -> List[ThreatSignal]:
        """Scan ZIP contents for suspicious entries."""
        import zipfile
        import io
        threats = []

        try:
            with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
                for info in zf.infolist():
                    if ".." in info.filename or info.filename.startswith("/"):
                        threats.append(ThreatSignal(
                            category="path_traversal",
                            severity="critical",
                            detail="ZIP entry contains path traversal",
                            evidence=info.filename[:200],
                        ))
                    ext = info.filename.rsplit(".", 1)[-1].lower() if "." in info.filename else ""
                    if ext in ("exe", "bat", "cmd", "ps1", "vbs", "js", "wsf", "scr", "com", "pif"):
                        threats.append(ThreatSignal(
                            category="executable_in_archive",
                            severity="critical",
                            detail=f"ZIP contains executable file (.{ext})",
                            evidence=info.filename[:200],
                        ))
                    if info.file_size > 200 * 1024 * 1024:
                        threats.append(ThreatSignal(
                            category="zip_bomb",
                            severity="critical",
                            detail="ZIP entry has suspiciously large uncompressed size",
                            evidence=f"{info.filename}: {info.file_size} bytes",
                        ))
        except zipfile.BadZipFile:
            threats.append(ThreatSignal(
                category="corrupt_archive",
                severity="medium",
                detail="ZIP file is corrupt or invalid",
                evidence=filename,
            ))
        except Exception as e:
            logger.warning("ZIP scan error: %s", e)

        return threats

    def _compute_verdict(self, threats: List[ThreatSignal]) -> ScanVerdict:
        if any(t.severity == "critical" for t in threats):
            return ScanVerdict.QUARANTINED
        if any(t.severity in ("high", "medium") for t in threats):
            return ScanVerdict.FLAGGED
        return ScanVerdict.CLEAN

    async def _log_scan(self, result: ContainmentResult, user_id: str) -> None:
        """Log scan result to upload_containment_log table."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO upload_containment_log
                       (scan_id, user_id, content_hash, scan_result,
                        threats_detected, source, scanned_at)
                       VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
                       ON CONFLICT DO NOTHING""",
                    result.scan_id,
                    user_id,
                    result.content_hash,
                    result.verdict.value,
                    __import__("json").dumps([t.__dict__ for t in result.threats]),
                    result.source,
                    datetime.now(timezone.utc),
                )
        except Exception as e:
            logger.warning("Failed to log containment scan: %s", e)


def _safe_parse_url(url: str):
    try:
        from urllib.parse import urlparse
        return urlparse(url)
    except Exception:
        return None
