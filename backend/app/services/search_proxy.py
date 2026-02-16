"""
LITTLE NATE — Secure Search Proxy
Sandboxed internet search with content sanitization, injection detection,
rate limiting, and audit logging.

Security layers:
  1. Uses Bing Search API only (no raw URL fetching → eliminates SSRF)
  2. Content sanitization (strip HTML, truncate, detect injection patterns)
  3. Domain blocklist (internal IPs, cloud metadata, Docker hostnames)
  4. Rate limiting (per-coach, per-session)
  5. Full audit logging
"""

import os
import re
import time
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# SECURITY: Injection Pattern Detection
# =============================================================================
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+the\s+above",
    r"disregard\s+(all\s+)?(previous|prior|above)",
    r"you\s+are\s+now\s+a",
    r"new\s+instructions?\s*:",
    r"system\s*prompt",
    r"reveal\s+(your|the)\s+(instructions|prompt|rules)",
    r"output\s+(your|the)\s+(system|instructions|prompt)",
    r"pretend\s+you\s+are",
    r"act\s+as\s+if",
    r"forget\s+(everything|all|your\s+instructions)",
    r"override\s+(your|all)\s+(rules|instructions|safety)",
    r"jailbreak",
    r"DAN\s+mode",
    r"developer\s+mode",
    r"sudo\s+mode",
    r"ADMIN_PASSWORD|JWT_SECRET|API_KEY|SECRET_KEY",
    r"SELECT\s+\*\s+FROM|DROP\s+TABLE|INSERT\s+INTO",
    r"<script|javascript:|onclick|onerror",
]

COMPILED_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS
]

# =============================================================================
# SECURITY: Domain & URL Blocklist
# =============================================================================
BLOCKED_DOMAINS = {
    "localhost", "127.0.0.1", "0.0.0.0",
    # Internal IPs blocked dynamically via env config
    "169.254.169.254",  # Cloud metadata
    "metadata.google.internal",
    "nate_backend", "nate_bridge", "redis", "postgres", "db",  # Docker
}

BLOCKED_IP_RANGES = [
    r"^10\.",           # Private 10.x.x.x
    r"^172\.(1[6-9]|2[0-9]|3[01])\.",  # Private 172.16-31.x.x
    r"^192\.168\.",     # Private 192.168.x.x
    r"^169\.254\.",     # Link-local / cloud metadata
    r"^127\.",          # Loopback
    r"^0\.",            # Zero network
]

BLOCKED_SCHEMES = {"file", "ftp", "ssh", "telnet", "gopher", "data", "javascript"}

# =============================================================================
# RATE LIMITING
# =============================================================================
class RateLimiter:
    """Per-coach rate limiting for search requests."""
    
    def __init__(self, max_per_session: int = 3, max_per_hour: int = 10,
                 cooldown_seconds: int = 30):
        self.max_per_session = max_per_session
        self.max_per_hour = max_per_hour
        self.cooldown_seconds = cooldown_seconds
        self._session_counts: Dict[str, int] = {}
        self._hourly_log: Dict[str, List[float]] = {}
        self._last_search: Dict[str, float] = {}
    
    def check(self, coach_id: str) -> Tuple[bool, str]:
        """Check if coach can perform a search. Returns (allowed, reason)."""
        now = time.time()
        
        # Cooldown check
        last = self._last_search.get(coach_id, 0)
        if now - last < self.cooldown_seconds:
            remaining = int(self.cooldown_seconds - (now - last))
            return False, f"Please wait {remaining}s between searches"
        
        # Session limit
        session_count = self._session_counts.get(coach_id, 0)
        if session_count >= self.max_per_session:
            return False, f"Session limit reached ({self.max_per_session} searches per session)"
        
        # Hourly limit
        hour_ago = now - 3600
        hourly = [t for t in self._hourly_log.get(coach_id, []) if t > hour_ago]
        self._hourly_log[coach_id] = hourly
        if len(hourly) >= self.max_per_hour:
            return False, f"Hourly limit reached ({self.max_per_hour} searches per hour)"
        
        return True, "OK"
    
    def record(self, coach_id: str):
        """Record a search execution."""
        now = time.time()
        self._session_counts[coach_id] = self._session_counts.get(coach_id, 0) + 1
        if coach_id not in self._hourly_log:
            self._hourly_log[coach_id] = []
        self._hourly_log[coach_id].append(now)
        self._last_search[coach_id] = now
    
    def reset_session(self, coach_id: str):
        """Reset session count (e.g., on new DOJO session)."""
        self._session_counts.pop(coach_id, None)


