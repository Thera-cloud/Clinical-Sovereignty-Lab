#!/usr/bin/env python3
"""
Sovereign Load Test Suite
=========================
Multi-phase load testing for Little Nate with automatic ramp-to-failure.

Phases:
  1. Connection Scaling  — Open N WebSocket connections, find max
  2. Chat Burst          — Single-turn, increasing concurrency
  3. Chat Sustained      — Multi-turn with variable think times (2s/5s/10s)
  4. REST API Stress     — Authenticated endpoint hammering
  5. Rate Limit Discovery— Find exact thresholds per endpoint
  6. Ramp to Failure     — Combine all, increase until system breaks

Usage:
  # Provision test accounts first
  python load_test_full.py provision --count 300 --ssh root@68.183.168.75

  # Quick smoke test (5 users)
  python load_test_full.py smoke --target wss://api.sovereignsanctuary.net/ws

  # Run specific phase
  python load_test_full.py chat-burst --users 50 --target wss://api.sovereignsanctuary.net/ws
  python load_test_full.py chat-sustained --users 20 --turns 5

  # Full ramp-to-failure
  python load_test_full.py ramp --target wss://api.sovereignsanctuary.net/ws --max-users 300

  # REST API stress
  python load_test_full.py rest-stress --target https://api.sovereignsanctuary.net --users 50

  # All phases sequentially
  python load_test_full.py full --target wss://api.sovereignsanctuary.net/ws --max-users 300

  # Collect server metrics while test runs (separate terminal)
  python load_test_full.py monitor --ssh root@68.183.168.75 --duration 300

Requires: pip install aiohttp
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac as hmac_mod
import json
import os
import secrets
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import aiohttp
except ImportError:
    print("ERROR: pip install aiohttp")
    sys.exit(1)

LOAD_TEST_PASSWORD = "LoadTest2026!Nate"
PER_IP_WS_LIMIT = 200
AI_RATE_LIMIT_PER_MIN = 15
GENERAL_RATE_LIMIT_PER_MIN = 120

TEST_PROMPTS = [
    "I'm feeling a bit overwhelmed today. Can you help me sort through it?",
    "What are some simple ways to practice mindfulness when I'm stressed?",
    "I've been having trouble sleeping. Any suggestions?",
    "How can I set better boundaries with family without feeling guilty?",
    "I want to work on my self-talk. Where do I start?",
    "Sometimes I feel like I'm not making progress. Is that normal?",
    "What does it mean to sit with difficult emotions?",
    "I'm nervous about an upcoming conversation. How do I prepare?",
    "How can I tell the difference between anxiety and excitement?",
    "I struggle to ask for help. Any advice?",
    "What helps when you're stuck in rumination?",
    "How do I know when I need to take a break vs push through?",
    "I feel disconnected from my body sometimes. Is that common?",
    "What's a gentle way to start a difficult conversation?",
    "I'm working on being more present. What helps you stay grounded?",
    "How do you practice self-compassion when you've made a mistake?",
    "I notice I'm irritable lately. What might be underneath that?",
    "What are signs that you're emotionally drained?",
    "How can I support someone without fixing their problems?",
    "I want to understand my triggers better. Where do I begin?",
]

FOLLOW_UP_PROMPTS = [
    "Can you tell me more about that?",
    "That resonates. How would I apply that practically?",
    "I've tried something similar before but it didn't stick. Why might that be?",
    "What if I feel resistance when I try that?",
    "How does this connect to what we talked about before?",
    "That's helpful. What's a small first step I could take today?",
    "I'm noticing some emotion as you say that. Is that normal?",
    "Can you give me an example?",
    "What would you say to someone who feels stuck despite knowing this?",
    "How long does it usually take to see progress with this approach?",
]

REST_ENDPOINTS = [
    ("GET", "/health", None),
    ("GET", "/api/skyeye/pulse", "auth"),
    ("GET", "/api/client/health-check", "auth"),
    ("GET", "/api/token-lab/health", "auth"),
    ("GET", "/api/gkm/health", "auth"),
    ("GET", "/api/billing/plans", "auth"),
    ("GET", "/api/skyeye/engine-status", "auth"),
    ("GET", "/api/skyeye/overview", "auth"),
    ("GET", "/api/skyeye/activity?limit=10", "auth"),
    ("GET", "/api/marketing/results", "auth"),
    ("GET", "/api/coherence/pulse", "auth"),
    ("GET", "/api/hive-defense/v4/overview", "auth"),
    ("GET", "/api/trust-enforcer/status", "auth"),
    ("GET", "/api/assessments/health", "auth"),
]

RATE_LIMIT_ENDPOINTS = [
    ("POST", "/api/summon", {"prompt": "test", "context": "load_test"}, 10),
    ("POST", "/api/summon/internal", {"prompt": "test", "context": "load_test"}, 30),
    ("GET", "/health", None, 999),
    ("GET", "/api/skyeye/pulse", None, 120),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"{salt}:{hashed.hex()}"


def pct(vals: list, p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (k - f) * (s[c] - s[f])


def fmt_t(s: Optional[float]) -> str:
    if s is None or s < 0:
        return "N/A"
    return f"{s * 1000:.0f}ms" if s < 1 else f"{s:.2f}s"


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def banner(title: str, width: int = 70):
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


def separator(width: int = 70):
    print(f"{'─' * width}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TurnMetrics:
    turn_num: int = 0
    first_chunk_s: Optional[float] = None
    full_response_s: Optional[float] = None
    response_chars: int = 0
    success: bool = False
    error: Optional[str] = None


@dataclass
class UserSession:
    user_id: str = ""
    connected: bool = False
    login_ok: bool = False
    turns_attempted: int = 0
    turns_completed: int = 0
    turns: List[TurnMetrics] = field(default_factory=list)
    connection_time_s: Optional[float] = None
    login_time_s: Optional[float] = None
    total_session_s: Optional[float] = None
    error: Optional[str] = None
    auth_token: Optional[str] = None


@dataclass
class PhaseResult:
    phase: str = ""
    users: int = 0
    turns_per_user: int = 0
    total_attempted: int = 0
    total_completed: int = 0
    total_errors: int = 0
    wall_time_s: float = 0
    throughput_rps: float = 0
    connect_p50: float = 0
    connect_p95: float = 0
    login_p50: float = 0
    login_p95: float = 0
    ttft_p50: float = 0
    ttft_p95: float = 0
    ttft_p99: float = 0
    response_p50: float = 0
    response_p95: float = 0
    response_p99: float = 0
    response_max: float = 0
    avg_response_chars: float = 0
    error_types: Dict[str, int] = field(default_factory=dict)
    per_turn_p50: Dict[int, float] = field(default_factory=dict)
    degraded: bool = False
    failed: bool = False
    notes: List[str] = field(default_factory=list)


@dataclass
class RESTResult:
    endpoint: str = ""
    method: str = "GET"
    status_code: int = 0
    latency_s: float = 0
    success: bool = False
    error: Optional[str] = None


@dataclass
class ServerSnapshot:
    timestamp: str = ""
    cpu_percent: float = 0
    mem_used_mb: float = 0
    mem_total_mb: float = 0
    backend_cpu: float = 0
    backend_mem_mb: float = 0
    bridge_cpu: float = 0
    bridge_mem_mb: float = 0
    redis_mem_mb: float = 0
    redis_keys: int = 0
    pg_connections: int = 0
    ws_connections: int = 0


# ---------------------------------------------------------------------------
# Account Provisioning
# ---------------------------------------------------------------------------

def provision_accounts(ssh_target: str, count: int):
    banner(f"PROVISIONING {count} LOAD TEST ACCOUNTS")
    pw_hash = hash_password(LOAD_TEST_PASSWORD)
    print(f"  Password hash: {pw_hash[:20]}...")

    sql_lines = []
    for i in range(1, count + 1):
        username = f"loadtest_{i:03d}"
        hw_id = f"LOADTEST_{i:03d}_ID"
        name = f"Load Test {i}"
        email = f"loadtest{i}@test.sovereignsanctuary.net"
        profile = json.dumps({
            "name": name,
            "email": email,
            "tier": "STANDARD",
            "token_balance": 999999,
            "coach_id": "COACH_COACHN_ID",
            "assigned_coach": "CoachN",
            "assigned_coach_id": "COACH_COACHN_ID",
            "consent_version": "v13.0_2026",
            "is_load_test": True,
        }).replace("'", "''")
        sql_lines.append(
            f"INSERT INTO users (username, hardware_id, role, name, email, "
            f"password_hash, subscription_status, tier, profile_data) "
            f"VALUES ('{username}', '{hw_id}', 'CLIENT', '{name}', '{email}', "
            f"'{pw_hash}', 'ACTIVE', 'STANDARD', '{profile}'::jsonb) "
            f"ON CONFLICT (username) DO UPDATE SET "
            f"password_hash = EXCLUDED.password_hash, "
            f"name = EXCLUDED.name, "
            f"profile_data = EXCLUDED.profile_data;"
        )

    full_sql = "\n".join(sql_lines)
    print(f"  Generated {len(sql_lines)} INSERT statements")

    sql_file = "/tmp/loadtest_accounts.sql"
    with open(sql_file, "w") as f:
        f.write(full_sql)

    print(f"  SQL written to {sql_file}")
    print(f"  Deploying to {ssh_target}...")

    try:
        subprocess.run(
            ["scp", sql_file, f"{ssh_target}:/tmp/loadtest_accounts.sql"],
            check=True, capture_output=True, text=True,
        )
        result = subprocess.run(
            ["ssh", ssh_target,
             "docker exec -i nate_postgres psql -U nate_admin -d little_nate < /tmp/loadtest_accounts.sql"],
            check=True, capture_output=True, text=True, timeout=60,
        )
        inserts = result.stdout.count("INSERT")
        updates = result.stdout.count("UPDATE")
        print(f"  Result: {inserts} inserted, {updates} updated")

        result2 = subprocess.run(
            ["ssh", ssh_target,
             "docker exec nate_postgres psql -U nate_admin -d little_nate -t -c "
             "\"SELECT COUNT(*) FROM users WHERE username LIKE 'loadtest_%'\""],
            check=True, capture_output=True, text=True, timeout=15,
        )
        total = result2.stdout.strip()
        print(f"  Total load test accounts in DB: {total}")
        print(f"\n  Restarting bridge to reload registry cache...")

        subprocess.run(
            ["ssh", ssh_target, "docker restart nate_bridge"],
            check=True, capture_output=True, text=True, timeout=30,
        )
        print(f"  Bridge restarting (15-30s to become ready)")
        print(f"  PROVISIONING COMPLETE")

    except subprocess.CalledProcessError as e:
        print(f"  ERROR: {e}")
        if e.stderr:
            print(f"  stderr: {e.stderr[:500]}")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print(f"  ERROR: SSH command timed out")
        sys.exit(1)


def cleanup_accounts(ssh_target: str):
    banner("CLEANING UP LOAD TEST ACCOUNTS")
    try:
        result = subprocess.run(
            ["ssh", ssh_target,
             "docker exec nate_postgres psql -U nate_admin -d little_nate -c "
             "\"DELETE FROM users WHERE username LIKE 'loadtest_%' AND "
             "profile_data->>'is_load_test' = 'true'\""],
            check=True, capture_output=True, text=True, timeout=30,
        )
        print(f"  {result.stdout.strip()}")
        subprocess.run(
            ["ssh", ssh_target, "docker restart nate_bridge"],
            check=True, capture_output=True, text=True, timeout=30,
        )
        print("  Bridge restarting to clear cache")
    except Exception as e:
        print(f"  ERROR: {e}")


# ---------------------------------------------------------------------------
# Server Metrics Monitor
# ---------------------------------------------------------------------------

async def collect_server_metrics(ssh_target: str) -> Optional[ServerSnapshot]:
    snap = ServerSnapshot(timestamp=ts())
    try:
        cmd = (
            "echo '---CPU---' && "
            "top -bn1 | grep 'Cpu(s)' | head -1 && "
            "echo '---MEM---' && "
            "free -m | grep Mem && "
            "echo '---DOCKER---' && "
            "docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' 2>/dev/null && "
            "echo '---REDIS---' && "
            "docker exec nate_redis redis-cli -a $(docker exec nate_redis printenv REDIS_PASSWORD 2>/dev/null || echo '') INFO memory 2>/dev/null | grep used_memory_human && "
            "docker exec nate_redis redis-cli -a $(docker exec nate_redis printenv REDIS_PASSWORD 2>/dev/null || echo '') DBSIZE 2>/dev/null && "
            "echo '---PG---' && "
            "docker exec nate_postgres psql -U nate_admin -d little_nate -t -c "
            "\"SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'active'\" && "
            "echo '---BRIDGE---' && "
            "docker logs nate_bridge --tail 1 2>&1 | grep -oP 'sockets_after=\\K[0-9]+' || echo '0'"
        )
        proc = await asyncio.create_subprocess_exec(
            "ssh", ssh_target, cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        output = stdout.decode()

        for line in output.split("\n"):
            line = line.strip()
            if "Cpu(s)" in line:
                parts = line.split(",")
                idle = [p for p in parts if "id" in p]
                if idle:
                    snap.cpu_percent = 100 - float(idle[0].strip().split()[0])
            elif line.startswith("Mem:"):
                parts = line.split()
                snap.mem_total_mb = float(parts[1])
                snap.mem_used_mb = float(parts[2])
            elif "nate_backend" in line:
                parts = line.split()
                snap.backend_cpu = float(parts[1].replace("%", ""))
                mem_str = parts[2].split("/")[0]
                if "GiB" in mem_str:
                    snap.backend_mem_mb = float(mem_str.replace("GiB", "")) * 1024
                elif "MiB" in mem_str:
                    snap.backend_mem_mb = float(mem_str.replace("MiB", ""))
            elif "nate_bridge" in line:
                parts = line.split()
                snap.bridge_cpu = float(parts[1].replace("%", ""))
                mem_str = parts[2].split("/")[0]
                if "GiB" in mem_str:
                    snap.bridge_mem_mb = float(mem_str.replace("GiB", "")) * 1024
                elif "MiB" in mem_str:
                    snap.bridge_mem_mb = float(mem_str.replace("MiB", ""))
            elif "used_memory_human" in line:
                val = line.split(":")[1].strip().rstrip("\r")
                if "M" in val:
                    snap.redis_mem_mb = float(val.replace("M", ""))
                elif "K" in val:
                    snap.redis_mem_mb = float(val.replace("K", "")) / 1024
                elif "G" in val:
                    snap.redis_mem_mb = float(val.replace("G", "")) * 1024
            elif line.startswith("db0:keys="):
                snap.redis_keys = int(line.split("=")[1].split(",")[0])
            elif line.strip().isdigit() and snap.pg_connections == 0:
                snap.pg_connections = int(line.strip())

        return snap
    except Exception:
        return None


def print_server_snapshot(s: ServerSnapshot):
    print(
        f"  [{s.timestamp}] CPU={s.cpu_percent:.0f}% "
        f"RAM={s.mem_used_mb:.0f}/{s.mem_total_mb:.0f}MB "
        f"Backend={s.backend_cpu:.0f}%/{s.backend_mem_mb:.0f}MB "
        f"Bridge={s.bridge_cpu:.0f}%/{s.bridge_mem_mb:.0f}MB "
        f"Redis={s.redis_mem_mb:.1f}MB "
        f"PG_active={s.pg_connections}"
    )


# ---------------------------------------------------------------------------
# WebSocket Chat Test Core
# ---------------------------------------------------------------------------

async def ws_chat_session(
    session: aiohttp.ClientSession,
    idx: int,
    target: str,
    username: str,
    password: str,
    role: str,
    prompts: List[str],
    sem: asyncio.Semaphore,
    metrics: UserSession,
    turns: int = 1,
    think_time: float = 5.0,
    first_chunk_timeout: float = 120.0,
):
    metrics.user_id = username
    ws = None
    session_start = time.monotonic()

    t0 = time.monotonic()
    try:
        ws = await session.ws_connect(target, heartbeat=30, receive_timeout=180)
        metrics.connection_time_s = time.monotonic() - t0
        metrics.connected = True
    except Exception as e:
        metrics.error = f"connect: {type(e).__name__}: {e}"
        return

    try:
        msg = await asyncio.wait_for(ws.receive(), timeout=10)
        data = json.loads(msg.data) if msg.type == aiohttp.WSMsgType.TEXT else {}
        if data.get("type") != "connected":
            metrics.error = f"handshake: {data.get('type')}"
            await ws.close()
            return

        t1 = time.monotonic()
        await ws.send_str(json.dumps({
            "type": "login_request",
            "username": username,
            "password": password,
            "expected_role": role,
            "hardware_id": f"LOADTEST_{idx:03d}_ID",
        }))

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(ws.receive(), timeout=10)
            if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                metrics.error = "closed during login"
                return
            data = json.loads(msg.data) if msg.type == aiohttp.WSMsgType.TEXT else {}
            if data.get("type") == "login_success":
                metrics.login_ok = True
                metrics.login_time_s = time.monotonic() - t1
                metrics.auth_token = data.get("token")
                break
            if data.get("type") in ("login_failed", "account_frozen", "account_banned"):
                metrics.error = f"{data['type']}: {data.get('message', '?')}"
                await ws.close()
                return

        if not metrics.login_ok:
            metrics.error = "login timeout"
            await ws.close()
            return

        # Drain post-login messages
        await asyncio.sleep(0.3)
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=0.2)
                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    break
            except asyncio.TimeoutError:
                break

        for turn_num in range(turns):
            metrics.turns_attempted += 1
            tm = TurnMetrics(turn_num=turn_num)

            prompt = prompts[idx % len(prompts)] if turn_num == 0 else \
                FOLLOW_UP_PROMPTS[(idx + turn_num) % len(FOLLOW_UP_PROMPTS)]

            t_start = time.monotonic()
            async with sem:
                await ws.send_str(json.dumps({
                    "type": "nate_query",
                    "text": prompt,
                    "nate_query": prompt,
                }))

            first_chunk = None
            last_chunk_time = None
            accumulated_len = 0
            resp_deadline = time.monotonic() + 300

            while time.monotonic() < resp_deadline:
                try:
                    wait = 5.0 if first_chunk is not None else first_chunk_timeout
                    msg = await asyncio.wait_for(ws.receive(), timeout=wait)
                except asyncio.TimeoutError:
                    if first_chunk is not None:
                        tm.success = True
                        tm.full_response_s = (last_chunk_time or time.monotonic()) - t_start
                        tm.response_chars = accumulated_len
                        break
                    tm.error = f"TTFT timeout ({first_chunk_timeout:.0f}s)"
                    break

                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    if first_chunk is not None:
                        tm.success = True
                        tm.full_response_s = (last_chunk_time or time.monotonic()) - t_start
                        tm.response_chars = accumulated_len
                    else:
                        tm.error = "ws closed before response"
                    break

                data = json.loads(msg.data) if msg.type == aiohttp.WSMsgType.TEXT else {}
                mt = data.get("type", "")

                if mt in ("nate_response", "ai_response"):
                    now = time.monotonic()
                    if first_chunk is None:
                        first_chunk = now - t_start
                        tm.first_chunk_s = first_chunk
                    last_chunk_time = now
                    chunk_text = data.get("text", data.get("response", ""))
                    accumulated_len = len(chunk_text)
                    tm.success = True
                    tm.full_response_s = now - t_start
                    tm.response_chars = accumulated_len
                elif mt == "error":
                    em = data.get("message", "server error")
                    tm.error = em
                    break

            metrics.turns.append(tm)
            if tm.success:
                metrics.turns_completed += 1
            else:
                if not metrics.error:
                    metrics.error = f"turn {turn_num}: {tm.error}"
                break

            if turn_num < turns - 1:
                await asyncio.sleep(think_time)

        metrics.total_session_s = time.monotonic() - session_start

    except asyncio.TimeoutError:
        metrics.error = "timeout"
    except asyncio.CancelledError:
        metrics.error = "cancelled"
    except Exception as e:
        metrics.error = f"{type(e).__name__}: {e}"
    finally:
        if ws:
            try:
                await ws.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Phase Executors
# ---------------------------------------------------------------------------

async def run_ws_phase(
    target: str,
    user_count: int,
    turns: int,
    think_time: float,
    ramp_time: float,
    max_rate: int,
    phase_name: str,
    first_chunk_timeout: float = 120.0,
    ssh_target: Optional[str] = None,
) -> PhaseResult:
    connector = aiohttp.TCPConnector(limit=0, limit_per_host=0)
    timeout = aiohttp.ClientTimeout(total=900, connect=30)
    all_m: List[UserSession] = [UserSession() for _ in range(user_count)]
    sem = asyncio.Semaphore(max_rate)

    banner(f"PHASE: {phase_name}  |  {user_count} users × {turns} turns = {user_count * turns} requests")
    print(f"  Target:       {target}")
    print(f"  Think time:   {think_time}s")
    print(f"  Max rate:     {max_rate} msg/s")
    print(f"  Ramp time:    {ramp_time}s")
    print(f"  TTFT timeout: {first_chunk_timeout}s")
    separator()

    server_snapshots: List[ServerSnapshot] = []

    async def monitor_loop():
        if not ssh_target:
            return
        while True:
            snap = await collect_server_metrics(ssh_target)
            if snap:
                server_snapshots.append(snap)
                print_server_snapshot(snap)
            await asyncio.sleep(10)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        monitor_task = asyncio.create_task(monitor_loop()) if ssh_target else None
        start = time.monotonic()
        ramp_per = ramp_time / max(1, user_count)

        tasks = []
        for i in range(user_count):
            if i > 0:
                await asyncio.sleep(ramp_per)
            username = f"loadtest_{i + 1:03d}"
            t = asyncio.create_task(ws_chat_session(
                session, i + 1, target, username, LOAD_TEST_PASSWORD,
                "CLIENT", TEST_PROMPTS, sem, all_m[i], turns, think_time,
                first_chunk_timeout,
            ))
            tasks.append(t)

            done_count = sum(1 for m in all_m if m.login_ok or m.error)
            connected_count = sum(1 for m in all_m if m.connected)
            if (i + 1) % 10 == 0:
                print(f"  [{ts()}] Launched {i + 1}/{user_count} users "
                      f"({connected_count} connected, {done_count} finished)")

        print(f"  [{ts()}] All {user_count} users launched. Waiting for completion...")
        await asyncio.gather(*tasks, return_exceptions=True)
        wall = time.monotonic() - start

        if monitor_task:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

    result = _compute_phase_result(all_m, phase_name, user_count, turns, wall)
    _print_phase_result(result, server_snapshots)
    return result


def _compute_phase_result(
    all_m: List[UserSession], phase: str, users: int, turns: int, wall: float,
) -> PhaseResult:
    r = PhaseResult(phase=phase, users=users, turns_per_user=turns, wall_time_s=round(wall, 1))

    r.total_attempted = sum(m.turns_attempted for m in all_m)
    r.total_completed = sum(m.turns_completed for m in all_m)
    r.total_errors = sum(1 for m in all_m if m.error)
    r.throughput_rps = round(r.total_completed / wall, 2) if wall > 0 else 0

    conn_t = [m.connection_time_s for m in all_m if m.connection_time_s is not None]
    login_t = [m.login_time_s for m in all_m if m.login_time_s is not None]
    resp_t, first_t, resp_len_list = [], [], []

    for m in all_m:
        for tm in m.turns:
            if tm.full_response_s is not None:
                resp_t.append(tm.full_response_s)
            if tm.first_chunk_s is not None:
                first_t.append(tm.first_chunk_s)
            if tm.success:
                resp_len_list.append(tm.response_chars)

    if conn_t:
        r.connect_p50, r.connect_p95 = pct(conn_t, 50), pct(conn_t, 95)
    if login_t:
        r.login_p50, r.login_p95 = pct(login_t, 50), pct(login_t, 95)
    if first_t:
        r.ttft_p50, r.ttft_p95, r.ttft_p99 = pct(first_t, 50), pct(first_t, 95), pct(first_t, 99)
    if resp_t:
        r.response_p50 = pct(resp_t, 50)
        r.response_p95 = pct(resp_t, 95)
        r.response_p99 = pct(resp_t, 99)
        r.response_max = max(resp_t)
    if resp_len_list:
        r.avg_response_chars = statistics.mean(resp_len_list)

    error_counts: Dict[str, int] = {}
    for m in all_m:
        if m.error:
            key = m.error.split(":")[0] if ":" in m.error else m.error
            error_counts[key] = error_counts.get(key, 0) + 1
    r.error_types = error_counts

    if turns > 1:
        per_turn: Dict[int, List[float]] = {}
        for m in all_m:
            for tm in m.turns:
                if tm.full_response_s is not None:
                    per_turn.setdefault(tm.turn_num, []).append(tm.full_response_s)
        r.per_turn_p50 = {tn: pct(vals, 50) for tn, vals in per_turn.items()}

    success_rate = r.total_completed / max(r.total_attempted, 1)
    r.degraded = success_rate < 0.9 or (r.response_p95 > 30 and resp_t)
    r.failed = success_rate < 0.5 or r.total_completed == 0

    return r


def _print_phase_result(r: PhaseResult, snapshots: List[ServerSnapshot] = None):
    separator()
    status = "FAILED" if r.failed else ("DEGRADED" if r.degraded else "HEALTHY")
    status_icon = "X" if r.failed else ("!" if r.degraded else "OK")
    print(f"  Status:           [{status_icon}] {status}")
    print(f"  Connected:        {r.users - r.total_errors}/{r.users}")
    print(f"  Turns completed:  {r.total_completed}/{r.total_attempted}")
    print(f"  Errors:           {r.total_errors}/{r.users}")
    print(f"  Wall time:        {r.wall_time_s}s")
    print(f"  Throughput:       {r.throughput_rps} responses/sec")
    separator()
    print(f"  Connect  p50={fmt_t(r.connect_p50)}  p95={fmt_t(r.connect_p95)}")
    print(f"  Login    p50={fmt_t(r.login_p50)}  p95={fmt_t(r.login_p95)}")
    print(f"  TTFT     p50={fmt_t(r.ttft_p50)}  p95={fmt_t(r.ttft_p95)}  p99={fmt_t(r.ttft_p99)}")
    print(f"  Response p50={fmt_t(r.response_p50)}  p95={fmt_t(r.response_p95)}  "
          f"p99={fmt_t(r.response_p99)}  MAX={fmt_t(r.response_max)}")
    if r.avg_response_chars > 0:
        print(f"  Avg response:     {r.avg_response_chars:.0f} chars")

    if r.per_turn_p50:
        separator()
        print("  Per-turn latency:")
        for tn in sorted(r.per_turn_p50.keys()):
            label = "initial" if tn == 0 else f"follow-up {tn}"
            print(f"    Turn {tn} ({label}): p50={fmt_t(r.per_turn_p50[tn])}")

    if r.error_types:
        separator()
        print("  Error breakdown:")
        for err, count in sorted(r.error_types.items(), key=lambda x: -x[1])[:8]:
            print(f"    {err}: {count}")

    if snapshots:
        separator()
        print("  Peak server metrics:")
        peak_cpu = max(s.cpu_percent for s in snapshots) if snapshots else 0
        peak_backend = max(s.backend_cpu for s in snapshots) if snapshots else 0
        peak_bridge = max(s.bridge_cpu for s in snapshots) if snapshots else 0
        peak_mem = max(s.mem_used_mb for s in snapshots) if snapshots else 0
        print(f"    Peak CPU: {peak_cpu:.0f}% (backend={peak_backend:.0f}%, bridge={peak_bridge:.0f}%)")
        print(f"    Peak RAM: {peak_mem:.0f}MB")


# ---------------------------------------------------------------------------
# REST API Stress Test
# ---------------------------------------------------------------------------

async def rest_stress_test(
    api_url: str, auth_token: str, concurrency: int, duration: float,
) -> List[RESTResult]:
    banner(f"REST API STRESS TEST | {concurrency} concurrent | {duration}s duration")
    print(f"  Target: {api_url}")
    print(f"  Endpoints: {len(REST_ENDPOINTS)}")
    separator()

    results: List[RESTResult] = []
    connector = aiohttp.TCPConnector(limit=concurrency)
    timeout = aiohttp.ClientTimeout(total=30)
    sem = asyncio.Semaphore(concurrency)
    stop_event = asyncio.Event()

    async def hit_endpoint(method: str, path: str, auth: Optional[str]):
        headers = {}
        if auth == "auth" and auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        url = f"{api_url}{path}"
        r = RESTResult(endpoint=path, method=method)
        t0 = time.monotonic()
        try:
            async with sem:
                async with aiohttp.ClientSession(connector_owner=False, connector=connector, timeout=timeout) as s:
                    if method == "GET":
                        async with s.get(url, headers=headers) as resp:
                            r.status_code = resp.status
                            await resp.read()
                    elif method == "POST":
                        async with s.post(url, headers=headers, json={}) as resp:
                            r.status_code = resp.status
                            await resp.read()
            r.latency_s = time.monotonic() - t0
            r.success = r.status_code in (200, 400, 404, 422)
        except Exception as e:
            r.latency_s = time.monotonic() - t0
            r.error = f"{type(e).__name__}: {e}"
        return r

    start = time.monotonic()
    cycle = 0
    while time.monotonic() - start < duration and not stop_event.is_set():
        cycle += 1
        tasks = [hit_endpoint(m, p, a) for m, p, a in REST_ENDPOINTS]
        batch = await asyncio.gather(*tasks, return_exceptions=True)
        for item in batch:
            if isinstance(item, RESTResult):
                results.append(item)

        if cycle % 5 == 0:
            ok = sum(1 for r in results if r.success)
            avg_lat = statistics.mean([r.latency_s for r in results[-len(REST_ENDPOINTS):]]) \
                if results else 0
            print(f"  [{ts()}] Cycle {cycle}: {ok}/{len(results)} ok, "
                  f"avg latency {avg_lat * 1000:.0f}ms")

    connector.close()

    separator()
    total = len(results)
    ok = sum(1 for r in results if r.success)
    errs = sum(1 for r in results if r.error)
    status_dist: Dict[int, int] = {}
    for r in results:
        status_dist[r.status_code] = status_dist.get(r.status_code, 0) + 1

    lats = [r.latency_s for r in results if r.latency_s > 0]

    print(f"  Total requests:   {total}")
    print(f"  Successes:        {ok}")
    print(f"  Errors:           {errs}")
    print(f"  Status codes:     {dict(sorted(status_dist.items()))}")
    if lats:
        print(f"  Latency  p50={fmt_t(pct(lats, 50))}  p95={fmt_t(pct(lats, 95))}  "
              f"MAX={fmt_t(max(lats))}")
    print(f"  Throughput:       {total / (time.monotonic() - start):.1f} req/s")

    separator()
    print("  Per-endpoint breakdown:")
    by_ep: Dict[str, List[RESTResult]] = {}
    for r in results:
        by_ep.setdefault(r.endpoint, []).append(r)
    for ep in sorted(by_ep.keys()):
        ep_results = by_ep[ep]
        ep_ok = sum(1 for r in ep_results if r.success)
        ep_lats = [r.latency_s for r in ep_results if r.latency_s > 0]
        ep_p50 = fmt_t(pct(ep_lats, 50)) if ep_lats else "N/A"
        ep_p95 = fmt_t(pct(ep_lats, 95)) if ep_lats else "N/A"
        statuses = set(r.status_code for r in ep_results)
        print(f"    {ep:50s} {ep_ok}/{len(ep_results)} ok  p50={ep_p50}  p95={ep_p95}  "
              f"codes={statuses}")

    return results


# ---------------------------------------------------------------------------
# Rate Limit Discovery
# ---------------------------------------------------------------------------

async def discover_rate_limits(api_url: str, auth_token: str):
    banner("RATE LIMIT DISCOVERY")
    print(f"  Target: {api_url}")
    separator()

    for method, path, body, expected_limit in RATE_LIMIT_ENDPOINTS:
        url = f"{api_url}{path}"
        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        print(f"\n  Testing {method} {path} (expected limit: {expected_limit}/min)")
        count_ok = 0
        count_429 = 0
        count_other = 0
        start = time.monotonic()

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for i in range(expected_limit + 20):
                try:
                    if method == "GET":
                        async with session.get(url, headers=headers) as resp:
                            code = resp.status
                    else:
                        async with session.post(url, headers=headers, json=body or {}) as resp:
                            code = resp.status

                    if code == 429:
                        count_429 += 1
                        if count_429 == 1:
                            print(f"    First 429 at request #{i + 1} "
                                  f"({time.monotonic() - start:.1f}s elapsed)")
                    elif code < 500:
                        count_ok += 1
                    else:
                        count_other += 1

                except Exception as e:
                    count_other += 1

                await asyncio.sleep(0.05)

        elapsed = time.monotonic() - start
        effective_rate = (count_ok + count_429) / elapsed if elapsed > 0 else 0
        print(f"    Results: {count_ok} ok, {count_429} rate-limited, {count_other} other")
        print(f"    Effective limit: ~{count_ok} requests in {elapsed:.1f}s "
              f"({effective_rate:.1f} req/s)")
        if count_429 > 0:
            print(f"    Rate limit CONFIRMED at ~{count_ok} requests")
        else:
            print(f"    No rate limit hit (sent {count_ok + count_429 + count_other} requests)")


# ---------------------------------------------------------------------------
# Ramp to Failure
# ---------------------------------------------------------------------------

async def ramp_to_failure(
    target: str, max_users: int, ssh_target: Optional[str] = None,
):
    banner(f"RAMP TO FAILURE | max={max_users} users")
    print(f"  Strategy: Double users each phase until failure or max reached")
    print(f"  Phases: 1 → 5 → 10 → 25 → 50 → 100 → 150 → 200 → 250 → 300")
    separator()

    ramp_steps = [1, 5, 10, 25, 50, 100, 150, 200, 250, 300]
    ramp_steps = [s for s in ramp_steps if s <= max_users]

    all_results: List[PhaseResult] = []

    for step_users in ramp_steps:
        max_rate = max(3, min(step_users, 15))
        ramp_time = max(5, step_users * 0.3)
        first_chunk_timeout = 120.0

        result = await run_ws_phase(
            target=target,
            user_count=step_users,
            turns=1,
            think_time=0,
            ramp_time=ramp_time,
            max_rate=max_rate,
            phase_name=f"RAMP {step_users} users",
            first_chunk_timeout=first_chunk_timeout,
            ssh_target=ssh_target,
        )
        all_results.append(result)

        if result.failed:
            print(f"\n  FAILURE DETECTED at {step_users} users. Stopping ramp.")
            break

        if result.degraded:
            print(f"\n  DEGRADATION at {step_users} users. Continuing to find failure point...")

        # Cool down between phases
        if step_users < max_users:
            cooldown = max(10, step_users * 0.2)
            print(f"\n  Cooling down {cooldown:.0f}s before next phase...")
            await asyncio.sleep(cooldown)

    # Summary
    banner("RAMP SUMMARY")
    print(f"  {'Users':>6} | {'Completed':>10} | {'Throughput':>12} | {'TTFT p50':>10} | "
          f"{'Resp p95':>10} | {'Errors':>6} | Status")
    separator()
    for r in all_results:
        status = "FAILED" if r.failed else ("DEGRADED" if r.degraded else "OK")
        print(f"  {r.users:>6} | {r.total_completed:>10} | {r.throughput_rps:>10.2f}/s | "
              f"{fmt_t(r.ttft_p50):>10} | {fmt_t(r.response_p95):>10} | "
              f"{r.total_errors:>6} | {status}")

    # Determine max healthy capacity
    max_healthy = 0
    for r in all_results:
        if not r.failed and not r.degraded:
            max_healthy = r.users

    separator()
    print(f"  MAX HEALTHY CAPACITY: {max_healthy} concurrent users")
    last = all_results[-1] if all_results else None
    if last:
        print(f"  MAX TESTED: {last.users} users "
              f"({'FAILED' if last.failed else 'DEGRADED' if last.degraded else 'OK'})")
        if last.throughput_rps > 0:
            print(f"  PEAK THROUGHPUT: {max(r.throughput_rps for r in all_results):.2f} responses/sec")

    return all_results


# ---------------------------------------------------------------------------
# Full Test Suite
# ---------------------------------------------------------------------------

async def full_test(target: str, max_users: int, ssh_target: Optional[str] = None):
    api_url = target.replace("wss://", "https://").replace("ws://", "http://").replace("/ws", "")

    banner("SOVEREIGN LOAD TEST SUITE — FULL RUN")
    print(f"  WS Target: {target}")
    print(f"  API URL:   {api_url}")
    print(f"  Max users: {max_users}")
    print(f"  SSH:       {ssh_target or 'N/A (no server metrics)'}")
    separator()

    if ssh_target:
        print("\n  Pre-test server snapshot:")
        snap = await collect_server_metrics(ssh_target)
        if snap:
            print_server_snapshot(snap)

    all_phases: List[PhaseResult] = []

    # Phase 1: Smoke — 1 user, 1 turn
    r = await run_ws_phase(target, 1, 1, 0, 1, 5, "SMOKE (1 user)", ssh_target=ssh_target)
    all_phases.append(r)
    if r.failed:
        print("\n  SMOKE TEST FAILED. System not responding. Aborting.")
        return all_phases

    auth_token = None
    connector = aiohttp.TCPConnector(limit=1)
    timeout_cfg = aiohttp.ClientTimeout(total=30, connect=10)
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout_cfg) as s:
            ws = await s.ws_connect(target, heartbeat=30, receive_timeout=30)
            await asyncio.wait_for(ws.receive(), timeout=10)
            await ws.send_str(json.dumps({
                "type": "login_request",
                "username": "loadtest_001",
                "password": LOAD_TEST_PASSWORD,
                "expected_role": "CLIENT",
                "hardware_id": "LOADTEST_001_ID",
            }))
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                msg = await asyncio.wait_for(ws.receive(), timeout=10)
                data = json.loads(msg.data) if msg.type == aiohttp.WSMsgType.TEXT else {}
                if data.get("type") == "login_success":
                    auth_token = data.get("token")
                    break
            await ws.close()
    except Exception as e:
        print(f"  Could not obtain auth token: {e}")

    # Phase 2: Chat Burst — 10 users, 1 turn
    r = await run_ws_phase(target, 10, 1, 0, 5, 10, "CHAT BURST (10 users)", ssh_target=ssh_target)
    all_phases.append(r)

    # Phase 3: Chat Sustained — 10 users, 3 turns, 5s think
    r = await run_ws_phase(target, 10, 3, 5.0, 5, 10, "SUSTAINED (10u × 3t)", ssh_target=ssh_target)
    all_phases.append(r)

    # Phase 4: REST API Stress
    if auth_token:
        await rest_stress_test(api_url, auth_token, concurrency=20, duration=30)
    else:
        print("\n  Skipping REST stress (no auth token)")

    # Phase 5: Rate Limit Discovery
    if auth_token:
        await discover_rate_limits(api_url, auth_token)

    # Phase 6: Scaling ramp
    ramp_results = await ramp_to_failure(target, max_users, ssh_target)
    all_phases.extend(ramp_results)

    if ssh_target:
        print("\n  Post-test server snapshot:")
        snap = await collect_server_metrics(ssh_target)
        if snap:
            print_server_snapshot(snap)

    # Final Summary
    banner("FINAL SUMMARY")
    print(f"  {'Phase':>30} | {'Users':>5} | {'OK':>5} | {'Throughput':>10} | "
          f"{'TTFT p50':>9} | {'Resp p95':>9} | Status")
    separator()
    for r in all_phases:
        status = "FAIL" if r.failed else ("DEGRADE" if r.degraded else "OK")
        print(f"  {r.phase:>30} | {r.users:>5} | "
              f"{r.total_completed:>5} | {r.throughput_rps:>8.2f}/s | "
              f"{fmt_t(r.ttft_p50):>9} | {fmt_t(r.response_p95):>9} | {status}")

    return all_phases


# ---------------------------------------------------------------------------
# Server Metrics Monitor (standalone)
# ---------------------------------------------------------------------------

async def monitor_server(ssh_target: str, duration: float, interval: float = 5):
    banner(f"SERVER MONITOR | {ssh_target} | {duration}s")
    start = time.monotonic()
    snapshots = []
    while time.monotonic() - start < duration:
        snap = await collect_server_metrics(ssh_target)
        if snap:
            snapshots.append(snap)
            print_server_snapshot(snap)
        await asyncio.sleep(interval)

    if snapshots:
        separator()
        print(f"  Peak CPU: {max(s.cpu_percent for s in snapshots):.0f}%")
        print(f"  Peak Backend CPU: {max(s.backend_cpu for s in snapshots):.0f}%")
        print(f"  Peak Bridge CPU: {max(s.bridge_cpu for s in snapshots):.0f}%")
        print(f"  Peak RAM: {max(s.mem_used_mb for s in snapshots):.0f}/"
              f"{snapshots[0].mem_total_mb:.0f}MB")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sovereign Load Test Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # provision
    p_prov = sub.add_parser("provision", help="Create load test accounts on server")
    p_prov.add_argument("--count", type=int, default=300)
    p_prov.add_argument("--ssh", required=True, help="SSH target (e.g., root@68.183.168.75)")

    # cleanup
    p_clean = sub.add_parser("cleanup", help="Remove load test accounts")
    p_clean.add_argument("--ssh", required=True)

    # smoke
    p_smoke = sub.add_parser("smoke", help="Quick 1-user smoke test")
    p_smoke.add_argument("--target", default="wss://api.sovereignsanctuary.net/ws")
    p_smoke.add_argument("--ssh", default=None)

    # chat-burst
    p_burst = sub.add_parser("chat-burst", help="Single-turn burst test")
    p_burst.add_argument("--users", type=int, default=10)
    p_burst.add_argument("--target", default="wss://api.sovereignsanctuary.net/ws")
    p_burst.add_argument("--max-rate", type=int, default=10)
    p_burst.add_argument("--ssh", default=None)

    # chat-sustained
    p_sust = sub.add_parser("chat-sustained", help="Multi-turn sustained test")
    p_sust.add_argument("--users", type=int, default=10)
    p_sust.add_argument("--turns", type=int, default=3)
    p_sust.add_argument("--think-time", type=float, default=5.0)
    p_sust.add_argument("--target", default="wss://api.sovereignsanctuary.net/ws")
    p_sust.add_argument("--max-rate", type=int, default=10)
    p_sust.add_argument("--ssh", default=None)

    # rest-stress
    p_rest = sub.add_parser("rest-stress", help="REST API stress test")
    p_rest.add_argument("--target", default="https://api.sovereignsanctuary.net")
    p_rest.add_argument("--users", type=int, default=20)
    p_rest.add_argument("--duration", type=float, default=60)
    p_rest.add_argument("--token", default=None, help="Auth token (or uses SKYEYE_AUDIT_TOKEN)")

    # rate-limits
    p_rates = sub.add_parser("rate-limits", help="Discover rate limits")
    p_rates.add_argument("--target", default="https://api.sovereignsanctuary.net")
    p_rates.add_argument("--token", default=None)

    # ramp
    p_ramp = sub.add_parser("ramp", help="Ramp users until failure")
    p_ramp.add_argument("--max-users", type=int, default=300)
    p_ramp.add_argument("--target", default="wss://api.sovereignsanctuary.net/ws")
    p_ramp.add_argument("--ssh", default=None)

    # full
    p_full = sub.add_parser("full", help="Run all phases sequentially")
    p_full.add_argument("--max-users", type=int, default=300)
    p_full.add_argument("--target", default="wss://api.sovereignsanctuary.net/ws")
    p_full.add_argument("--ssh", default=None)

    # monitor
    p_mon = sub.add_parser("monitor", help="Monitor server metrics")
    p_mon.add_argument("--ssh", required=True)
    p_mon.add_argument("--duration", type=float, default=300)
    p_mon.add_argument("--interval", type=float, default=5)

    args = parser.parse_args()

    if args.command == "provision":
        provision_accounts(args.ssh, args.count)
        return

    if args.command == "cleanup":
        cleanup_accounts(args.ssh)
        return

    if args.command == "monitor":
        asyncio.run(monitor_server(args.ssh, args.duration, args.interval))
        return

    if args.command == "smoke":
        asyncio.run(run_ws_phase(
            args.target, 1, 1, 0, 1, 5, "SMOKE", ssh_target=args.ssh,
        ))
        return

    if args.command == "chat-burst":
        asyncio.run(run_ws_phase(
            args.target, args.users, 1, 0, max(5, args.users * 0.3),
            args.max_rate, f"CHAT BURST ({args.users}u)", ssh_target=args.ssh,
        ))
        return

    if args.command == "chat-sustained":
        asyncio.run(run_ws_phase(
            args.target, args.users, args.turns, args.think_time,
            max(5, args.users * 0.3), args.max_rate,
            f"SUSTAINED ({args.users}u × {args.turns}t)", ssh_target=args.ssh,
        ))
        return

    if args.command == "rest-stress":
        token = args.token or os.environ.get("SKYEYE_AUDIT_TOKEN", "")
        asyncio.run(rest_stress_test(args.target, token, args.users, args.duration))
        return

    if args.command == "rate-limits":
        token = args.token or os.environ.get("SKYEYE_AUDIT_TOKEN", "")
        asyncio.run(discover_rate_limits(args.target, token))
        return

    if args.command == "ramp":
        asyncio.run(ramp_to_failure(args.target, args.max_users, args.ssh))
        return

    if args.command == "full":
        asyncio.run(full_test(args.target, args.max_users, args.ssh))
        return


if __name__ == "__main__":
    main()
