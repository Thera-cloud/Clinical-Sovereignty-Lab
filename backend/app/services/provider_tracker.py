"""
Provider Utilization Tracker — logs every inference call and provides cost/usage stats.

JSONL append-only log at DATA_DIR/provider_usage.jsonl.
In-memory running totals by provider for the current session.
Thread-safe via asyncio.Lock.
"""

import asyncio
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

COST_PER_CALL: Dict[str, float] = {
    "ollama": 0.0,
    "sovereign": 0.0,
    "workers_ai": 0.0,
    "home_gpu": 0.0,
    "hetzner": 0.0,
    "digitalocean": 0.0,
    "grok": 0.00025,
    "azure": 0.002,
}

_data_dir = os.getenv("DATA_DIR", "app/websocket/data")
_jsonl_path: Optional[Path] = None
_lock = asyncio.Lock()

_session_stats: Dict[str, Dict] = defaultdict(lambda: {
    "calls": 0,
    "tokens_in": 0,
    "tokens_out": 0,
    "duration_ms": 0,
    "cost_usd": 0.0,
})

_session_start = time.time()


def _get_jsonl_path() -> Path:
    global _jsonl_path
    if _jsonl_path is None:
        p = Path(_data_dir) / "provider_usage.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        _jsonl_path = p
    return _jsonl_path


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English."""
    return max(1, len(text) // 4) if text else 0


async def log_call(
    provider: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    duration_ms: int = 0,
    domain: str = "general",
    odpe_signal: str = "PROVISIONAL",
    chars_in: int = 0,
    chars_out: int = 0,
) -> None:
    """Record an inference call to both in-memory stats and JSONL log."""
    if not tokens_in and chars_in:
        tokens_in = _estimate_tokens("x" * chars_in)
    if not tokens_out and chars_out:
        tokens_out = _estimate_tokens("x" * chars_out)

    cost = COST_PER_CALL.get(provider, 0.002)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "duration_ms": duration_ms,
        "cost_usd": cost,
        "domain": domain,
        "odpe_signal": odpe_signal,
    }

    s = _session_stats[provider]
    s["calls"] += 1
    s["tokens_in"] += tokens_in
    s["tokens_out"] += tokens_out
    s["duration_ms"] += duration_ms
    s["cost_usd"] += cost

    async with _lock:
        try:
            with open(_get_jsonl_path(), "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass


def get_session_stats() -> Dict:
    """Current session stats by provider."""
    total_calls = sum(s["calls"] for s in _session_stats.values())
    total_cost = sum(s["cost_usd"] for s in _session_stats.values())
    grok_baseline = total_calls * COST_PER_CALL["grok"]
    azure_baseline = total_calls * COST_PER_CALL["azure"]

    by_provider = {}
    for prov, s in sorted(_session_stats.items()):
        pct = (s["calls"] / total_calls * 100) if total_calls else 0
        by_provider[prov] = {
            "calls": s["calls"],
            "pct": round(pct, 1),
            "tokens_in": s["tokens_in"],
            "tokens_out": s["tokens_out"],
            "avg_ms": round(s["duration_ms"] / s["calls"]) if s["calls"] else 0,
            "cost_usd": round(s["cost_usd"], 6),
        }

    return {
        "session_uptime_s": round(time.time() - _session_start),
        "total_calls": total_calls,
        "total_cost_usd": round(total_cost, 6),
        "savings_vs_grok": round(grok_baseline - total_cost, 6),
        "savings_vs_azure": round(azure_baseline - total_cost, 6),
        "by_provider": by_provider,
    }


async def get_alltime_stats() -> Dict:
    """Get lifetime provider stats across all families."""
    from app.services.api_server import get_db
    
    async with get_db().acquire() as conn:
        rows = await conn.fetch("SELECT * FROM provider_stats_daily ORDER BY date DESC LIMIT 30")
        total_calls = sum(r['total_calls'] for r in rows)
        total_cost = sum(r['total_cost'] for r in rows)
        
        by_provider = {}
        for r in rows:
            for prov in ['grok', 'azure', 'ollama', 'sovereign']:
                if prov not in by_provider:
                    by_provider[prov] = {'calls': 0, 'cost_usd': 0.0}
                by_provider[prov]['calls'] += r['total_calls']
                by_provider[prov]['cost_usd'] += r['total_cost']
        
        return {
            'total_calls': total_calls,
            'total_cost_usd': round(total_cost, 6),
            'by_provider': by_provider
        }

async def get_family_stats(user_id: str, *, family_only: bool = True) -> Dict:
    """Get provider stats filtered by family_id from provider_stats table."""
    from app.services.api_server import get_db
    
    async with get_db().acquire() as conn:
        if family_only:
            # Resolve user_id → family_id
            row = await conn.fetchrow("SELECT family_id FROM users WHERE id = $1", user_id)
            family_id = row['family_id'] if row else None
            if not family_id:
                return {"total_calls": 0, "by_provider": {}}
            
            row = await conn.fetchrow(
                "SELECT * FROM provider_stats WHERE family_id = $1", family_id
            )
            return row or {"total_calls": 0, "by_provider": {}}
        else:
            # Global stats (admin only)
            rows = await conn.fetch("SELECT * FROM provider_stats")
            total_calls = sum(r['total_calls'] for r in rows)
            by_provider = {}
            for r in rows:
                for prov, stats in r['by_provider'].items():
                    if prov not in by_provider:
                        by_provider[prov] = stats
                    else:
                        # Simple sum (production would aggregate properly)
                        by_provider[prov]['calls'] += stats['calls']
            return {"total_calls": total_calls, "by_provider": by_provider}


def _parse_jsonl_logs() -> Dict[str, Any]:
    path = _get_jsonl_path()
    if not path.exists():
        return {"total_calls": 0, "total_cost_usd": 0, "by_provider": {}}

    by_prov: Dict[str, Dict] = defaultdict(lambda: {"calls": 0, "cost_usd": 0.0})
    total_calls = 0
    total_cost = 0.0

    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                prov = row.get("provider", "unknown")
                cost = row.get("cost_usd", 0)
                by_prov[prov]["calls"] += 1
                by_prov[prov]["cost_usd"] += cost
                total_calls += 1
                total_cost += cost
    except OSError:
        pass

    grok_baseline = total_calls * COST_PER_CALL["grok"]

    for prov in by_prov:
        pct = (by_prov[prov]["calls"] / total_calls * 100) if total_calls else 0
        by_prov[prov]["pct"] = round(pct, 1)
        by_prov[prov]["cost_usd"] = round(by_prov[prov]["cost_usd"], 6)

    return {
        "total_calls": total_calls,
        "total_cost_usd": round(total_cost, 6),
        "savings_vs_grok": round(grok_baseline - total_cost, 6),
        "by_provider": dict(by_prov),
    }