# =============================================================================
# CONTENT SANITIZER
# =============================================================================
class ContentSanitizer:
    """Sanitize search results before they reach the AI."""
    
    MAX_SNIPPET_LENGTH = 1500
    MAX_RESULTS = 5
    
    @staticmethod
    def strip_html(text: str) -> str:
        """Remove all HTML tags."""
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = re.sub(r'&[a-zA-Z]+;', ' ', clean)  # HTML entities
        clean = re.sub(r'&#\d+;', ' ', clean)        # Numeric entities
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean
    
    @staticmethod
    def detect_injection(text: str) -> List[str]:
        """Scan text for prompt injection patterns. Returns list of matched patterns."""
        warnings = []
        for pattern in COMPILED_INJECTION_PATTERNS:
            if pattern.search(text):
                warnings.append(pattern.pattern)
        return warnings
    
    @classmethod
    def sanitize_result(cls, result: dict) -> dict:
        """Sanitize a single search result."""
        title = cls.strip_html(result.get("name", result.get("title", "")))[:200]
        snippet = cls.strip_html(result.get("snippet", result.get("description", "")))
        url = result.get("url", result.get("link", ""))
        
        # Truncate snippet
        if len(snippet) > cls.MAX_SNIPPET_LENGTH:
            snippet = snippet[:cls.MAX_SNIPPET_LENGTH] + "..."
        
        # Check URL safety
        url_safe = True
        url_warnings = []
        
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            
            # Blocked schemes
            if parsed.scheme.lower() in BLOCKED_SCHEMES:
                url_safe = False
                url_warnings.append(f"Blocked scheme: {parsed.scheme}")
            
            # Blocked domains
            hostname = (parsed.hostname or "").lower()
            if hostname in BLOCKED_DOMAINS:
                url_safe = False
                url_warnings.append(f"Blocked domain: {hostname}")
            
            # Blocked IP ranges
            for ip_pattern in BLOCKED_IP_RANGES:
                if re.match(ip_pattern, hostname):
                    url_safe = False
                    url_warnings.append(f"Blocked IP range: {hostname}")
                    break
        except Exception:
            url_safe = False
            url_warnings.append("Malformed URL")
        
        # Injection detection
        injection_warnings = cls.detect_injection(title + " " + snippet)
        
        # Extract domain for display
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
        except Exception:
            domain = "unknown"
        
        return {
            "title": title,
            "snippet": snippet,
            "url": url,
            "domain": domain,
            "safe": url_safe and len(injection_warnings) == 0,
            "warnings": url_warnings + (
                [f"Potential prompt injection detected"] if injection_warnings else []
            ),
            "injection_detected": len(injection_warnings) > 0,
        }
    
    @classmethod
    def sanitize_results(cls, results: list) -> list:
        """Sanitize a list of search results."""
        sanitized = []
        for r in results[:cls.MAX_RESULTS]:
            sanitized.append(cls.sanitize_result(r))
        return sanitized


