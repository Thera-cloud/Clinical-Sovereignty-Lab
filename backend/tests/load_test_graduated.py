#!/usr/bin/env python3
"""
Graduated Load Test — Find Maximum Concurrent Users
====================================================
Runs load tests at increasing user counts: 10 → 25 → 50 → 75 → 100 → 150 → 200 → 300
Stops early if failure rate exceeds threshold. Reports comparison table.

Usage:
    python load_test_graduated.py
    python load_test_graduated.py --target wss://api.sovereignsanctuary.net/ws
    python load_test_graduated.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import aiohttp
except ImportError:
    print("ERROR: aiohttp required. Run: pip install aiohttp")
    sys.exit(1)

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

LEVELS = [10, 25, 50, 75, 100, 150, 200, 300]


@dataclass
class UserMetrics:
    user_id: str = ""
    connected: bool = False
    login_ok: bool = False
    message_sent: bool = False
    response_received: bool = False
    connection_time_s: Optional[float] = None
    login_time_s: Optional[float] = None
    chat_first_chunk_s: Optional[float] = None
    chat_full_s: Optional[float] = None
    error: Optional[str] = None


@dataclass
class LevelResult:
    users: int = 0
    connected: int = 0
    logins: int = 0
    messages_sent: int = 0
    responses: int = 0
    errors: int = 0
    conn_p50: float = 0.0
    conn_p95: float = 0.0
    login_p50: float = 0.0
    login_p95: float = 0.0
    chat_p50: float = 0.0
    chat_p95: float = 0.0
    throughput: float = 0.0
    duration_s: float = 0.0
    error_samples: list = field(default_factory=list)
    verdict: str = ""


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (p / 100)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_values) else f
    return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])


def fmt_ms(s: Optional[float]) -> str:
    if s is None or s <= 0:
        return "-"
    if s < 1:
        return f"{s*1000:.0f}ms"
    return f"{s:.1f}s"


async def run_single_user(
    session: aiohttp.ClientSession,
    user_index: int,
    target_url: str,
    username: str,
    password: str,
    expected_role: str,
    prompt: str,
    dry_run: bool,
    rate_limiter: asyncio.Semaphore,
    metrics: UserMetrics,
    per_user_accounts: bool = False,
) -> None:
    uid = user_index + 1
    if per_user_accounts:
        username = f"loadtest_{uid:03d}"
        password = "LoadTest2026!Nate"
    hw_id = f"LOADTEST_{uid:03d}_ID"
    metrics.user_id = f"loadtest_{uid:03d}"
    ws = None

    t0_connect = time.monotonic()
    try:
        ws = await session.ws_connect(target_url, heartbeat=30, receive_timeout=180)
        metrics.connection_time_s = time.monotonic() - t0_connect
        metrics.connected = True
    except Exception as e:
        metrics.error = f"connect: {type(e).__name__}: {e}"
        return

    try:
        msg = await asyncio.wait_for(ws.receive(), timeout=10)
        data = json.loads(msg.data) if msg.type == aiohttp.WSMsgType.TEXT else {}
        if data.get("type") != "connected" or data.get("status") != "ready":
            metrics.error = f"handshake: got {data.get('type', '?')}"
            await ws.close()
            return

        t0_login = time.monotonic()
        await ws.send_str(json.dumps({
            "type": "login_request",
            "username": username,
            "password": password,
            "expected_role": expected_role,
            "hardware_id": hw_id,
        }))

        login_success = False
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(ws.receive(), timeout=15)
            if msg.type == aiohttp.WSMsgType.CLOSE:
                metrics.error = "closed during login"
                return
            data = json.loads(msg.data) if msg.type == aiohttp.WSMsgType.TEXT else {}
            if data.get("type") == "login_success":
                login_success = True
                break
            if data.get("type") == "login_failed":
                metrics.error = f"login_failed: {data.get('message', 'unknown')}"
                await ws.close()
                return

        metrics.login_time_s = time.monotonic() - t0_login
        metrics.login_ok = login_success
        if not login_success:
            metrics.error = "login timeout"
            await ws.close()
            return

        if dry_run:
            await ws.close()
            return

        await asyncio.sleep(0.2)
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=0.1)
                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    break
            except asyncio.TimeoutError:
                break

        async with rate_limiter:
            t0_chat = time.monotonic()
            await ws.send_str(json.dumps({
                "type": "nate_query",
                "text": prompt,
                "nate_query": prompt,
            }))
            metrics.message_sent = True

        deadline = time.monotonic() + 120
        first_chunk_time = None
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(ws.receive(), timeout=45)
            if msg.type == aiohttp.WSMsgType.CLOSE:
                if not metrics.response_received:
                    metrics.error = "closed before response"
                break
            if msg.type == aiohttp.WSMsgType.ERROR:
                metrics.error = "ws error"
                break
            data = json.loads(msg.data) if msg.type == aiohttp.WSMsgType.TEXT else {}
            mt = data.get("type", "")
            if mt in ("nate_response", "ai_response"):
                now = time.monotonic()
                if first_chunk_time is None:
                    first_chunk_time = now - t0_chat
                metrics.response_received = True
                metrics.chat_first_chunk_s = first_chunk_time
                metrics.chat_full_s = now - t0_chat
                break
            if mt == "nate_status" and first_chunk_time is None:
                first_chunk_time = time.monotonic() - t0_chat
            if mt == "error":
                metrics.error = data.get("message", "server error")
                break

        if not metrics.response_received and not metrics.error:
            metrics.error = "response timeout"

    except asyncio.TimeoutError:
        metrics.error = "timeout"
    except Exception as e:
        metrics.error = f"{type(e).__name__}: {e}"
    finally:
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass


async def run_level(
    level: int,
    target_url: str,
    username: str,
    password: str,
    expected_role: str,
    dry_run: bool,
    max_rate: int,
    duration: float,
    ramp_time: float,
    per_user_accounts: bool = False,
) -> LevelResult:
    connector = aiohttp.TCPConnector(limit=0, limit_per_host=0)
    timeout = aiohttp.ClientTimeout(total=900, connect=30)
    prompts = TEST_PROMPTS * (level // len(TEST_PROMPTS) + 1)
    all_metrics = [UserMetrics() for _ in range(level)]
    rate_limiter = asyncio.Semaphore(max_rate)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        start_wall = time.monotonic()
        ramp_per_user = ramp_time / max(1, level)
        tasks = []

        for i in range(level):
            await asyncio.sleep(ramp_per_user)
            t = asyncio.create_task(run_single_user(
                session=session,
                user_index=i,
                target_url=target_url,
                username=username,
                password=password,
                expected_role=expected_role,
                prompt=prompts[i],
                dry_run=dry_run,
                rate_limiter=rate_limiter,
                metrics=all_metrics[i],
                per_user_accounts=per_user_accounts,
            ))
            tasks.append(t)

            done = sum(1 for m in all_metrics if m.connected or m.error)
            print(f"\r  Ramping: {i+1}/{level} users launched, {done} settled...", end="")

        elapsed = time.monotonic() - start_wall
        remaining = max(0, duration - elapsed)
        if remaining > 0:
            print(f"\r  Running for {remaining:.0f}s more...                              ", end="")
            await asyncio.sleep(remaining)

        await asyncio.sleep(3)
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.sleep(1)

    total_duration = time.monotonic() - start_wall

    connected = sum(1 for m in all_metrics if m.connected)
    logins = sum(1 for m in all_metrics if m.login_ok)
    msgs_sent = sum(1 for m in all_metrics if m.message_sent)
    responses = sum(1 for m in all_metrics if m.response_received)
    errors = sum(1 for m in all_metrics if m.error)

    conn_times = sorted([m.connection_time_s for m in all_metrics if m.connection_time_s])
    login_times = sorted([m.login_time_s for m in all_metrics if m.login_time_s])
    chat_times = sorted([m.chat_full_s for m in all_metrics if m.chat_full_s])

    error_samples = []
    seen = set()
    for m in all_metrics:
        if m.error and m.error not in seen and len(error_samples) < 3:
            seen.add(m.error)
            error_samples.append(f"{m.user_id}: {m.error}")

    success_rate = (responses / level * 100) if level > 0 else 0
    if success_rate >= 90:
        verdict = "PASS"
    elif success_rate >= 70:
        verdict = "DEGRADED"
    elif success_rate >= 40:
        verdict = "STRESSED"
    else:
        verdict = "FAIL"

    return LevelResult(
        users=level,
        connected=connected,
        logins=logins,
        messages_sent=msgs_sent,
        responses=responses,
        errors=errors,
        conn_p50=percentile(conn_times, 50),
        conn_p95=percentile(conn_times, 95),
        login_p50=percentile(login_times, 50),
        login_p95=percentile(login_times, 95),
        chat_p50=percentile(chat_times, 50),
        chat_p95=percentile(chat_times, 95),
        throughput=responses / total_duration if total_duration > 0 else 0,
        duration_s=total_duration,
        error_samples=error_samples,
        verdict=verdict,
    )


def print_summary(results: list[LevelResult], dry_run: bool) -> None:
    print("\n")
    print("=" * 100)
    print("  GRADUATED LOAD TEST RESULTS — Little Nate WebSocket Bridge")
    print("=" * 100)

    if dry_run:
        header = f"{'Level':>6} | {'Conn':>5} | {'Login':>5} | {'Conn p50':>9} | {'Conn p95':>9} | {'Login p50':>10} | {'Login p95':>10} | {'Errors':>6} | Verdict"
        print(header)
        print("-" * 100)
        for r in results:
            conn_rate = f"{r.connected}/{r.users}"
            login_rate = f"{r.logins}/{r.users}"
            print(
                f"{r.users:>6} | {conn_rate:>5} | {login_rate:>5} | "
                f"{fmt_ms(r.conn_p50):>9} | {fmt_ms(r.conn_p95):>9} | "
                f"{fmt_ms(r.login_p50):>10} | {fmt_ms(r.login_p95):>10} | "
                f"{r.errors:>6} | {r.verdict}"
            )
    else:
        header = (
            f"{'Level':>6} | {'Conn':>5} | {'Login':>5} | {'Resp':>5} | "
            f"{'Chat p50':>9} | {'Chat p95':>9} | {'Tput':>8} | {'Errors':>6} | Verdict"
        )
        print(header)
        print("-" * 100)
        for r in results:
            conn_rate = f"{r.connected}/{r.users}"
            login_rate = f"{r.logins}/{r.users}"
            resp_rate = f"{r.responses}/{r.users}"
            tput = f"{r.throughput:.1f}/s"
            print(
                f"{r.users:>6} | {conn_rate:>5} | {login_rate:>5} | {resp_rate:>5} | "
                f"{fmt_ms(r.chat_p50):>9} | {fmt_ms(r.chat_p95):>9} | "
                f"{tput:>8} | {r.errors:>6} | {r.verdict}"
            )

    print("-" * 100)

    passing = [r for r in results if r.verdict == "PASS"]
    if passing:
        max_pass = passing[-1].users
        print(f"\n  MAX STABLE CAPACITY: {max_pass} concurrent users (>=90% success)")
    else:
        print(f"\n  MAX STABLE CAPACITY: <{results[0].users if results else '?'} (no level passed)")

    degraded = [r for r in results if r.verdict in ("DEGRADED", "STRESSED")]
    if degraded:
        print(f"  DEGRADATION STARTS: {degraded[0].users} users")

    failed = [r for r in results if r.verdict == "FAIL"]
    if failed:
        print(f"  HARD FAILURE AT: {failed[0].users} users")

    print()
    for r in results:
        if r.error_samples:
            print(f"  Errors at {r.users} users:")
            for e in r.error_samples:
                print(f"    {e}")
    print()


async def main_async(args: argparse.Namespace) -> None:
    levels = LEVELS
    if args.levels:
        levels = [int(x.strip()) for x in args.levels.split(",")]

    results: list[LevelResult] = []
    stop_early = False

    for i, level in enumerate(levels):
        print(f"\n{'='*60}")
        print(f"  LEVEL {i+1}/{len(levels)}: {level} concurrent users")
        print(f"{'='*60}")

        result = await run_level(
            level=level,
            target_url=args.target,
            username=args.username,
            password=args.password,
            expected_role=args.expected_role,
            dry_run=args.dry_run,
            max_rate=args.max_rate,
            duration=args.duration,
            ramp_time=args.ramp_time,
            per_user_accounts=args.per_user,
        )
        results.append(result)

        success_pct = (result.responses / level * 100) if not args.dry_run else (result.logins / level * 100)
        print(f"\r  Result: {result.verdict} — "
              f"{result.connected}/{level} connected, "
              f"{result.responses}/{level} responses, "
              f"{result.errors} errors, "
              f"chat p50={fmt_ms(result.chat_p50)}, p95={fmt_ms(result.chat_p95)}")

        if result.verdict == "FAIL" and not args.no_stop:
            print(f"\n  *** STOPPING EARLY — {level} users caused FAIL (>{60}% errors) ***")
            stop_early = True

        if i < len(levels) - 1 and not stop_early:
            recovery = args.recovery
            print(f"  Recovering for {recovery}s before next level...")
            await asyncio.sleep(recovery)

        if stop_early:
            break

    print_summary(results, args.dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Graduated load test for Little Nate bridge")
    parser.add_argument("--target", default="wss://api.sovereignsanctuary.net/ws",
                        help="WebSocket URL (default: wss://api.sovereignsanctuary.net/ws)")
    parser.add_argument("--username", default="audit_client", help="Test account username")
    parser.add_argument("--password", default="AuditClient2026!", help="Test account password")
    parser.add_argument("--expected-role", default="CLIENT", help="Expected role")
    parser.add_argument("--dry-run", action="store_true", help="Only test connect+login, no chat")
    parser.add_argument("--max-rate", type=int, default=8, help="Max messages/sec (default: 8)")
    parser.add_argument("--duration", type=float, default=60, help="Seconds per level (default: 60)")
    parser.add_argument("--ramp-time", type=float, default=15, help="Ramp time per level (default: 15)")
    parser.add_argument("--recovery", type=float, default=15, help="Recovery seconds between levels (default: 15)")
    parser.add_argument("--levels", type=str, default=None,
                        help="Comma-separated user counts (default: 10,25,50,75,100,150,200,300)")
    parser.add_argument("--no-stop", action="store_true", help="Don't stop on FAIL, run all levels")
    parser.add_argument("--per-user", action=argparse.BooleanOptionalAction, default=False,
                        help="Use per-user loadtest_XXX accounts (default: False, uses single audit_client)")

    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def on_sigint(*_):
        print("\n[Ctrl+C] Stopping...")
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGINT, on_sigint)
    except (ValueError, OSError):
        pass

    try:
        loop.run_until_complete(main_async(args))
    except SystemExit:
        pass
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
