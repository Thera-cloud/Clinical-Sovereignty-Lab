#!/usr/bin/env python3
"""
Phase 6c: Concurrent User Load Test
=================================
Real concurrent user load test for the Little Nate WebSocket bridge.
Simulates connect → login → chat → measure latency → disconnect.

Usage:
    python load_test.py --users 10 --ramp-time 30 --duration 120
    python load_test.py --users 50 --target ws://localhost:8765 --dry-run
    python load_test.py --users 100 --target wss://api.sovereignsanctuary.net/ws --max-rate 10

Requires: aiohttp (pip install aiohttp)
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


# ---------------------------------------------------------------------------
# Test prompts (therapy-adjacent, realistic)
# ---------------------------------------------------------------------------
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


@dataclass
class UserMetrics:
    """Per-user collected metrics."""

    user_id: str
    connected: bool = False
    login_ok: bool = False
    message_sent: bool = False
    response_received: bool = False
    connection_time_s: Optional[float] = None
    login_time_s: Optional[float] = None
    chat_first_chunk_s: Optional[float] = None
    chat_full_s: Optional[float] = None
    error: Optional[str] = None


def percentile(sorted_values: list[float], p: float) -> float:
    """Compute percentile (0-100)."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (p / 100)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_values) else f
    return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])


def format_duration(s: float) -> str:
    """Format seconds for display."""
    if s is None or s < 0:
        return "N/A"
    if s < 1:
        return f"{s*1000:.0f}ms"
    return f"{s:.2f}s"


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
) -> None:
    """Connect, login, send one chat message, collect metrics, disconnect."""
    hw_id = f"loadtest_{user_index:03d}"
    metrics.user_id = hw_id
    ws = None

    t0_connect = time.monotonic()
    try:
        ws = await session.ws_connect(target_url, heartbeat=30, receive_timeout=60)
        metrics.connection_time_s = time.monotonic() - t0_connect
        metrics.connected = True
    except Exception as e:
        metrics.error = f"connect: {type(e).__name__}: {e}"
        return

    try:
        # Wait for connected handshake
        msg = await asyncio.wait_for(ws.receive(), timeout=10)
        data = json.loads(msg.data) if msg.type == aiohttp.WSMsgType.TEXT else {}
        if data.get("type") != "connected" or data.get("status") != "ready":
            metrics.error = f"handshake: got {data.get('type', '?')}"
            await ws.close()
            return

        # Login
        t0_login = time.monotonic()
        await ws.send(
            json.dumps(
                {
                    "type": "login_request",
                    "username": username,
                    "password": password,
                    "expected_role": expected_role,
                    "hardware_id": hw_id,
                }
            )
        )

        login_success = False
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(ws.receive(), timeout=5)
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

        # Drain any post-login messages (metrics, etc.)
        await asyncio.sleep(0.2)
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=0.1)
                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    break
            except asyncio.TimeoutError:
                break

        # Send chat message (rate limited)
        async with rate_limiter:
            t0_chat = time.monotonic()
            await ws.send(
                json.dumps(
                    {
                        "type": "nate_query",
                        "text": prompt,
                        "nate_query": prompt,
                    }
                )
            )
            metrics.message_sent = True

        # Wait for nate_response
        first_chunk_time: Optional[float] = None
        full_response_time: Optional[float] = None
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(ws.receive(), timeout=10)
            if msg.type == aiohttp.WSMsgType.CLOSE:
                if not metrics.response_received:
                    metrics.error = "closed before response"
                break
            if msg.type == aiohttp.WSMsgType.ERROR:
                metrics.error = "ws error"
                break
            data = json.loads(msg.data) if msg.type == aiohttp.WSMsgType.TEXT else {}
            mt = data.get("type", "")
            if mt == "nate_response":
                now = time.monotonic()
                if first_chunk_time is None:
                    first_chunk_time = now - t0_chat
                full_response_time = now - t0_chat
                metrics.response_received = True
                metrics.chat_first_chunk_s = first_chunk_time
                metrics.chat_full_s = full_response_time
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


async def progress_reporter(
    all_metrics: list[UserMetrics],
    total_users: int,
    stop_event: asyncio.Event,
    interval: float = 2.0,
) -> None:
    """Print real-time progress."""
    while not stop_event.is_set():
        await asyncio.sleep(interval)
        if stop_event.is_set():
            break
        connected = sum(1 for m in all_metrics if m.connected)
        msgs_sent = sum(1 for m in all_metrics if m.message_sent)
        responses = sum(1 for m in all_metrics if m.response_received)
        latencies = [m.chat_full_s for m in all_metrics if m.chat_full_s is not None]
        avg_lat = statistics.mean(latencies) if latencies else 0
        print(
            f"\r[{connected}/{total_users} users connected] "
            f"[{msgs_sent} messages sent] "
            f"[{responses} responses] "
            f"[avg latency: {avg_lat:.1f}s]   ",
            end="",
        )


