"""
Autonomous Controller — Phase 7b/7c/7e
Sovereign Sanctuary · Little Nate Infrastructure

The autonomous loop controller. Runs forever:
  - When health gates PASS → LEARN MODE (crystallize, ingest, maintain)
  - When health gates FAIL → FIX MODE (run playbooks, log failures)

Safety: The controller enforces a strict whitelist of autonomous actions.
Anything not on the whitelist requires Big Nate's approval.

File: backend/app/websocket/autonomous_controller.py
Lines: ~280
Dependencies: autonomous_health.py (Phase 7a)
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from .autonomous_health import AutonomousHealthGates, GateResult, HealthReport


# =============================================================================
# PHASE 7e: AUTONOMOUS RESTRICTIONS
# =============================================================================

class AutonomousRestrictions:
    """
    Whitelist of what the autonomous loop CAN and CANNOT do.
    Based on the 45-rule operating protocol.
    """

    # Actions the autonomous loop CAN perform without human approval
    ALLOWED_ACTIONS: Set[str] = {
        "restart_bridge",           # Restart the bridge process
        "clear_pycache",            # Clear __pycache__ directories
        "run_diagnostics",          # Read-only diagnostic commands
        "crystallize_sessions",     # Append-only crystal forging
        "ingest_feeds",             # Append-only RSS feed ingestion
        "run_test_suite",           # Execute test suites (read-only)
        "log_pending_fix",          # Write to pending_fixes.jsonl
        "send_health_alert",        # WebSocket health_status broadcast
        "tail_logs",                # Read log files
        "crystal_maintenance",      # Decay, promote, supersede crystals
        "refresh_r2_cache",         # Push workspace files to R2 (Phase 8)
    }

    # Actions that REQUIRE Big Nate's explicit approval
    FORBIDDEN_ACTIONS: Set[str] = {
        "deploy_build",             # Blue-Green-Orange promotion (Rule 18)
        "run_migration",            # Database schema changes (Rule 18)
        "git_commit",               # All git writes (Rule 41)
        "git_push",                 # All git writes (Rule 41)
        "pip_install",              # Package installation (Rule 10)
        "modify_formula",           # Nevedal constants (Rule 37)
        "modify_crystallizer",      # Crystal thresholds (Rule 43)
        "modify_security",          # HIPAA/Hive Defense (Rule 16)
        "write_production_file",    # Direct file writes to bridge_server.py etc. (Rule 1)
        "modify_auditor",           # Trust system changes (Rule 29)
    }

    @classmethod
    def is_allowed(cls, action: str) -> bool:
        """Check if an action is permitted in autonomous mode."""
        return action in cls.ALLOWED_ACTIONS

    @classmethod
    def check_or_raise(cls, action: str) -> None:
        """Raise if action is forbidden. Used as a safety gate."""
        if action in cls.FORBIDDEN_ACTIONS:
            raise AutonomousRestrictionViolation(
                f"Action '{action}' requires Big Nate's approval. "
                f"Logged to pending_fixes.jsonl for manual review."
            )
        if action not in cls.ALLOWED_ACTIONS:
            raise AutonomousRestrictionViolation(
                f"Action '{action}' is not in the autonomous whitelist. "
                f"Add to ALLOWED_ACTIONS or get manual approval."
            )


class AutonomousRestrictionViolation(Exception):
    """Raised when autonomous mode attempts a forbidden action."""
    pass


# =============================================================================
# PHASE 7b: FIX PLAYBOOKS
# =============================================================================

@dataclass
class PlaybookResult:
    """Result of running a fix playbook."""
    gate_name: str
    steps_run: int
    fixed: bool
    detail: str
    attempted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate": self.gate_name,
            "steps_run": self.steps_run,
            "fixed": self.fixed,
            "detail": self.detail,
            "attempted_at": self.attempted_at,
        }


class FixPlaybooks:
    """
    Automated diagnostic playbooks for each health gate failure.

    Each playbook is a sequence of read-only diagnostic steps.
    If the playbook can fix the issue (e.g., restart bridge), it does.
    If not, it logs to pending_fixes.jsonl for Big Nate's review.

    Key constraint: playbooks ONLY run commands from AutonomousRestrictions.ALLOWED_ACTIONS.
    """

    def __init__(self, project_root: Path, pending_fixes_path: Optional[Path] = None):
        self._root = project_root
        self._pending = pending_fixes_path or (
            project_root / "backend" / "app" / "websocket" / "data" / "pending_fixes.jsonl"
        )
        self._max_retries = 3

    async def run_playbook(self, failed_gate: GateResult) -> PlaybookResult:
        """Run the appropriate playbook for a failed gate."""
        handler = getattr(self, f"_fix_{failed_gate.name}", None)
        if not handler:
            return await self._log_unfixable(failed_gate, "No playbook for this gate")
        try:
            return await handler(failed_gate)
        except AutonomousRestrictionViolation as e:
            return await self._log_unfixable(failed_gate, str(e))
        except Exception as e:
            return await self._log_unfixable(failed_gate, f"Playbook exception: {e}")

    async def _log_unfixable(self, gate: GateResult, reason: str) -> PlaybookResult:
        """Log a failure that can't be auto-fixed to pending_fixes.jsonl."""
        AutonomousRestrictions.check_or_raise("log_pending_fix")
        entry = {
            "gate": gate.name,
            "detail": gate.detail,
            "reason": reason,
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending_review",
        }
        self._pending.parent.mkdir(parents=True, exist_ok=True)
        with open(self._pending, "a") as f:
            f.write(json.dumps(entry) + "\n")
        print(f">>> [FIX] Logged unfixable gate '{gate.name}' to pending_fixes.jsonl: {reason}")
        return PlaybookResult(
            gate_name=gate.name, steps_run=0, fixed=False,
            detail=f"Logged for review: {reason}"
        )

    # --- Individual Playbooks ---

    async def _fix_bridge_alive(self, gate: GateResult) -> PlaybookResult:
        """Restart the bridge process."""
        AutonomousRestrictions.check_or_raise("restart_bridge")
        # Check if bridge process exists
        try:
            result = subprocess.run(
                ["pgrep", "-f", "bridge_server.py"],
                capture_output=True, timeout=5,
            )
            if result.returncode != 0:
                # Bridge not running — attempt restart
                start_script = self._root / "start_bridge_local.sh"
                if start_script.exists():
                    subprocess.Popen(
                        ["bash", str(start_script)],
                        cwd=str(self._root),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    await asyncio.sleep(5)  # Wait for bridge to start
                    return PlaybookResult(
                        gate_name="bridge_alive", steps_run=2, fixed=True,
                        detail="Bridge restarted via start_bridge_local.sh"
                    )
            return await self._log_unfixable(
                gate, "Bridge process exists but not responding — possible hang"
            )
        except Exception as e:
            return await self._log_unfixable(gate, str(e))

    async def _fix_inference_available(self, gate: GateResult) -> PlaybookResult:
        """Check inference providers and log status."""
        AutonomousRestrictions.check_or_raise("run_diagnostics")
        steps = 0
        details = []

        # Check Ollama
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "--max-time", "3", "http://localhost:11434/api/tags",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            steps += 1
            if proc.returncode == 0:
                details.append("Ollama: responding")
                return PlaybookResult(
                    gate_name="inference_available", steps_run=steps, fixed=True,
                    detail="; ".join(details)
                )
            else:
                details.append("Ollama: not responding")
                # Try to start Ollama
                try:
                    subprocess.Popen(
                        ["ollama", "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    await asyncio.sleep(5)
                    details.append("Ollama: attempted restart")
                    steps += 1
                except FileNotFoundError:
                    details.append("Ollama: not installed")
        except Exception as e:
            details.append(f"Ollama check error: {e}")

        # Check Grok key
        grok_key = os.environ.get("NATE_CHAT_KEY", "")
        steps += 1
        if grok_key and len(grok_key) > 10:
            details.append(f"Grok: key present ({len(grok_key)} chars)")
            return PlaybookResult(
                gate_name="inference_available", steps_run=steps, fixed=True,
                detail="; ".join(details)
            )
        details.append("Grok: no key configured")

        return await self._log_unfixable(
            gate, f"Diagnostic: {'; '.join(details)}"
        )

    async def _fix_error_free(self, gate: GateResult) -> PlaybookResult:
        """Tail error logs and categorize."""
        AutonomousRestrictions.check_or_raise("tail_logs")
        log_path = self._root / "backend" / "app" / "websocket" / "data" / "bridge_errors.log"
        if not log_path.exists():
            return PlaybookResult(
                gate_name="error_free", steps_run=1, fixed=True,
                detail="Error log file does not exist (cleared)"
            )
        try:
            with open(log_path, "r") as f:
                lines = f.readlines()[-50:]
            errors = []
            for line in lines:
                try:
                    entry = json.loads(line)
                    if entry.get("level") == "ERROR":
                        errors.append(entry.get("message", "unknown")[:100])
                except json.JSONDecodeError:
                    continue
            if not errors:
                return PlaybookResult(
                    gate_name="error_free", steps_run=1, fixed=True,
                    detail="Recent errors have cleared"
                )
            # Categorize and log
            return await self._log_unfixable(
                gate, f"Recent errors ({len(errors)}): {errors[0]}..."
            )
        except Exception as e:
            return await self._log_unfixable(gate, str(e))

    async def _fix_db_pool(self, gate: GateResult) -> PlaybookResult:
        """Diagnose database connection pool issues."""
        AutonomousRestrictions.check_or_raise("run_diagnostics")
        return await self._log_unfixable(
            gate, f"DB pool degraded: {gate.detail}. Check PostgreSQL and connection limits."
        )

    async def _fix_redis_alive(self, gate: GateResult) -> PlaybookResult:
        """Diagnose Redis connectivity."""
        AutonomousRestrictions.check_or_raise("run_diagnostics")
        return await self._log_unfixable(
            gate, f"Redis unreachable: {gate.detail}. Check redis service."
        )

    async def _fix_disk_space(self, gate: GateResult) -> PlaybookResult:
        """Attempt to clear caches when disk is low."""
        AutonomousRestrictions.check_or_raise("clear_pycache")
        steps = 0
        freed_mb = 0
        # Clear __pycache__
        for cache_dir in (self._root / "backend").rglob("__pycache__"):
            try:
                size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())
                shutil.rmtree(cache_dir)
                freed_mb += size / (1024 * 1024)
                steps += 1
            except Exception:
                continue
        if freed_mb > 100:
            return PlaybookResult(
                gate_name="disk_space", steps_run=steps, fixed=True,
                detail=f"Cleared {freed_mb:.0f}MB of __pycache__"
            )
        return await self._log_unfixable(
            gate, f"Cleared {freed_mb:.0f}MB but still below threshold: {gate.detail}"
        )

    async def _fix_service_count(self, gate: GateResult) -> PlaybookResult:
        return await self._log_unfixable(gate, f"Service count issue: {gate.detail}")

    async def _fix_trust_score(self, gate: GateResult) -> PlaybookResult:
        return await self._log_unfixable(
            gate, f"Trust score below 100%: {gate.detail}. "
                  f"Per Rule 30: never reduce auditor checks to fake 100%."
        )

    async def _fix_crystal_pipeline(self, gate: GateResult) -> PlaybookResult:
        return await self._log_unfixable(gate, f"Crystal pipeline issue: {gate.detail}")

    async def _fix_migrations_current(self, gate: GateResult) -> PlaybookResult:
        return await self._log_unfixable(
            gate, f"Unapplied migrations: {gate.detail}. "
                  f"Per Rule 18: migrations require manual approval."
        )


# =============================================================================
# PHASE 7c: LEARN MODE
# =============================================================================

class LearnMode:
    """
    When all health gates pass, the autonomous loop enters LEARN MODE.
    Three activities in priority order, each with a time budget.

    1. Session crystallization — forge crystals from today's tool call logs
    2. Organic ingestion — fetch and process RSS feeds
    3. Crystal maintenance — run decay/promote/supersede rules
    """

    def __init__(
        self,
        crystallizer: Optional[Any] = None,
        project_root: Optional[Path] = None,
        time_budget_seconds: int = 600,  # 10 minutes per learn cycle
        r2_cache: Optional[Any] = None,
        db_pool: Optional[Any] = None,
    ):
        self._crystallizer = crystallizer
        self._root = project_root or Path(os.environ.get("CLI_PROJECT_ROOT", "."))
        self._budget = time_budget_seconds
        self._r2_cache = r2_cache
        self._db_pool = db_pool
        self._crystals_forged_today: int = 0
        self._last_learn_at: Optional[str] = None
        self._last_internet_search: float = 0.0
        self._internet_search_interval: float = float(
            os.environ.get("AUTONOMOUS_RESEARCH_INTERVAL_SEC", "10")
        )
        self._research_queries_per_cycle: int = max(
            1, int(os.environ.get("AUTONOMOUS_RESEARCH_QUERIES_PER_CYCLE", "1"))
        )
        self._research_query_spacing_sec: float = max(
            0.0, float(os.environ.get("AUTONOMOUS_RESEARCH_QUERY_SPACING_SEC", "10"))
        )
        self._evergreen_cursor: int = 0

    async def run_learn_cycle(self) -> Dict[str, Any]:
        """
        Run one learn cycle. Returns summary of what was done.
        Respects the time budget — stops when time runs out.
        """
        AutonomousRestrictions.check_or_raise("crystallize_sessions")
        start = time.monotonic()

        _count_before = 0
        if self._crystallizer and hasattr(self._crystallizer, "_local_store") and self._crystallizer._local_store:
            _count_before = self._crystallizer._local_store.get_crystal_count()

        results: Dict[str, Any] = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "activities": [],
        }

        # Priority 1: Session crystallization
        remaining = self._budget - (time.monotonic() - start)
        if remaining > 30:
            r = await self._crystallize_sessions(max_seconds=min(remaining * 0.5, 300))
            results["activities"].append(r)

        # Priority 2: Crystal maintenance
        remaining = self._budget - (time.monotonic() - start)
        if remaining > 30:
            r = await self._crystal_maintenance(max_seconds=min(remaining * 0.5, 180))
            results["activities"].append(r)

        # Priority 3: Organic ingestion (if time remains)
        remaining = self._budget - (time.monotonic() - start)
        if remaining > 60:
            r = await self._organic_ingestion(max_seconds=remaining)
            results["activities"].append(r)

        # Priority 4: Idle crystallization from R2 cached workspace files
        remaining = self._budget - (time.monotonic() - start)
        if remaining > 30 and self._r2_cache:
            r = await self._idle_crystallization(max_seconds=min(remaining, 120))
            results["activities"].append(r)

        # Priority 5: Autonomous internet search for knowledge gaps (high cadence)
        remaining = self._budget - (time.monotonic() - start)
        _since_last_search = time.monotonic() - self._last_internet_search
        if remaining > 30 and _since_last_search >= self._internet_search_interval:
            r = await self._internet_research(max_seconds=min(remaining * 0.5, 120))
            results["activities"].append(r)
            if r.get("queries_run", 0) > 0:
                self._last_internet_search = time.monotonic()

        # Priority 6: Forge crystals from buffered fragments.
        # The crystallizer's own _run_loop sleeps 30 min between cycles and only
        # synthesizes when its internal timer fires. Internet research fragments
        # bypass that harvest and land directly in the buffer. Without this
        # explicit trigger, fragments accumulate but never crystallize while the
        # bridge runs continuously.
        remaining = self._budget - (time.monotonic() - start)
        if (remaining > 60
                and self._crystallizer
                and hasattr(self._crystallizer, "_harvest_buffer")
                and hasattr(self._crystallizer, "_cluster_and_synthesize_cycle")
                and len(self._crystallizer._harvest_buffer) >= 2):
            try:
                from app.services.nate_memory_crystallizer import CLUSTER_MIN_ITEMS
                if len(self._crystallizer._harvest_buffer) >= CLUSTER_MIN_ITEMS:
                    self._crystallizer._synthesis_count_this_cycle = 0
                    await asyncio.wait_for(
                        self._crystallizer._cluster_and_synthesize_cycle(
                            datetime.now(timezone.utc)),
                        timeout=min(remaining, 120),
                    )
                    results["activities"].append({
                        "activity": "buffer_synthesis",
                        "buffer_before": len(self._crystallizer._harvest_buffer),
                    })
            except asyncio.TimeoutError:
                results["activities"].append({
                    "activity": "buffer_synthesis", "detail": "timeout",
                })
            except Exception as _synth_err:
                results["activities"].append({
                    "activity": "buffer_synthesis",
                    "detail": f"error: {_synth_err}",
                })

        # Priority 7: BLUE→GREEN crystal sync (when production DB is reachable)
        remaining = self._budget - (time.monotonic() - start)
        if remaining > 10 and self._crystallizer and hasattr(self._crystallizer, "_is_blue") and self._crystallizer._is_blue:
            r = await self._sync_blue_to_green()
            results["activities"].append(r)

        elapsed = time.monotonic() - start
        results["elapsed_seconds"] = round(elapsed, 1)

        # Report NEW crystals forged this cycle (delta), not total count.
        # In BLUE mode, local SQLite totals can drift from GREEN network-active
        # totals because GREEN dedup/archival uses global DB state. To keep the
        # autonomous status line in sync with `crystal_factory.py --status`,
        # prefer GREEN mac node totals when reachable.
        if self._crystallizer and hasattr(self._crystallizer, "_local_store") and self._crystallizer._local_store:
            _count_after = self._crystallizer._local_store.get_crystal_count()
            _green_total = await self._fetch_green_mac_total()
            results["crystals_forged"] = _count_after - _count_before
            results["local_total_crystals"] = _count_after
            results["green_total_crystals"] = _green_total
            results["total_crystals"] = _green_total if _green_total is not None else _count_after
            results["total_crystals_source"] = (
                "green_network_active" if _green_total is not None else "blue_local_store"
            )
            results["buffer_size"] = len(self._crystallizer._harvest_buffer)
        else:
            results["crystals_forged"] = self._crystals_forged_today
            results["total_crystals"] = self._crystals_forged_today

        self._last_learn_at = datetime.now(timezone.utc).isoformat()
        return results

    async def _fetch_green_mac_total(self) -> Optional[int]:
        """Fetch GREEN mac-blue active crystal total from production API.

        Returns None when unavailable so caller can gracefully fall back to
        local BLUE totals.
        """
        api_url = os.environ.get("PRODUCTION_API_URL", "").strip()
        api_token = os.environ.get("SKYEYE_AUDIT_TOKEN", "").strip()
        if not api_url or not api_token:
            return None

        status_url = f"{api_url.rstrip('/')}/api/nate-agent/admin/crystal-network/status"
        headers = {"Authorization": f"Bearer {api_token}"}
        try:
            import aiohttp

            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(status_url, headers=headers) as resp:
                    if resp.status != 200:
                        return None
                    payload = await resp.json()

            nodes = payload.get("nodes", []) if isinstance(payload, dict) else []
            for node in nodes:
                if node.get("node") == "mac-blue":
                    try:
                        return int(node.get("total", 0))
                    except Exception:
                        return None
        except Exception:
            return None
        return None

    async def _crystallize_sessions(self, max_seconds: float) -> Dict[str, Any]:
        """Review today's TENSION resolutions from tool call logs.

        Prefers PostgreSQL cli_tool_calls table when db_pool is available,
        falls back to the JSONL file for local development.
        """
        start = time.monotonic()
        forged = 0
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        tension_resolutions: List[Dict[str, Any]] = []

        # Source 1: PostgreSQL cli_tool_calls table (preferred)
        _db = self._db_pool or (self._crystallizer._db_pool if self._crystallizer and hasattr(self._crystallizer, "_db_pool") else None)
        if _db:
            try:
                async with _db.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT tool_name, tool_input::text, tool_output::text,
                               status, duration_ms, created_at
                        FROM cli_tool_calls
                        WHERE created_at::date = CURRENT_DATE
                          AND status = 'completed'
                        ORDER BY created_at DESC
                        LIMIT 50
                    """)
                    for row in rows:
                        if time.monotonic() - start > max_seconds:
                            break
                        try:
                            tool_input = json.loads(row["tool_input"]) if row["tool_input"] else {}
                        except (json.JSONDecodeError, TypeError):
                            tool_input = {}
                        tension_resolutions.append({
                            "tool": row["tool_name"],
                            "query": tool_input.get("command", tool_input.get("query", str(tool_input)[:300])),
                            "signal": "TENSION",
                            "success": True,
                            "date": today,
                        })
            except Exception as db_err:
                print(f">>> [CRYSTAL] DB query for tool calls failed: {db_err}")

        # Source 2: JSONL file fallback (local dev)
        if not tension_resolutions:
            log_path = (
                self._root / "backend" / "app" / "websocket" / "data" / "cli_tool_calls.jsonl"
            )
            if not log_path.exists():
                return {"activity": "session_crystallization", "forged": 0, "detail": "No tool call log (DB unavailable, no JSONL)"}

            try:
                with open(log_path, "r") as f:
                    for line in f:
                        if time.monotonic() - start > max_seconds:
                            break
                        try:
                            entry = json.loads(line)
                            if (entry.get("date", "")[:10] == today
                                    and entry.get("signal") in ("TENSION", "DEEP_TENSION")
                                    and entry.get("success")):
                                tension_resolutions.append(entry)
                        except (json.JSONDecodeError, KeyError):
                            continue
            except Exception as file_err:
                return {"activity": "session_crystallization", "error": str(file_err)}

        # Forge crystals from novel tension resolutions
        if self._crystallizer and hasattr(self._crystallizer, "_harvest_buffer"):
            for resolution in tension_resolutions[:20]:
                if time.monotonic() - start > max_seconds:
                    break
                fragment = {
                    "text": f"Tool: {resolution.get('tool')}, "
                            f"Query: {resolution.get('query', '')[:300]}",
                    "source": "session_crystallization",
                    "domain": "coding",
                    "scope": "global",
                    "created_at": datetime.now(timezone.utc),
                }
                self._crystallizer._harvest_buffer.append(fragment)
                forged += 1

        self._crystals_forged_today += forged
        return {
            "activity": "session_crystallization",
            "forged": forged,
            "tension_resolutions_found": len(tension_resolutions),
            "source": "postgresql" if _db else "jsonl",
        }

    async def _crystal_maintenance(self, max_seconds: float) -> Dict[str, Any]:
        """Run decay rules, check for supersession, promote high-recall crystals."""
        AutonomousRestrictions.check_or_raise("crystal_maintenance")
        if not self._crystallizer:
            return {"activity": "crystal_maintenance", "detail": "No crystallizer"}
        # If crystallizer has a maintenance method, call it
        if hasattr(self._crystallizer, "run_maintenance"):
            try:
                result = await asyncio.wait_for(
                    self._crystallizer.run_maintenance(),
                    timeout=max_seconds,
                )
                return {"activity": "crystal_maintenance", "result": str(result)}
            except asyncio.TimeoutError:
                return {"activity": "crystal_maintenance", "detail": "Timed out"}
            except Exception as e:
                return {"activity": "crystal_maintenance", "error": str(e)}
        return {"activity": "crystal_maintenance", "detail": "No maintenance method"}

    async def _organic_ingestion(self, max_seconds: float) -> Dict[str, Any]:
        """Fetch from RSS feeds and add to harvest buffer."""
        AutonomousRestrictions.check_or_raise("ingest_feeds")
        # This hooks into the existing CodeIntelligenceAgent RSS pipeline
        # if it's available. Otherwise, just log that it was attempted.
        if not self._crystallizer:
            return {"activity": "organic_ingestion", "detail": "No crystallizer for ingestion"}
        if hasattr(self._crystallizer, "run_organic_ingestion"):
            try:
                result = await asyncio.wait_for(
                    self._crystallizer.run_organic_ingestion(),
                    timeout=max_seconds,
                )
                return {"activity": "organic_ingestion", "result": str(result)}
            except asyncio.TimeoutError:
                return {"activity": "organic_ingestion", "detail": "Timed out"}
            except Exception as e:
                return {"activity": "organic_ingestion", "error": str(e)}
        return {"activity": "organic_ingestion", "detail": "No ingestion pipeline configured"}

    async def _idle_crystallization(self, max_seconds: float) -> Dict[str, Any]:
        """
        Scan R2-cached workspace files and forge crystals from novel patterns.
        Only runs when the R2 cache is configured and has cached files.
        """
        AutonomousRestrictions.check_or_raise("crystallize_sessions")
        if not self._r2_cache or not self._crystallizer:
            return {"activity": "idle_crystallization", "detail": "Missing r2_cache or crystallizer"}

        start = time.monotonic()
        forged = 0
        scanned = 0
        try:
            cache_stats = await self._r2_cache.stats()
            cached_count = cache_stats.get("files_cached", 0)
            if cached_count == 0:
                return {"activity": "idle_crystallization", "detail": "No cached files"}

            keys = await self._r2_cache.list_keys()
            interesting_exts = {".py", ".ts", ".dart", ".sql", ".md"}
            for key in keys:
                if time.monotonic() - start > max_seconds:
                    break
                ext = Path(key).suffix.lower()
                if ext not in interesting_exts:
                    continue

                content = await self._r2_cache.get_file(key)
                if not content or len(content) < 50:
                    continue
                scanned += 1

                if hasattr(self._crystallizer, "_harvest_buffer"):
                    fragment = {
                        "text": f"Workspace file {key} ({len(content)} chars): "
                                f"{content[:500]}",
                        "source": "idle_crystallization",
                        "domain": "coding",
                        "scope": "global",
                        "created_at": datetime.now(timezone.utc),
                    }
                    self._crystallizer._harvest_buffer.append(fragment)
                    forged += 1

            self._crystals_forged_today += forged
            return {
                "activity": "idle_crystallization",
                "scanned": scanned,
                "forged": forged,
                "cached_files": cached_count,
                "elapsed_seconds": round(time.monotonic() - start, 1),
            }
        except Exception as e:
            return {"activity": "idle_crystallization", "error": str(e)}

    async def _internet_research(self, max_seconds: float) -> Dict[str, Any]:
        """Autonomous internet search for knowledge gaps and trending topics.

        Queries DuckDuckGo/Bing via SecureSearchProxy for topics where
        crystals have low confidence or no coverage. Results feed into
        the crystallizer harvest buffer as web_research fragments.
        """
        AutonomousRestrictions.check_or_raise("ingest_feeds")
        start = time.monotonic()
        queries_run = 0
        fragments_added = 0

        if not self._crystallizer or not hasattr(self._crystallizer, "_harvest_buffer"):
            return {"activity": "internet_research", "detail": "No crystallizer"}

        research_queries: List[str] = []

        # Source 1: Low-confidence crystals needing research (BLUE or GREEN)
        _weak_crystals = []
        if self._crystallizer._local_store:
            try:
                _weak_crystals = self._crystallizer._local_store.get_low_confidence_crystals(limit=3)
            except Exception:
                pass
        else:
            _pool = self._db_pool or (
                self._crystallizer._db_pool
                if self._crystallizer and hasattr(self._crystallizer, "_db_pool")
                else None
            )
            if _pool:
                try:
                    async with _pool.acquire() as conn:
                        rows = await conn.fetch("""
                            SELECT crystal_text, domain, confidence
                            FROM nate_intelligence_crystals
                            WHERE scope != 'archived'
                              AND superseded_by IS NULL
                              AND confidence < 0.5
                            ORDER BY confidence ASC
                            LIMIT 3
                        """)
                        _weak_crystals = [dict(r) for r in rows]
                except Exception:
                    pass
        for c in _weak_crystals:
            text = c.get("crystal_text", "")[:100]
            domain = c.get("domain", "")
            if len(text) > 20:
                research_queries.append(
                    f"{text.split('.')[0]} latest research {domain}"
                )

        # Source 2: Evergreen queries rotating across all intelligence domains.
        # BLUE-exclusive queries — topics NOT covered by Hetzner's
        # DOMAIN_SEARCH_QUERIES or RSS feeds. Hetzner handles: standard
        # clinical, coding, defense, coaching, marketing, and research
        # search queries. BLUE focuses on deep Nevedal science, novel
        # therapeutic modalities, competitive intelligence, and edge
        # topics that require the local crystallizer's context.
        _evergreen = [
            # ── Nevedal formula deep science (8) ──
            "quantum decoherence biological systems neuroscience 2026",
            "interpersonal neural synchrony dyadic coherence fMRI",
            "emotional contagion group therapy coherence dynamics",
            "psychophysiological coherence HeartMath clinical validation",
            "allostasis interoceptive inference mental health model",
            "entropy emotional regulation predictive brain",
            "coupled oscillators interpersonal synchrony therapy",
            "field coherence group consciousness research",

            # ── BLUE-only clinical deep dives (10) ──
            "therapeutic rupture repair patterns real-time session analysis",
            "trauma-informed care somatic markers digital therapy platform",
            "family systems therapy coherence measurement AI-assisted",
            "motivational interviewing AI coaching outcomes meta-analysis",
            "reconsolidation window memory therapy timing fMRI research",
            "accelerated experiential dynamic psychotherapy mechanism",
            "affect regulation computational model limbic system",
            "therapist-client attunement physiological synchrony measure",
            "mentalizing based therapy digital adaptation research",
            "schema therapy mode model AI-assisted assessment",

            # ── Novel neuroscience (6) ──
            "embodied cognition emotion regulation computational model",
            "emotional granularity therapeutic outcomes precision",
            "mirror neuron empathy therapeutic relationship evidence",
            "predictive processing psychotherapy Bayesian brain",
            "social baseline theory co-regulation neural mechanisms",
            "network neuroscience psychopathology connectome treatment",

            # ── Computational psychiatry unique (6) ──
            "ecological momentary assessment AI prediction accuracy",
            "sentiment analysis psychotherapy process change detection",
            "digital therapeutic FDA clearance pathway 2026",
            "prescription digital therapeutics clinical evidence review",
            "AI therapist ethical framework informed consent",
            "machine learning suicide risk prediction validation prospective",

            # ── Biochemistry (BLUE-only) (5) ──
            "BDNF psychotherapy response prediction biomarker",
            "HPA axis dysregulation therapy normalization evidence",
            "inflammatory cytokines depression psychotherapy change",
            "telomere length psychological intervention longevity",
            "ketamine-assisted psychotherapy mechanism neural",

            # ── Platform engineering (BLUE-only — Hetzner has basics) (8) ──
            "Flutter state management Riverpod advanced patterns 2026",
            "BLE mesh networking mobile low-latency iOS Android",
            "OAuth2 PKCE token rotation WebSocket persistent session",
            "Cloudflare Workers Durable Objects state management",
            "asyncio Python structured concurrency taskgroup",
            "PostgreSQL advisory locks distributed coordination",
            "WebSocket binary protocol custom framing production",
            "Stripe Connect platform marketplace billing patterns",

            # ── Competitive intelligence (5) ──
            "therapy AI startup funding 2026",
            "digital mental health market size growth forecast",
            "Woebot Wysa Talkspace clinical outcomes comparison",
            "AI companion emotional support regulatory landscape",
            "venture capital mental health technology investment trends",

            # ── Patent / IP (BLUE-only — Hetzner now has basics) (4) ──
            "therapeutic AI memory architecture patent claims analysis",
            "emotional coherence biometric measurement patent landscape",
            "knowledge crystallization distributed AI patent prior art",
            "voice biomarker mental health screening patent WIPO 2025",

            # ── Predictive intelligence + cycle detection (6) ──
            "therapeutic prediction engine calibration longitudinal",
            "cycle detection FFT autocorrelation behavioral data",
            "temporal intelligence intervention timing optimization",
            "compound cycle convergence risk forecasting",
            "early warning relapse prediction sequence modeling",
            "predictive analytics explainability for mental health",

            # ── Operations unique (4) ──
            "postgresql replication streaming failover automatic",
            "redis sentinel high availability production patterns",
            "Cloudflare Tunnel zero-trust application access",
            "WireGuard VPN multi-node mesh production deployment",

            # ── Culture / voice integrity (4) ──
            "parasocial relationship AI companion long-term engagement",
            "authentic voice maintenance social media scaling",
            "therapeutic language consistency brand identity research",
            "silence pacing digital communication psychotherapy",
        ]
        # Deterministic round-robin rotation to guarantee all topics are visited.
        _n = len(_evergreen)
        if _n:
            self._evergreen_cursor = self._evergreen_cursor % _n
            for _ in range(min(self._research_queries_per_cycle, _n)):
                research_queries.append(_evergreen[self._evergreen_cursor])
                self._evergreen_cursor = (self._evergreen_cursor + 1) % _n

        try:
            from app.services.search_proxy import SecureSearchProxy
            proxy = SecureSearchProxy(data_dir="/tmp/nate_autonomous_search")
            if not proxy.is_available:
                print(">>> [INTERNET RESEARCH] No search backend (install ddgs or set BING_SEARCH_API_KEY)")
                return {"activity": "internet_research", "detail": "No search backend available"}
        except Exception as _proxy_err:
            print(f">>> [INTERNET RESEARCH] SecureSearchProxy unavailable: {_proxy_err}")
            return {"activity": "internet_research", "detail": f"SecureSearchProxy unavailable: {_proxy_err}"}

        for i, query in enumerate(research_queries[: self._research_queries_per_cycle]):
            if time.monotonic() - start > max_seconds:
                break
            if i > 0 and self._research_query_spacing_sec > 0:
                await asyncio.sleep(self._research_query_spacing_sec)
            try:
                result = await proxy.execute_search(query, coach_id="autonomous_learner")
                if result.get("success") and result.get("results"):
                    for sr in result["results"][:3]:
                        snippet = sr.get("snippet", "")
                        title = sr.get("title", "")
                        url = sr.get("url", "")
                        if len(snippet) > 30:
                            self._crystallizer._harvest_buffer.append({
                                "text": f"[Web Research: {title}]\n{snippet}\nSource: {url}",
                                "source": "internet_research",
                                "domain": self._classify_research_domain(query),
                                "scope": "global",
                                "created_at": datetime.now(timezone.utc),
                            })
                            fragments_added += 1
                    queries_run += 1
                elif result.get("error"):
                    print(f">>> [INTERNET RESEARCH] Query failed: {result['error'][:80]}")
            except Exception as _sq_err:
                print(f">>> [INTERNET RESEARCH] Search error: {_sq_err}")
                continue

        if queries_run or fragments_added:
            print(f">>> [INTERNET RESEARCH] {queries_run} queries, +{fragments_added} fragments ({round(time.monotonic() - start, 1)}s)")
        return {
            "activity": "internet_research",
            "queries_run": queries_run,
            "fragments_added": fragments_added,
            "elapsed_seconds": round(time.monotonic() - start, 1),
        }

    @staticmethod
    def _classify_research_domain(query: str) -> str:
        """Map a research query to the best crystal domain.

        Clinical and research domains feed directly into the Nevedal C_emo
        formula refinement — coherence science, voice biometrics, therapeutic
        alliance measurement, and affect computing all inform the formula's
        parameters (p_ent, T_tunnel, gamma_env, E_G_joint).
        """
        q = query.lower()
        if any(k in q for k in ("coherence", "decoherence", "vagal", "polyvagal",
                                 "neural synchrony", "heart rate variability",
                                 "biometric", "emotional regulation",
                                 "emotional contagion", "interpersonal",
                                 "interoception", "allostasis", "interoceptive")):
            return "clinical"
        if any(k in q for k in ("voice biomarker", "pitch variance", "speech prosody",
                                 "pause ratio", "speech rate", "vocal",
                                 "affective computing", "emotion recognition")):
            return "clinical"
        if any(k in q for k in ("therapy", "clinical", "emotional", "mental health",
                                 "counseling", "trauma", "reconsolidation",
                                 "therapeutic", "somatic", "family systems",
                                 "motivational interviewing", "aedp",
                                 "psychotherapy", "attachment theory",
                                 "ifs", "eft", "rupture repair",
                                 "digital therapeutic", "chatbot mental",
                                 "digital phenotyping", "ecological momentary",
                                 "sentiment analysis psycho", "conversational ai therap",
                                 "fda clearance", "prescription digital")):
            return "clinical"
        if any(k in q for k in ("neurotransmitter", "cortisol", "psychopharmacology",
                                 "pharmacogenomics", "neuroinflammation",
                                 "epigenetic", "microbiome", "gut-brain",
                                 "amygdala", "prefrontal", "neuroplasticity",
                                 "default mode network", "oxytocin",
                                 "mirror neuron", "embodied cognition",
                                 "emotional granularity", "fmri", "eeg")):
            return "research"
        if any(k in q for k in ("hipaa", "cve", "breach", "owasp",
                                 "security", "hardening", "oauth", "authentication",
                                 "encryption", "vulnerability", "pkce")):
            return "defense"
        if any(k in q for k in ("fastapi", "python", "flutter", "docker", "asyncio",
                                 "postgres", "redis", "cloudflare", "websocket",
                                 "git", "ble", "mesh", "nginx", "systemd",
                                 "deployment", "replication", "sentinel")):
            return "coding"
        if any(k in q for k in ("patent", "ip intelligence", "wipo", "prior art",
                                 "patent claims", "patent landscape")):
            return "research"
        if any(k in q for k in ("marketing", "funnel", "engagement", "social media",
                                 "content strategy", "seo", "pricing psychology",
                                 "user acquisition", "drip campaign",
                                 "app store optimization", "parasocial",
                                 "authentic voice", "brand identity",
                                 "competitive intelligence", "market size")):
            return "marketing"
        if any(k in q for k in ("coaching", "mentoring", "supervision", "dojo",
                                 "enterprise coaching", "employee wellness",
                                 "workplace mental health", "hr tech",
                                 "b2b saas", "staffing")):
            return "coaching"
        if any(k in q for k in ("research", "quantum", "study", "theory", "paper",
                                 "neuroscience", "retrieval augmented",
                                 "knowledge graph", "knowledge distillation",
                                 "continual learning", "mixture of experts",
                                 "vector database", "rlhf", "durable objects",
                                 "structured concurrency", "advisory locks",
                                 "predictive intelligence", "cycle detection",
                                 "therapeutic predictions", "forecast engine",
                                 "venture capital", "startup funding")):
            return "research"
        return "general"

    async def _sync_blue_to_green(self) -> Dict[str, Any]:
        """Push unsynced BLUE crystals to production GREEN PostgreSQL.

        Attempts to connect to the production database via the API.
        If the production server is reachable, calls sync_to_production().
        """
        if not self._crystallizer or not hasattr(self._crystallizer, "sync_to_production"):
            return {"activity": "blue_green_sync", "detail": "No crystallizer sync method"}

        if not self._crystallizer._local_store:
            return {"activity": "blue_green_sync", "detail": "No local store (already GREEN)"}

        unsynced_count = 0
        try:
            unsynced = self._crystallizer._local_store.get_unsynced_crystals(limit=1)
            unsynced_count = len(unsynced)
        except Exception:
            pass

        if unsynced_count == 0:
            return {"activity": "blue_green_sync", "detail": "All crystals synced"}

        # Try to establish a production DB connection
        try:
            import asyncpg
            _prod_url = os.environ.get("PRODUCTION_DATABASE_URL", "")
            if not _prod_url:
                return {"activity": "blue_green_sync", "detail": "PRODUCTION_DATABASE_URL not set",
                        "unsynced": unsynced_count}

            pool = await asyncpg.create_pool(_prod_url, min_size=1, max_size=2, timeout=10)
            try:
                result = await self._crystallizer.sync_to_production(pool)
                return {"activity": "blue_green_sync", **result}
            finally:
                await pool.close()
        except Exception as e:
            return {"activity": "blue_green_sync", "detail": f"Connection failed: {e}",
                    "unsynced": unsynced_count}


# =============================================================================
# MAIN AUTONOMOUS CONTROLLER
# =============================================================================

class AutonomousController:
    """
    The top-level autonomous loop controller.

    Orchestrates health gates, fix playbooks, and learn mode.
    Runs forever as a background task in bridge_server.py.

    Usage in bridge_server.py:
        controller = AutonomousController(
            health_gates=gates,
            project_root=project_root,
            crystallizer=crystallizer,
            broadcast_fn=my_ws_broadcast,
        )
        asyncio.create_task(controller.run())

    Status bar reads:
        controller.status_line()  →  "Health: 10/10 | LEARN | Crystals: 47 | $0.003"
    """

    def __init__(
        self,
        health_gates: AutonomousHealthGates,
        project_root: Optional[Path] = None,
        crystallizer: Optional[Any] = None,
        broadcast_fn: Optional[Callable[[Dict], Coroutine]] = None,
        health_interval: int = 10,
        learn_budget: int = 600,
        r2_cache: Optional[Any] = None,
        db_pool: Optional[Any] = None,
    ):
        self._gates = health_gates
        self._root = project_root or Path(os.environ.get("CLI_PROJECT_ROOT", "."))
        self._playbooks = FixPlaybooks(self._root)
        self._learn = LearnMode(
            crystallizer=crystallizer,
            project_root=self._root,
            time_budget_seconds=learn_budget,
            r2_cache=r2_cache,
            db_pool=db_pool,
        )
        self._broadcast = broadcast_fn
        self._interval = health_interval
        self._r2_cache = r2_cache
        self._running = False
        self._mode = "STARTING"
        self._last_report: Optional[HealthReport] = None
        self._cycles: int = 0
        self._total_crystals: int = 0
        self._fix_attempts: int = 0

    @property
    def mode(self) -> str:
        return self._mode

    def status_line(self) -> str:
        """One-line summary for status bar."""
        if self._last_report:
            health = self._last_report.summary_line()
            return f"{health} | Crystals: {self._total_crystals} | Cycles: {self._cycles}"
        return f"Health: ?/? | {self._mode}"

    async def run(self):
        """Main autonomous loop. Runs forever."""
        self._running = True
        print(">>> [AUTONOMOUS] Controller started")
        while self._running:
            try:
                self._cycles += 1

                # Step 1: Check health
                report = await self._gates.check_all()
                self._last_report = report
                self._mode = report.mode

                # Broadcast health status
                if self._broadcast:
                    try:
                        await self._broadcast({
                            "type": "health_status",
                            "mode": self._mode,
                            "cycles": self._cycles,
                            "total_crystals": self._total_crystals,
                            **report.to_dict(),
                        })
                    except Exception:
                        pass

                print(f">>> [AUTONOMOUS] Cycle {self._cycles}: {report.summary_line()}")

                if report.all_passed:
                    # Step 2a: LEARN MODE
                    self._mode = "LEARN"
                    try:
                        result = await self._learn.run_learn_cycle()
                        forged = result.get("crystals_forged", 0)
                        _total = result.get("total_crystals", 0)
                        self._total_crystals = _total
                        _cryst = self._learn._crystallizer
                        _mode_tag = "BLUE" if (_cryst and getattr(_cryst, "_is_blue", False)) else "GREEN"
                        print(f">>> [AUTONOMOUS] Learn cycle: "
                              f"+{forged} new, "
                              f"buffer={len(_cryst._harvest_buffer) if _cryst else 0}, "
                              f"total={_total} "
                              f"({_mode_tag}), "
                              f"{result.get('elapsed_seconds', 0)}s")
                    except Exception as e:
                        print(f"[!] Learn cycle error: {e}")
                else:
                    # Step 2b: FIX MODE
                    self._mode = "FIX"
                    for failed in report.failed_gates:
                        self._fix_attempts += 1
                        try:
                            result = await self._playbooks.run_playbook(failed)
                            print(f">>> [FIX] {failed.name}: "
                                  f"{'FIXED' if result.fixed else 'LOGGED'} — {result.detail}")
                        except Exception as e:
                            print(f"[!] Playbook error for {failed.name}: {e}")

            except Exception as e:
                print(f"[!] Autonomous controller error: {e}")
                self._mode = "ERROR"

            await asyncio.sleep(self._interval)

    def stop(self):
        """Stop the autonomous loop."""
        self._running = False
        print(">>> [AUTONOMOUS] Controller stopped")
