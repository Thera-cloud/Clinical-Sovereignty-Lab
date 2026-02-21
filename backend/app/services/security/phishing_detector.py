"""
HIVE DEFENSE — Phishing Detector
Stateless analyzer that scores text, email bodies, URLs, and raw headers
for phishing signals.  Used by:
  - Hive Inspect API  (manual admin submission)
  - Gmail Hive Monitor (continuous automated scanning)
  - Nate Guardian      (device-side link checks via REST)

Verdict levels: CLEAN / SUSPICIOUS / MALICIOUS
Score 0–100 (0 = safe, 100 = certain phish)

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

# ─── Protected Domains ────────────────────────────────────────────────────────
SOVEREIGN_DOMAINS = frozenset({
    "sovereignsanctuary.net",
    "app.sovereignsanctuary.net",
    "coach.sovereignsanctuary.net",
    "command.sovereignsanctuary.net",
    "littlenate.ai",
})

ADMIN_DOMAINS = frozenset({
    "sovereignsanctuary.net",
    "gmail.com",
})

# ─── Verdict ──────────────────────────────────────────────────────────────────
VERDICT_CLEAN = "CLEAN"
VERDICT_SUSPICIOUS = "SUSPICIOUS"
VERDICT_MALICIOUS = "MALICIOUS"


@dataclass
class PhishingSignal:
    """Single detected phishing indicator."""
    category: str          # e.g. "credential_harvesting", "spoofed_domain"
    severity: str          # "low", "medium", "high", "critical"
    detail: str            # human-readable description
    score: int             # 0-100 contribution to total score
    evidence: str = ""     # the matched text / URL / pattern


@dataclass
class PhishingVerdict:
    """Aggregate result of phishing analysis."""
    verdict: str           # CLEAN / SUSPICIOUS / MALICIOUS
    score: int             # 0-100
    signals: List[PhishingSignal] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "score": self.score,
            "signal_count": len(self.signals),
            "signals": [
                {
                    "category": s.category,
                    "severity": s.severity,
                    "detail": s.detail,
                    "score": s.score,
                    "evidence": s.evidence[:200],
                }
                for s in self.signals
            ],
            "recommendations": self.recommendations,
        }


# ═════════════════════════════════════════════════════════════════════════════
# PATTERN DATABASES
# ═════════════════════════════════════════════════════════════════════════════

# Credential harvesting phrases
_CREDENTIAL_PATTERNS: List[Tuple[re.Pattern, int, str]] = [
    (re.compile(r"verify\s+your\s+(account|identity|email|password)", re.I), 30, "Account verification request"),
    (re.compile(r"confirm\s+your\s+(identity|account|payment|billing)", re.I), 30, "Identity confirmation request"),
    (re.compile(r"(update|verify)\s+your\s+(payment|billing|credit\s+card)", re.I), 35, "Payment info harvesting"),
    (re.compile(r"unusual\s+(sign.?in|login|activity|access)", re.I), 25, "Fake unusual activity alert"),
    (re.compile(r"(unauthorized|suspicious)\s+(access|activity|login|transaction)", re.I), 25, "Fake security alert"),
    (re.compile(r"your\s+account\s+(has\s+been|was|is)\s+(suspended|locked|disabled|compromised)", re.I), 35, "Account suspension scare"),
    (re.compile(r"reset\s+your\s+password\s+immediately", re.I), 25, "Urgent password reset"),
    (re.compile(r"click\s+(here|below|the\s+link)\s+to\s+(verify|confirm|secure|unlock)", re.I), 30, "Click-to-verify lure"),
    (re.compile(r"enter\s+your\s+(credentials|username|password|SSN|social\s+security)", re.I), 40, "Direct credential request"),
    (re.compile(r"(sign|log)\s*in\s+to\s+(secure|protect|verify|confirm)", re.I), 20, "Fake sign-in prompt"),
]

# Urgency / fear language
_URGENCY_PATTERNS: List[Tuple[re.Pattern, int, str]] = [
    (re.compile(r"immediate\s+action\s+(required|needed)", re.I), 20, "Urgency pressure"),
    (re.compile(r"within\s+\d+\s+(hours?|minutes?|days?)", re.I), 15, "Time pressure"),
    (re.compile(r"(act|respond|reply)\s+(now|immediately|urgently|today)", re.I), 20, "Urgency demand"),
    (re.compile(r"failure\s+to\s+(respond|act|verify|confirm)\s+(will|may)\s+(result|lead)", re.I), 25, "Consequence threat"),
    (re.compile(r"(last|final)\s+(warning|notice|reminder|chance)", re.I), 20, "Final warning scare"),
    (re.compile(r"your\s+(data|files|account)\s+(will\s+be|are\s+being)\s+(deleted|erased|removed|terminated)", re.I), 30, "Data loss threat"),
    (re.compile(r"(legal|law\s+enforcement|police|FBI|IRS)\s+action", re.I), 25, "Legal threat scare"),
    (re.compile(r"(you\s+have\s+been|you\s+are)\s+selected", re.I), 15, "Prize/selection scam"),
]

# Suspicious URL patterns
_URL_SHORTENERS = frozenset({
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd",
    "buff.ly", "rebrand.ly", "bl.ink", "short.io", "cutt.ly", "rb.gy",
})

# Dangerous attachment extensions
_DANGEROUS_EXTENSIONS = frozenset({
    ".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".vbs", ".vbe",
    ".js", ".jse", ".wsf", ".wsh", ".ps1", ".msi", ".msp",
    ".docm", ".xlsm", ".pptm", ".dotm", ".xltm",
    ".hta", ".cpl", ".inf", ".reg", ".lnk", ".jar",
})

# Double extension patterns (e.g., invoice.pdf.exe)
_DOUBLE_EXT_PATTERN = re.compile(
    r"\.\w{2,4}\.(exe|scr|bat|cmd|com|pif|vbs|js|jar|msi|ps1)$", re.I
)

# Homoglyph map for typosquat detection
_HOMOGLYPHS: Dict[str, List[str]] = {
    "a": ["à", "á", "â", "ã", "ä", "å", "ɑ", "а"],
    "e": ["è", "é", "ê", "ë", "ε", "е"],
    "i": ["ì", "í", "î", "ï", "ι", "і", "1", "l"],
    "o": ["ò", "ó", "ô", "õ", "ö", "ø", "0", "ο", "о"],
    "u": ["ù", "ú", "û", "ü", "μ"],
    "n": ["ñ", "η", "п"],
    "s": ["ş", "ś", "ṣ", "$", "5"],
    "g": ["ğ", "ġ", "9"],
    "c": ["ç", "ć", "с"],
    "r": ["г", "ŗ"],
    "t": ["ţ", "ť", "т"],
    "l": ["ł", "1", "i", "|"],
    "v": ["ν", "ѵ"],
    "y": ["ý", "ÿ", "γ", "у"],
}


# ═════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═════════════════════════════════════════════════════════════════════════════

def _extract_urls(text: str) -> List[str]:
    """Extract all URLs from text."""
    url_pattern = re.compile(
        r'https?://[^\s<>"\')\]]+|'
        r'www\.[^\s<>"\')\]]+',
        re.I,
    )
    return url_pattern.findall(text)


def _extract_domains_from_urls(urls: List[str]) -> List[str]:
    """Extract domain names from URLs."""
    domains = []
    for url in urls:
        try:
            if not url.startswith("http"):
                url = "http://" + url
            parsed = urlparse(url)
            if parsed.hostname:
                domains.append(parsed.hostname.lower())
        except Exception:
            continue
    return domains


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _has_homoglyph(domain: str, target: str) -> bool:
    """Check if domain uses homoglyph characters to mimic target."""
    if domain == target:
        return False
    for char, glyphs in _HOMOGLYPHS.items():
        for g in glyphs:
            if g in domain and char in target:
                normalized = domain.replace(g, char)
                if normalized == target or _levenshtein(normalized, target) <= 1:
                    return True
    return False


def _is_ip_url(url: str) -> bool:
    """Check if URL uses an IP address instead of a domain."""
    try:
        parsed = urlparse(url if url.startswith("http") else "http://" + url)
        host = parsed.hostname or ""
        return bool(re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", host))
    except Exception:
        return False


def _shannon_entropy(text: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not text:
        return 0.0
    freq: Dict[str, int] = {}
    for c in text:
        freq[c] = freq.get(c, 0) + 1
    length = len(text)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


# ═════════════════════════════════════════════════════════════════════════════
# ANALYZERS
# ═════════════════════════════════════════════════════════════════════════════

def _analyze_credential_harvesting(text: str) -> List[PhishingSignal]:
    """Detect credential harvesting language."""
    signals = []
    for pattern, score, desc in _CREDENTIAL_PATTERNS:
        match = pattern.search(text)
        if match:
            signals.append(PhishingSignal(
                category="credential_harvesting",
                severity="high" if score >= 30 else "medium",
                detail=desc,
                score=score,
                evidence=match.group(0),
            ))
    return signals


def _analyze_urgency(text: str) -> List[PhishingSignal]:
    """Detect urgency and fear manipulation."""
    signals = []
    for pattern, score, desc in _URGENCY_PATTERNS:
        match = pattern.search(text)
        if match:
            signals.append(PhishingSignal(
                category="urgency_manipulation",
                severity="medium" if score < 25 else "high",
                detail=desc,
                score=score,
                evidence=match.group(0),
            ))
    return signals


def _analyze_urls(text: str) -> List[PhishingSignal]:
    """Analyze URLs for phishing indicators."""
    signals = []
    urls = _extract_urls(text)
    domains = _extract_domains_from_urls(urls)

    for url in urls:
        # IP-based URLs
        if _is_ip_url(url):
            signals.append(PhishingSignal(
                category="suspicious_url",
                severity="high",
                detail="URL uses IP address instead of domain name",
                score=30,
                evidence=url[:100],
            ))

        # data: URIs
        if url.lower().startswith("data:"):
            signals.append(PhishingSignal(
                category="suspicious_url",
                severity="critical",
                detail="Data URI detected — may contain embedded malicious content",
                score=40,
                evidence=url[:80],
            ))

        # High entropy subdomains (random-looking)
        try:
            parsed = urlparse(url if url.startswith("http") else "http://" + url)
            host = parsed.hostname or ""
            parts = host.split(".")
            if len(parts) > 3:
                subdomain = ".".join(parts[:-2])
                if _shannon_entropy(subdomain) > 4.0:
                    signals.append(PhishingSignal(
                        category="suspicious_url",
                        severity="medium",
                        detail="High-entropy subdomain (possibly randomized)",
                        score=20,
                        evidence=host,
                    ))
        except Exception:
            pass

    # Suspicious keywords in URL domains/paths (brand impersonation, credential harvesting)
    _PHISHING_DOMAIN_KEYWORDS = {
        "login", "signin", "sign-in", "log-in", "logon", "signon",
        "verify", "verification", "validate", "confirm", "secure",
        "account", "update", "suspend", "locked", "unlock",
        "bank", "banking", "paypal", "chase", "wellsfargo", "citi",
        "appleid", "icloud", "microsoft", "outlook", "office365",
        "amazon", "netflix", "walmart", "costco", "usps", "fedex",
        "irs", "tax", "refund", "invoice", "payment",
        "password", "credential", "auth", "token", "reset",
    }
    _SAFE_ANALYSIS_DOMAINS = frozenset({
        "example.com", "example.org", "example.net",
        "test.com", "localhost",
    })

    for url in urls:
        url_lower = url.lower()
        try:
            parsed = urlparse(url_lower if url_lower.startswith("http") else "http://" + url_lower)
            host = parsed.hostname or ""
            path = parsed.path or ""
            full_url_text = host + path

            matched_keywords = [kw for kw in _PHISHING_DOMAIN_KEYWORDS if kw in full_url_text]

            base_domain = ".".join(host.rsplit(".", 2)[-2:]) if "." in host else host
            is_safe_domain = base_domain in _SAFE_ANALYSIS_DOMAINS

            if matched_keywords and not is_safe_domain:
                severity = "critical" if len(matched_keywords) >= 3 else "high" if len(matched_keywords) >= 2 else "medium"
                score = min(50, 15 + 10 * len(matched_keywords))
                signals.append(PhishingSignal(
                    category="suspicious_url",
                    severity=severity,
                    detail=f"URL contains phishing keywords: {', '.join(matched_keywords[:5])}",
                    score=score,
                    evidence=url[:120],
                ))
            elif matched_keywords and is_safe_domain:
                signals.append(PhishingSignal(
                    category="suspicious_url",
                    severity="medium",
                    detail=f"URL contains phishing keywords ({', '.join(matched_keywords[:5])}) on test domain",
                    score=10 + 5 * len(matched_keywords),
                    evidence=url[:120],
                ))
        except Exception:
            pass

    for domain in domains:
        # URL shorteners
        if domain in _URL_SHORTENERS:
            signals.append(PhishingSignal(
                category="suspicious_url",
                severity="medium",
                detail=f"URL shortener detected: {domain}",
                score=15,
                evidence=domain,
            ))

        # Typosquat of sovereign domains
        for target in SOVEREIGN_DOMAINS:
            if domain == target:
                continue
            dist = _levenshtein(domain, target)
            if 0 < dist <= 2:
                signals.append(PhishingSignal(
                    category="spoofed_domain",
                    severity="critical",
                    detail=f"Domain '{domain}' is a near-typosquat of '{target}' (edit distance {dist})",
                    score=45,
                    evidence=domain,
                ))
            elif _has_homoglyph(domain, target):
                signals.append(PhishingSignal(
                    category="spoofed_domain",
                    severity="critical",
                    detail=f"Domain '{domain}' uses homoglyph characters to mimic '{target}'",
                    score=50,
                    evidence=domain,
                ))

    return signals


def _analyze_sender(from_address: str) -> List[PhishingSignal]:
    """Analyze sender address for impersonation."""
    signals = []
    if not from_address:
        return signals

    from_lower = from_address.lower().strip()

    # Extract domain from email
    if "@" in from_lower:
        sender_domain = from_lower.split("@")[-1]

        # Check for typosquat of sovereign domains
        for target in SOVEREIGN_DOMAINS:
            if sender_domain == target:
                continue
            dist = _levenshtein(sender_domain, target)
            if 0 < dist <= 2:
                signals.append(PhishingSignal(
                    category="sender_spoofing",
                    severity="critical",
                    detail=f"Sender domain '{sender_domain}' mimics '{target}'",
                    score=45,
                    evidence=from_address,
                ))
            elif _has_homoglyph(sender_domain, target):
                signals.append(PhishingSignal(
                    category="sender_spoofing",
                    severity="critical",
                    detail=f"Sender domain uses homoglyph characters to mimic '{target}'",
                    score=50,
                    evidence=from_address,
                ))

        # Check for admin name impersonation
        admin_names = ["nevedal", "nathan", "nate", "dssmllc", "admin"]
        local_part = from_lower.split("@")[0]
        for name in admin_names:
            if name in local_part and sender_domain not in ("sovereignsanctuary.net", "gmail.com"):
                signals.append(PhishingSignal(
                    category="sender_spoofing",
                    severity="high",
                    detail=f"Sender local part contains admin name '{name}' from non-admin domain",
                    score=30,
                    evidence=from_address,
                ))

    return signals


def _analyze_attachments(text: str, attachment_names: Optional[List[str]] = None) -> List[PhishingSignal]:
    """Analyze attachment references and filenames."""
    signals = []
    names = attachment_names or []

    # Also extract filenames mentioned in email body
    file_pattern = re.compile(r'[\w\-]+\.[\w]{2,5}(?:\.[\w]{2,5})?', re.I)
    mentioned = file_pattern.findall(text)
    all_names = list(set(names + mentioned))

    for name in all_names:
        lower = name.lower()

        # Double extension
        if _DOUBLE_EXT_PATTERN.search(lower):
            signals.append(PhishingSignal(
                category="dangerous_attachment",
                severity="critical",
                detail=f"Double extension detected: '{name}' — likely disguised executable",
                score=45,
                evidence=name,
            ))
            continue

        # Dangerous single extension
        for ext in _DANGEROUS_EXTENSIONS:
            if lower.endswith(ext):
                signals.append(PhishingSignal(
                    category="dangerous_attachment",
                    severity="high" if ext in (".exe", ".scr", ".bat", ".ps1", ".hta") else "medium",
                    detail=f"Dangerous file type: '{name}' ({ext})",
                    score=35 if ext in (".exe", ".scr", ".bat", ".ps1") else 20,
                    evidence=name,
                ))
                break

    return signals


def _analyze_headers(raw_headers: str) -> List[PhishingSignal]:
    """Analyze raw email headers for SPF/DKIM/DMARC failures."""
    signals = []
    if not raw_headers:
        return signals

    headers_lower = raw_headers.lower()

    # SPF
    spf_fail = re.search(r"spf=(fail|softfail|temperror|permerror)", headers_lower)
    if spf_fail:
        signals.append(PhishingSignal(
            category="header_failure",
            severity="high",
            detail=f"SPF check failed: {spf_fail.group(0)}",
            score=30,
            evidence=spf_fail.group(0),
        ))

    # DKIM
    dkim_fail = re.search(r"dkim=(fail|temperror|permerror|none)", headers_lower)
    if dkim_fail:
        signals.append(PhishingSignal(
            category="header_failure",
            severity="high",
            detail=f"DKIM check failed: {dkim_fail.group(0)}",
            score=30,
            evidence=dkim_fail.group(0),
        ))

    # DMARC
    dmarc_fail = re.search(r"dmarc=(fail|none)", headers_lower)
    if dmarc_fail:
        signals.append(PhishingSignal(
            category="header_failure",
            severity="high",
            detail=f"DMARC check failed: {dmarc_fail.group(0)}",
            score=35,
            evidence=dmarc_fail.group(0),
        ))

    # Received-SPF pass but From domain mismatch (relay spoofing)
    received_spf = re.search(r"received-spf:\s*pass.*?sender=([^\s;]+)", headers_lower)
    from_match = re.search(r"from:\s*.*?([a-z0-9._%+-]+@[a-z0-9.-]+)", headers_lower)
    if received_spf and from_match:
        spf_sender = received_spf.group(1)
        from_addr = from_match.group(1)
        if "@" in spf_sender and "@" in from_addr:
            spf_domain = spf_sender.split("@")[-1]
            from_domain = from_addr.split("@")[-1]
            if spf_domain != from_domain:
                signals.append(PhishingSignal(
                    category="header_mismatch",
                    severity="high",
                    detail=f"SPF domain ({spf_domain}) doesn't match From domain ({from_domain})",
                    score=35,
                    evidence=f"SPF: {spf_sender}, From: {from_addr}",
                ))

    return signals


# ═════════════════════════════════════════════════════════════════════════════
# MAIN ANALYSIS FUNCTION
# ═════════════════════════════════════════════════════════════════════════════

def analyze(
    content: str,
    content_type: str = "text",
    from_address: str = "",
    subject: str = "",
    raw_headers: str = "",
    attachment_names: Optional[List[str]] = None,
) -> PhishingVerdict:
    """
    Run full phishing analysis on submitted content.

    Args:
        content: The email body, URL, or raw text to analyze
        content_type: "email", "url", "text", or "raw_headers"
        from_address: Sender email (for email content)
        subject: Email subject line (analyzed alongside body)
        raw_headers: Full email headers (for SPF/DKIM/DMARC analysis)
        attachment_names: List of attachment filenames

    Returns:
        PhishingVerdict with score, signals, and recommendations
    """
    all_signals: List[PhishingSignal] = []
    full_text = f"{subject}\n{content}" if subject else content

    # Run all analyzers
    all_signals.extend(_analyze_credential_harvesting(full_text))
    all_signals.extend(_analyze_urgency(full_text))
    all_signals.extend(_analyze_urls(full_text))
    all_signals.extend(_analyze_sender(from_address))
    all_signals.extend(_analyze_attachments(full_text, attachment_names))

    if raw_headers:
        all_signals.extend(_analyze_headers(raw_headers))

    # Deduplicate by (category, evidence)
    seen: Set[Tuple[str, str]] = set()
    unique_signals: List[PhishingSignal] = []
    for s in all_signals:
        key = (s.category, s.evidence)
        if key not in seen:
            seen.add(key)
            unique_signals.append(s)

    # Calculate total score (capped at 100)
    total_score = min(100, sum(s.score for s in unique_signals))

    # Determine verdict
    if total_score >= 60:
        verdict = VERDICT_MALICIOUS
    elif total_score >= 25:
        verdict = VERDICT_SUSPICIOUS
    else:
        verdict = VERDICT_CLEAN

    # Generate recommendations
    recommendations = _generate_recommendations(unique_signals, verdict)

    return PhishingVerdict(
        verdict=verdict,
        score=total_score,
        signals=unique_signals,
        recommendations=recommendations,
    )


def _generate_recommendations(signals: List[PhishingSignal], verdict: str) -> List[str]:
    """Generate actionable recommendations based on detected signals."""
    recs = []
    categories = {s.category for s in signals}

    if verdict == VERDICT_MALICIOUS:
        recs.append("DO NOT click any links or download any attachments in this message.")
        recs.append("Mark this message as phishing in your email client.")

    if "credential_harvesting" in categories:
        recs.append("Never enter credentials through email links. Go directly to the official site.")

    if "spoofed_domain" in categories or "sender_spoofing" in categories:
        recs.append("The sender domain appears to impersonate a trusted domain. Verify the sender independently.")

    if "dangerous_attachment" in categories:
        recs.append("Do not open the attached file(s). Executable and macro-enabled files are common malware vectors.")

    if "header_failure" in categories or "header_mismatch" in categories:
        recs.append("Email authentication (SPF/DKIM/DMARC) failed. The sender may be forged.")

    if "urgency_manipulation" in categories:
        recs.append("Urgency language is a common social engineering tactic. Take time to verify before acting.")

    if "suspicious_url" in categories:
        recs.append("Suspicious URLs detected. Hover over links to verify their destination before clicking.")

    if verdict == VERDICT_CLEAN and not signals:
        recs.append("No phishing indicators detected. Standard caution still advised.")

    return recs