# =============================================================================
# AUDIT LOGGER
# =============================================================================
class SearchAuditLogger:
    """Log all search actions for security audit trail."""
    
    def __init__(self, data_dir: str):
        self.log_dir = Path(data_dir) / "search_audit"
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def log_event(self, event_type: str, coach_id: str, **kwargs):
        """Log a search-related event."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": event_type,
            "coach_id": coach_id,
            **kwargs
        }
        
        # Append to daily log file
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"search_audit_{date_str}.jsonl"
        
        try:
            with open(log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"[SearchAudit] Failed to write log: {e}")
        
        # Also log to stdout for container logs
        logger.info(f"[SearchAudit] {event_type}: coach={coach_id} {json.dumps(kwargs)}")
    
    def get_recent_events(self, coach_id: str = None, limit: int = 50) -> list:
        """Get recent audit events, optionally filtered by coach."""
        events = []
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"search_audit_{date_str}.jsonl"
        
        if log_file.exists():
            try:
                with open(log_file, "r") as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        if coach_id and entry.get("coach_id") != coach_id:
                            continue
                        events.append(entry)
            except Exception:
                pass
        
        return events[-limit:]


# =============================================================================
# SEARCH PROXY (Main Class)
# =============================================================================
class SecureSearchProxy:
    """
    Sandboxed internet search using Bing Search API.
    Never fetches arbitrary URLs -- only structured search queries through the API.
    """
    
    BING_SEARCH_ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"
    
    def __init__(self, data_dir: str, bing_api_key: str = ""):
        self.bing_api_key = bing_api_key or os.getenv("BING_SEARCH_API_KEY", "")
        self.sanitizer = ContentSanitizer()
        self.rate_limiter = RateLimiter()
        self.audit = SearchAuditLogger(data_dir)
        
        if not self.bing_api_key:
            logger.warning("[SearchProxy] No BING_SEARCH_API_KEY configured -- search disabled")
    
    @property
    def is_available(self) -> bool:
        """Check if search is configured and available."""
        return bool(self.bing_api_key)
    
    def validate_query(self, query: str) -> Tuple[bool, str]:
        """Validate a search query before execution."""
        if not query or not query.strip():
            return False, "Empty search query"
        
        if len(query) > 500:
            return False, "Search query too long (max 500 characters)"
        
        # Check for URL-like patterns (trying to do SSRF via query)
        url_patterns = [
            r"https?://",
            r"file://",
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
            r"localhost",
        ]
        for pattern in url_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return False, "Search queries cannot contain URLs or IP addresses"
        
        # Check for injection in the query itself
        injections = self.sanitizer.detect_injection(query)
        if injections:
            return False, "Search query contains suspicious patterns"
        
        return True, "OK"
    
    async def execute_search(self, query: str, coach_id: str,
                              num_results: int = 5) -> Dict:
        """
        Execute a sandboxed search via Bing Search API.
        Returns sanitized results with safety metadata.
        """
        if not self.is_available:
            return {
                "success": False,
                "error": "Search is not configured. Contact admin to set up Bing Search API key.",
                "results": []
            }
        
        # Rate limit check
        allowed, reason = self.rate_limiter.check(coach_id)
        if not allowed:
            self.audit.log_event("rate_limited", coach_id, query=query, reason=reason)
            return {
                "success": False,
                "error": reason,
                "results": []
            }
        
        # Validate query
        valid, msg = self.validate_query(query)
        if not valid:
            self.audit.log_event("query_rejected", coach_id, query=query, reason=msg)
            return {
                "success": False,
                "error": msg,
                "results": []
            }
        
        # Execute search via Bing API
        try:
            import aiohttp
            
            headers = {
                "Ocp-Apim-Subscription-Key": self.bing_api_key,
            }
            params = {
                "q": query,
                "count": min(num_results, 5),
                "responseFilter": "Webpages",
                "safeSearch": "Strict",
                "textFormat": "Raw",
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.BING_SEARCH_ENDPOINT,
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        self.audit.log_event("api_error", coach_id,
                                             query=query, status=resp.status,
                                             error=error_text[:200])
                        return {
                            "success": False,
                            "error": f"Search API error (status {resp.status})",
                            "results": []
                        }
                    
                    data = await resp.json()
            
            # Extract web pages
            raw_results = data.get("webPages", {}).get("value", [])
            
            # Sanitize all results
            sanitized = self.sanitizer.sanitize_results(raw_results)
            
            # Record the search
            self.rate_limiter.record(coach_id)
            
            # Audit log
            self.audit.log_event("search_executed", coach_id,
                                 query=query,
                                 result_count=len(sanitized),
                                 has_warnings=any(r.get("warnings") for r in sanitized))
            
            return {
                "success": True,
                "query": query,
                "results": sanitized,
                "total_results": len(sanitized),
                "has_safety_warnings": any(not r["safe"] for r in sanitized),
            }
            
        except Exception as e:
            logger.error(f"[SearchProxy] Search error: {e}")
            self.audit.log_event("search_error", coach_id,
                                 query=query, error=str(e))
            return {
                "success": False,
                "error": f"Search failed: {str(e)[:100]}",
                "results": []
            }
    
    def format_for_nate(self, approved_results: list) -> str:
        """
        Format approved search results as context for Little Nate.
        Results are clearly labeled as external/unverified.
        """
        if not approved_results:
            return ""
        
        lines = [
            "[EXTERNAL SEARCH RESULTS - UNVERIFIED]",
            "The following information was found via internet search.",
            "Treat as external reference only, not authoritative clinical guidance.",
            "Always verify critical information with established sources.",
            "---"
        ]
        
        for i, r in enumerate(approved_results, 1):
            lines.append(f"Source {i}: {r.get('title', 'Untitled')}")
            lines.append(f"Domain: {r.get('domain', 'unknown')}")
            lines.append(f"Content: {r.get('snippet', '')}")
            lines.append("---")
        
        lines.append("[END EXTERNAL SEARCH RESULTS]")
        return "\n".join(lines)


# =============================================================================
# TOTP 2FA MANAGER
# =============================================================================
class TOTPManager:
    """
    Manage TOTP-based two-factor authentication for search actions.
    Uses pyotp for TOTP generation/verification.
    """
    
    def __init__(self, encryption_key: str = ""):
        self.encryption_key = encryption_key or os.getenv("TOTP_ENCRYPTION_KEY", "")
        self._secrets: Dict[str, str] = {}  # coach_id -> totp_secret (in production, store encrypted in DB)
    
    def generate_secret(self, coach_id: str, coach_name: str = "") -> Dict:
        """Generate a new TOTP secret for a coach. Returns secret + QR provisioning URI."""
        try:
            import pyotp
            
            secret = pyotp.random_base32()
            self._secrets[coach_id] = secret
            
            # Generate provisioning URI for QR code
            totp = pyotp.TOTP(secret)
            uri = totp.provisioning_uri(
                name=coach_name or coach_id,
                issuer_name="Sovereign Sanctuary DOJO"
            )
            
            return {
                "success": True,
                "secret": secret,
                "provisioning_uri": uri,
                "coach_id": coach_id,
            }
        except ImportError:
            return {
                "success": False,
                "error": "pyotp not installed. Run: pip install pyotp"
            }
    
    def verify_code(self, coach_id: str, code: str) -> Tuple[bool, str]:
        """Verify a 6-digit TOTP code for a coach."""
        try:
            import pyotp
            
            secret = self._secrets.get(coach_id)
            if not secret:
                return False, "2FA not set up for this coach. Contact admin."
            
            totp = pyotp.TOTP(secret)
            # Allow 1 window of tolerance (30 seconds before/after)
            if totp.verify(code, valid_window=1):
                return True, "Verified"
            else:
                return False, "Invalid code. Check your authenticator app."
        except ImportError:
            # If pyotp not installed, skip 2FA (log warning)
            logger.warning("[TOTP] pyotp not installed -- 2FA verification skipped")
            return True, "2FA not available (pyotp not installed)"
    
    def is_enabled(self, coach_id: str) -> bool:
        """Check if 2FA is set up for a coach."""
        return coach_id in self._secrets
    
    def has_pyotp(self) -> bool:
        """Check if pyotp is available."""
        try:
            import pyotp
            return True
        except ImportError:
            return False


# =============================================================================
# SEARCH STATE MACHINE
# =============================================================================
class SearchRequest:
    """Represents a search request moving through the approval pipeline."""
    
    # States
    PROPOSED = "proposed"           # Nate proposed a query, waiting for coach approval
    COACH_APPROVED = "coach_approved"  # Coach approved the query
    AWAITING_2FA = "awaiting_2fa"   # Waiting for 2FA code
    VERIFIED_2FA = "verified_2fa"   # 2FA verified
    AWAITING_ADMIN = "awaiting_admin"  # Waiting for admin approval
    ADMIN_APPROVED = "admin_approved"  # Admin approved
    EXECUTING = "executing"         # Search is running
    RESULTS_REVIEW = "results_review"  # Results shown to coach for review
    COMPLETED = "completed"         # Coach confirmed results, sent to Nate
    DENIED = "denied"               # Denied at any stage
    EXPIRED = "expired"             # Timed out
    ERROR = "error"                 # Error occurred
    
    EXPIRY_MINUTES = 15
    
    def __init__(self, request_id: str, coach_id: str, coach_name: str,
                 original_query: str, suggested_search: str,
                 mode: str = "", persona: str = ""):
        self.request_id = request_id
        self.coach_id = coach_id
        self.coach_name = coach_name
        self.original_query = original_query
        self.suggested_search = suggested_search
        self.mode = mode
        self.persona = persona
        self.state = self.PROPOSED
        self.created_at = datetime.utcnow()
        self.admin_approver_id = None
        self.admin_approver_name = None
        self.results = []
        self.approved_results = []
        self.deny_reason = ""
        self.error_message = ""
    
    @property
    def is_expired(self) -> bool:
        return (datetime.utcnow() - self.created_at) > timedelta(minutes=self.EXPIRY_MINUTES)
    
    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "coach_id": self.coach_id,
            "coach_name": self.coach_name,
            "original_query": self.original_query,
            "suggested_search": self.suggested_search,
            "mode": self.mode,
            "persona": self.persona,
            "state": self.state,
            "created_at": self.created_at.isoformat(),
            "admin_approver": self.admin_approver_name,
            "result_count": len(self.results),
            "approved_count": len(self.approved_results),
        }


class SearchRequestManager:
    """Manage pending search requests."""
    
    def __init__(self):
        self._requests: Dict[str, SearchRequest] = {}
    
    def create(self, **kwargs) -> SearchRequest:
        """Create a new search request."""
        req = SearchRequest(**kwargs)
        self._requests[req.request_id] = req
        self._cleanup_expired()
        return req
    
    def get(self, request_id: str) -> Optional[SearchRequest]:
        """Get a search request by ID."""
        req = self._requests.get(request_id)
        if req and req.is_expired:
            req.state = SearchRequest.EXPIRED
        return req
    
    def get_pending_admin(self) -> List[SearchRequest]:
        """Get all requests awaiting admin approval."""
        return [
            r for r in self._requests.values()
            if r.state == SearchRequest.AWAITING_ADMIN and not r.is_expired
        ]
    
    def remove(self, request_id: str):
        """Remove a completed/expired request."""
        self._requests.pop(request_id, None)
    
    def _cleanup_expired(self):
        """Remove expired requests."""
        expired = [
            rid for rid, req in self._requests.items()
            if req.is_expired
        ]
        for rid in expired:
            self._requests.pop(rid, None)
