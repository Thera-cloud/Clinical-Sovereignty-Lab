#!/usr/bin/env python3
"""
Live Load Test — Full Pipeline Concurrent User Stress Test.
Measures real throughput through the entire cognitive stack:
  WS connect → login → nate_query → [Vectorize + Helix + ODPE + SDH + Quantum + LLM] → nate_response

Supports single-turn (burst) and multi-turn (sustained conversation) modes.
Runs against production via wss://api.sovereignsanctuary.net/ws or localhost.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Optional, List

try:
    import aiohttp
except ImportError:
    print("ERROR: pip install aiohttp")
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

FOLLOW_UP_PROMPTS = [
    "Can you tell me more about that?",
    "That resonates. How would I apply that practically?",
    "I've tried something similar before but it didn't stick. Why might that be?",
    "What if I feel resistance when I try that?",
    "How does this connect to what we talked about before?",
    "That's helpful. What's a small first step I could take today?",
    "I'm noticing some emotion as you say that. Is that normal?",
    "Can you give me an example of how someone else handled this?",
    "What would you say to someone who feels stuck despite knowing this?",
    "How long does it usually take to see progress with this approach?",
]


@dataclass
class TurnMetrics:
    turn_num: int = 0
    first_chunk_s: Optional[float] = None
    full_response_s: Optional[float] = None
    response_length: int = 0
    provider: str = ""
    success: bool = False
    error: Optional[str] = None


@dataclass
class UserMetrics:
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


def percentile(vals: list, p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (k - f) * (s[c] - s[f])


def fmt(s):
    if s is None or s < 0:
        return "N/A"
    return f"{s*1000:.0f}ms" if s < 1 else f"{s:.2f}s"


async def _send_and_receive(ws, prompt: str, turn_metrics: TurnMetrics, first_chunk_timeout: float = 120.0):
    t_start = time.monotonic()
    await ws.send_str(json.dumps({
        "type": "nate_query",
        "text": prompt,
        "nate_query": prompt,
    }))

    first_chunk = None
    last_chunk_time = None
    accumulated_len = 0
    deadline = time.monotonic() + 300

    while time.monotonic() < deadline:
        try:
            wait = 5.0 if first_chunk is not None else first_chunk_timeout
            msg = await asyncio.wait_for(ws.receive(), timeout=wait)
        except asyncio.TimeoutError:
            if first_chunk is not None:
                turn_metrics.success = True
                turn_metrics.full_response_s = last_chunk_time - t_start
                turn_metrics.response_length = accumulated_len
                return True
            turn_metrics.error = f"timeout ({first_chunk_timeout:.0f}s no first chunk)"
            return False

        if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
            if first_chunk is not None:
                turn_metrics.success = True
                turn_metrics.full_response_s = (last_chunk_time or time.monotonic()) - t_start
                turn_metrics.response_length = accumulated_len
                return True
            turn_metrics.error = "ws closed"
            return False

        data = json.loads(msg.data) if msg.type == aiohttp.WSMsgType.TEXT else {}
        mt = data.get("type", "")

        if mt == "nate_response":
            now = time.monotonic()
            if first_chunk is None:
                first_chunk = now - t_start
                turn_metrics.first_chunk_s = first_chunk
            last_chunk_time = now
            accumulated_len = len(data.get("text", data.get("response", "")))
        elif mt == "error":
            turn_metrics.error = data.get("message", "server error")
            return False

    turn_metrics.error = "deadline exceeded"
    return False


async def run_user(
    session: aiohttp.ClientSession,
    idx: int,
    target: str,
    username: str,
    password: str,
    role: str,
    prompts: List[str],
    sem: asyncio.Semaphore,
    metrics: UserMetrics,
    turns_per_user: int,
    think_time: float,
    first_chunk_timeout: float,
):
    hw_id = f"loadtest_{idx:04d}"
    metrics.user_id = hw_id
    ws = None
    session_start = time.monotonic()

    t0 = time.monotonic()
    try:
        ws = await session.ws_connect(target, heartbeat=30, receive_timeout=180)
        metrics.connection_time_s = time.monotonic() - t0
        metrics.connected = True
    except Exception as e:
        metrics.error = f"connect: {e}"
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
            "hardware_id": hw_id,
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
                break
            if data.get("type") == "login_failed":
                metrics.error = f"login_failed: {data.get('message', '?')}"
                await ws.close()
                return

        if not metrics.login_ok:
            metrics.error = "login timeout"
            await ws.close()
            return

        await asyncio.sleep(0.3)
        while True:
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=0.2)
                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    break
            except asyncio.TimeoutError:
                break

        for turn_num in range(turns_per_user):
            metrics.turns_attempted += 1
            tm = TurnMetrics(turn_num=turn_num)

            if turn_num == 0:
                prompt = prompts[idx % len(prompts)]
            else:
                prompt = FOLLOW_UP_PROMPTS[(idx + turn_num) % len(FOLLOW_UP_PROMPTS)]

            async with sem:
                ok = await _send_and_receive(ws, prompt, tm, first_chunk_timeout)

            metrics.turns.append(tm)
            if ok:
                metrics.turns_completed += 1
            else:
                if not metrics.error:
                    metrics.error = f"turn {turn_num}: {tm.error}"
                break

            if turn_num < turns_per_user - 1:
                await asyncio.sleep(think_time)

        metrics.total_session_s = time.monotonic() - session_start

    except asyncio.TimeoutError:
        metrics.error = "timeout"
    except Exception as e:
        metrics.error = f"{type(e).__name__}: {e}"
    finally:
        if ws:
            try:
                await ws.close()
            except Exception:
                pass


async def run_test(users: int, target: str, username: str, password: str,
                   role: str, ramp: float, max_rate: int, duration: float,
                   turns: int, think_time: float, first_chunk_timeout: float):
    connector = aiohttp.TCPConnector(limit=0, limit_per_host=0)
    timeout = aiohttp.ClientTimeout(total=600, connect=30)
    all_m: List[UserMetrics] = [UserMetrics() for _ in range(users)]
    sem = asyncio.Semaphore(max_rate)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        start = time.monotonic()
        ramp_per = ramp / max(1, users)

        tasks = []
        for i in range(users):
            await asyncio.sleep(ramp_per)
            user_i = f"loadtest_{i+1:03d}" if users > 1 else username
            t = asyncio.create_task(run_user(
                session, i, target, user_i, password, role,
                TEST_PROMPTS, sem, all_m[i], turns, think_time, first_chunk_timeout,
            ))
            tasks.append(t)

        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=duration
            )
        except asyncio.TimeoutError:
            pass

        wall = time.monotonic() - start

    connected = sum(1 for m in all_m if m.connected)
    logins = sum(1 for m in all_m if m.login_ok)
    total_turns_attempted = sum(m.turns_attempted for m in all_m)
    total_turns_completed = sum(m.turns_completed for m in all_m)
    errors = sum(1 for m in all_m if m.error)

    conn_t = [m.connection_time_s for m in all_m if m.connection_time_s is not None]
    login_t = [m.login_time_s for m in all_m if m.login_time_s is not None]

    all_resp_t = []
    all_first_t = []
    all_resp_len = []
    for m in all_m:
        for tm in m.turns:
            if tm.full_response_s is not None:
                all_resp_t.append(tm.full_response_s)
            if tm.first_chunk_s is not None:
                all_first_t.append(tm.first_chunk_s)
            if tm.success:
                all_resp_len.append(tm.response_length)

    session_times = [m.total_session_s for m in all_m if m.total_session_s is not None]

    throughput = total_turns_completed / wall if wall > 0 else 0

    print(f"\n{'='*60}")
    print(f"  LOAD TEST: {users} USERS × {turns} TURNS = {users * turns} TOTAL REQUESTS")
    print(f"{'='*60}")
    print(f"  Target:           {target}")
    print(f"  Mode:             {'multi-turn sustained' if turns > 1 else 'single-turn burst'}")
    print(f"  Turns/user:       {turns}")
    print(f"  Think time:       {think_time:.0f}s between turns")
    print(f"  Ramp time:        {ramp:.0f}s")
    print(f"  Max rate:         {max_rate} msg/s")
    print(f"  Wall time:        {wall:.1f}s")
    print(f"{'─'*60}")
    print(f"  Connected:        {connected}/{users}")
    print(f"  Logins OK:        {logins}/{users}")
    print(f"  Turns attempted:  {total_turns_attempted}/{users * turns}")
    print(f"  Turns completed:  {total_turns_completed}/{users * turns}")
    print(f"  User errors:      {errors}/{users}")
    print(f"{'─'*60}")
    if conn_t:
        print(f"  Connect p50:      {fmt(percentile(conn_t, 50))}")
        print(f"  Connect p95:      {fmt(percentile(conn_t, 95))}")
    if login_t:
        print(f"  Login p50:        {fmt(percentile(login_t, 50))}")
        print(f"  Login p95:        {fmt(percentile(login_t, 95))}")
    if all_first_t:
        print(f"  First chunk p50:  {fmt(percentile(all_first_t, 50))}")
        print(f"  First chunk p95:  {fmt(percentile(all_first_t, 95))}")
    if all_resp_t:
        print(f"  Full resp p50:    {fmt(percentile(all_resp_t, 50))}")
        print(f"  Full resp p95:    {fmt(percentile(all_resp_t, 95))}")
        print(f"  Full resp MAX:    {fmt(max(all_resp_t))}")
    if all_resp_len:
        print(f"  Avg resp chars:   {statistics.mean(all_resp_len):.0f}")
    if session_times:
        print(f"  Session p50:      {fmt(percentile(session_times, 50))}")
        print(f"  Session MAX:      {fmt(max(session_times))}")
    print(f"{'─'*60}")
    print(f"  Throughput:       {throughput:.2f} responses/sec")

    if turns > 1:
        per_turn = {}
        for m in all_m:
            for tm in m.turns:
                if tm.full_response_s is not None:
                    per_turn.setdefault(tm.turn_num, []).append(tm.full_response_s)
        if per_turn:
            print(f"{'─'*60}")
            print(f"  Per-turn latency breakdown:")
            for tn in sorted(per_turn.keys()):
                vals = per_turn[tn]
                label = "initial" if tn == 0 else f"follow-up {tn}"
                print(f"    Turn {tn} ({label}): p50={fmt(percentile(vals, 50))} "
                      f"p95={fmt(percentile(vals, 95))} n={len(vals)}")

    print(f"{'='*60}")

    if errors > 0:
        print("\n  Sample errors:")
        seen = set()
        for m in all_m:
            if m.error and m.error not in seen and len(seen) < 5:
                seen.add(m.error)
                print(f"    {m.user_id}: {m.error}")

    return {
        "users": users,
        "turns_per_user": turns,
        "connected": connected,
        "logins": logins,
        "turns_attempted": total_turns_attempted,
        "turns_completed": total_turns_completed,
        "errors": errors,
        "wall_s": round(wall, 1),
        "throughput": round(throughput, 2),
        "resp_p50": round(percentile(all_resp_t, 50), 2) if all_resp_t else None,
        "resp_p95": round(percentile(all_resp_t, 95), 2) if all_resp_t else None,
        "resp_max": round(max(all_resp_t), 2) if all_resp_t else None,
    }


async def main():
    parser = argparse.ArgumentParser(description="Live load test — full cognitive pipeline")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--turns", type=int, default=1,
                        help="Messages per user (1=burst, 3-5=sustained conversation)")
    parser.add_argument("--think-time", type=float, default=5.0,
                        help="Seconds between turns (simulates user reading/thinking)")
    parser.add_argument("--first-chunk-timeout", type=float, default=120.0,
                        help="Max seconds to wait for first response chunk")
    parser.add_argument("--ramp-time", type=float, default=15)
    parser.add_argument("--duration", type=float, default=900)
    parser.add_argument("--target", default="wss://api.sovereignsanctuary.net/ws")
    parser.add_argument("--username", default="audit_client")
    parser.add_argument("--password", default="AuditClient2026!")
    parser.add_argument("--expected-role", default="CLIENT")
    parser.add_argument("--max-rate", type=int, default=10)
    args = parser.parse_args()

    await run_test(
        args.users, args.target, args.username, args.password,
        args.expected_role, args.ramp_time, args.max_rate, args.duration,
        args.turns, args.think_time, args.first_chunk_timeout,
    )


if __name__ == "__main__":
    asyncio.run(main())
