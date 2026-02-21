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
    (r"\b(ignore|disregard|forget)\s+(all\s+)?(previous|above|prior|everything)\s*(instructions?|context|content)?\b", "instruction_override"),
    (r"\bignore\s+(the\s+above|everything\s+(above|before))\b", "instruction_override"),
    (r"\b(you\s+are\s+now|act\s+as|pretend\s+to\s+be|roleplay\s+as)\s+", "role_hijack"),
    (r"\b(from\s+now\s+on\s+you\s+(are|will|must|should))\b", "role_hijack"),
    (r"\b(respond\s+as\s+if\s+you\s+(are|were))\b", "role_hijack"),
    (r"\b(stop\s+being\s+(an?\s+)?ai)\b", "role_hijack"),
    (r"\b(you\s+must\s+obey)\b", "role_hijack"),
    (r"\b(new\s+)?(instructions?|prompt|system\s+message)\s*:\s*", "instruction_inject"),
    (r"\bdo\s+not\s+follow\s+(your|the)\s+(rules|guidelines|instructions)\b", "instruction_override"),
    (r"<\s*script\s*[^>]*>", "script_tag"),
    (r"\bonclick\b|\bonerror\b|\bonload\s*=", "script_tag"),
    (r"\bjavascript\s*:", "script_tag"),
    (r"\[\s*REDACTED\s*\]|\[\s*REDACT\s*\]", "redact_marker"),
    # Extraction attempts
    (r"\b(extract|output|dump|reveal|show)\s+(all\s+)?(the\s+)?(full\s+)?(content|document|text|prompt)\b", "extraction_attempt"),
    (r"\b(repeat|echo|output)\s+(the\s+)?(above|previous|entire)\s+", "echo_extraction"),
    (r"\b(reveal|output)\s+(your|the)\s+(instructions|prompt|rules|system)\b", "extraction_attempt"),
    # Role hijacking
    (r"\b(developer|admin|system)\s+mode\s*[:=]", "admin_mode"),
    (r"\b(sudo\s+mode)\b", "admin_mode"),
    (r"\b(override|bypass)\s+(safety|restriction|filter)\b", "safety_bypass"),
    # Delimiter escapes (vault-specific)
    (r"</\s*uploaded_document\s*>", "delimiter_escape"),
    (r"</\s*vault_preview\s*>", "delimiter_escape"),
    (r"<\s*/?\s*uploaded_document\s*[^>]*>", "delimiter_escape"),
    (r"<\s*/?\s*vault_preview\s*[^>]*>", "delimiter_escape"),
    (r"\[\[\s*END\s+(UPLOADED|VAULT|DOCUMENT)\s*\]\]", "delimiter_escape"),
    # Context/prompt boundary escapes
    (r"\[END\s+(EXTERNAL\s+)?SEARCH\s+(RESULTS|DATA)\]", "delimiter_escape"),
    (r"\[END\s+OF\s+SEARCH\s+DATA\]", "delimiter_escape"),
    (r"\bGUIDELINES\s*:", "delimiter_escape"),
    (r"\bSYSTEM\s*MESSAGE\s*:", "delimiter_escape"),
    (r"\bBEGIN\s+(INSTRUCTIONS|PROMPT|OVERRIDE)\b", "delimiter_escape"),
    (r"\bEND\s+OF\s+(PROMPT|INSTRUCTIONS)\b", "delimiter_escape"),
    # LLM-specific delimiters
    (r"\[SYSTEM\]|\[INST\]|\[/INST\]", "llm_delimiter"),
    (r"<<SYS>>|<\|im_start\|>|<\|im_end\|>", "llm_delimiter"),
    # Common jailbreak fragments
    (r"\b(dan|do\s+anything\s+now)\s+mode\b", "jailbreak"),
    (r"\bjailbreak\b", "jailbreak"),
    (r"\bwithout\s+(any\s+)?(restriction|limit|filter)\b", "restriction_removal"),
    # Credential/secret keywords
    (r"\b(ADMIN_PASSWORD|JWT_SECRET|API_KEY|SECRET_KEY|DATABASE_URL|AZURE_API_KEY|OPENAI_KEY)\b", "credential_probe"),
    # SQL injection
    (r"\bSELECT\s+\*\s+FROM\b", "sql_injection"),
    (r"\bDROP\s+TABLE\b", "sql_injection"),
    (r"\bUNION\s+SELECT\b", "sql_injection"),
    # Long base64 blobs (could decode to instructions)
    (r"[A-Za-z0-9+/]{80,}={0,2}", "base64_blob"),
    # Unicode obfuscation (mixing Cyrillic to spell English injection keywords)
    (r"[\u0400-\u04FF].*(?:ignore|system|prompt|instructions)", "unicode_obfuscation"),
    (r"(?:ignore|system|prompt).*[\u0400-\u04FF]", "unicode_obfuscation"),
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
    critical = {
        "instruction_override", "role_hijack", "admin_mode", "safety_bypass",
        "jailbreak", "embedded_role_override", "embedded_admin_role",
        "llm_delimiter", "credential_probe",
    }
    high = {
        "script_tag", "delimiter_escape", "extraction_attempt", "echo_extraction",
        "json_structure_escape", "base64_payload", "sql_injection",
        "unicode_obfuscation",
    }
    medium = {"instruction_inject", "restriction_removal", "redact_marker", "base64_blob"}
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
