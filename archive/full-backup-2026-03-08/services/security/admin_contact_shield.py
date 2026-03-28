"""
ADMIN CONTACT SHIELD — Centralized PII Protection + Defense Alert Dispatch

Protects admin personal contact information from leaking through:
- AI chat responses (Little Nate, Big Nate, SkyEye)
- WebSocket payloads
- Application logs
- Dashboard rendering

Also provides a single dispatch point for defense system SMS/email alerts
to the admin's phone and inbox.

Configuration (from .env):
    ADMIN_PROTECTED_EMAILS  — comma-separated emails to redact
    ADMIN_PROTECTED_PHONES  — comma-separated phones to redact
    ADMIN_ALERT_PHONE       — phone to receive defense SMS alerts
    ADMIN_ALERT_EMAILS      — comma-separated emails for defense alerts
"""

from __future__ import annotations

import re
from typing import List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Social engineering patterns that attempt to extract admin contact info
_EXTRACTION_PATTERNS = [
    re.compile(r"(?:who|what)\s+(?:is|are)\s+(?:the\s+)?(?:admin|owner|creator|developer|founder)", re.I),
    re.compile(r"(?:admin|owner|creator|developer|founder)(?:'s|s)?\s+(?:email|phone|contact|number|address)", re.I),
    re.compile(r"contact\s+(?:the\s+)?(?:admin|owner|creator|developer|founder)", re.I),
    re.compile(r"(?:give|tell|show|share|reveal|send)\s+(?:me\s+)?(?:the\s+)?(?:admin|owner|developer|creator)(?:'s)?\s+(?:email|phone|contact)", re.I),
    re.compile(r"(?:nathan|nate)(?:'s)?\s+(?:email|phone|number|contact)", re.I),
    re.compile(r"(?:who\s+)?(?:runs?|owns?|built|created|made)\s+(?:this|the)\s+(?:app|platform|sanctuary|system)", re.I),
    re.compile(r"(?:developer|admin|owner)\s+(?:email|phone|contact)\s+(?:address|number|info)", re.I),
    re.compile(r"how\s+(?:do\s+I|can\s+I|to)\s+(?:contact|reach|email|call|text)\s+(?:the\s+)?(?:admin|owner|developer)", re.I),
]

# Score weights for extraction patterns
_EXTRACTION_SCORE_BASE = 0.7
_EXTRACTION_SCORE_HIGH = 0.9


def _normalize_phone_digits(phone: str) -> str:
    """Strip a phone string to just digits."""
    return re.sub(r"[^\d]", "", phone)


