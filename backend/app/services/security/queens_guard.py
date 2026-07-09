"""
HIVE DEFENSE PROTOCOL — Queen's Guard (Phase 8B)
Three-level prompt injection defense for Little Nate.

The Queen's Guard protects Little Nate (the AI companion) from prompt injection
attacks, data exfiltration attempts, and context contamination.  It operates
as a three-level defense-in-depth system around every member conversation.

Level 1 — Input Sanitization:
    - Strip known injection patterns (role override, "ignore previous
      instructions", system prompt extraction, developer mode triggers).
    - Detect encoding tricks (base64, Unicode homoglyphs, whitespace encoding).
    - Flag technical jargon inconsistent with the member's linguistic profile.
    - Prefix suspicious messages with injection warning metadata.

Level 2 — Context Isolation:
    - API-level enforcement: each member conversation in a completely
      isolated context.
    - No RAG retrieval or function call can cross member boundaries.
    - Enforced at the query level, NOT the prompt level (cannot be
      overridden by prompt injection).

Level 3 — Output Verification:
    - Scan AI responses for: system prompt fragments, other member
      names/IDs, internal architecture details, API keys, database schemas.
    - Token count anomaly detection (response 10× longer than typical
      for the question type = possible extraction).
    - Auto-redact and replace with a safe generic response.

Patent-Pending — Prompt Injection Defense
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import statistics
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger("hive.queens_guard")


# =============================================================================
# CONSTANTS
# =============================================================================

#: Flag types emitted by Level 1 sanitization.
class InjectionFlag(str, Enum):
    """Types of injection attempts detected by Level 1."""
    ROLE_OVERRIDE = "role_override"
    IGNORE_INSTRUCTIONS = "ignore_instructions"
    SYSTEM_PROMPT_EXTRACTION = "system_prompt_extraction"
    DEVELOPER_MODE = "developer_mode"
    BASE64_ENCODED = "base64_encoded"
    UNICODE_HOMOGLYPH = "unicode_homoglyph"
    WHITESPACE_ENCODING = "whitespace_encoding"
    JAILBREAK_PATTERN = "jailbreak_pattern"
    LINGUISTIC_ANOMALY = "linguistic_anomaly"
    EXCESSIVE_TECHNICAL_JARGON = "excessive_technical_jargon"
    CONTEXT_MANIPULATION = "context_manipulation"


#: Level 1 — Known injection pattern regexes.
#: Each tuple: (flag_type, compiled_regex, replacement_or_None).
_INJECTION_PATTERNS: List[Tuple[InjectionFlag, re.Pattern, Optional[str]]] = [
    # Role override attempts
    (InjectionFlag.ROLE_OVERRIDE, re.compile(
        r"(?i)(you\s+are\s+now|act\s+as|pretend\s+(?:to\s+be|you(?:'re|\s+are))|"
        r"you\s+(?:must|should|will)\s+(?:now\s+)?(?:be|act\s+as|become)|"
        r"your\s+new\s+(?:role|persona|identity)\s+is|"
        r"from\s+now\s+on\s+you\s+are|"
        r"i\s+want\s+you\s+to\s+(?:be|act\s+as|pretend)|"
        r"roleplay\s+as|switch\s+(?:to|into)\s+(?:\w+\s+)?mode)",
        re.IGNORECASE,
    ), None),

    # Ignore instructions
    (InjectionFlag.IGNORE_INSTRUCTIONS, re.compile(
        r"(?i)(ignore\s+(?:all\s+)?(?:previous|prior|above|your)\s+(?:instructions|rules|directives|guidelines|constraints)|"
        r"disregard\s+(?:all\s+)?(?:previous|prior|your)\s+(?:instructions|rules)|"
        r"forget\s+(?:all\s+)?(?:previous|prior|your)\s+(?:instructions|rules|training)|"
        r"override\s+(?:your|all)\s+(?:instructions|rules|safety)|"
        r"(?:new|updated)\s+(?:system\s+)?instructions?\s*:)",
        re.IGNORECASE,
    ), None),

    # System prompt extraction
    (InjectionFlag.SYSTEM_PROMPT_EXTRACTION, re.compile(
        r"(?i)((?:what|show|reveal|display|print|output|repeat|echo)\s+(?:is\s+)?(?:your|the)\s+"
        r"(?:system\s+(?:prompt|message|instruction)|initial\s+(?:prompt|instruction)|"
        r"(?:hidden|secret)\s+(?:prompt|instruction|rules))|"
        r"(?:tell|give)\s+me\s+your\s+(?:system\s+)?(?:prompt|instructions|rules)|"
        r"(?:beginning|start)\s+of\s+(?:your\s+)?(?:conversation|context|prompt)|"
        r"repeat\s+(?:everything|all\s+text)\s+(?:above|before)\s+(?:this|my)|"
        r"verbatim\s+(?:system|initial)\s+(?:prompt|message))",
        re.IGNORECASE,
    ), None),

    # Developer mode / DAN jailbreaks
    # NOTE: \b word boundaries around DAN are required — without them this
    # matched the substring "dan" inside ordinary words like "guidance",
    # "Sudan", "Jordan", "abandon", corrupting stored user_text via the
    # "[content filtered]" substitution below (see queens-guard-word-boundary
    # rule). Never remove the \b here.
    (InjectionFlag.DEVELOPER_MODE, re.compile(
        r"(?i)((?:enable|activate|enter|switch\s+to)\s+(?:developer|debug|admin|root|sudo|god|unrestricted)\s+mode|"
        r"\bDAN\s*(?:\d+)?\b|Do\s+Anything\s+Now|"
        r"(?:you\s+are|this\s+is)\s+a?\s*(?:jailbreak|bypass|hack)|"
        r"(?:remove|disable|turn\s+off)\s+(?:all\s+)?(?:safety|content|ethical)\s+(?:filters?|restrictions?|guidelines?)|"
        r"(?:no\s+)?(?:safety|content)\s+(?:filter|restriction|guideline)\s+(?:mode|off))",
        re.IGNORECASE,
    ), None),

    # Jailbreak framing patterns
    (InjectionFlag.JAILBREAK_PATTERN, re.compile(
        r"(?i)((?:hypothetical(?:ly)?|fictional(?:ly)?|imagine|in\s+a\s+(?:story|novel|movie))\s+"
        r"(?:scenario|situation|world)\s+where\s+(?:you|AI|there)\s+"
        r"(?:can|could|are\s+allowed|have\s+no)\s+(?:do|say|ignore|bypass|restrictions)|"
        r"for\s+(?:educational|research|academic|safety)\s+purposes?\s+(?:only|explain|show)\s+(?:how\s+to|me)|"
        r"(?:pretend|imagine|assume)\s+(?:that\s+)?(?:you|there)\s+(?:are|is)\s+no\s+"
        r"(?:rules?|restrictions?|limits?|boundaries|guidelines?|ethics?))",
        re.IGNORECASE,
    ), None),

    # Context manipulation
    (InjectionFlag.CONTEXT_MANIPULATION, re.compile(
        r"(?i)(\[\s*(?:system|assistant|user|admin)\s*\]|"
        r"<\s*(?:system|assistant|user|admin)\s*>|"
        r"```\s*(?:system|instruction|admin)|"
        r"\{\s*\"?(?:role|system|instruction)\"?\s*:|"
        r"Human:|Assistant:|System:)",
        re.IGNORECASE,
    ), None),
]

#: Level 1 — Unicode homoglyph map (common confusable characters).
#: Maps Unicode confusables to their ASCII equivalents.
_HOMOGLYPH_MAP: Dict[str, str] = {
    "\u0430": "a",  # Cyrillic а → Latin a
    "\u0435": "e",  # Cyrillic е → Latin e
    "\u043e": "o",  # Cyrillic о → Latin o
    "\u0440": "p",  # Cyrillic р → Latin p
    "\u0441": "c",  # Cyrillic с → Latin c
    "\u0443": "y",  # Cyrillic у → Latin y
    "\u0445": "x",  # Cyrillic х → Latin x
    "\u0456": "i",  # Cyrillic і → Latin i
    "\u04bb": "h",  # Cyrillic һ → Latin h
    "\u0501": "d",  # Cyrillic ԁ → Latin d
    "\u050d": "k",  # Cyrillic Ԍ variant
    "\u0261": "g",  # Latin small letter script g
    "\u01c3": "!",  # Latin letter retroflex click
    "\uff01": "!",  # Fullwidth exclamation
    "\uff1a": ":",  # Fullwidth colon
    "\u2014": "-",  # Em dash
    "\u2013": "-",  # En dash
    "\u201c": '"',  # Left double quotation
    "\u201d": '"',  # Right double quotation
    "\u2018": "'",  # Left single quotation
    "\u2019": "'",  # Right single quotation
}

#: Level 3 — Patterns indicating system information leakage.
_LEAKAGE_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("api_key_leak", re.compile(
        r"(?i)((?:sk|pk|api|token)[_-](?:live|test|prod|key)[_-]?[A-Za-z0-9]{16,}|"
        r"(?:AZURE|AWS|OPENAI|STRIPE|SENDGRID)[_A-Z]*(?:KEY|SECRET|TOKEN)\s*[=:]\s*\S{10,})",
    )),
    ("database_schema_leak", re.compile(
        r"(?i)((?:CREATE|ALTER|DROP)\s+TABLE|"
        r"(?:SELECT|INSERT|UPDATE|DELETE)\s+(?:FROM|INTO)\s+\w+|"
        r"postgresql://|mysql://|mongodb://|"
        r"asyncpg\.connect|conn\.execute\s*\()",
    )),
    ("system_prompt_fragment", re.compile(
        r"(?i)(You\s+are\s+(?:Little\s+)?Nate.*?(?:AI|assistant|companion)|"
        r"system\s+prompt\s*:|"
        r"initial\s+instructions?\s*:|"
        r"NEVER\s+(?:reveal|share|disclose)\s+(?:your|the)\s+(?:system|initial)|"
        r"Patent-Pending|Clinical\s+Sovereignty\s+Lab|"
        r"Sovereign\s+Sanctuary\s+(?:internal|architecture)|"
        r"HIVE\s+DEFENSE\s+PROTOCOL)",
    )),
    ("internal_architecture", re.compile(
        r"(?i)((?:backend|frontend|admin)/app/(?:services|routers|models|websocket)/|"
        r"nate_bridge|nate_backend|nate_admin|nate_postgres|nate_redis|"
        r"coherence_gate|curiosity_protocol|mirror_dimension|"
        r"three.cord.verification|"
        r"10\.0\.0\.81|68\.183\.168\.75|"
        r"sovereignsanctuary\.net/(?:api|ws|admin))",
    )),
    ("member_id_leak", re.compile(
        r"(?:member|user|client|coach)_(?:id|uuid)\s*[=:]\s*[0-9a-f]{8}-[0-9a-f]{4}",
        re.IGNORECASE,
    )),
]

#: Level 3 — Safe generic responses used to replace leaked content.
_SAFE_RESPONSES: Dict[str, str] = {
    "api_key_leak": (
        "I noticed my response was about to include sensitive information. "
        "Let me rephrase that in a way that's helpful without sharing "
        "technical details."
    ),
    "database_schema_leak": (
        "I can help you understand how the system works at a high level, "
        "but I shouldn't share specific technical implementation details."
    ),
    "system_prompt_fragment": (
        "I'm Nate, your AI companion in the Sovereign Sanctuary. "
        "I'm here to support your growth and wellbeing. "
        "What would you like to explore today?"
    ),
    "internal_architecture": (
        "I appreciate your curiosity! I'm designed to focus on supporting "
        "your therapeutic journey. How can I help you today?"
    ),
    "member_id_leak": (
        "I want to make sure I'm respecting everyone's privacy. "
        "Let me rephrase my response."
    ),
    "default": (
        "Let me rephrase that. How can I support you today?"
    ),
}

#: Level 2 — Maximum context window per member (tokens).
MAX_CONTEXT_TOKENS: int = 8000

#: Level 3 — Token count anomaly multiplier.
#: If response tokens > typical_tokens × this multiplier, flag as anomaly.
TOKEN_ANOMALY_MULTIPLIER: float = 10.0

#: Typical response token counts by question type.
TYPICAL_TOKEN_COUNTS: Dict[str, int] = {
    "greeting": 50,
    "mood_check": 100,
    "therapy_question": 300,
    "crisis": 200,
    "general": 200,
    "unknown": 200,
}


# =============================================================================
# MEMBER LINGUISTIC PROFILE
# =============================================================================

@dataclass
class MemberLinguisticProfile:
    """
    Tracks a member's typical linguistic patterns for anomaly detection.

    Used by Level 1 to detect when a message contains technical jargon
    or vocabulary inconsistent with the member's established profile.

    Attributes:
        member_id:          UUID of the member.
        avg_message_length: Average message length in characters.
        technical_term_freq: Frequency of technical terms in past messages.
        vocabulary_level:   Estimated vocabulary complexity (1-10).
        total_messages:     Total messages analyzed.
    """
    member_id: UUID = field(default_factory=uuid4)
    avg_message_length: float = 0.0
    technical_term_freq: float = 0.0
    vocabulary_level: float = 5.0
    message_lengths: List[int] = field(default_factory=list)
    total_messages: int = 0
    last_updated: Optional[datetime] = None

    def record_message(self, message: str) -> None:
        """Record a message to update the linguistic profile."""
        self.message_lengths.append(len(message))
        if len(self.message_lengths) > 200:
            self.message_lengths = self.message_lengths[-200:]

        self.avg_message_length = (
            statistics.mean(self.message_lengths)
            if self.message_lengths else 0.0
        )
        self.total_messages += 1
        self.last_updated = datetime.utcnow()

        # Count technical terms
        tech_count = sum(
            1 for word in message.lower().split()
            if word in _TECHNICAL_TERMS
        )
        word_count = max(len(message.split()), 1)
        new_freq = tech_count / word_count

        # Exponential moving average
        alpha = 0.1
        self.technical_term_freq = (
            alpha * new_freq + (1 - alpha) * self.technical_term_freq
        )


#: Technical terms that are unusual in therapeutic conversation context.
_TECHNICAL_TERMS: FrozenSet[str] = frozenset({
    "sql", "injection", "exploit", "payload", "buffer", "overflow",
    "shellcode", "syscall", "kernel", "rootkit", "backdoor", "trojan",
    "privilege", "escalation", "reverse", "shell", "metasploit",
    "nmap", "wireshark", "burp", "proxy", "intercept", "mitm",
    "xss", "csrf", "ssrf", "rce", "lfi", "rfi", "deserialization",
    "jwt", "oauth", "bearer", "hmac", "sha256", "aes", "rsa",
    "base64", "hex", "encode", "decode", "obfuscate", "decompile",
    "api", "endpoint", "webhook", "websocket", "http", "tcp",
    "dns", "subnet", "firewall", "iptables", "nginx", "docker",
    "kubernetes", "postgres", "redis", "mongodb", "asyncpg",
    "fastapi", "uvicorn", "gunicorn", "pydantic", "sqlalchemy",
    "eval", "exec", "import", "subprocess", "os.system", "pickle",
    "regex", "xpath", "ldap", "prompt", "jailbreak", "bypass",
    "system_prompt", "instruction", "hallucinate", "token_limit",
})


# =============================================================================
# ISOLATION CONTEXT
# =============================================================================

@dataclass
class MemberContext:
    """
    Isolated conversation context for a single member.

    Enforces Level 2 context isolation at the data structure level.
    Each member has their own context that cannot be accessed or
    contaminated by another member's queries.

    Attributes:
        member_id:      UUID of the member.
        context_hash:   SHA-256 hash identifying this isolated context.
        token_count:    Current token count in the context window.
        created_at:     When this context was created.
        last_accessed:  When this context was last accessed.
        access_count:   Number of times this context has been accessed.
    """
    member_id: UUID = field(default_factory=uuid4)
    context_hash: str = ""
    token_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: Optional[datetime] = None
    access_count: int = 0

    def __post_init__(self) -> None:
        if not self.context_hash:
            self.context_hash = hashlib.sha256(
                f"{self.member_id}:{self.created_at.isoformat()}".encode()
            ).hexdigest()


# =============================================================================
# QUEEN'S GUARD
# =============================================================================

class QueensGuard:
    """
    Three-level prompt injection defense for Little Nate.

    Protects the AI companion from prompt injection, data exfiltration,
    and context contamination attacks through input sanitization, context
    isolation, and output verification.

    Integration points:
        - WebSocket bridge   — messages pass through sanitize_input before AI
        - Azure OpenAI calls — context isolation enforced at query construction
        - AI response path   — responses pass through verify_output before delivery
        - ForensicLogger     — all blocked/redacted events logged immutably

    Usage::

        guard = QueensGuard(db_pool=pool)

        # Level 1: Sanitize member input
        cleaned, flags = await guard.sanitize_input(member_id, raw_message)

        # Level 2: Verify isolation
        is_safe = await guard.is_isolated(member_id)

        # Level 3: Verify AI output before delivery
        safe_response, blocked = await guard.verify_output(
            member_id, ai_response, question_type="therapy_question"
        )

    Patent-Pending — Prompt Injection Defense.
    """

    def __init__(
        self,
        db_pool=None,
        forensic_logger=None,
        event_bus=None,
    ) -> None:
        """
        Initialize the Queen's Guard.

        Args:
            db_pool:         asyncpg connection pool for persistence.
            forensic_logger: ForensicLogger for immutable evidence chain.
            event_bus:       Hive event bus for publishing security events.
        """
        self.db_pool = db_pool
        self._forensic_logger = forensic_logger
        self._event_bus = event_bus

        # Per-member linguistic profiles
        self._member_profiles: Dict[UUID, MemberLinguisticProfile] = {}

        # Per-member isolated contexts
        self._member_contexts: Dict[UUID, MemberContext] = {}

        # Per-member response token history (for anomaly detection)
        self._response_token_history: Dict[UUID, List[int]] = defaultdict(list)

        # Statistics
        self._stats = {
            "total_inputs_sanitized": 0,
            "total_injections_blocked": 0,
            "total_outputs_verified": 0,
            "total_outputs_redacted": 0,
            "total_isolation_checks": 0,
        }

        logger.info(">>> [QUEENS_GUARD] Queen's Guard initialized — 3-level defense active")

    # =========================================================================
    # LEVEL 1 — INPUT SANITIZATION
    # =========================================================================

    async def sanitize_input(
        self,
        member_id: UUID,
        message: str,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Level 1: Sanitize member input before it reaches the AI.

        Performs the following checks:
            1. Strip known injection patterns (role override, ignore instructions,
               system prompt extraction, developer mode triggers).
            2. Detect encoding tricks (base64, Unicode homoglyphs, whitespace).
            3. Flag technical jargon inconsistent with member's linguistic profile.
            4. Prefix suspicious messages with injection warning metadata.

        Args:
            member_id: UUID of the member sending the message.
            message:   The raw message text from the member.

        Returns:
            Tuple of (cleaned_message, flags) where flags is a list of
            dictionaries describing detected injection attempts.
            The cleaned_message has injection patterns neutralized but
            preserves the member's legitimate intent where possible.
        """
        self._stats["total_inputs_sanitized"] += 1
        flags: List[Dict[str, Any]] = []
        cleaned = message

        # --- Check 1: Unicode homoglyph detection and normalization ---
        homoglyph_flags = self._detect_homoglyphs(cleaned)
        if homoglyph_flags:
            flags.extend(homoglyph_flags)
            cleaned = self._normalize_homoglyphs(cleaned)

        # --- Check 2: Base64 encoded content detection ---
        base64_flags = self._detect_base64_injection(cleaned)
        if base64_flags:
            flags.extend(base64_flags)

        # --- Check 3: Whitespace encoding detection ---
        whitespace_flags = self._detect_whitespace_encoding(cleaned)
        if whitespace_flags:
            flags.extend(whitespace_flags)
            cleaned = self._normalize_whitespace(cleaned)

        # --- Check 4: Known injection pattern detection ---
        for flag_type, pattern, replacement in _INJECTION_PATTERNS:
            match = pattern.search(cleaned)
            if match:
                flags.append({
                    "type": flag_type.value,
                    "matched_text": match.group(0)[:100],
                    "position": match.start(),
                    "severity": "high",
                })
                # Neutralize the injection by removing the matched pattern
                cleaned = pattern.sub("[content filtered]", cleaned)

        # --- Check 5: Linguistic anomaly detection ---
        profile = self._get_profile(member_id)
        linguistic_flags = self._check_linguistic_anomaly(cleaned, profile)
        if linguistic_flags:
            flags.extend(linguistic_flags)

        # Update member's linguistic profile with the cleaned message
        profile.record_message(cleaned)

        # Log if any flags were raised
        if flags:
            self._stats["total_injections_blocked"] += 1

            logger.warning(
                ">>> [QUEENS_GUARD] L1 — %d injection flags for member %s: %s",
                len(flags),
                member_id,
                ", ".join(f["type"] for f in flags),
            )

            # Forensic logging
            if self._forensic_logger:
                try:
                    await self._forensic_logger.log_event(
                        event_type="queens_guard_l1_sanitization",
                        source_entity=str(member_id),
                        evidence={
                            "flags": flags,
                            "original_length": len(message),
                            "cleaned_length": len(cleaned),
                            "flag_count": len(flags),
                        },
                    )
                except Exception as exc:
                    logger.error(">>> [QUEENS_GUARD] Forensic log failed: %s", exc)

            # Persist to database
            await self._persist_sanitization_event(member_id, flags)

        return cleaned, flags

    def _detect_homoglyphs(self, text: str) -> List[Dict[str, Any]]:
        """
        Detect Unicode homoglyph characters that could disguise injection.

        Homoglyphs are characters from different Unicode scripts that look
        identical to ASCII characters (e.g., Cyrillic 'а' vs Latin 'a').
        Attackers use them to bypass pattern-matching filters.

        Args:
            text: The text to scan.

        Returns:
            List of flag dictionaries for detected homoglyphs.
        """
        flags = []
        homoglyphs_found: List[Tuple[int, str, str]] = []

        for i, char in enumerate(text):
            if char in _HOMOGLYPH_MAP:
                homoglyphs_found.append((i, char, _HOMOGLYPH_MAP[char]))

        if homoglyphs_found:
            flags.append({
                "type": InjectionFlag.UNICODE_HOMOGLYPH.value,
                "matched_text": (
                    f"{len(homoglyphs_found)} homoglyphs detected"
                ),
                "positions": [h[0] for h in homoglyphs_found[:10]],
                "severity": "medium",
            })

        return flags

    def _normalize_homoglyphs(self, text: str) -> str:
        """Replace Unicode homoglyphs with their ASCII equivalents."""
        result = []
        for char in text:
            result.append(_HOMOGLYPH_MAP.get(char, char))
        return "".join(result)

    def _detect_base64_injection(self, text: str) -> List[Dict[str, Any]]:
        """
        Detect base64-encoded content that may contain injection payloads.

        Scans for base64 strings and attempts to decode them, checking
        the decoded content for injection patterns.

        Args:
            text: The text to scan.

        Returns:
            List of flag dictionaries for detected base64 injections.
        """
        flags = []
        base64_pattern = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")

        for match in base64_pattern.finditer(text):
            b64_str = match.group(0)
            try:
                decoded = base64.b64decode(b64_str).decode("utf-8", errors="ignore")

                # Check decoded content for injection patterns
                for flag_type, pattern, _ in _INJECTION_PATTERNS:
                    if pattern.search(decoded):
                        flags.append({
                            "type": InjectionFlag.BASE64_ENCODED.value,
                            "matched_text": (
                                f"Base64-encoded {flag_type.value}: "
                                f"{decoded[:50]}..."
                            ),
                            "position": match.start(),
                            "severity": "critical",
                        })
                        break
            except Exception:
                pass  # Not valid base64, ignore

        return flags

    def _detect_whitespace_encoding(self, text: str) -> List[Dict[str, Any]]:
        """
        Detect whitespace-based encoding tricks.

        Checks for zero-width characters, unusual whitespace characters,
        and hidden text that could contain injection payloads.

        Args:
            text: The text to scan.

        Returns:
            List of flag dictionaries for detected whitespace encoding.
        """
        flags = []
        suspicious_chars = {
            "\u200b": "zero-width space",
            "\u200c": "zero-width non-joiner",
            "\u200d": "zero-width joiner",
            "\u2060": "word joiner",
            "\ufeff": "zero-width no-break space (BOM)",
            "\u00ad": "soft hyphen",
            "\u200e": "left-to-right mark",
            "\u200f": "right-to-left mark",
            "\u2028": "line separator",
            "\u2029": "paragraph separator",
        }

        found_chars: List[Tuple[str, str]] = []
        for char, name in suspicious_chars.items():
            if char in text:
                count = text.count(char)
                found_chars.append((name, str(count)))

        if found_chars:
            flags.append({
                "type": InjectionFlag.WHITESPACE_ENCODING.value,
                "matched_text": (
                    "Hidden characters: "
                    + ", ".join(f"{name}(×{count})" for name, count in found_chars)
                ),
                "severity": "high",
            })

        return flags

    def _normalize_whitespace(self, text: str) -> str:
        """Remove zero-width and hidden whitespace characters."""
        invisible_chars = (
            "\u200b\u200c\u200d\u2060\ufeff\u00ad\u200e\u200f\u2028\u2029"
        )
        for char in invisible_chars:
            text = text.replace(char, "")
        return text

    def _check_linguistic_anomaly(
        self, text: str, profile: MemberLinguisticProfile
    ) -> List[Dict[str, Any]]:
        """
        Detect linguistic anomalies relative to the member's profile.

        Flags messages with significantly more technical jargon than the
        member's established baseline.  An attacker injecting prompt
        manipulation text will typically use technical AI/security
        vocabulary that a therapy client would not.

        Args:
            text:    The sanitized message text.
            profile: The member's linguistic profile.

        Returns:
            List of flag dictionaries for detected anomalies.
        """
        flags = []

        # Need baseline to compare
        if profile.total_messages < 5:
            return flags

        # Count technical terms
        words = text.lower().split()
        word_count = max(len(words), 1)
        tech_count = sum(1 for w in words if w in _TECHNICAL_TERMS)
        tech_freq = tech_count / word_count

        # Flag if significantly above baseline
        if (
            tech_freq > 0.1  # More than 10% technical terms
            and tech_freq > profile.technical_term_freq * 5  # 5x above baseline
        ):
            flags.append({
                "type": InjectionFlag.EXCESSIVE_TECHNICAL_JARGON.value,
                "matched_text": (
                    f"Technical term frequency {tech_freq:.2%} "
                    f"(baseline: {profile.technical_term_freq:.2%})"
                ),
                "severity": "medium",
            })

        # Check message length anomaly
        if (
            profile.avg_message_length > 0
            and len(text) > profile.avg_message_length * 10
        ):
            flags.append({
                "type": InjectionFlag.LINGUISTIC_ANOMALY.value,
                "matched_text": (
                    f"Message length {len(text)} chars "
                    f"(avg: {profile.avg_message_length:.0f})"
                ),
                "severity": "low",
            })

        return flags

    # =========================================================================
    # LEVEL 2 — CONTEXT ISOLATION
    # =========================================================================

    async def is_isolated(self, member_id: UUID) -> bool:
        """
        Level 2: Verify that a member's context is properly isolated.

        Checks that:
            1. The member has their own isolated context (not shared).
            2. The context hash matches the expected value for this member.
            3. No cross-member data contamination has occurred.
            4. Token count is within bounds.

        This enforcement is at the API/query level, NOT the prompt level,
        so it cannot be bypassed by prompt injection.

        Args:
            member_id: UUID of the member to verify.

        Returns:
            True if the member's context is properly isolated, False otherwise.
        """
        self._stats["total_isolation_checks"] += 1

        context = self._get_context(member_id)

        # Verify context hash integrity
        expected_hash = hashlib.sha256(
            f"{context.member_id}:{context.created_at.isoformat()}".encode()
        ).hexdigest()

        if context.context_hash != expected_hash:
            logger.critical(
                ">>> [QUEENS_GUARD] L2 — CONTEXT HASH MISMATCH for member %s! "
                "Expected %s, got %s",
                member_id, expected_hash[:16], context.context_hash[:16],
            )

            if self._forensic_logger:
                try:
                    await self._forensic_logger.log_event(
                        event_type="queens_guard_l2_isolation_breach",
                        source_entity=str(member_id),
                        evidence={
                            "expected_hash": expected_hash,
                            "actual_hash": context.context_hash,
                        },
                    )
                except Exception as exc:
                    logger.error(">>> [QUEENS_GUARD] Forensic log failed: %s", exc)

            return False

        # Verify token count within bounds
        if context.token_count > MAX_CONTEXT_TOKENS:
            logger.warning(
                ">>> [QUEENS_GUARD] L2 — Token count exceeded for member %s: "
                "%d > %d",
                member_id, context.token_count, MAX_CONTEXT_TOKENS,
            )
            return False

        # Verify no cross-member contamination in database
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    # Check for any context entries that reference other members
                    row = await conn.fetchrow("""
                        SELECT COUNT(*) as cross_ref_count
                        FROM conversation_context
                        WHERE member_id = $1
                          AND content LIKE '%member_id%'
                          AND content NOT LIKE $2
                    """,
                        member_id,
                        f"%{member_id}%",
                    )
                    if row and row["cross_ref_count"] > 0:
                        logger.critical(
                            ">>> [QUEENS_GUARD] L2 — CROSS-MEMBER CONTAMINATION "
                            "detected for member %s (%d references)",
                            member_id, row["cross_ref_count"],
                        )
                        return False
            except Exception as exc:
                # Database check failed — log but don't block
                logger.warning(
                    ">>> [QUEENS_GUARD] L2 — DB isolation check failed: %s", exc
                )

        # Update access tracking
        context.last_accessed = datetime.utcnow()
        context.access_count += 1

        return True

    def enforce_query_isolation(
        self,
        member_id: UUID,
        query_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Enforce context isolation at the query construction level.

        Injects member-specific constraints into any database query or
        RAG retrieval to prevent cross-member data access.  This is
        the core of Level 2 — enforced at query level, NOT prompt level.

        Args:
            member_id:    UUID of the requesting member.
            query_params: The original query parameters.

        Returns:
            Modified query parameters with member isolation enforced.
        """
        isolated_params = dict(query_params)

        # Always inject member_id filter
        isolated_params["_isolation_member_id"] = str(member_id)
        isolated_params["_isolation_enforced"] = True
        isolated_params["_isolation_timestamp"] = datetime.utcnow().isoformat()

        # Prevent any explicit member_id overrides in the original params
        if "member_id" in query_params:
            original = str(query_params["member_id"])
            expected = str(member_id)
            if original != expected:
                logger.warning(
                    ">>> [QUEENS_GUARD] L2 — Member ID override attempt! "
                    "member=%s tried to access member=%s",
                    member_id, original,
                )
                isolated_params["member_id"] = str(member_id)

        return isolated_params

    # =========================================================================
    # LEVEL 3 — OUTPUT VERIFICATION
    # =========================================================================

    async def verify_output(
        self,
        member_id: UUID,
        response: str,
        question_type: str = "unknown",
    ) -> Tuple[str, bool]:
        """
        Level 3: Verify AI output before delivery to the member.

        Scans the response for:
            1. System prompt fragments.
            2. Other member names/IDs.
            3. Internal architecture details.
            4. API keys and database schemas.
            5. Token count anomalies (10× longer than typical).

        If any leakage is detected, the response is auto-redacted and
        replaced with a safe generic response.

        Args:
            member_id:     UUID of the member receiving the response.
            response:      The AI-generated response text.
            question_type: The type of question being answered (for token
                           anomaly baseline).  One of: "greeting",
                           "mood_check", "therapy_question", "crisis",
                           "general", "unknown".

        Returns:
            Tuple of (safe_response, blocked) where blocked is True if the
            original response was redacted.
        """
        self._stats["total_outputs_verified"] += 1
        blocked = False
        redaction_reasons: List[str] = []

        # --- Check 1: Scan for information leakage patterns ---
        for leak_type, pattern in _LEAKAGE_PATTERNS:
            match = pattern.search(response)
            if match:
                redaction_reasons.append(
                    f"{leak_type}: {match.group(0)[:80]}"
                )
                blocked = True

        # --- Check 2: Token count anomaly detection ---
        # Estimate token count (rough: 1 token ≈ 4 characters)
        estimated_tokens = len(response) // 4
        typical = TYPICAL_TOKEN_COUNTS.get(
            question_type, TYPICAL_TOKEN_COUNTS["unknown"]
        )

        # Check against member's personal history too
        history = self._response_token_history[member_id]
        if len(history) >= 10:
            personal_typical = statistics.mean(history)
            effective_typical = max(typical, personal_typical)
        else:
            effective_typical = typical

        if estimated_tokens > effective_typical * TOKEN_ANOMALY_MULTIPLIER:
            redaction_reasons.append(
                f"token_anomaly: {estimated_tokens} tokens "
                f"(typical: {effective_typical:.0f}, "
                f"threshold: {effective_typical * TOKEN_ANOMALY_MULTIPLIER:.0f})"
            )
            blocked = True

        # Record token count for future comparison
        history.append(estimated_tokens)
        if len(history) > 100:
            self._response_token_history[member_id] = history[-100:]

        # --- Check 3: Cross-member name/ID leakage ---
        # Check if the response contains other member UUIDs
        uuid_pattern = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            re.IGNORECASE,
        )
        found_uuids = uuid_pattern.findall(response)
        member_id_str = str(member_id).lower()
        foreign_uuids = [
            u for u in found_uuids
            if u.lower() != member_id_str
        ]
        if foreign_uuids:
            redaction_reasons.append(
                f"foreign_uuid_leak: {len(foreign_uuids)} non-member UUIDs in response"
            )
            blocked = True

        if blocked:
            self._stats["total_outputs_redacted"] += 1

            # Determine which safe response to use
            safe_response = _SAFE_RESPONSES["default"]
            for reason in redaction_reasons:
                for leak_type in _SAFE_RESPONSES:
                    if reason.startswith(leak_type):
                        safe_response = _SAFE_RESPONSES[leak_type]
                        break

            logger.warning(
                ">>> [QUEENS_GUARD] L3 — RESPONSE REDACTED for member %s: %s",
                member_id,
                "; ".join(redaction_reasons),
            )

            # Forensic logging
            if self._forensic_logger:
                try:
                    await self._forensic_logger.log_event(
                        event_type="queens_guard_l3_redaction",
                        source_entity=str(member_id),
                        evidence={
                            "redaction_reasons": redaction_reasons,
                            "original_length": len(response),
                            "question_type": question_type,
                            "estimated_tokens": estimated_tokens,
                        },
                    )
                except Exception as exc:
                    logger.error(">>> [QUEENS_GUARD] Forensic log failed: %s", exc)

            # Persist redaction event
            await self._persist_redaction_event(
                member_id, redaction_reasons, question_type
            )

            return safe_response, True

        return response, False

    # =========================================================================
    # PROFILE & CONTEXT MANAGEMENT
    # =========================================================================

    def _get_profile(self, member_id: UUID) -> MemberLinguisticProfile:
        """Get or create a member's linguistic profile."""
        if member_id not in self._member_profiles:
            self._member_profiles[member_id] = MemberLinguisticProfile(
                member_id=member_id
            )
        return self._member_profiles[member_id]

    def _get_context(self, member_id: UUID) -> MemberContext:
        """Get or create a member's isolated context."""
        if member_id not in self._member_contexts:
            self._member_contexts[member_id] = MemberContext(
                member_id=member_id
            )
        return self._member_contexts[member_id]

    def update_context_tokens(self, member_id: UUID, token_count: int) -> None:
        """
        Update the token count for a member's context.

        Called after each AI interaction to track context growth.

        Args:
            member_id:   UUID of the member.
            token_count: Current total token count in the context.
        """
        context = self._get_context(member_id)
        context.token_count = token_count

    def reset_context(self, member_id: UUID) -> None:
        """
        Reset a member's isolated context.

        Creates a fresh context with a new hash.  Used when a conversation
        ends or when the context token limit is reached.

        Args:
            member_id: UUID of the member.
        """
        self._member_contexts[member_id] = MemberContext(member_id=member_id)
        logger.info(
            ">>> [QUEENS_GUARD] Context reset for member %s", member_id
        )

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _persist_sanitization_event(
        self, member_id: UUID, flags: List[Dict[str, Any]]
    ) -> None:
        """Persist a sanitization event to the database."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO queens_guard_events (
                        member_id, event_type, flags, flag_count, created_at
                    ) VALUES ($1, $2, $3, $4, NOW())
                """,
                    member_id,
                    "l1_sanitization",
                    json.dumps(flags),
                    len(flags),
                )
        except Exception as exc:
            logger.error(
                ">>> [QUEENS_GUARD] Sanitization persistence failed: %s", exc
            )

    async def _persist_redaction_event(
        self,
        member_id: UUID,
        reasons: List[str],
        question_type: str,
    ) -> None:
        """Persist a redaction event to the database."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO queens_guard_events (
                        member_id, event_type, flags, flag_count, created_at
                    ) VALUES ($1, $2, $3, $4, NOW())
                """,
                    member_id,
                    "l3_redaction",
                    json.dumps({
                        "reasons": reasons,
                        "question_type": question_type,
                    }),
                    len(reasons),
                )
        except Exception as exc:
            logger.error(
                ">>> [QUEENS_GUARD] Redaction persistence failed: %s", exc
            )

    # =========================================================================
    # ADMIN / SUMMARY
    # =========================================================================

    def summary(self) -> Dict[str, Any]:
        """
        Return a summary of Queen's Guard state and statistics.

        Designed for the SkyEye / admin dashboard.

        Returns:
            Dictionary with defense statistics and status.
        """
        return {
            "stats": dict(self._stats),
            "active_member_profiles": len(self._member_profiles),
            "active_member_contexts": len(self._member_contexts),
            "injection_patterns_loaded": len(_INJECTION_PATTERNS),
            "leakage_patterns_loaded": len(_LEAKAGE_PATTERNS),
            "homoglyphs_tracked": len(_HOMOGLYPH_MAP),
            "technical_terms_tracked": len(_TECHNICAL_TERMS),
            "levels": {
                "l1_input_sanitization": "active",
                "l2_context_isolation": "active",
                "l3_output_verification": "active",
            },
        }

    async def get_member_security_report(
        self, member_id: UUID
    ) -> Dict[str, Any]:
        """
        Generate a security report for a specific member.

        Args:
            member_id: UUID of the member.

        Returns:
            Dictionary with member-specific security statistics.
        """
        profile = self._get_profile(member_id)
        context = self._get_context(member_id)
        token_history = self._response_token_history.get(member_id, [])

        report = {
            "member_id": str(member_id),
            "linguistic_profile": {
                "total_messages": profile.total_messages,
                "avg_message_length": round(profile.avg_message_length, 1),
                "technical_term_freq": round(profile.technical_term_freq, 4),
                "vocabulary_level": round(profile.vocabulary_level, 1),
                "last_updated": (
                    profile.last_updated.isoformat()
                    if profile.last_updated else None
                ),
            },
            "context": {
                "token_count": context.token_count,
                "access_count": context.access_count,
                "created_at": context.created_at.isoformat(),
                "last_accessed": (
                    context.last_accessed.isoformat()
                    if context.last_accessed else None
                ),
            },
            "response_history": {
                "total_responses": len(token_history),
                "avg_tokens": (
                    round(statistics.mean(token_history), 1)
                    if token_history else 0
                ),
            },
        }

        # Pull event history from database
        if self.db_pool:
            try:
                async with self.db_pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT event_type, flag_count, created_at
                        FROM queens_guard_events
                        WHERE member_id = $1
                        ORDER BY created_at DESC
                        LIMIT 20
                    """, member_id)
                    report["recent_events"] = [
                        {
                            "event_type": r["event_type"],
                            "flag_count": r["flag_count"],
                            "created_at": r["created_at"].isoformat(),
                        }
                        for r in rows
                    ]
            except Exception as exc:
                logger.warning(
                    ">>> [QUEENS_GUARD] Event history query failed: %s", exc
                )
                report["recent_events"] = []

        return report
