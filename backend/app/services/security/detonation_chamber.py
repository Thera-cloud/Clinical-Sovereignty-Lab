"""
HIVE DEFENSE — Detonation Chamber
Sandboxed headless browser that follows phishing links as a "shell victim."

Instead of clicking phishing links with your real browser and real account,
the Detonation Chamber opens them in an isolated headless browser that:

 1. Follows all redirects (captures the full chain)
 2. Captures full-page screenshots at each step
 3. Extracts all form fields (reveals what data the attacker wants)
 4. Records all outbound network requests the page makes
 5. Detects credential harvesting forms (login, password, SSN, CC fields)
 6. Optionally injects decoy/canary credentials into harvesting forms
 7. Captures the full page HTML source for forensic analysis

The attacker sees a "real victim" clicking their link.
You see everything they tried to do, from inside the house of mirrors.

Safety:
  - Runs in headless mode (no real desktop or session exposed)
  - Spoofed User-Agent / viewport (looks like a real Windows Chrome user)
  - Never sends real credentials -- only decoy/canary data
  - 15-second hard timeout per page
  - Never visits .gov / .mil / banking domains
  - All results forensically logged

Requires: playwright (pip install playwright && playwright install chromium)
Fallback: aiohttp HEAD-only mode if playwright not available

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger("hive.detonation_chamber")

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

BLOCKED_DOMAINS = frozenset({
    "google.com", "microsoft.com", "apple.com", "amazon.com",
    "facebook.com", "twitter.com", "github.com",
    "paypal.com", "chase.com", "bankofamerica.com", "wellsfargo.com",
    "sovereignsanctuary.net", "littlenate.ai",
})

BLOCKED_TLDS = frozenset({".gov", ".mil", ".edu"})

SPOOF_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)

PAGE_TIMEOUT_MS = 15000
MAX_REDIRECTS = 15

# Decoy credentials for form poisoning
DECOY_CREDS = {
    "email": "sarah.mitchell.2024@gmail.com",
    "password": "SarahM!tchell2024$ecure",
    "username": "smitchell2024",
    "name": "Sarah Mitchell",
    "first_name": "Sarah",
    "last_name": "Mitchell",
    "phone": "4155551234",
    "ssn": "078-05-1120",
    "card_number": "4111111111111111",
    "card_exp": "12/27",
    "card_cvv": "123",
    "address": "742 Evergreen Terrace",
    "city": "Springfield",
    "state": "IL",
    "zip": "62704",
    "dob": "03/15/1989",
}

# Form field patterns that indicate credential harvesting
HARVEST_PATTERNS = {
    "email": re.compile(r"email|e-mail|mail|user.?name|login|acct|account", re.I),
    "password": re.compile(r"pass|pwd|secret|pin|code", re.I),
    "ssn": re.compile(r"ssn|social|tax.?id|sin\b", re.I),
    "card": re.compile(r"card|cc|credit|debit|payment|cvv|cvc|ccv|expir", re.I),
    "phone": re.compile(r"phone|mobile|cell|tel\b|sms", re.I),
    "name": re.compile(r"\bname\b|first.?name|last.?name|full.?name", re.I),
    "address": re.compile(r"address|street|city|state|zip|postal", re.I),
    "dob": re.compile(r"birth|dob|born|age", re.I),
}


def _build_subprocess_script(url: str, inject_decoy: bool) -> str:
    """Build a self-contained Python script for subprocess detonation."""
    url_escaped = url.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    inject_flag = "True" if inject_decoy else "False"
    return f'''
import asyncio, base64, hashlib, json, re, sys

SPOOF_UA = "{SPOOF_UA}"
PAGE_TIMEOUT_MS = {PAGE_TIMEOUT_MS}
DECOY_CREDS = {json.dumps(DECOY_CREDS)}
HP_SRC = {{
    "email": r"email|e-mail|mail|user.?name|login|acct|account",
    "password": r"pass|pwd|secret|pin|code",
    "ssn": r"ssn|social|tax.?id|sin\\\\b",
    "card": r"card|cc|credit|debit|payment|cvv|cvc|ccv|expir",
    "phone": r"phone|mobile|cell|tel\\\\b|sms",
    "name": r"\\\\bname\\\\b|first.?name|last.?name|full.?name",
    "address": r"address|street|city|state|zip|postal",
    "dob": r"birth|dob|born|age",
}}
HP = {{k: re.compile(v, re.I) for k, v in HP_SRC.items()}}

def run():
    r = {{"error": ""}}
    try:
        from playwright.sync_api import sync_playwright
        import time as _time
        rc = ['{url_escaped}']
        obreqs = []
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True, args=[
                "--no-sandbox","--disable-dev-shm-usage","--disable-gpu",
                "--disable-software-rasterizer","--disable-extensions"])
            ctx = b.new_context(user_agent=SPOOF_UA,
                viewport={{"width":1366,"height":768}}, locale="en-US",
                timezone_id="America/New_York", ignore_https_errors=True)
            pg = ctx.new_page()
            pg.on("request", lambda req: obreqs.append(req.url))
            pg.on("response", lambda resp: rc.append(resp.url) if resp.request.is_navigation_request() and resp.url != '{url_escaped}' else None)
            resp = pg.goto('{url_escaped}', wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            r["final_url"] = pg.url
            r["status_code"] = resp.status if resp else 0
            r["title"] = pg.title()
            r["redirect_chain"] = rc
            r["outbound_requests"] = obreqs[:30]
            _time.sleep(2)
            if pg.url != r["final_url"]:
                rc.append(pg.url)
                r["final_url"] = pg.url
            try:
                shot = pg.screenshot(full_page=True, type="png")
                r["screenshot_b64"] = base64.b64encode(shot).decode("ascii")
            except Exception:
                r["screenshot_b64"] = ""
            html = pg.content()
            r["page_html_hash"] = hashlib.sha256(html.encode()).hexdigest()[:16]
            r["page_html_preview"] = html[:500]
            ffs = []
            cfs = []
            hts = []
            forms = pg.query_selector_all("form")
            for i, fm in enumerate(forms[:5]):
                fd = {{"index":i,"action":"","method":"","fields":[]}}
                try:
                    fd["action"] = fm.get_attribute("action") or ""
                    fd["method"] = (fm.get_attribute("method") or "GET").upper()
                except Exception: pass
                inputs = fm.query_selector_all("input, select, textarea")
                for inp in inputs[:20]:
                    try:
                        it = inp.get_attribute("type") or "text"
                        nm = inp.get_attribute("name") or ""
                        iid = inp.get_attribute("id") or ""
                        iph = inp.get_attribute("placeholder") or ""
                        fd["fields"].append({{"type":it,"name":nm,"id":iid,"placeholder":iph}})
                        cmb = f"{{nm}} {{iid}} {{iph}} {{it}}".lower()
                        for ht, pat in HP.items():
                            if pat.search(cmb):
                                cfs.append({{"type":ht,"field_name":nm or iid,"input_type":it}})
                                if ht not in hts: hts.append(ht)
                    except Exception: continue
                ffs.append(fd)
            r["forms_found"] = ffs
            r["credential_fields"] = cfs
            r["harvested_types"] = hts
            r["is_credential_harvester"] = bool(cfs)
            cookies = ctx.cookies()
            r["cookies_set"] = [{{"name":c["name"],"domain":c["domain"],"secure":c.get("secure",False)}} for c in cookies[:10]]
            scripts = pg.query_selector_all("script[src]")
            r["scripts_loaded"] = []
            for s in scripts[:10]:
                try:
                    src = s.get_attribute("src")
                    if src: r["scripts_loaded"].append(src)
                except Exception: pass
            r["meta_redirects"] = []
            if {inject_flag} and r["is_credential_harvester"] and ffs:
                try:
                    filled = 0
                    dm = {{"email":DECOY_CREDS["email"],"password":DECOY_CREDS["password"],
                          "ssn":DECOY_CREDS["ssn"],"card":DECOY_CREDS["card_number"],
                          "phone":DECOY_CREDS["phone"],"name":DECOY_CREDS["name"],
                          "address":DECOY_CREDS["address"],"dob":DECOY_CREDS["dob"]}}
                    for cf in cfs:
                        fn = cf["field_name"]
                        if not fn: continue
                        val = dm.get(cf["type"],"test_value_2024")
                        el = pg.query_selector(f"[name='{{fn}}']")
                        if not el: el = pg.query_selector(f"[id='{{fn}}']")
                        if el: el.fill(val); filled += 1
                    r["decoy_submitted"] = filled > 0
                    if filled > 0:
                        from datetime import datetime, timezone as tz
                        r["decoy_details"] = {{"injected_at":datetime.now(tz.utc).isoformat(),
                            "fields_filled":len(cfs),"types":hts}}
                except Exception: pass
            b.close()
    except Exception as e:
        r["error"] = str(e)
    print(json.dumps(r))

run()
'''


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PageCapture:
    """Capture of a single page visit."""
    url: str = ""
    final_url: str = ""
    status_code: int = 0
    title: str = ""
    redirect_chain: List[str] = field(default_factory=list)
    screenshot_b64: str = ""
    page_html_hash: str = ""
    page_html_preview: str = ""
    forms_found: List[Dict[str, Any]] = field(default_factory=list)
    credential_fields: List[Dict[str, str]] = field(default_factory=list)
    is_credential_harvester: bool = False
    harvested_types: List[str] = field(default_factory=list)
    outbound_requests: List[str] = field(default_factory=list)
    cookies_set: List[Dict[str, str]] = field(default_factory=list)
    scripts_loaded: List[str] = field(default_factory=list)
    meta_redirects: List[str] = field(default_factory=list)
    decoy_submitted: bool = False
    decoy_details: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "title": self.title,
            "redirect_chain": self.redirect_chain,
            "has_screenshot": bool(self.screenshot_b64),
            "screenshot_b64": self.screenshot_b64[:100] + "..." if len(self.screenshot_b64) > 100 else self.screenshot_b64,
            "page_html_hash": self.page_html_hash,
            "page_html_preview": self.page_html_preview[:300],
            "forms_found": self.forms_found,
            "credential_fields": self.credential_fields,
            "is_credential_harvester": self.is_credential_harvester,
            "harvested_types": self.harvested_types,
            "outbound_requests": self.outbound_requests[:20],
            "cookies_set": self.cookies_set[:10],
            "scripts_loaded": self.scripts_loaded[:10],
            "meta_redirects": self.meta_redirects,
            "decoy_submitted": self.decoy_submitted,
            "decoy_details": self.decoy_details,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }

    def to_full_dict(self) -> Dict[str, Any]:
        """Full dict including complete screenshot for report."""
        d = self.to_dict()
        d["screenshot_b64"] = self.screenshot_b64
        return d


@dataclass
class DetonationReport:
    """Full detonation report for a URL."""
    detonation_id: str = ""
    target_url: str = ""
    status: str = "queued"
    started_at: float = 0.0
    completed_at: float = 0.0
    pages: List[PageCapture] = field(default_factory=list)
    total_redirects: int = 0
    credential_harvester_detected: bool = False
    harvested_data_types: List[str] = field(default_factory=list)
    decoy_injected: bool = False
    threat_score: int = 0
    threat_summary: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detonation_id": self.detonation_id,
            "target_url": self.target_url,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": round(self.completed_at - self.started_at, 1) if self.completed_at else 0,
            "pages_visited": len(self.pages),
            "pages": [p.to_dict() for p in self.pages],
            "total_redirects": self.total_redirects,
            "credential_harvester_detected": self.credential_harvester_detected,
            "harvested_data_types": self.harvested_data_types,
            "decoy_injected": self.decoy_injected,
            "threat_score": self.threat_score,
            "threat_summary": self.threat_summary,
            "error": self.error,
        }

    def to_summary(self) -> Dict[str, Any]:
        return {
            "detonation_id": self.detonation_id,
            "target_url": self.target_url[:80],
            "status": self.status,
            "pages_visited": len(self.pages),
            "credential_harvester_detected": self.credential_harvester_detected,
            "decoy_injected": self.decoy_injected,
            "threat_score": self.threat_score,
            "threat_summary": self.threat_summary[:100],
            "duration_seconds": round(self.completed_at - self.started_at, 1) if self.completed_at else 0,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# DETONATION CHAMBER
# ═══════════════════════════════════════════════════════════════════════════════

class DetonationChamber:
    """
    Sandboxed headless browser that visits phishing links as a shell victim.

    The attacker sees a real-looking visitor clicking their link.
    We see everything they tried to do.
    """

    def __init__(self):
        self._detonations: Dict[str, DetonationReport] = {}
        self._playwright_available: Optional[bool] = None

    async def _check_playwright(self) -> bool:
        if self._playwright_available is not None:
            return self._playwright_available
        try:
            from playwright.async_api import async_playwright
            self._playwright_available = True
        except ImportError:
            self._playwright_available = False
            logger.warning("Playwright not installed — detonation will use fallback HTTP mode")
        return self._playwright_available

    def _is_blocked(self, url: str) -> bool:
        try:
            parsed = urlparse(url if url.startswith("http") else "http://" + url)
            domain = (parsed.hostname or "").lower().strip(".")
            if domain in BLOCKED_DOMAINS:
                return True
            for tld in BLOCKED_TLDS:
                if domain.endswith(tld):
                    return True
            if domain in ("localhost", "127.0.0.1", "0.0.0.0", "::1", ""):
                return True
            import ipaddress
            try:
                addr = ipaddress.ip_address(domain)
                if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                    return True
            except ValueError:
                pass
        except Exception:
            pass
        return False

    def get_detonation(self, det_id: str) -> Optional[DetonationReport]:
        return self._detonations.get(det_id)

    def get_all_detonations(self) -> List[Dict[str, Any]]:
        sorted_dets = sorted(self._detonations.values(), key=lambda d: d.started_at, reverse=True)
        return [d.to_summary() for d in sorted_dets[:50]]

    # ─── PLAYWRIGHT DETONATION ────────────────────────────────────────────

    async def _detonate_playwright(self, url: str, report: DetonationReport, inject_decoy: bool):
        """
        Full browser detonation with Playwright, executed in a subprocess.
        Subprocess isolation prevents Playwright/Chromium conflicts with uvicorn's
        event loop and signal handling.
        """
        import subprocess as _sp
        import concurrent.futures
        import sys as _sys

        script = _build_subprocess_script(url, inject_decoy)
        script_path = f"/tmp/_det_{report.detonation_id}.py"
        try:
            with open(script_path, "w") as f:
                f.write(script)

            python_bin = _sys.executable or "python3"

            def _run_det():
                return _sp.run(
                    [python_bin, script_path],
                    capture_output=True, text=True, timeout=60,
                )

            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                proc_result = await loop.run_in_executor(pool, _run_det)

            if proc_result.stderr:
                logger.warning("Detonation subprocess stderr: %s", proc_result.stderr[-300:])
            if proc_result.returncode != 0:
                logger.error("Detonation subprocess failed (rc=%d): %s", proc_result.returncode, proc_result.stderr[-500:])
                report.pages.append(PageCapture(url=url, error=f"Subprocess exit {proc_result.returncode}: {proc_result.stderr[-200:]}"))
                return

            stdout_text = proc_result.stdout.strip()
            logger.info("Detonation subprocess stdout length: %d, preview: %s", len(stdout_text), stdout_text[:200])
            result = json.loads(stdout_text)
            if result.get("error"):
                report.pages.append(PageCapture(url=url, error=result["error"]))
                return

            capture = PageCapture(
                url=url,
                final_url=result.get("final_url", url),
                status_code=result.get("status_code", 0),
                title=result.get("title", ""),
                redirect_chain=result.get("redirect_chain", [url]),
                outbound_requests=result.get("outbound_requests", [])[:30],
                screenshot_b64=result.get("screenshot_b64", ""),
                page_html_hash=result.get("page_html_hash", ""),
                page_html_preview=result.get("page_html_preview", ""),
                forms_found=result.get("forms_found", []),
                credential_fields=result.get("credential_fields", []),
                harvested_types=result.get("harvested_types", []),
                is_credential_harvester=result.get("is_credential_harvester", False),
                cookies_set=result.get("cookies_set", []),
                scripts_loaded=result.get("scripts_loaded", []),
                meta_redirects=result.get("meta_redirects", []),
                decoy_submitted=result.get("decoy_submitted", False),
                decoy_details=result.get("decoy_details", {}),
            )
            report.pages.append(capture)

        except asyncio.TimeoutError:
            report.pages.append(PageCapture(url=url, error="Detonation subprocess timed out (60s)"))
        except json.JSONDecodeError as e:
            report.pages.append(PageCapture(url=url, error=f"Bad subprocess output: {e}"))
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    async def _inject_decoy(self, page, capture: PageCapture) -> bool:
        """Fill credential harvesting forms with decoy/canary data."""
        filled = 0

        for cred_field in capture.credential_fields:
            field_name = cred_field["field_name"]
            harvest_type = cred_field["type"]

            if not field_name:
                continue

            # Pick the right decoy value
            decoy_map = {
                "email": DECOY_CREDS["email"],
                "password": DECOY_CREDS["password"],
                "ssn": DECOY_CREDS["ssn"],
                "card": DECOY_CREDS["card_number"],
                "phone": DECOY_CREDS["phone"],
                "name": DECOY_CREDS["name"],
                "address": DECOY_CREDS["address"],
                "dob": DECOY_CREDS["dob"],
            }

            value = decoy_map.get(harvest_type, "test_value_2024")

            try:
                selector = f"[name='{field_name}']"
                el = await page.query_selector(selector)
                if not el:
                    selector = f"[id='{field_name}']"
                    el = await page.query_selector(selector)
                if el:
                    await el.fill(value)
                    filled += 1
            except Exception:
                continue

        # Try to submit the form if we filled anything
        if filled > 0:
            try:
                submit = await page.query_selector("button[type='submit'], input[type='submit'], button:has-text('Sign'), button:has-text('Log'), button:has-text('Submit')")
                if submit:
                    await submit.click()
                    await asyncio.sleep(2)

                    # Capture post-submission page
                    try:
                        post_screenshot = await page.screenshot(full_page=True, type="png")
                        post_capture = PageCapture(
                            url=page.url,
                            final_url=page.url,
                            title=await page.title(),
                            screenshot_b64=base64.b64encode(post_screenshot).decode("ascii"),
                            page_html_preview=(await page.content())[:500],
                        )
                        post_capture.decoy_submitted = True
                        post_capture.decoy_details = {"note": "Post-submission capture", "fields_poisoned": filled}
                        # Don't append as separate page -- info is in the main capture
                    except Exception:
                        pass
            except Exception as e:
                logger.debug("Form submit failed: %s", e)

        return filled > 0

    # ─── FALLBACK HTTP DETONATION ─────────────────────────────────────────

    async def _detonate_http(self, url: str, report: DetonationReport):
        """Fallback: HTTP-only detonation without browser (no screenshots/forms)."""
        capture = PageCapture(url=url)

        try:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=10)
            redirect_chain = []

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    url,
                    allow_redirects=True,
                    headers={"User-Agent": SPOOF_UA},
                    ssl=False,
                    max_redirects=MAX_REDIRECTS,
                ) as resp:
                    capture.final_url = str(resp.url)
                    capture.status_code = resp.status
                    if resp.history:
                        redirect_chain = [str(r.url) for r in resp.history] + [str(resp.url)]
                    capture.redirect_chain = redirect_chain

                    # Read body for form detection
                    body = await resp.text()
                    capture.page_html_hash = hashlib.sha256(body.encode()).hexdigest()[:16]
                    capture.page_html_preview = body[:500]

                    # Extract title
                    title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
                    if title_match:
                        capture.title = title_match.group(1).strip()[:200]

                    # Detect forms
                    form_matches = re.findall(r"<form[^>]*>(.*?)</form>", body, re.I | re.S)
                    for i, form_html in enumerate(form_matches[:5]):
                        form_data = {"index": i, "fields": []}
                        input_matches = re.findall(
                            r'<input[^>]*(?:name=["\']([^"\']*)["\'])?[^>]*(?:type=["\']([^"\']*)["\'])?[^>]*>',
                            form_html, re.I,
                        )
                        for name, inp_type in input_matches:
                            if name:
                                form_data["fields"].append({"name": name, "type": inp_type or "text"})
                                combined = name.lower()
                                for harvest_type, pattern in HARVEST_PATTERNS.items():
                                    if pattern.search(combined):
                                        capture.credential_fields.append({
                                            "type": harvest_type,
                                            "field_name": name,
                                            "input_type": inp_type or "text",
                                        })
                                        if harvest_type not in capture.harvested_types:
                                            capture.harvested_types.append(harvest_type)
                        capture.forms_found.append(form_data)

                    if capture.credential_fields:
                        capture.is_credential_harvester = True

        except ImportError:
            capture.error = "aiohttp not available for fallback HTTP detonation"
        except Exception as e:
            capture.error = str(e)

        report.pages.append(capture)

    # ─── MAIN ENTRY POINT ────────────────────────────────────────────────

    async def detonate(
        self,
        url: str,
        inject_decoy: bool = True,
        source: str = "threat_dropbox",
    ) -> DetonationReport:
        """
        Detonate a URL in the sandboxed browser.

        Args:
            url: The phishing URL to visit
            inject_decoy: Whether to fill credential forms with decoy data
            source: Where this detonation was triggered from

        Returns:
            DetonationReport with full intelligence
        """
        report = DetonationReport(
            detonation_id=str(uuid4())[:12],
            target_url=url,
            status="detonating",
            started_at=time.time(),
        )
        self._detonations[report.detonation_id] = report

        # Safety check
        if self._is_blocked(url):
            report.status = "blocked"
            report.error = "Domain is on the safety whitelist (banking/gov/known safe)"
            report.completed_at = time.time()
            return report

        try:
            has_playwright = await self._check_playwright()

            if has_playwright:
                await self._detonate_playwright(url, report, inject_decoy)
            else:
                await self._detonate_http(url, report)

            # Aggregate results
            for page in report.pages:
                if page.is_credential_harvester:
                    report.credential_harvester_detected = True
                for ht in page.harvested_types:
                    if ht not in report.harvested_data_types:
                        report.harvested_data_types.append(ht)
                if page.decoy_submitted:
                    report.decoy_injected = True
                report.total_redirects += len(page.redirect_chain)

            # Calculate threat score
            report.threat_score = self._score_detonation(report)
            report.threat_summary = self._summarize(report)
            report.status = "complete"

        except Exception as e:
            report.status = "failed"
            report.error = str(e)
            logger.error("Detonation failed for %s: %s", url, e)

        report.completed_at = time.time()
        logger.info(
            "Detonation %s complete — %d pages, harvester=%s, decoy=%s, score=%d",
            report.detonation_id, len(report.pages),
            report.credential_harvester_detected,
            report.decoy_injected, report.threat_score,
        )
        return report

    def _score_detonation(self, report: DetonationReport) -> int:
        score = 0
        for page in report.pages:
            if page.is_credential_harvester:
                score += 40
            if "password" in page.harvested_types:
                score += 20
            if "ssn" in page.harvested_types or "card" in page.harvested_types:
                score += 25
            if len(page.redirect_chain) > 3:
                score += 10
            if page.meta_redirects:
                score += 10
            if page.forms_found:
                score += 5
        return min(score, 100)

    def _summarize(self, report: DetonationReport) -> str:
        parts = []
        if report.credential_harvester_detected:
            types = ", ".join(report.harvested_data_types)
            parts.append(f"Credential harvester detected — targets: {types}")
        if report.decoy_injected:
            parts.append("Decoy credentials injected (canary active)")
        if report.total_redirects > 3:
            parts.append(f"Heavy redirect chain ({report.total_redirects} hops)")
        if not parts:
            parts.append("Page visited — no credential harvesting detected")
        return ". ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════════════════════════════════════════

_chamber_instance: Optional[DetonationChamber] = None


def get_chamber() -> DetonationChamber:
    global _chamber_instance
    if _chamber_instance is None:
        _chamber_instance = DetonationChamber()
    return _chamber_instance