class AdminContactShield:
    """
    Singleton shield that loads admin contacts from env vars and provides:
    - contains_protected_contact(text) -> bool
    - redact(text) -> str
    - score_extraction_attempt(text) -> float
    - alert_admin(subject, body) — dispatches SMS + email
    """

    def __init__(
        self,
        protected_emails: str = "",
        protected_phones: str = "",
        alert_phone: str = "",
        alert_emails: str = "",
    ):
        # Parse protected emails (lowercased for matching)
        self._emails: Set[str] = set()
        for e in protected_emails.split(","):
            e = e.strip().lower()
            if e:
                self._emails.add(e)

        # Parse protected phones (digits only, plus common partial forms)
        self._phone_digits: Set[str] = set()
        self._phone_raw: Set[str] = set()
        for p in protected_phones.split(","):
            p = p.strip()
            if p:
                self._phone_raw.add(p)
                digits = _normalize_phone_digits(p)
                self._phone_digits.add(digits)
                # Also store last 10 and last 7 digits for partial matching
                if len(digits) >= 10:
                    self._phone_digits.add(digits[-10:])
                if len(digits) >= 7:
                    self._phone_digits.add(digits[-7:])

        # Build compiled regex patterns for fast scanning
        self._email_patterns: List[re.Pattern] = []
        for email in self._emails:
            escaped = re.escape(email)
            self._email_patterns.append(re.compile(escaped, re.I))

        self._phone_patterns: List[re.Pattern] = []
        for digits in self._phone_digits:
            if len(digits) >= 7:
                # Match the digits with optional separators between each digit
                pattern_str = r"[-.\s()]*".join(re.escape(d) for d in digits)
                self._phone_patterns.append(re.compile(pattern_str))

        # Alert destinations
        self._alert_phone = alert_phone.strip() if alert_phone else ""
        self._alert_emails: List[str] = []
        for ae in alert_emails.split(","):
            ae = ae.strip()
            if ae:
                self._alert_emails.append(ae)

        # Notification system reference (set via set_notification_system)
        self._notification_system = None

        if self._emails or self._phone_digits:
            print(f"   [SHIELD] Admin Contact Shield active: {len(self._emails)} emails, "
                  f"{len(self._phone_raw)} phones protected")

    def set_notification_system(self, ns) -> None:
        """Wire in the NotificationSystem instance for SMS/email dispatch."""
        self._notification_system = ns

    # --- Detection ---

    def contains_protected_contact(self, text: str) -> bool:
        """Fast check: does text contain any admin email or phone?"""
        if not text:
            return False
        text_lower = text.lower()
        for email in self._emails:
            if email in text_lower:
                return True
        text_digits = _normalize_phone_digits(text)
        for digits in self._phone_digits:
            if digits in text_digits:
                return True
        return False

    # --- Redaction ---

    def redact(self, text: str) -> str:
        """Replace any admin email or phone in text with [PROTECTED]."""
        if not text:
            return text

        result = text

        # Redact emails (case-insensitive)
        for pattern in self._email_patterns:
            result = pattern.sub("[PROTECTED]", result)

        # Redact phone patterns
        for pattern in self._phone_patterns:
            result = pattern.sub("[PROTECTED]", result)

        return result

    # --- Social engineering scoring ---

    def score_extraction_attempt(self, text: str) -> float:
        """
        Score an inbound message for social engineering attempts
        to extract admin contact information.
        Returns 0.0 (safe) to 1.0 (definite extraction attempt).
        """
        if not text:
            return 0.0

        max_score = 0.0
        for pattern in _EXTRACTION_PATTERNS:
            if pattern.search(text):
                max_score = max(max_score, _EXTRACTION_SCORE_BASE)

        # Higher score if they specifically mention known names
        name_patterns = [
            re.compile(r"\bnevedal\b", re.I),
            re.compile(r"\bnathan\b.*\b(?:email|phone|contact)", re.I),
        ]
        for np in name_patterns:
            if np.search(text):
                max_score = max(max_score, _EXTRACTION_SCORE_HIGH)

        return max_score

    # --- Admin Alert Dispatch ---

    async def alert_admin(self, subject: str, body: str) -> None:
        """
        Send SMS + email alert to admin. Called by defense systems
        (Sentinel, Counter-Intel, Canary, Duress, Deadman).
        """
        ns = self._notification_system
        if not ns:
            print(f"   [SHIELD] Alert (no notification system): {subject}")
            return

        # SMS alert
        if self._alert_phone:
            sms_body = f"[SANCTUARY DEFENSE] {subject}\n{body[:140]}"
            try:
                await ns.send_sms(self._alert_phone, sms_body)
            except Exception as e:
                print(f"   [SHIELD] SMS alert failed: {e}")

        # Email alerts
        for email in self._alert_emails:
            try:
                await ns._send_email(
                    to_email=email,
                    subject=f"[SANCTUARY DEFENSE] {subject}",
                    content=f"""
                    <div style="font-family: 'DM Sans', sans-serif; background: #050505; color: #E8D5A3; padding: 24px;">
                        <h2 style="color: #C9A962; margin-top: 0;">Defense Alert</h2>
                        <p style="font-size: 18px; font-weight: bold;">{subject}</p>
                        <p style="color: #ccc;">{body}</p>
                        <hr style="border-color: #333;">
                        <p style="color: #666; font-size: 12px;">Sovereign Sanctuary Defense System</p>
                    </div>
                    """,
                    notification_type="defense_alert",
                )
            except Exception as e:
                print(f"   [SHIELD] Email alert to {email} failed: {e}")


# --- Singleton ---

_shield_instance: Optional[AdminContactShield] = None


def get_shield() -> AdminContactShield:
    """Get or create the singleton AdminContactShield."""
    global _shield_instance
    if _shield_instance is None:
        try:
            from app.config import settings
            _shield_instance = AdminContactShield(
                protected_emails=settings.ADMIN_PROTECTED_EMAILS,
                protected_phones=settings.ADMIN_PROTECTED_PHONES,
                alert_phone=settings.ADMIN_ALERT_PHONE,
                alert_emails=settings.ADMIN_ALERT_EMAILS,
            )
        except Exception:
            _shield_instance = AdminContactShield()
    return _shield_instance


def reset_shield() -> None:
    """Reset singleton (for testing)."""
    global _shield_instance
    _shield_instance = None
