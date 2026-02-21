"""
HIVE DEFENSE — Phishing Link Hunter
Active pursuit of phishing infrastructure.  When a phishing email is detected,
the hunter follows URLs, performs DNS/WHOIS/TLS reconnaissance, builds an
attacker infrastructure profile, and deploys counter-intelligence measures
(retrieval seeds, decoy credentials, mirror traps) to trap the attacker
in a house of mirrors.

Triggered by:
  - GmailHiveMonitor (automated, on threat detection)
  - Threat Dropbox   (manual admin submission via SkyEye)

Safety:
  - All outbound requests use generic User-Agent with 5s timeout
  - HEAD-only HTTP (no JS execution, no cookie storage)
  - Never pursues .gov, .mil, or whitelisted banking domains
  - Rate-limited: max 5 hunts per hour
  - All operations forensically logged

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger("hive.phishing_link_hunter")

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

SAFE_DOMAINS = frozenset({
    "google.com", "microsoft.com", "apple.com", "amazon.com",
    "facebook.com", "twitter.com", "linkedin.com", "github.com",
    "paypal.com", "chase.com", "bankofamerica.com", "wellsfargo.com",
    "capitalone.com", "usbank.com", "citi.com",
    "sovereignsanctuary.net", "littlenate.ai",
})

BLOCKED_TLDS = frozenset({".gov", ".mil", ".edu"})

GENERIC_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

MAX_HUNTS_PER_HOUR = 5
REQUEST_TIMEOUT = 5


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ReconResult:
    """Reconnaissance results for a single URL/domain."""
    url: str = ""
    domain: str = ""
    ip_addresses: List[str] = field(default_factory=list)
    dns_records: Dict[str, Any] = field(default_factory=dict)
    redirect_chain: List[str] = field(default_factory=list)
    final_url: str = ""
    http_headers: Dict[str, str] = field(default_factory=dict)
    server_software: str = ""
    tls_issuer: str = ""
    tls_subject: str = ""
    tls_san: List[str] = field(default_factory=list)
    tls_expiry: str = ""
    whois_registrar: str = ""
    whois_creation_date: str = ""
    whois_registrant: str = ""
    whois_raw: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "domain": self.domain,
            "ip_addresses": self.ip_addresses,
            "dns_records": self.dns_records,
            "redirect_chain": self.redirect_chain,
            "final_url": self.final_url,
            "http_headers": self.http_headers,
            "server_software": self.server_software,
            "tls_issuer": self.tls_issuer,
            "tls_subject": self.tls_subject,
            "tls_san": self.tls_san,
            "tls_expiry": self.tls_expiry,
            "whois_registrar": self.whois_registrar,
            "whois_creation_date": self.whois_creation_date,
            "whois_registrant": self.whois_registrant,
            "error": self.error,
        }


@dataclass
class HuntReport:
    """Complete hunt report."""
    hunt_id: str = ""
    status: str = "queued"  # queued, hunting, complete, failed
    source: str = ""  # "gmail_monitor" or "threat_dropbox"
    threat_type: str = ""  # url, email, phone, domain, raw_text
    submitted_content: str = ""
    source_note: str = ""
    submitted_at: float = 0.0
    completed_at: float = 0.0
    urls_found: List[str] = field(default_factory=list)
    recon_results: List[ReconResult] = field(default_factory=list)
    attacker_profile: Dict[str, Any] = field(default_factory=dict)
    traps_deployed: List[Dict[str, Any]] = field(default_factory=list)
    phishing_score: int = 0
    phishing_verdict: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hunt_id": self.hunt_id,
            "status": self.status,
            "source": self.source,
            "threat_type": self.threat_type,
            "submitted_content": self.submitted_content[:200],
            "source_note": self.source_note,
            "submitted_at": self.submitted_at,
            "completed_at": self.completed_at,
            "duration_seconds": round(self.completed_at - self.submitted_at, 1) if self.completed_at else 0,
            "urls_found": self.urls_found,
            "recon_results": [r.to_dict() for r in self.recon_results],
            "attacker_profile": self.attacker_profile,
            "traps_deployed": self.traps_deployed,
            "phishing_score": self.phishing_score,
            "phishing_verdict": self.phishing_verdict,
            "error": self.error,
        }

    def to_summary(self) -> Dict[str, Any]:
        """Short summary for list views."""
        return {
            "hunt_id": self.hunt_id,
            "status": self.status,
            "source": self.source,
            "threat_type": self.threat_type,
            "submitted_content": self.submitted_content[:80],
            "source_note": self.source_note[:50],
            "submitted_at": self.submitted_at,
            "completed_at": self.completed_at,
            "urls_found": len(self.urls_found),
            "recon_count": len(self.recon_results),
            "traps_deployed": len(self.traps_deployed),
            "phishing_score": self.phishing_score,
            "phishing_verdict": self.phishing_verdict,
            "error": self.error[:80] if self.error else "",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PHISHING LINK HUNTER
# ═══════════════════════════════════════════════════════════════════════════════

class PhishingLinkHunter:
    """
    Active threat pursuit engine.  Extracts URLs from phishing content,
    performs sandboxed reconnaissance, builds attacker profiles, and
    deploys counter-intelligence traps.
    """

    def __init__(self):
        self._hunts: Dict[str, HuntReport] = {}
        self._hunt_timestamps: List[float] = []
        self._url_pattern = re.compile(
            r'https?://[^\s<>"\')\]]+|www\.[^\s<>"\')\]]+',
            re.I,
        )

    @property
    def active_hunts(self) -> List[HuntReport]:
        return list(self._hunts.values())

    def get_hunt(self, hunt_id: str) -> Optional[HuntReport]:
        return self._hunts.get(hunt_id)

    def get_all_hunts(self) -> List[Dict[str, Any]]:
        sorted_hunts = sorted(self._hunts.values(), key=lambda h: h.submitted_at, reverse=True)
        return [h.to_summary() for h in sorted_hunts[:100]]

    def _is_rate_limited(self) -> bool:
        now = time.time()
        cutoff = now - 3600
        self._hunt_timestamps = [t for t in self._hunt_timestamps if t > cutoff]
        return len(self._hunt_timestamps) >= MAX_HUNTS_PER_HOUR

    def _is_safe_domain(self, domain: str) -> bool:
        """Check if domain should NOT be hunted."""
        domain = domain.lower().strip(".")
        if domain in SAFE_DOMAINS:
            return True
        for tld in BLOCKED_TLDS:
            if domain.endswith(tld):
                return True
        return False

    def _extract_urls(self, text: str) -> List[str]:
        urls = self._url_pattern.findall(text)
        cleaned = []
        for u in urls:
            u = u.rstrip(".,;:!?)>")
            if not u.startswith("http"):
                u = "http://" + u
            cleaned.append(u)
        return list(dict.fromkeys(cleaned))

    def _extract_domains(self, urls: List[str]) -> Set[str]:
        domains = set()
        for url in urls:
            try:
                parsed = urlparse(url if url.startswith("http") else "http://" + url)
                if parsed.hostname:
                    domains.add(parsed.hostname.lower())
            except Exception:
                continue
        return domains

    # ─── RECONNAISSANCE ───────────────────────────────────────────────────

    async def _recon_dns(self, domain: str) -> Dict[str, Any]:
        """Resolve DNS records for a domain."""
        records: Dict[str, Any] = {}
        try:
            loop = asyncio.get_event_loop()
            addrs = await loop.run_in_executor(None, socket.getaddrinfo, domain, None)
            ips = list(set(a[4][0] for a in addrs))
            records["A"] = ips
        except Exception as e:
            records["error"] = str(e)
        return records

    async def _recon_http(self, url: str) -> Dict[str, Any]:
        """Follow URL with HEAD requests, capture redirect chain and headers."""
        result: Dict[str, Any] = {"redirect_chain": [], "headers": {}, "final_url": "", "server": ""}

        try:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.head(
                    url,
                    allow_redirects=True,
                    headers={"User-Agent": GENERIC_UA},
                    ssl=False,
                    max_redirects=10,
                ) as resp:
                    result["final_url"] = str(resp.url)
                    result["status"] = resp.status
                    result["headers"] = {k: v for k, v in resp.headers.items()}
                    result["server"] = resp.headers.get("Server", "")
                    if resp.history:
                        result["redirect_chain"] = [str(r.url) for r in resp.history] + [str(resp.url)]
        except ImportError:
            # aiohttp not available, fall back to urllib
            import urllib.request
            try:
                req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": GENERIC_UA})
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT))
                result["final_url"] = resp.url
                result["status"] = resp.status
                result["headers"] = dict(resp.headers)
                result["server"] = resp.headers.get("Server", "")
            except Exception as e:
                result["error"] = str(e)
        except Exception as e:
            result["error"] = str(e)

        return result

    async def _recon_tls(self, domain: str) -> Dict[str, Any]:
        """Inspect TLS certificate for a domain."""
        result: Dict[str, Any] = {}
        try:
            loop = asyncio.get_event_loop()

            def _get_cert():
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
                    s.settimeout(REQUEST_TIMEOUT)
                    s.connect((domain, 443))
                    cert = s.getpeercert(binary_form=False)
                    if cert is None:
                        der = s.getpeercert(binary_form=True)
                        return {"raw_der_length": len(der) if der else 0}
                    return cert

            cert = await loop.run_in_executor(None, _get_cert)
            if isinstance(cert, dict):
                subject = cert.get("subject", ())
                issuer = cert.get("issuer", ())
                result["subject"] = str(subject)
                result["issuer"] = str(issuer)
                result["notAfter"] = cert.get("notAfter", "")
                san = cert.get("subjectAltName", ())
                result["san"] = [v for _, v in san] if san else []

                issuer_cn = ""
                for rdn in issuer:
                    for attr_type, attr_value in rdn:
                        if attr_type == "organizationName":
                            issuer_cn = attr_value
                result["issuer_org"] = issuer_cn
        except Exception as e:
            result["error"] = str(e)
        return result

    async def _recon_whois(self, domain: str) -> Dict[str, Any]:
        """WHOIS lookup for domain registration info."""
        result: Dict[str, Any] = {}
        try:
            import whois
            loop = asyncio.get_event_loop()
            w = await loop.run_in_executor(None, whois.whois, domain)
            result["registrar"] = str(w.registrar or "")
            creation = w.creation_date
            if isinstance(creation, list):
                creation = creation[0]
            result["creation_date"] = str(creation) if creation else ""
            result["registrant"] = str(getattr(w, "name", "") or getattr(w, "org", "") or "")
            result["expiration_date"] = str(w.expiration_date) if w.expiration_date else ""
            result["name_servers"] = list(w.name_servers) if w.name_servers else []
        except ImportError:
            result["error"] = "python-whois not installed"
        except Exception as e:
            result["error"] = str(e)
        return result

    async def _recon_url(self, url: str) -> ReconResult:
        """Full reconnaissance on a single URL."""
        result = ReconResult(url=url)
        try:
            parsed = urlparse(url if url.startswith("http") else "http://" + url)
            domain = parsed.hostname or ""
            result.domain = domain

            if not domain or self._is_safe_domain(domain):
                result.error = f"Skipped: {'safe' if domain else 'no'} domain"
                return result

            # Run DNS, HTTP, TLS, WHOIS in parallel
            dns_task = self._recon_dns(domain)
            http_task = self._recon_http(url)
            tls_task = self._recon_tls(domain)
            whois_task = self._recon_whois(domain)

            dns, http, tls_info, whois_info = await asyncio.gather(
                dns_task, http_task, tls_task, whois_task,
                return_exceptions=True,
            )

            # DNS
            if isinstance(dns, dict):
                result.dns_records = dns
                result.ip_addresses = dns.get("A", [])

            # HTTP
            if isinstance(http, dict):
                result.redirect_chain = http.get("redirect_chain", [])
                result.final_url = http.get("final_url", "")
                result.http_headers = http.get("headers", {})
                result.server_software = http.get("server", "")

            # TLS
            if isinstance(tls_info, dict):
                result.tls_issuer = tls_info.get("issuer_org", "")
                result.tls_subject = tls_info.get("subject", "")
                result.tls_san = tls_info.get("san", [])
                result.tls_expiry = tls_info.get("notAfter", "")

            # WHOIS
            if isinstance(whois_info, dict):
                result.whois_registrar = whois_info.get("registrar", "")
                result.whois_creation_date = whois_info.get("creation_date", "")
                result.whois_registrant = whois_info.get("registrant", "")

        except Exception as e:
            result.error = str(e)

        return result

    # ─── COUNTER-INTELLIGENCE ────────────────────────────────────────────

    async def _deploy_traps(self, report: HuntReport) -> List[Dict[str, Any]]:
        """Deploy counter-intelligence measures against identified infrastructure."""
        traps: List[Dict[str, Any]] = []

        if report.phishing_score < 60:
            return traps

        try:
            # Deploy retrieval seeds
            from app.services.counter_intelligence.retrieval_seed import RetrievalSeedCrafter, SeedType
            crafter = RetrievalSeedCrafter()
            attacker_id = report.hunt_id

            dns_seed = await crafter.craft_dns_seed(target_attacker=attacker_id)
            traps.append({
                "type": "retrieval_seed",
                "seed_type": "dns",
                "seed_id": str(dns_seed.seed_id),
                "tracking": dns_seed.tracking_endpoint,
            })

            http_seed = await crafter.craft_http_seed(target_attacker=attacker_id)
            traps.append({
                "type": "retrieval_seed",
                "seed_type": "http",
                "seed_id": str(http_seed.seed_id),
                "tracking": http_seed.tracking_endpoint,
            })

            logger.info("Deployed %d retrieval seeds for hunt %s", len(traps), report.hunt_id)
        except Exception as e:
            logger.warning("Seed deployment failed: %s", e)

        try:
            # Generate decoy credentials
            from app.services.counter_intelligence.decoy_generator import DecoyGenerator
            decoy_gen = DecoyGenerator()
            decoy_pkg = await decoy_gen.generate_decoy_package()
            traps.append({
                "type": "decoy_package",
                "package_id": str(getattr(decoy_pkg, "package_id", uuid4())),
                "contents": "credentials + honeypot data",
            })
            logger.info("Decoy package generated for hunt %s", report.hunt_id)
        except Exception as e:
            logger.warning("Decoy generation failed: %s", e)

        return traps

    # ─── MAIN HUNT ENTRY POINTS ──────────────────────────────────────────

    async def hunt(
        self,
        email_body: str = "",
        from_address: str = "",
        subject: str = "",
        raw_headers: str = "",
        threat_record: Any = None,
        source: str = "gmail_monitor",
    ) -> HuntReport:
        """Hunt phishing infrastructure from a detected email threat."""
        report = HuntReport(
            hunt_id=str(uuid4())[:12],
            status="hunting",
            source=source,
            threat_type="email",
            submitted_content=f"From: {from_address}\nSubject: {subject}\n\n{email_body[:500]}",
            submitted_at=time.time(),
        )
        self._hunts[report.hunt_id] = report

        if self._is_rate_limited():
            report.status = "failed"
            report.error = "Rate limited: max hunts per hour exceeded"
            report.completed_at = time.time()
            return report

        self._hunt_timestamps.append(time.time())

        try:
            # Extract URLs from email body
            all_text = f"{subject} {email_body} {raw_headers}"
            report.urls_found = self._extract_urls(all_text)

            # Run phishing analysis
            try:
                try:
                    from app.services.security.phishing_detector import analyze as phishing_analyze
                except ImportError:
                    from phishing_detector import analyze as phishing_analyze
                verdict = phishing_analyze(
                    content=email_body,
                    content_type="email",
                    from_address=from_address,
                    subject=subject,
                    raw_headers=raw_headers,
                )
                report.phishing_score = verdict.score
                report.phishing_verdict = verdict.verdict
            except Exception:
                pass

            # Recon each URL (max 5)
            for url in report.urls_found[:5]:
                recon = await self._recon_url(url)
                report.recon_results.append(recon)

            # Build attacker profile
            report.attacker_profile = self._build_profile(report)

            # Deploy counter-intelligence
            report.traps_deployed = await self._deploy_traps(report)

            report.status = "complete"
        except Exception as e:
            report.status = "failed"
            report.error = str(e)
            logger.error("Hunt %s failed: %s", report.hunt_id, e)

        report.completed_at = time.time()
        logger.info(
            "Hunt %s complete — %d URLs, %d recon, %d traps, score=%d",
            report.hunt_id, len(report.urls_found),
            len(report.recon_results), len(report.traps_deployed),
            report.phishing_score,
        )
        return report

    async def hunt_dropbox(
        self,
        threat_type: str,
        content: str,
        source_note: str = "",
    ) -> HuntReport:
        """Hunt from a manual Threat Dropbox submission."""
        report = HuntReport(
            hunt_id=str(uuid4())[:12],
            status="hunting",
            source="threat_dropbox",
            threat_type=threat_type,
            submitted_content=content,
            source_note=source_note,
            submitted_at=time.time(),
        )
        self._hunts[report.hunt_id] = report

        if self._is_rate_limited():
            report.status = "failed"
            report.error = "Rate limited: max hunts per hour exceeded"
            report.completed_at = time.time()
            return report

        self._hunt_timestamps.append(time.time())

        try:
            # Extract email addresses from content for sender analysis
            _from_addr = ""
            try:
                _email_pat = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
                _found_emails = _email_pat.findall(content)
                if _found_emails:
                    _from_addr = _found_emails[0]
            except Exception:
                pass

            try:
                try:
                    from app.services.security.phishing_detector import analyze as phishing_analyze
                except ImportError:
                    from phishing_detector import analyze as phishing_analyze
                verdict = phishing_analyze(
                    content=content,
                    content_type="email" if _from_addr else "text",
                    from_address=_from_addr,
                )
                report.phishing_score = verdict.score
                report.phishing_verdict = verdict.verdict
            except Exception as _pa_err:
                logger.warning("Phishing analysis failed: %s", _pa_err)
                pass

            if threat_type == "url":
                report.urls_found = [content.strip()]
            elif threat_type == "domain":
                report.urls_found = [f"https://{content.strip()}"]
            elif threat_type == "phone":
                report.attacker_profile = {
                    "type": "phone_number",
                    "number": content.strip(),
                    "note": source_note,
                    "logged_at": datetime.now(timezone.utc).isoformat(),
                }
                report.status = "complete"
                report.completed_at = time.time()
                return report
            else:
                # email body or raw text — extract URLs
                report.urls_found = self._extract_urls(content)

            # Recon each URL (max 5)
            for url in report.urls_found[:5]:
                recon = await self._recon_url(url)
                report.recon_results.append(recon)

            # Build profile
            report.attacker_profile = self._build_profile(report)

            # Deploy traps
            report.traps_deployed = await self._deploy_traps(report)

            report.status = "complete"
        except Exception as e:
            report.status = "failed"
            report.error = str(e)
            logger.error("Dropbox hunt %s failed: %s", report.hunt_id, e)

        report.completed_at = time.time()
        return report

    def _build_profile(self, report: HuntReport) -> Dict[str, Any]:
        """Build attacker infrastructure profile from recon results."""
        profile: Dict[str, Any] = {
            "domains": [],
            "ip_addresses": [],
            "hosting_providers": [],
            "registrars": [],
            "domain_ages": [],
            "tls_issuers": [],
            "server_software": [],
            "redirect_depth": 0,
        }

        for recon in report.recon_results:
            if recon.error and "Skipped" in recon.error:
                continue
            if recon.domain:
                profile["domains"].append(recon.domain)
            profile["ip_addresses"].extend(recon.ip_addresses)
            if recon.server_software:
                profile["server_software"].append(recon.server_software)
            if recon.tls_issuer:
                profile["tls_issuers"].append(recon.tls_issuer)
            if recon.whois_registrar:
                profile["registrars"].append(recon.whois_registrar)
            if recon.whois_creation_date:
                profile["domain_ages"].append(recon.whois_creation_date)
            if recon.redirect_chain:
                profile["redirect_depth"] = max(profile["redirect_depth"], len(recon.redirect_chain))

        # Deduplicate
        for key in ["domains", "ip_addresses", "hosting_providers", "registrars", "tls_issuers", "server_software"]:
            profile[key] = list(set(profile[key]))

        return profile


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════════════

_hunter_instance: Optional[PhishingLinkHunter] = None


def get_hunter() -> PhishingLinkHunter:
    """Get or create the singleton hunter."""
    global _hunter_instance
    if _hunter_instance is None:
        _hunter_instance = PhishingLinkHunter()
    return _hunter_instance
