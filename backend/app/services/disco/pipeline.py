"""
Sovereign Sanctuary — Discoverability pipeline gap fixes (reference implementation).
Each class is the executable proof for one §18 gap resolution.
Pure stdlib so it runs anywhere; adapters are stubbed at the network boundary only.
"""
from __future__ import annotations
import hashlib, json, time, random
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Callable, Iterable


# ── GAP 1: probe automation feasibility + graded fallback ───────────────────────
class ProbeMode(Enum):
    API = "api"              # official API: full automation, high frequency
    GROUNDED = "grounded"    # search-grounded proxy: automated, correlates w/ answers
    MANUAL = "manual"        # no lawful automation: sampled, human/queue assisted


@dataclass
class EngineAdapter:
    name: str
    mode: ProbeMode
    max_daily: int
    _probe: Callable[[str], dict] | None = None

    def probe(self, prompt: str) -> dict:
        if self._probe:
            return self._probe(prompt)
        # deterministic stub standing in for the network call
        seed = int(hashlib.sha256((self.name + prompt).encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        named = rng.random() < 0.35
        return {
            "engine": self.name, "mode": self.mode.value, "prompt": prompt,
            "named_entities": ["Sovereign Sanctuary"] if named else [],
            "claims": {"price_day": "$5 you+partner"} if named else {},
        }


class ProbeScheduler:
    """Adaptive sampling: budget by mode, escalate on volatility (§15.1)."""
    def __init__(self, adapters: list[EngineAdapter]):
        self.adapters = adapters
        self.volatility = 0.0

    def daily_plan(self, prompts: list[str]) -> dict[str, int]:
        mult = 1 + min(self.volatility, 1.0) * 2  # up to 3x on high volatility
        plan = {}
        for a in self.adapters:
            base = {ProbeMode.API: 1.0, ProbeMode.GROUNDED: 0.6, ProbeMode.MANUAL: 0.05}[a.mode]
            plan[a.name] = min(a.max_daily, int(len(prompts) * base * mult))
        return plan

    def run(self, prompts: list[str]) -> list[dict]:
        out = []
        for a in self.adapters:
            n = self.daily_plan(prompts)[a.name]
            for p in prompts[:n]:
                out.append(a.probe(p))
        return out

    def coverage(self, prompts: list[str]) -> float:
        """Fraction of prompt-space observed per day across all engines."""
        plan = self.daily_plan(prompts)
        return min(1.0, sum(plan.values()) / max(1, len(prompts) * len(self.adapters)))


# ── GAP 2: integration contract between the two plans ──────────────────────────
class BuildBoundary:
    """
    Discoverability NEVER reads v1.5 tables directly. It consumes 4 read-only
    contracts. Missing contract => degrade, never crash (DAC-style guarantee).
    """
    CONTRACTS = ("credentials", "engagements", "content_topics", "authoring")

    def __init__(self, available: Iterable[str] = ()):
        self.available = set(available)

    def get(self, contract: str, default):
        if contract not in self.CONTRACTS:
            raise KeyError(f"undeclared contract: {contract}")
        if contract not in self.available:
            return {"degraded": True, "reason": f"{contract} not yet provided by v1.5 build",
                    "value": default}
        return {"degraded": False, "value": default}

    def readiness(self) -> dict:
        return {c: (c in self.available) for c in self.CONTRACTS}


# ── GAP 3: incremental render (no full-site rebuilds) ──────────────────────────
class RenderGraph:
    """Dependency graph: a canonical change regenerates only affected pages."""
    def __init__(self):
        self.deps: dict[str, set[str]] = {}   # page -> sources it depends on

    def register(self, page: str, sources: Iterable[str]):
        self.deps[page] = set(sources)

    def affected(self, changed: Iterable[str]) -> list[str]:
        changed = set(changed)
        return sorted(p for p, s in self.deps.items() if s & changed)

    def rebuild(self, changed: Iterable[str]) -> dict:
        pages = self.affected(changed)
        return {"changed_sources": sorted(set(changed)),
                "rebuilt_pages": pages,
                "skipped_pages": len(self.deps) - len(pages)}


# ── GAP 4: cost governance + budget freeze ─────────────────────────────────────
@dataclass
class CostLedger:
    daily_budget_usd: float
    spent: float = 0.0
    by_worker: dict = field(default_factory=dict)
    frozen: bool = False
    freeze_reason: str = ""

    def charge(self, worker: str, usd: float) -> bool:
        if self.frozen:
            return False
        if self.spent + usd > self.daily_budget_usd:
            self.frozen = True
            self.freeze_reason = f"BUDGET_EXCEEDED at {worker}"
            return False
        self.spent += usd
        self.by_worker[worker] = round(self.by_worker.get(worker, 0.0) + usd, 4)
        return True

    def utilization(self) -> float:
        return round(self.spent / self.daily_budget_usd, 3)


# ── GAP 5: locale routing + hreflang ───────────────────────────────────────────
class LocaleRouter:
    LOCALES = ("en", "de", "fr")

    @staticmethod
    def url(locale: str, slug: str) -> str:
        base = "https://www.sovereignsanctuary.net"
        return f"{base}/coaches/{slug}" if locale == "en" else f"{base}/{locale}/coaches/{slug}"

    @classmethod
    def hreflang_block(cls, slug: str, available: Iterable[str]) -> list[dict]:
        av = [l for l in cls.LOCALES if l in set(available)]
        tags = [{"rel": "alternate", "hreflang": l, "href": cls.url(l, slug)} for l in av]
        tags.append({"rel": "alternate", "hreflang": "x-default", "href": cls.url("en", slug)})
        return tags


# ── GAP 6: worker resilience — retry, dead-letter, heartbeat ───────────────────
class WorkerRuntime:
    def __init__(self, max_attempts=3, stale_after_s=90):
        self.dead_letter: list[dict] = []
        self.heartbeats: dict[str, float] = {}
        self.max_attempts = max_attempts
        self.stale_after_s = stale_after_s

    def run(self, worker: str, fn: Callable, *args):
        delay = 0.0
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = fn(*args)
                self.heartbeats[worker] = time.time()
                return {"worker": worker, "ok": True, "attempts": attempt, "result": result}
            except Exception as e:                      # noqa: BLE001
                delay = (2 ** (attempt - 1)) * 0.01     # exponential backoff
                time.sleep(delay)
                last = str(e)
        self.dead_letter.append({"worker": worker, "error": last, "args": repr(args)})
        return {"worker": worker, "ok": False, "attempts": self.max_attempts, "dead_lettered": True}

    def stale_workers(self, expected: Iterable[str]) -> list[str]:
        now = time.time()
        return sorted(w for w in expected
                      if w not in self.heartbeats or now - self.heartbeats[w] > self.stale_after_s)


# ── GAP 7: search-console ingestion into multi-horizon memory ──────────────────
HORIZONS = (7, 30, 90, 180, 365)


def consolidate_horizons(daily_series: list[float]) -> list[dict]:
    """
    Aggregate a daily metric into the five horizons.
    BUGFIX (caught by test): a horizon lacking a full prior window must report
    trend='insufficient_history', NOT 'stable'. Reporting young horizons as
    stable silently suppresses the §15.2 divergence rule during the system's
    first year — exactly when backfilled/short history is normal.
    """
    rows = []
    n = len(daily_series)
    for h in HORIZONS:
        window = daily_series[-h:] if n >= h else daily_series
        has_window = n >= h
        has_prior = n >= 2 * h
        prior = daily_series[-2 * h:-h] if has_prior else []
        val = sum(window) / max(1, len(window))
        if not has_prior:
            rows.append({"horizon_days": h, "value": round(val, 3),
                         "delta_vs_prior": None, "trend": "insufficient_history",
                         "window_complete": has_window})
            continue
        pri = sum(prior) / len(prior)
        delta = val - pri
        trend = "rising" if delta > 0.05 * max(pri, 1e-9) else \
                "declining" if delta < -0.05 * max(pri, 1e-9) else "stable"
        rows.append({"horizon_days": h, "value": round(val, 3),
                     "delta_vs_prior": round(delta, 3), "trend": trend,
                     "window_complete": has_window})
    return rows


def divergence_action(rows: list[dict]) -> str:
    """
    §15.2 binding rule: short-vs-long conflict → experiment, long horizon governs.
    Compares 7d against the LONGEST horizon that has real history, so the rule
    still functions before 360+ days of data exist.
    """
    short = next(r for r in rows if r["horizon_days"] == 7)
    usable = [r for r in rows if r["horizon_days"] > 7 and r["trend"] != "insufficient_history"]
    if not usable:
        return "INSUFFICIENT_HISTORY: observe only, no strategy change"
    long_ = max(usable, key=lambda r: r["horizon_days"])
    if short["trend"] == "insufficient_history":
        return f"FOLLOW_TREND:{long_['trend']} (h={long_['horizon_days']})"
    if short["trend"] != long_["trend"] and "stable" not in (short["trend"], long_["trend"]):
        return (f"OPEN_EXPERIMENT (7d={short['trend']} vs "
                f"{long_['horizon_days']}d={long_['trend']}; long horizon governs strategy)")
    return f"FOLLOW_TREND:{long_['trend']} (h={long_['horizon_days']})"


# ── GAP 8: staging + canary promotion for autonomous changes ───────────────────
class CanaryPromoter:
    def __init__(self, canary_share=0.1, min_samples=200, degrade_threshold=-0.10):
        self.canary_share, self.min_samples = canary_share, min_samples
        self.degrade_threshold = degrade_threshold

    def evaluate(self, control_rate: float, variant_rate: float, samples: int) -> dict:
        if samples < self.min_samples:
            return {"decision": "HOLD", "reason": "insufficient_samples"}
        lift = (variant_rate - control_rate) / max(control_rate, 1e-9)
        if lift <= self.degrade_threshold:
            return {"decision": "ROLLBACK", "lift": round(lift, 3)}
        if lift > 0.05:
            return {"decision": "PROMOTE", "lift": round(lift, 3)}
        return {"decision": "CONTINUE", "lift": round(lift, 3)}


# ── GAP: register linter (existing worker #15) — proof it blocks pre-publish ────
CLINICAL_TERMS = {"therapy", "treatment", "psychotherapy", "diagnose", "diagnosis", "patient"}


def register_lint(text: str, relationship_class: str) -> dict:
    hits = sorted({w for w in CLINICAL_TERMS if w in text.lower()})
    blocked = bool(hits) and relationship_class != "clinical"
    return {"blocked": blocked, "violations": hits,
            "action": "BLOCK_PUBLISH+QUEENS_RED" if blocked else "ALLOW"}