async def main_async(args: argparse.Namespace) -> None:
    """Main async entry point."""
    connector = aiohttp.TCPConnector(limit=0, limit_per_host=0)
    timeout = aiohttp.ClientTimeout(total=120, connect=15)

    prompts = TEST_PROMPTS * (args.users // len(TEST_PROMPTS) + 1)
    all_metrics: list[UserMetrics] = [UserMetrics(user_id="") for _ in range(args.users)]

    rate_limiter: asyncio.Semaphore = asyncio.Semaphore(args.max_rate)
    stop_progress = asyncio.Event()

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        progress_task = asyncio.create_task(
            progress_reporter(all_metrics, args.users, stop_progress)
        )

        start_wall = time.monotonic()
        ramp_per_user = args.ramp_time / max(1, args.users)

        for i in range(args.users):
            await asyncio.sleep(ramp_per_user)
            m = all_metrics[i]
            asyncio.create_task(
                run_single_user(
                    session=session,
                    user_index=i,
                    target_url=args.target,
                    username=args.username,
                    password=args.password,
                    expected_role=args.expected_role,
                    prompt=prompts[i],
                    dry_run=args.dry_run,
                    rate_limiter=rate_limiter,
                    metrics=m,
                )
            )

        # Run for duration
        elapsed = 0
        while elapsed < args.duration:
            await asyncio.sleep(1)
            elapsed = time.monotonic() - start_wall

        stop_progress.set()
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

        # Allow in-flight tasks to finish (with a bound)
        await asyncio.sleep(5)

    # Summary
    connected = sum(1 for m in all_metrics if m.connected)
    msgs_sent = sum(1 for m in all_metrics if m.message_sent)
    responses = sum(1 for m in all_metrics if m.response_received)
    errors = sum(1 for m in all_metrics if m.error)
    conn_times = sorted([m.connection_time_s for m in all_metrics if m.connection_time_s is not None])
    login_times = sorted([m.login_time_s for m in all_metrics if m.login_time_s is not None])
    chat_times = sorted([m.chat_full_s for m in all_metrics if m.chat_full_s is not None])

    duration_actual = time.monotonic() - start_wall
    throughput = responses / duration_actual if duration_actual > 0 else 0

    # Box (inner width 36)
    def _fmt(val: str, w: int = 10) -> str:
        return val[:w].rjust(w) if len(val) <= w else val[:w]

    conn_p50 = format_duration(percentile(conn_times, 50)) if conn_times else "N/A"
    conn_p95 = format_duration(percentile(conn_times, 95)) if conn_times else "N/A"
    login_p50 = format_duration(percentile(login_times, 50)) if login_times else "N/A"
    login_p95 = format_duration(percentile(login_times, 95)) if login_times else "N/A"
    chat_p50 = format_duration(percentile(chat_times, 50)) if chat_times else "N/A"
    chat_p95 = format_duration(percentile(chat_times, 95)) if chat_times else "N/A"

    lines = [
        "╔══════════════════════════════════════╗",
        "║     Load Test Results                ║",
        "╠══════════════════════════════════════╣",
        f"║ Users attempted:  {args.users:<18}║",
        f"║ Users connected:  {connected:<18}║",
        f"║ Messages sent:    {msgs_sent:<18}║",
        f"║ Messages received: {responses:<17}║",
        f"║ Errors:          {errors:<18}║",
        "║                                      ║",
        f"║ Connection time (p50): {_fmt(conn_p50):>10}║",
        f"║ Connection time (p95): {_fmt(conn_p95):>10}║",
        f"║ Login time (p50):      {_fmt(login_p50):>10}║",
        f"║ Login time (p95):      {_fmt(login_p95):>10}║",
        f"║ Chat response (p50):   {_fmt(chat_p50):>10}║",
        f"║ Chat response (p95):   {_fmt(chat_p95):>10}║",
        "║                                      ║",
        f"║ Throughput: {throughput:.1f} msg/sec{' ' * 11}║",
        "║ Peak memory (server): N/A            ║",
        "╚══════════════════════════════════════╝",
    ]

    for line in lines:
        print(line)

    if errors > 0:
        print("\nSample errors:")
        seen: set[str] = set()
        count = 0
        for m in all_metrics:
            if m.error and m.error not in seen and count < 5:
                seen.add(m.error)
                print(f"  {m.user_id}: {m.error}")
                count += 1
        if errors > count:
            print(f"  ... and {errors - count} more")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 6c: Concurrent user load test for Little Nate bridge"
    )
    parser.add_argument(
        "--users",
        type=int,
        default=10,
        help="Number of concurrent users (default: 10)",
    )
    parser.add_argument(
        "--ramp-time",
        type=float,
        default=30,
        help="Seconds to ramp up all users (default: 30)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=120,
        help="Total test duration in seconds (default: 120)",
    )
    parser.add_argument(
        "--target",
        type=str,
        default="ws://localhost:8765",
        help="WebSocket URL (default: ws://localhost:8765)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default="http://localhost:8000",
        help="REST API URL for health checks (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--username",
        type=str,
        default="audit_client",
        help="Test account username (default: audit_client)",
    )
    parser.add_argument(
        "--password",
        type=str,
        default="AuditClient2026!",
        help="Test account password (default: AuditClient2026!)",
    )
    parser.add_argument(
        "--expected-role",
        type=str,
        default="CLIENT",
        help="Expected role for login (default: CLIENT)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only test connectivity, no chat messages",
    )
    parser.add_argument(
        "--max-rate",
        type=int,
        default=5,
        help="Max messages per second globally (default: 5)",
    )

    args = parser.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def on_sigint(*_):  # type: ignore
        print("\n[Ctrl+C] Graceful shutdown...")
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGINT, on_sigint)
    except (ValueError, OSError):
        pass  # Windows

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
