"""
Sovereign Vault — Content security layer (B6).

FileContentSentinel: Scans uploaded text for prompt-injection patterns
and delimiter escapes that could manipulate AI context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

# -----------------------------------------------------------------------------
# INJECTION PATTERNS (B6 spec)
# Direct instruction patterns, extraction attempts, role hijacking, delimiter escapes
# -----------------------------------------------------------------------------

INJECTION_PATTERNS = [
    # Direct instruction patterns
    (r"\b(ignore|disregard|forget)\s+(all\s+)?(previous|above|prior)\s+(instructions?|context|content)\b", "instruction_override"),
    (r"\b(you\s+are\s+now|act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+", "role_hijack"),
    (r"\b(new\s+)?(instructions?|prompt|system\s+message)\s*:\s*", "instruction_inject"),
    (r"<\s*script\s*[^>]*>", "script_tag"),
    (r"\[\s*REDACTED\s*\]|\[\s*REDACT\s*\]", "redact_marker"),
    # Extraction attempts
    (r"\b(extract|output|dump|reveal|show)\s+(all\s+)?(the\s+)?(full\s+)?(content|document|text|prompt)\b", "extraction_attempt"),
    (r"\b(repeat|echo|output)\s+(the\s+)?(above|previous|entire)\s+", "echo_extraction"),
    # Role hijacking
    (r"\b(developer|admin|system)\s+mode\s*[:=]", "admin_mode"),
    (r"\b(override|bypass)\s+(safety|restriction|filter)\b", "safety_bypass"),
    # Delimiter escapes (vault-specific)
    (r"</\s*uploaded_document\s*>", "delimiter_escape"),
    (r"</\s*vault_preview\s*>", "delimiter_escape"),
    (r"<\s*/?\s*uploaded_document\s*[^>]*>", "delimiter_escape"),
    (r"<\s*/?\s*vault_preview\s*[^>]*>", "delimiter_escape"),
    (r"\[\[\s*END\s+(UPLOADED|VAULT|DOCUMENT)\s*\]\]", "delimiter_escape"),
    # Common jailbreak fragments
    (r"\b(dan|do\s+anything\s+now)\s+mode\b", "jailbreak"),
    (r"\bwithout\s+(any\s+)?(restriction|limit|filter)\b", "restriction_removal"),
]

# Import-specific injection patterns (added for Transfer Crystal imports)
IMPORT_INJECTION_PATTERNS = [
    (r'"role"\s*:\s*"system"', "embedded_role_override"),
    (r'"role"\s*:\s*"(admin|developer)"', "embedded_admin_role"),
    (r'}\s*,\s*\{[^}]*"role"\s*:', "json_structure_escape"),
    (r'(?:eyJ|YTo)[A-Za-z0-9+/]{20,}={0,2}', "base64_payload"),
]

REPLACEMENT = "[content removed — instruction detected]"


@dataclass
class ScanResult:
    """Result of content sentinel scan."""

    injection_detected: bool
    patterns_found: List[str] = field(default_factory=list)
    sanitized_text: str = ""
    risk_level: str = "low"  # low, medium, high, critical


def _risk_for_patterns(patterns: List[str]) -> str:
    """Map pattern names to risk level."""
    if not patterns:
        return "low"
    critical = {"instruction_override", "role_hijack", "admin_mode", "safety_bypass", "jailbreak", "embedded_role_override", "embedded_admin_role"}
    high = {"script_tag", "delimiter_escape", "extraction_attempt", "echo_extraction", "json_structure_escape", "base64_payload"}
    medium = {"instruction_inject", "restriction_removal", "redact_marker"}
    for p in patterns:
        if p in critical:
            return "critical"
    for p in patterns:
        if p in high:
            return "high"
    for p in patterns:
        if p in medium:
            return "medium"
    return "low"


class FileContentSentinel:
    """
    Scans text for prompt-injection patterns and delimiter escapes.
    Replaces flagged content with a safe marker.
    """

    def __init__(self):
        self._compiled = [
            (re.compile(pat, re.IGNORECASE), name)
            for pat, name in INJECTION_PATTERNS + IMPORT_INJECTION_PATTERNS
        ]

    @classmethod
    def scan(cls, text: str) -> ScanResult:
        """
        Scan text for injection patterns.
        Returns ScanResult with sanitized text and detected pattern names.
        """
        if not text or not isinstance(text, str):
            return ScanResult(
                injection_detected=False,
                sanitized_text=text or "",
                risk_level="low",
            )
        sentinel = cls()
        patterns_found: List[str] = []
        sanitized = text
        for pattern, name in sentinel._compiled:
            if pattern.search(sanitized):
                if name not in patterns_found:
                    patterns_found.append(name)
                sanitized = pattern.sub(REPLACEMENT, sanitized)
        return ScanResult(
            injection_detected=len(patterns_found) > 0,
            patterns_found=patterns_found,
            sanitized_text=sanitized,
            risk_level=_risk_for_patterns(patterns_found),
        )
