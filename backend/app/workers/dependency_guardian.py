"""
SOVEREIGN SWARM — Dependency Guardian
Daily background audit of all dependency versions, Docker images, and API key health.
Reports findings to disk and pushes critical alerts to Sovereign Command.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp


SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"
SEVERITY_OK = "OK"

REPORT_DIR = Path(os.getenv("DATA_DIR", "/app/data")) / "guardian"
REQUIREMENTS_PATH = Path("/app/requirements.txt")
PACKAGE_JSON_PATH = Path("/app/admin_package.json")
PUBSPEC_PATH = Path("/app/mobile_pubspec.yaml")

_INTERVAL_DAILY = 86400  # 24 hours


def _parse_version(v: str) -> tuple:
    """Parse '1.2.3' into (1, 2, 3) for comparison."""
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) if parts else (0,)


def _classify_update(current: str, latest: str) -> str:
    cur = _parse_version(current)
    lat = _parse_version(latest)
    if lat <= cur:
        return SEVERITY_OK
    if len(cur) >= 1 and len(lat) >= 1 and lat[0] > cur[0]:
        return SEVERITY_WARNING
    return SEVERITY_INFO


def _parse_requirements_txt(path: Path) -> List[dict]:
    """Parse pip requirements.txt into [{name, constraint, version}]."""
    packages = []
    if not path.exists():
        return packages
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Match: package~=1.2.3, package>=1.2.3, package==1.2.3
        m = re.match(r"^([a-zA-Z0-9_-]+)(?:\[.*?\])?\s*(~=|>=|==|<=|!=|>|<)\s*(.+)$", line)
        if m:
            packages.append({
                "name": m.group(1).lower().replace("-", "-"),
                "raw_name": m.group(1),
                "constraint": m.group(2),
                "version": m.group(3).strip(),
            })
    return packages


def _parse_package_json(path: Path) -> List[dict]:
    """Parse package.json dependencies."""
    packages = []
    if not path.exists():
        return packages
    try:
        data = json.loads(path.read_text())
        for section in ("dependencies", "devDependencies"):
            for name, version in data.get(section, {}).items():
                clean = re.sub(r"[^0-9.]", "", version)
                packages.append({"name": name, "version": clean, "raw_version": version})
    except Exception:
        pass
    return packages


def _parse_pubspec_yaml(path: Path) -> List[dict]:
    """Parse pubspec.yaml dependencies (simple regex, no yaml lib needed)."""
    packages = []
    if not path.exists():
        return packages
    in_deps = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped in ("dependencies:", "dev_dependencies:"):
            in_deps = True
            continue
        if not line.startswith(" ") and not line.startswith("\t"):
            in_deps = False
            continue
        if in_deps and ":" in stripped:
            parts = stripped.split(":", 1)
            name = parts[0].strip()
            ver_raw = parts[1].strip()
            if name in ("flutter", "sdk"):
                continue
            clean = re.sub(r"[^0-9.]", "", ver_raw)
            if clean:
                packages.append({"name": name, "version": clean, "raw_version": ver_raw})
    return packages


class DependencyGuardian:
    """Audits all dependency surfaces and produces a structured report."""

    def __init__(self, settings: Any = None, notifications: Any = None):
        self._settings = settings
        self._notifications = notifications
        self._task: Optional[asyncio.Task] = None
        self._running = False
        REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        print(f">>> [GUARDIAN] Dependency Guardian started (daily at 03:00 UTC)")

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _run_loop(self) -> None:
        # Wait until 03:00 UTC for the first run, then every 24h
        await self._sleep_until_next_run()
        while self._running:
            try:
                report = await self.run_audit()
                print(f">>> [GUARDIAN] Audit complete: "
                      f"{report['summary']['critical']} critical, "
                      f"{report['summary']['warning']} warning, "
                      f"{report['summary']['info']} info")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f">>> [GUARDIAN] Audit error: {e}")
            await asyncio.sleep(_INTERVAL_DAILY)

    async def _sleep_until_next_run(self) -> None:
        """Sleep until the next 03:00 UTC."""
        now = datetime.utcnow()
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        # Cap first wait to 5 min for fresh deploys so we get an initial report quickly
        wait_seconds = min(wait_seconds, 300)
        print(f">>> [GUARDIAN] First audit in {int(wait_seconds)}s")
        await asyncio.sleep(wait_seconds)

    # ------------------------------------------------------------------
    # Main audit
    # ------------------------------------------------------------------
    async def run_audit(self) -> dict:
        """Run all checks and produce a report."""
        findings: List[dict] = []
        started = time.time()

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            checks = [
                ("python", self._check_python(session, findings)),
                ("node", self._check_node(session, findings)),
                ("flutter", self._check_flutter(session, findings)),
                ("docker", self._check_docker(session, findings)),
                ("api_keys", self._check_api_keys(session, findings)),
                ("playwright", self._check_playwright(session, findings)),
            ]
            for name, coro in checks:
                try:
                    await coro
                except Exception as e:
                    findings.append({
                        "category": name,
                        "package": f"[{name} checker]",
                        "severity": SEVERITY_WARNING,
                        "message": f"Checker failed: {e}",
                    })
                # Be polite to registries
                await asyncio.sleep(0.5)

        elapsed = round(time.time() - started, 1)
        summary = {
            "critical": sum(1 for f in findings if f["severity"] == SEVERITY_CRITICAL),
            "warning": sum(1 for f in findings if f["severity"] == SEVERITY_WARNING),
            "info": sum(1 for f in findings if f["severity"] == SEVERITY_INFO),
            "ok": sum(1 for f in findings if f["severity"] == SEVERITY_OK),
            "total": len(findings),
            "elapsed_seconds": elapsed,
        }

        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "summary": summary,
            "findings": findings,
        }

        # Save to disk
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        report_path = REPORT_DIR / f"report_{date_str}.json"
        report_path.write_text(json.dumps(report, indent=2, default=str))

        # Clean old reports (keep 30 days)
        self._cleanup_old_reports(30)

        # Push critical findings to admin notifications
        if summary["critical"] > 0 and self._notifications:
            crit_msgs = [f["message"] for f in findings if f["severity"] == SEVERITY_CRITICAL]
            try:
                await self._notifications.send(
                    recipient_id="ADMIN_DRNEVEDAL1_ID",
                    notification_type="warning",
                    title=f"Dependency Guardian: {summary['critical']} CRITICAL issue(s)",
                    message="\n".join(crit_msgs[:5]),
                    priority="HIGH",
                )
            except Exception:
                pass

        return report

    def _cleanup_old_reports(self, keep_days: int) -> None:
        cutoff = datetime.utcnow() - timedelta(days=keep_days)
        for f in REPORT_DIR.glob("report_*.json"):
            m = re.search(r"report_(\d{4}-\d{2}-\d{2})", f.name)
            if m:
                try:
                    d = datetime.strptime(m.group(1), "%Y-%m-%d")
                    if d < cutoff:
                        f.unlink()
                except ValueError:
                    pass

    def get_latest_report(self) -> Optional[dict]:
        """Load the most recent report from disk."""
        reports = sorted(REPORT_DIR.glob("report_*.json"), reverse=True)
        if not reports:
            return None
        try:
            return json.loads(reports[0].read_text())
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Checker: Python packages (PyPI)
    # ------------------------------------------------------------------
    async def _check_python(self, session: aiohttp.ClientSession,
                            findings: List[dict]) -> None:
        packages = _parse_requirements_txt(REQUIREMENTS_PATH)
        if not packages:
            # Fallback: try the path relative to the app
            alt = Path("/app/app/../requirements.txt").resolve()
            packages = _parse_requirements_txt(alt)

        for pkg in packages:
            try:
                url = f"https://pypi.org/pypi/{pkg['raw_name']}/json"
                async with session.get(url) as resp:
                    if resp.status == 404:
                        findings.append({
                            "category": "python",
                            "package": pkg["raw_name"],
                            "current": pkg["version"],
                            "latest": "NOT FOUND",
                            "severity": SEVERITY_WARNING,
                            "message": f"{pkg['raw_name']} not found on PyPI (renamed or deprecated?)",
                        })
                        continue
                    if resp.status != 200:
                        continue
                    data = await resp.json()

                latest = data.get("info", {}).get("version", "")
                severity = _classify_update(pkg["version"], latest)
                findings.append({
                    "category": "python",
                    "package": pkg["raw_name"],
                    "current": pkg["version"],
                    "latest": latest,
                    "severity": severity,
                    "message": (
                        f"{pkg['raw_name']}: {pkg['version']} -> {latest}"
                        if severity != SEVERITY_OK
                        else f"{pkg['raw_name']}: up to date ({latest})"
                    ),
                })
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue
            await asyncio.sleep(0.2)

    # ------------------------------------------------------------------
    # Checker: Node packages (npm)
    # ------------------------------------------------------------------
    async def _check_node(self, session: aiohttp.ClientSession,
                          findings: List[dict]) -> None:
        packages = _parse_package_json(PACKAGE_JSON_PATH)
        if not packages:
            # Try mounted path
            alt = Path("/app/admin_package.json")
            if not alt.exists():
                return
            packages = _parse_package_json(alt)

        for pkg in packages:
            try:
                url = f"https://registry.npmjs.org/{pkg['name']}/latest"
                async with session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()

                latest = data.get("version", "")
                severity = _classify_update(pkg["version"], latest)
                findings.append({
                    "category": "node",
                    "package": pkg["name"],
                    "current": pkg["version"],
                    "latest": latest,
                    "severity": severity,
                    "message": (
                        f"{pkg['name']}: {pkg['version']} -> {latest}"
                        if severity != SEVERITY_OK
                        else f"{pkg['name']}: up to date ({latest})"
                    ),
                })
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue
            await asyncio.sleep(0.2)

    # ------------------------------------------------------------------
    # Checker: Flutter packages (pub.dev)
    # ------------------------------------------------------------------
    async def _check_flutter(self, session: aiohttp.ClientSession,
                             findings: List[dict]) -> None:
        packages = _parse_pubspec_yaml(PUBSPEC_PATH)
        if not packages:
            alt = Path("/app/mobile_pubspec.yaml")
            if not alt.exists():
                return
            packages = _parse_pubspec_yaml(alt)

        for pkg in packages:
            try:
                url = f"https://pub.dev/api/packages/{pkg['name']}"
                async with session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()

                latest = data.get("latest", {}).get("version", "")
                severity = _classify_update(pkg["version"], latest)
                findings.append({
                    "category": "flutter",
                    "package": pkg["name"],
                    "current": pkg["version"],
                    "latest": latest,
                    "severity": severity,
                    "message": (
                        f"{pkg['name']}: {pkg['version']} -> {latest}"
                        if severity != SEVERITY_OK
                        else f"{pkg['name']}: up to date ({latest})"
                    ),
                })
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue
            await asyncio.sleep(0.2)

    # ------------------------------------------------------------------
    # Checker: Docker images (Docker Hub)
    # ------------------------------------------------------------------
    async def _check_docker(self, session: aiohttp.ClientSession,
                            findings: List[dict]) -> None:
        images = [
            {"image": "library/python", "current_tag": "3.11-slim", "label": "python:3.11-slim"},
            {"image": "library/node", "current_tag": "22-alpine", "label": "node:22-alpine"},
            {"image": "library/postgres", "current_tag": "15.10-alpine", "label": "postgres:15.10-alpine"},
            {"image": "library/redis", "current_tag": "7.4-alpine", "label": "redis:7.4-alpine"},
        ]

        for img in images:
            try:
                url = f"https://hub.docker.com/v2/repositories/{img['image']}/tags/?page_size=25&ordering=last_updated"
                async with session.get(url) as resp:
                    if resp.status != 200:
                        findings.append({
                            "category": "docker",
                            "package": img["label"],
                            "severity": SEVERITY_INFO,
                            "message": f"Could not check {img['label']} (HTTP {resp.status})",
                        })
                        continue
                    data = await resp.json()

                tags = [t["name"] for t in data.get("results", []) if t.get("name")]
                # Extract the major version prefix from our current tag
                prefix = img["current_tag"].split("-")[0]  # e.g. "3.11", "22", "15.10", "7.4"
                base_suffix = img["current_tag"].split("-", 1)[1] if "-" in img["current_tag"] else ""

                newer_tags = []
                for t in tags:
                    if base_suffix and not t.endswith(base_suffix):
                        continue
                    tag_ver = t.replace(f"-{base_suffix}", "") if base_suffix else t
                    if _parse_version(tag_ver) > _parse_version(prefix):
                        newer_tags.append(t)

                if newer_tags:
                    findings.append({
                        "category": "docker",
                        "package": img["label"],
                        "current": img["current_tag"],
                        "latest": newer_tags[0],
                        "severity": SEVERITY_INFO,
                        "message": f"{img['label']}: newer tag available: {newer_tags[0]}",
                    })
                else:
                    findings.append({
                        "category": "docker",
                        "package": img["label"],
                        "current": img["current_tag"],
                        "latest": img["current_tag"],
                        "severity": SEVERITY_OK,
                        "message": f"{img['label']}: up to date",
                    })
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue
            await asyncio.sleep(0.3)

    # ------------------------------------------------------------------
    # Checker: API key health
    # ------------------------------------------------------------------
    async def _check_api_keys(self, session: aiohttp.ClientSession,
                              findings: List[dict]) -> None:
        checks = [
            self._check_bing_key(session),
            self._check_azure_openai(session),
            self._check_stripe_key(session),
            self._check_sendgrid_key(session),
        ]
        for coro in checks:
            try:
                result = await coro
                if result:
                    findings.append(result)
            except Exception:
                pass

    async def _check_bing_key(self, session: aiohttp.ClientSession) -> Optional[dict]:
        key = os.getenv("BING_SEARCH_API_KEY", "")
        if not key:
            return {
                "category": "api_keys", "package": "Bing Search API",
                "severity": SEVERITY_INFO,
                "message": "Bing Search API key not configured (using DuckDuckGo fallback)",
            }
        try:
            async with session.get(
                "https://api.bing.microsoft.com/v7.0/search",
                headers={"Ocp-Apim-Subscription-Key": key},
                params={"q": "test", "count": 1},
            ) as resp:
                if resp.status == 401:
                    return {
                        "category": "api_keys", "package": "Bing Search API",
                        "severity": SEVERITY_CRITICAL,
                        "message": "Bing Search API key EXPIRED or INVALID (401). Search is degraded to DuckDuckGo.",
                    }
                if resp.status == 200:
                    return {
                        "category": "api_keys", "package": "Bing Search API",
                        "severity": SEVERITY_OK,
                        "message": "Bing Search API key valid",
                    }
                return {
                    "category": "api_keys", "package": "Bing Search API",
                    "severity": SEVERITY_WARNING,
                    "message": f"Bing Search API returned unexpected status {resp.status}",
                }
        except Exception as e:
            return {
                "category": "api_keys", "package": "Bing Search API",
                "severity": SEVERITY_WARNING,
                "message": f"Bing Search API check failed: {e}",
            }

    async def _check_azure_openai(self, session: aiohttp.ClientSession) -> Optional[dict]:
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        key = os.getenv("AZURE_API_KEY", "")
        if not endpoint or not key:
            return {
                "category": "api_keys", "package": "Azure OpenAI",
                "severity": SEVERITY_CRITICAL,
                "message": "Azure OpenAI endpoint or key not configured",
            }
        try:
            clean_endpoint = endpoint.rstrip("/")
            if not clean_endpoint.startswith("http"):
                clean_endpoint = f"https://{clean_endpoint}"
            url = f"{clean_endpoint}/openai/models?api-version=2024-10-01-preview"
            async with session.get(url, headers={"api-key": key}) as resp:
                if resp.status == 401:
                    return {
                        "category": "api_keys", "package": "Azure OpenAI",
                        "severity": SEVERITY_CRITICAL,
                        "message": "Azure OpenAI API key EXPIRED or INVALID (401)",
                    }
                if resp.status in (200, 403):
                    return {
                        "category": "api_keys", "package": "Azure OpenAI",
                        "severity": SEVERITY_OK,
                        "message": "Azure OpenAI API key valid",
                    }
                return {
                    "category": "api_keys", "package": "Azure OpenAI",
                    "severity": SEVERITY_INFO,
                    "message": f"Azure OpenAI returned status {resp.status}",
                }
        except Exception as e:
            return {
                "category": "api_keys", "package": "Azure OpenAI",
                "severity": SEVERITY_WARNING,
                "message": f"Azure OpenAI check failed: {e}",
            }

    async def _check_stripe_key(self, session: aiohttp.ClientSession) -> Optional[dict]:
        key = os.getenv("STRIPE_SECRET_KEY", "")
        if not key:
            return {
                "category": "api_keys", "package": "Stripe",
                "severity": SEVERITY_INFO,
                "message": "Stripe key not configured",
            }
        try:
            async with session.get(
                "https://api.stripe.com/v1/balance",
                headers={"Authorization": f"Bearer {key}"},
            ) as resp:
                if resp.status == 401:
                    return {
                        "category": "api_keys", "package": "Stripe",
                        "severity": SEVERITY_CRITICAL,
                        "message": "Stripe API key EXPIRED or INVALID (401). Billing is broken.",
                    }
                if resp.status == 200:
                    return {
                        "category": "api_keys", "package": "Stripe",
                        "severity": SEVERITY_OK,
                        "message": "Stripe API key valid",
                    }
        except Exception as e:
            return {
                "category": "api_keys", "package": "Stripe",
                "severity": SEVERITY_WARNING,
                "message": f"Stripe check failed: {e}",
            }

    async def _check_sendgrid_key(self, session: aiohttp.ClientSession) -> Optional[dict]:
        key = os.getenv("SENDGRID_API_KEY", "")
        if not key:
            return {
                "category": "api_keys", "package": "SendGrid",
                "severity": SEVERITY_INFO,
                "message": "SendGrid key not configured",
            }
        try:
            async with session.get(
                "https://api.sendgrid.com/v3/user/profile",
                headers={"Authorization": f"Bearer {key}"},
            ) as resp:
                if resp.status == 401:
                    return {
                        "category": "api_keys", "package": "SendGrid",
                        "severity": SEVERITY_CRITICAL,
                        "message": "SendGrid API key EXPIRED or INVALID (401). Email notifications are broken.",
                    }
                if resp.status == 200:
                    return {
                        "category": "api_keys", "package": "SendGrid",
                        "severity": SEVERITY_OK,
                        "message": "SendGrid API key valid",
                    }
        except Exception as e:
            return {
                "category": "api_keys", "package": "SendGrid",
                "severity": SEVERITY_WARNING,
                "message": f"SendGrid check failed: {e}",
            }

    # ------------------------------------------------------------------
    # Checker: Playwright / Chromium
    # ------------------------------------------------------------------
    async def _check_playwright(self, session: aiohttp.ClientSession,
                                findings: List[dict]) -> None:
        try:
            url = "https://api.github.com/repos/microsoft/playwright-python/releases/latest"
            async with session.get(url, headers={"Accept": "application/vnd.github.v3+json"}) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()

            latest_tag = data.get("tag_name", "").lstrip("v")
            current = "1.49.0"  # Pinned in Dockerfile.sandbox
            severity = _classify_update(current, latest_tag)
            findings.append({
                "category": "playwright",
                "package": "playwright",
                "current": current,
                "latest": latest_tag,
                "severity": severity,
                "message": (
                    f"Playwright: {current} -> {latest_tag}"
                    if severity != SEVERITY_OK
                    else f"Playwright: up to date ({latest_tag})"
                ),
            })
        except Exception:
            pass
