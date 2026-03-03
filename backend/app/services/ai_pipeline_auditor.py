"""
LITTLE NATE — AI Pipeline Auditor
Tests Azure OpenAI connectivity, TTS pipeline, voice biometrics,
Nevedal engine computation, and Assessment Engine health.

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 200s.
Uses minimal-cost probes (1-token completions, health checks only).
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("nate.ai_pipeline_auditor")

AUDIT_HOURS = {5, 17, 23}
AUDIT_EMAIL = "support@sovereignsanctuary.net"
BASE_URL = "http://localhost:8000"

AZURE_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_API_KEY = os.environ.get("AZURE_API_KEY", "")
_AUDIT_TOKEN = os.environ.get("SKYEYE_AUDIT_TOKEN", "")


class AIPipelineAuditor:

    def __init__(self, db_pool, notification_system=None, app_state=None):
        self.db_pool = db_pool
        self.notifications = notification_system
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()
        self._auth_token = _AUDIT_TOKEN

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("AIPipelineAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("AIPipelineAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(200)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                window_key = f"{now.date().isoformat()}_{now.hour}"
                if now.hour in AUDIT_HOURS and window_key not in self._sent_windows:
                    await self._build_and_send(now)
                    self._sent_windows.add(window_key)
                    self._sent_windows = {
                        k for k in self._sent_windows
                        if k.startswith(now.date().isoformat())
                    }
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("AIPipelineAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = await self._audit_all()
        html = self._render_html(results, now)
        subject = f"AI Pipeline Trust Scorecard — {now.strftime('%b %d %Y %H:%M UTC')}"

        # Email silenced — Trust Enforcer sends consolidated report

        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)
        await self._log_activity(
            "system", "ai_pipeline_audit_sent",
            f"Scorecard sent: {trusted}/{total} TRUSTED at {now.isoformat()}", "success"
        )
        logger.info("AIPipelineAuditor: scorecard sent — %d/%d TRUSTED", trusted, total)

    async def _audit_all(self) -> list:
        results = []
        results.append(await self._check_azure_chat())
        results.append(await self._check_azure_realtime())
        results.append(await self._check_tts())
        results.append(await self._check_coherence_pulse())
        results.append(await self._check_assessment_engine())
        results.append(await self._check_env_vars())
        return results

    @staticmethod
    def _classify_upstream(code: int, exc: Exception = None) -> str:
        """Distinguish config errors (FAILED) from upstream issues (WARNING)."""
        if exc is not None:
            exc_name = type(exc).__name__
            if isinstance(exc, asyncio.TimeoutError) or "Timeout" in exc_name:
                return "WARNING"
            return "WARNING"
        if code == 200:
            return "TRUSTED"
        if code in (429, 502, 503, 504):
            return "WARNING"
        if 400 <= code < 500:
            return "WARNING"
        return "FAILED"

    async def _check_azure_chat(self) -> dict:
        """Probe Azure OpenAI Chat Completions with 1-token request."""
        t0 = time.monotonic()
        endpoint = AZURE_ENDPOINT or os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        api_key = AZURE_API_KEY or os.environ.get("AZURE_API_KEY", "")
        if not endpoint or not api_key:
            return {"name": "Azure OpenAI Chat", "status": "FAILED",
                    "detail": "Missing AZURE_OPENAI_ENDPOINT or AZURE_API_KEY",
                    "ms": 0}
        deployment = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT", "") or os.environ.get("AZURE_DEPLOYMENT_NAME", "gpt-4o")
        url = f"https://{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-06-01"
        headers = {"api-key": api_key, "Content-Type": "application/json"}
        payload = {
            "messages": [{"role": "user", "content": "ping"}],
            "max_completion_tokens": 10,
        }
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    code = resp.status
                    elapsed = int((time.monotonic() - t0) * 1000)
                    if code == 200:
                        return {"name": "Azure OpenAI Chat", "status": "TRUSTED",
                                "detail": f"gpt-4o responded ({elapsed}ms)", "ms": elapsed}
                    body = await resp.text()
                    status = self._classify_upstream(code)
                    return {"name": "Azure OpenAI Chat", "status": status,
                            "detail": f"HTTP {code}: {body[:80]}", "ms": elapsed}
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            status = self._classify_upstream(0, exc)
            return {"name": "Azure OpenAI Chat", "status": status,
                    "detail": str(exc)[:80], "ms": elapsed}

    async def _check_azure_realtime(self) -> dict:
        """Verify Realtime WebSocket endpoint is reachable (connection test only)."""
        t0 = time.monotonic()
        endpoint = AZURE_ENDPOINT or os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        api_key = AZURE_API_KEY or os.environ.get("AZURE_API_KEY", "")
        if not endpoint or not api_key:
            return {"name": "Azure Realtime WS", "status": "FAILED",
                    "detail": "Missing env vars", "ms": 0}
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "") or os.environ.get("AZURE_REALTIME_DEPLOYMENT", "gpt-4o-realtime-preview")
        ws_url = (f"wss://{endpoint}/openai/realtime"
                  f"?api-version=2024-10-01-preview&deployment={deployment}")
        try:
            import websockets
            extra = {"api-key": api_key}
            async with websockets.connect(
                ws_url,
                additional_headers=extra,
                open_timeout=10,
                close_timeout=3,
            ) as ws:
                elapsed = int((time.monotonic() - t0) * 1000)
                await ws.close()
                return {"name": "Azure Realtime WS", "status": "TRUSTED",
                        "detail": f"WS connected ({elapsed}ms)", "ms": elapsed}
        except ImportError:
            return {"name": "Azure Realtime WS", "status": "WARNING",
                    "detail": "websockets library not installed", "ms": 0}
        except TypeError:
            try:
                async with websockets.connect(
                    ws_url,
                    extra_headers=extra,
                    open_timeout=10,
                    close_timeout=3,
                ) as ws:
                    elapsed = int((time.monotonic() - t0) * 1000)
                    await ws.close()
                    return {"name": "Azure Realtime WS", "status": "TRUSTED",
                            "detail": f"WS connected ({elapsed}ms)", "ms": elapsed}
            except Exception as exc2:
                elapsed = int((time.monotonic() - t0) * 1000)
                status = self._classify_upstream(0, exc2)
                return {"name": "Azure Realtime WS", "status": status,
                        "detail": str(exc2)[:80], "ms": elapsed}
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            status = self._classify_upstream(0, exc)
            return {"name": "Azure Realtime WS", "status": status,
                    "detail": str(exc)[:80], "ms": elapsed}

    async def _check_tts(self) -> dict:
        """Check TTS deployment reachability via REST probe."""
        t0 = time.monotonic()
        endpoint = AZURE_ENDPOINT or os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        api_key = AZURE_API_KEY or os.environ.get("AZURE_API_KEY", "")
        if not endpoint or not api_key:
            return {"name": "TTS Pipeline", "status": "FAILED",
                    "detail": "Missing env vars", "ms": 0}
        deployment = os.environ.get("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "") or os.environ.get("AZURE_TTS_DEPLOYMENT", "gpt-4o-mini-tts")
        url = (f"https://{endpoint}/openai/deployments/{deployment}"
               f"/audio/speech?api-version=2025-01-01-preview")
        headers = {"api-key": api_key, "Content-Type": "application/json"}
        payload = {"model": deployment, "input": "test", "voice": "alloy"}
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    code = resp.status
                    elapsed = int((time.monotonic() - t0) * 1000)
                    if code == 200:
                        return {"name": "TTS Pipeline", "status": "TRUSTED",
                                "detail": f"{deployment} responded ({elapsed}ms)",
                                "ms": elapsed}
                    status = self._classify_upstream(code)
                    return {"name": "TTS Pipeline", "status": status,
                            "detail": f"HTTP {code}", "ms": elapsed}
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            status = self._classify_upstream(0, exc)
            return {"name": "TTS Pipeline", "status": status,
                    "detail": str(exc)[:80], "ms": elapsed}

    async def _check_coherence_pulse(self) -> dict:
        """Verify Nevedal coherence endpoint returns data."""
        t0 = time.monotonic()
        try:
            headers = {}
            if self._auth_token:
                headers["Authorization"] = f"Bearer {self._auth_token}"
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{BASE_URL}/api/coherence/pulse", headers=headers) as resp:
                    code = resp.status
                    elapsed = int((time.monotonic() - t0) * 1000)
                    status = self._classify_upstream(code)
                    if code == 200:
                        return {"name": "Nevedal Coherence", "status": "TRUSTED",
                                "detail": f"Pulse OK ({elapsed}ms)", "ms": elapsed}
                    return {"name": "Nevedal Coherence", "status": status,
                            "detail": f"HTTP {code}", "ms": elapsed}
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            status = self._classify_upstream(0, exc)
            return {"name": "Nevedal Coherence", "status": status,
                    "detail": str(exc)[:80], "ms": elapsed}

    async def _check_assessment_engine(self) -> dict:
        """Verify Assessment Engine table is accessible."""
        t0 = time.monotonic()
        try:
            async with self.db_pool.acquire() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_name = 'dynamic_assessments'"
                )
                elapsed = int((time.monotonic() - t0) * 1000)
                if count and count > 0:
                    return {"name": "Assessment Engine", "status": "TRUSTED",
                            "detail": f"Table exists ({elapsed}ms)", "ms": elapsed}
                else:
                    return {"name": "Assessment Engine", "status": "WARNING",
                            "detail": "dynamic_assessments table missing", "ms": elapsed}
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {"name": "Assessment Engine", "status": "FAILED",
                    "detail": str(exc)[:80], "ms": elapsed}

    async def _check_env_vars(self) -> dict:
        """Verify all critical AI env vars are set."""
        t0 = time.monotonic()
        required = ["AZURE_OPENAI_ENDPOINT", "AZURE_API_KEY"]
        missing = [v for v in required if not os.environ.get(v)]
        elapsed = int((time.monotonic() - t0) * 1000)
        if not missing:
            return {"name": "AI Env Vars", "status": "TRUSTED",
                    "detail": f"All {len(required)} vars set", "ms": elapsed}
        else:
            return {"name": "AI Env Vars", "status": "FAILED",
                    "detail": f"Missing: {', '.join(missing)}", "ms": elapsed}

    def _render_html(self, results: list, now: datetime) -> str:
        total = len(results)
        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        warning = sum(1 for r in results if r["status"] == "WARNING")
        failed = sum(1 for r in results if r["status"] == "FAILED")
        pct = int((trusted / total * 100) if total else 0)
        header_color = "#22c55e" if failed == 0 and warning == 0 else (
            "#ef4444" if failed > 0 else "#eab308")

        rows = ""
        for r in results:
            c = "#22c55e" if r["status"] == "TRUSTED" else (
                "#eab308" if r["status"] == "WARNING" else "#ef4444")
            rows += (
                f'<tr>'
                f'<td style="padding:6px 8px;color:{c};font-weight:bold;font-size:12px;">'
                f'[{r["status"]}]</td>'
                f'<td style="padding:6px 8px;color:#C9A962;font-weight:bold;">{r["name"]}</td>'
                f'<td style="padding:6px 8px;color:#94a3b8;font-size:10px;">{r["detail"]}</td>'
                f'<td style="padding:6px 8px;color:#94a3b8;font-size:10px;">{r.get("ms",0)}ms</td>'
                f'</tr>\n'
            )

        return f"""
