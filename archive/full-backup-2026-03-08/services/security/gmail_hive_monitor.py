"""
HIVE DEFENSE — Gmail Hive Monitor
Continuous background polling of protected email inboxes via Gmail API.
Each new message is run through the PhishingDetector; threats trigger
admin alerts via the AdminContactShield.

Supported auth modes:
  1. Google Workspace Service Account (domain-wide delegation)
     — for @sovereignsanctuary.net addresses
  2. OAuth2 Refresh Token (per-user consent)
     — for personal Gmail (dssmllc@gmail.com, nevedal.nathan@gmail.com)

Environment variables:
  GMAIL_SERVICE_ACCOUNT_KEY_PATH   — path to SA JSON key
  GMAIL_OAUTH_CLIENT_ID            — OAuth2 client ID for personal Gmail
  GMAIL_OAUTH_CLIENT_SECRET        — OAuth2 client secret
  GMAIL_OAUTH_REFRESH_TOKENS       — JSON dict mapping email → refresh_token
  GMAIL_POLL_INTERVAL_SECONDS      — poll interval (default 120)
  ADMIN_PROTECTED_EMAILS           — comma-separated list of emails to monitor

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

logger = logging.getLogger("hive.gmail_monitor")


# ═════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═════════════════════════════════════════════════════════════════════════════

class MonitoredInbox:
    """State tracking for a single monitored inbox."""

    def __init__(self, email: str, auth_mode: str):
        self.email = email
        self.auth_mode = auth_mode  # "service_account" or "oauth2"
        self.last_history_id: Optional[str] = None
        self.last_poll_time: float = 0.0
        self.messages_scanned: int = 0
        self.threats_found: int = 0
        self.last_error: Optional[str] = None
        self.healthy: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "auth_mode": self.auth_mode,
            "last_poll_time": self.last_poll_time,
            "messages_scanned": self.messages_scanned,
            "threats_found": self.threats_found,
            "last_error": self.last_error,
            "healthy": self.healthy,
        }


class ThreatRecord:
    """Record of a detected phishing threat from an email."""

    def __init__(
        self,
        inbox_email: str,
        message_id: str,
        from_address: str,
        subject: str,
        verdict: str,
        score: int,
        signals: List[Dict[str, Any]],
        timestamp: float,
    ):
        self.inbox_email = inbox_email
        self.message_id = message_id
        self.from_address = from_address
        self.subject = subject
        self.verdict = verdict
        self.score = score
        self.signals = signals
        self.timestamp = timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inbox_email": self.inbox_email,
            "message_id": self.message_id,
            "from_address": self.from_address,
            "subject": self.subject[:100],
            "verdict": self.verdict,
            "score": self.score,
            "signal_count": len(self.signals),
            "timestamp": self.timestamp,
        }


# ═════════════════════════════════════════════════════════════════════════════
# GMAIL API CLIENT (lightweight, no google-api-python-client dependency)
# ═════════════════════════════════════════════════════════════════════════════

class GmailClient:
    """
    Minimal Gmail API client using httpx for async HTTP.
    Handles both Service Account (JWT) and OAuth2 (refresh token) auth.
    """

    GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

    def __init__(self):
        self._access_tokens: Dict[str, str] = {}  # email -> token
        self._token_expiry: Dict[str, float] = {}  # email -> epoch
        self._sa_key: Optional[Dict] = None
        self._oauth_client_id: str = ""
        self._oauth_client_secret: str = ""
        self._oauth_refresh_tokens: Dict[str, str] = {}  # email -> refresh_token

        self._load_config()

    def _load_config(self):
        """Load auth configuration from environment."""
        # Service Account
        sa_path = os.getenv("GMAIL_SERVICE_ACCOUNT_KEY_PATH", "")
        if sa_path and os.path.isfile(sa_path):
            try:
                with open(sa_path) as f:
                    self._sa_key = json.load(f)
                logger.info("Gmail SA key loaded from %s", sa_path)
            except Exception as e:
                logger.warning("Failed to load SA key: %s", e)

        # OAuth2
        self._oauth_client_id = os.getenv("GMAIL_OAUTH_CLIENT_ID", "")
        self._oauth_client_secret = os.getenv("GMAIL_OAUTH_CLIENT_SECRET", "")
        refresh_json = os.getenv("GMAIL_OAUTH_REFRESH_TOKENS", "{}")
        try:
            self._oauth_refresh_tokens = json.loads(refresh_json)
        except json.JSONDecodeError:
            self._oauth_refresh_tokens = {}

    def can_auth(self, email: str) -> str:
        """
        Return the auth mode for a given email, or '' if not possible.
        """
        domain = email.split("@")[-1] if "@" in email else ""

        if domain == "sovereignsanctuary.net" and self._sa_key:
            return "service_account"
        if email in self._oauth_refresh_tokens and self._oauth_client_id:
            return "oauth2"
        return ""

    async def _get_token_sa(self, email: str) -> str:
        """Get access token via Service Account with domain-wide delegation."""
        import jwt as pyjwt  # PyJWT
        import httpx

        now = int(time.time())
        claim_set = {
            "iss": self._sa_key["client_email"],
            "scope": self.SCOPE,
            "aud": self.TOKEN_URL,
            "sub": email,  # impersonate
            "iat": now,
            "exp": now + 3600,
        }
        signed_jwt = pyjwt.encode(claim_set, self._sa_key["private_key"], algorithm="RS256")

        async with httpx.AsyncClient() as client:
            resp = await client.post(self.TOKEN_URL, data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": signed_jwt,
            })
            resp.raise_for_status()
            data = resp.json()
            return data["access_token"]

    async def _get_token_oauth(self, email: str) -> str:
        """Get access token via OAuth2 refresh token."""
        import httpx

        refresh_token = self._oauth_refresh_tokens.get(email, "")
        if not refresh_token:
            raise ValueError(f"No refresh token for {email}")

        async with httpx.AsyncClient() as client:
            resp = await client.post(self.TOKEN_URL, data={
                "client_id": self._oauth_client_id,
                "client_secret": self._oauth_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            })
            resp.raise_for_status()
            data = resp.json()
            return data["access_token"]

    async def get_token(self, email: str, auth_mode: str) -> str:
        """Get a valid access token (cached)."""
        now = time.time()
        if email in self._access_tokens and self._token_expiry.get(email, 0) > now + 60:
            return self._access_tokens[email]

        if auth_mode == "service_account":
            token = await self._get_token_sa(email)
        else:
            token = await self._get_token_oauth(email)

        self._access_tokens[email] = token
        self._token_expiry[email] = now + 3500  # ~58 min
        return token

    async def list_messages(
        self,
        email: str,
        auth_mode: str,
        query: str = "is:unread newer_than:1h",
        max_results: int = 20,
    ) -> List[Dict]:
        """List messages matching query."""
        import httpx

        token = await self.get_token(email, auth_mode)
        url = f"{self.GMAIL_API}/users/me/messages"
        params = {"q": query, "maxResults": max_results}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 401:
                # Token expired, refresh
                self._access_tokens.pop(email, None)
                token = await self.get_token(email, auth_mode)
                resp = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            data = resp.json()
            return data.get("messages", [])

    async def get_message(self, email: str, auth_mode: str, msg_id: str) -> Dict:
        """Get full message by ID."""
        import httpx

        token = await self.get_token(email, auth_mode)
        url = f"{self.GMAIL_API}/users/me/messages/{msg_id}"
        params = {"format": "full"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            return resp.json()


# ═════════════════════════════════════════════════════════════════════════════
# GMAIL HIVE MONITOR (Background Service)
# ═════════════════════════════════════════════════════════════════════════════

class GmailHiveMonitor:
    """
    Background service that polls protected inboxes and scans for threats.
    """

    def __init__(
        self,
        alert_callback: Optional[Callable[..., Coroutine]] = None,
    ):
        self._poll_interval = int(os.getenv("GMAIL_POLL_INTERVAL_SECONDS", "120"))
        self._protected_emails = [
            e.strip() for e in os.getenv("ADMIN_PROTECTED_EMAILS", "").split(",") if e.strip()
        ]
        self._client = GmailClient()
        self._inboxes: Dict[str, MonitoredInbox] = {}
        self._seen_ids: Dict[str, Set[str]] = {}  # email -> set of message IDs
        self._threats: List[ThreatRecord] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._alert_callback = alert_callback
        self._total_scanned = 0

        # Initialize inbox objects
        for email in self._protected_emails:
            auth_mode = self._client.can_auth(email)
            if auth_mode:
                self._inboxes[email] = MonitoredInbox(email, auth_mode)
                self._seen_ids[email] = set()
                logger.info("Gmail Monitor: will monitor %s via %s", email, auth_mode)
            else:
                logger.warning("Gmail Monitor: no auth available for %s — skipping", email)

    @property
    def monitored_count(self) -> int:
        return len(self._inboxes)

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> Dict[str, Any]:
        """Return current monitoring status for dashboard display."""
        return {
            "running": self._running,
            "poll_interval_seconds": self._poll_interval,
            "protected_emails": self._protected_emails,
            "monitored_inboxes": [inbox.to_dict() for inbox in self._inboxes.values()],
            "unmonitored_emails": [
                e for e in self._protected_emails if e not in self._inboxes
            ],
            "total_scanned": self._total_scanned,
            "total_threats": len(self._threats),
            "recent_threats": [t.to_dict() for t in self._threats[-20:]],
        }

    async def start(self):
        """Start background polling loop."""
        if self._running:
            return
        if not self._inboxes:
            logger.warning("Gmail Monitor: no inboxes configured — not starting")
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Gmail Hive Monitor started — monitoring %d inboxes", len(self._inboxes))

    async def stop(self):
        """Stop background polling."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Gmail Hive Monitor stopped")

    async def _poll_loop(self):
        """Main polling loop."""
        while self._running:
            for email, inbox in self._inboxes.items():
                try:
                    await self._poll_inbox(email, inbox)
                except Exception as e:
                    inbox.last_error = str(e)
                    inbox.healthy = False
                    logger.error("Gmail Monitor error for %s: %s", email, e)
            await asyncio.sleep(self._poll_interval)

    async def _poll_inbox(self, email: str, inbox: MonitoredInbox):
        """Poll a single inbox for new messages."""
        from app.services.security.phishing_detector import analyze as phishing_analyze

        messages = await self._client.list_messages(
            email,
            inbox.auth_mode,
            query="is:unread newer_than:2h",
            max_results=30,
        )
        inbox.last_poll_time = time.time()
        inbox.healthy = True

        new_ids = [m["id"] for m in messages if m["id"] not in self._seen_ids[email]]
        if not new_ids:
            return

        for msg_id in new_ids[:20]:  # cap per poll
            self._seen_ids[email].add(msg_id)
            try:
                msg = await self._client.get_message(email, inbox.auth_mode, msg_id)
                inbox.messages_scanned += 1
                self._total_scanned += 1

                # Extract fields
                headers = msg.get("payload", {}).get("headers", [])
                from_addr = ""
                subject = ""
                for h in headers:
                    name_lower = h.get("name", "").lower()
                    if name_lower == "from":
                        from_addr = h.get("value", "")
                    elif name_lower == "subject":
                        subject = h.get("value", "")

                # Extract body
                body_text = self._extract_body(msg)

                # Extract attachment names
                attachment_names = []
                parts = msg.get("payload", {}).get("parts", [])
                for part in parts:
                    filename = part.get("filename", "")
                    if filename:
                        attachment_names.append(filename)

                # Build raw header string
                raw_headers = "\n".join(
                    f"{h['name']}: {h['value']}" for h in headers
                )

                # Run phishing analysis
                verdict = phishing_analyze(
                    content=body_text,
                    content_type="email",
                    from_address=from_addr,
                    subject=subject,
                    raw_headers=raw_headers,
                    attachment_names=attachment_names,
                )

                if verdict.verdict != "CLEAN":
                    threat = ThreatRecord(
                        inbox_email=email,
                        message_id=msg_id,
                        from_address=from_addr,
                        subject=subject,
                        verdict=verdict.verdict,
                        score=verdict.score,
                        signals=[s.__dict__ for s in verdict.signals],
                        timestamp=time.time(),
                    )
                    self._threats.append(threat)
                    inbox.threats_found += 1
                    logger.warning(
                        "THREAT detected in %s — from=%s subject=%s verdict=%s score=%d",
                        email, from_addr[:50], subject[:50], verdict.verdict, verdict.score,
                    )

                    # Fire alert
                    if self._alert_callback:
                        await self._alert_callback(
                            f"PHISHING THREAT ({verdict.verdict}) in {email}\n"
                            f"From: {from_addr}\n"
                            f"Subject: {subject}\n"
                            f"Score: {verdict.score}/100\n"
                            f"Signals: {len(verdict.signals)}"
                        )

                    # Deploy hunter against confirmed threats
                    if verdict.score >= 60:
                        try:
                            from app.services.security.phishing_link_hunter import get_hunter
                            hunter = get_hunter()
                            asyncio.create_task(hunter.hunt(
                                email_body=body_text,
                                from_address=from_addr,
                                subject=subject,
                                raw_headers=raw_headers,
                                threat_record=threat,
                                source="gmail_monitor",
                            ))
                            logger.info("Hunter deployed for threat in %s (score=%d)", email, verdict.score)
                        except Exception as hunt_err:
                            logger.warning("Hunter deployment failed: %s", hunt_err)

            except Exception as e:
                logger.error("Gmail Monitor: failed to process msg %s in %s: %s", msg_id, email, e)

        # Cap seen_ids to prevent unbounded growth
        if len(self._seen_ids[email]) > 5000:
            excess = len(self._seen_ids[email]) - 3000
            to_remove = list(self._seen_ids[email])[:excess]
            for item in to_remove:
                self._seen_ids[email].discard(item)

    @staticmethod
    def _extract_body(msg: Dict) -> str:
        """Extract plain text body from Gmail message."""
        payload = msg.get("payload", {})

        # Try top-level body
        body_data = payload.get("body", {}).get("data", "")
        if body_data:
            try:
                return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
            except Exception:
                pass

        # Walk parts
        parts = payload.get("parts", [])
        for part in parts:
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data", "")
            if "text/plain" in mime and data:
                try:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                except Exception:
                    pass
            # Nested parts
            for sub in part.get("parts", []):
                sub_mime = sub.get("mimeType", "")
                sub_data = sub.get("body", {}).get("data", "")
                if "text/plain" in sub_mime and sub_data:
                    try:
                        return base64.urlsafe_b64decode(sub_data).decode("utf-8", errors="replace")
                    except Exception:
                        pass

        # Fallback to HTML
        for part in parts:
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data", "")
            if "text/html" in mime and data:
                try:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                except Exception:
                    pass

        return ""


# ═════════════════════════════════════════════════════════════════════════════
# API ENDPOINTS (added to hive_defense_api router)
# ═════════════════════════════════════════════════════════════════════════════

_monitor_instance: Optional[GmailHiveMonitor] = None


def get_monitor() -> GmailHiveMonitor:
    """Get or create the singleton monitor."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = GmailHiveMonitor()
    return _monitor_instance


def set_monitor(monitor: GmailHiveMonitor):
    """Set the singleton (used during app startup)."""
    global _monitor_instance
    _monitor_instance = monitor
