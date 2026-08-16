"""Port of geo-sources/test_disco_pipeline.py — 27/27 §18 proof."""

from app.services.disco.pipeline import (
    BuildBoundary,
    CanaryPromoter,
    CostLedger,
    EngineAdapter,
    LocaleRouter,
    ProbeMode,
    ProbeScheduler,
    RenderGraph,
    WorkerRuntime,
    consolidate_horizons,
    divergence_action,
    register_lint,
)

PASS = []


def check(name, cond, detail=""):
    PASS.append((name, cond))
    assert cond, f"{name}{(' :: ' + detail) if detail else ''}"


def test_disco_pipeline_27():
    PASS.clear()

    adapters = [
        EngineAdapter("engine_api", ProbeMode.API, max_daily=500),
        EngineAdapter("engine_grounded", ProbeMode.GROUNDED, max_daily=300),
        EngineAdapter("engine_manual", ProbeMode.MANUAL, max_daily=20),
    ]
    prompts = [f"prompt_{i}" for i in range(32)]
    sched = ProbeScheduler(adapters)
    plan_low = sched.daily_plan(prompts)
    sched.volatility = 0.9
    plan_high = sched.daily_plan(prompts)
    res = sched.run(prompts)
    check("automation degrades per engine instead of failing", plan_low["engine_manual"] < plan_low["engine_api"])
    check("sampling escalates on volatility", sum(plan_high.values()) > sum(plan_low.values()))
    check("manual-mode engine still yields data", any(r["engine"] == "engine_manual" for r in res))

    b_partial = BuildBoundary(available=["credentials"])
    r1 = b_partial.get("credentials", {"class": "licensed_clinical"})
    r2 = b_partial.get("engagements", [])
    check("available contract returns live data", r1["degraded"] is False)
    check("missing contract degrades, does not crash", r2["degraded"] is True)
    try:
        b_partial.get("some_random_table", None)
        check("undeclared access blocked", False)
    except KeyError as e:
        check("undeclared table access raises", True, str(e))

    g = RenderGraph()
    for i in range(500):
        g.register(f"/coaches/coach_{i}", [f"canonical:{i}"])
    g.register("/hubs/trauma/michigan", ["canonical:7", "canonical:12", "taxonomy:trauma"])
    g.register("/llms.txt", [f"canonical:{i}" for i in range(500)])
    out = g.rebuild(["canonical:7"])
    check("single change does not trigger full rebuild", len(out["rebuilt_pages"]) < 5)
    check("dependent hub page included", "/hubs/trauma/michigan" in out["rebuilt_pages"])
    check("aggregate page (llms.txt) included", "/llms.txt" in out["rebuilt_pages"])

    led = CostLedger(daily_budget_usd=25.0)
    ok_count = 0
    for _i in range(400):
        if led.charge("disco_visibility_panel", 0.08):
            ok_count += 1
    check("spend never exceeds budget", led.spent <= 25.0)
    check("freeze triggers automatically", led.frozen is True)
    check("post-freeze charges rejected", led.charge("any_worker", 0.01) is False)
    assert ok_count > 0

    tags = LocaleRouter.hreflang_block("jane-doe", ["en", "de"])
    check("x-default present", any(t["hreflang"] == "x-default" for t in tags))
    check("unavailable locale omitted", not any(t["hreflang"] == "fr" for t in tags))
    check("non-en uses locale prefix", "/de/coaches/" in LocaleRouter.url("de", "jane-doe"))

    rt = WorkerRuntime()
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("transient upstream error")
        return "ok"

    def always_fails():
        raise RuntimeError("permanent failure")

    r_ok = rt.run("disco_drift_auditor", flaky)
    r_bad = rt.run("disco_gbp_manager", always_fails)
    stale = rt.stale_workers(["disco_drift_auditor", "disco_canonical_renderer", "disco_gbp_manager"])
    check("transient failure recovers via retry", r_ok["ok"] and r_ok["attempts"] == 3)
    check("permanent failure dead-letters, no crash", r_bad.get("dead_lettered") is True)
    check("silent worker detected by heartbeat", "disco_canonical_renderer" in stale)

    series = [max(0.0, 100 - i * 0.4) for i in range(193)] + [140, 150, 160, 155, 165, 170, 168]
    rows = consolidate_horizons(series)
    action = divergence_action(rows)
    check("all five horizons computed", len(rows) == 5)
    check("7d spike vs long-horizon decline opens an experiment", action.startswith("OPEN_EXPERIMENT"))
    young = consolidate_horizons([50.0] * 60)
    y180 = next(r for r in young if r["horizon_days"] == 180)
    check("young horizon reports insufficient_history, not false 'stable'",
          y180["trend"] == "insufficient_history")

    cp = CanaryPromoter()
    check("insufficient samples held", cp.evaluate(0.04, 0.06, 50)["decision"] == "HOLD")
    check("winner promoted", cp.evaluate(0.04, 0.052, 1000)["decision"] == "PROMOTE")
    check("degradation rolled back", cp.evaluate(0.04, 0.030, 1000)["decision"] == "ROLLBACK")

    coaching_bad = register_lint("Trauma treatment and psychotherapy for patients", "coaching")
    coaching_ok = register_lint("Trauma-informed integration coaching and support", "coaching")
    clinical_ok = register_lint("Trauma treatment and psychotherapy", "clinical")
    check("clinical language on coaching profile is BLOCKED", coaching_bad["blocked"] is True)
    check("correct coaching register allowed", coaching_ok["blocked"] is False)
    check("clinical profile may use clinical terms", clinical_ok["blocked"] is False)

    assert sum(1 for _, c in PASS if c) == 27
    assert len(PASS) == 27