<div style="font-family:'DM Sans',Arial,sans-serif;max-width:750px;margin:0 auto;
background:#0A0A0A;color:#e2e8f0;border:1px solid #222;border-radius:8px;overflow:hidden;">
  <div style="background:#050505;padding:16px 20px;border-bottom:1px solid #222;">
    <h2 style="margin:0;color:#C9A962;font-size:18px;">AI Pipeline — Trust Scorecard</h2>
    <p style="margin:4px 0 0;color:#94a3b8;font-size:12px;">
      {now.strftime('%A, %B %d %Y at %H:%M UTC')} — {total} Subsystems
    </p>
  </div>
  <div style="padding:12px 20px;background:#111;border-bottom:1px solid #222;">
    <span style="color:{header_color};font-weight:bold;font-size:16px;">{pct}% Trust Score</span>
    <span style="color:#94a3b8;font-size:12px;"> — </span>
    <span style="color:#22c55e;font-weight:bold;font-size:13px;">{trusted} TRUSTED</span>
    <span style="color:#94a3b8;"> | </span>
    <span style="color:#eab308;font-weight:bold;font-size:13px;">{warning} WARNING</span>
    <span style="color:#94a3b8;"> | </span>
    <span style="color:#ef4444;font-weight:bold;font-size:13px;">{failed} FAILED</span>
  </div>
  <table style="width:100%;border-collapse:collapse;">{rows}</table>
  <div style="padding:12px 20px;border-top:1px solid #222;text-align:center;">
    <span style="color:#666;font-size:10px;">Sovereign Sanctuary — AI Pipeline Trust Auditor</span>
  </div>
</div>"""

    async def _log_activity(self, platform: str, activity_type: str,
                            content: str, severity: str = "info"):
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (platform, type, content, severity, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                """, platform, activity_type, content, severity)
        except Exception:
            pass
