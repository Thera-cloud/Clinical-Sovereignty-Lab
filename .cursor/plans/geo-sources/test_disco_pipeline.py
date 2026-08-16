"""Proof harness — each block prints verifiable evidence for one §18 gap fix."""
from disco_pipeline import *

PASS = []


def check(name, cond, detail=""):
    PASS.append((name, cond))
    print(f"  {'PASS' if cond else 'FAIL'} — {name}{(' :: ' + detail) if detail else ''}")


print("\nGAP 1 — probe automation with graded fallback")
adapters = [
    EngineAdapter("engine_api", ProbeMode.API, max_daily=500),
    EngineAdapter("engine_grounded", ProbeMode.GROUNDED, max_daily=300),
    EngineAdapter("engine_manual", ProbeMode.MANUAL, max_daily=20),
]
prompts = [f"prompt_{i}" for i in range(32)]  # T3.1 set, 8 classes x 4
sched = ProbeScheduler(adapters)
plan_low = sched.daily_plan(prompts)
sched.volatility = 0.9
plan_high = sched.daily_plan(prompts)
print(f"   normal plan: {plan_low}")
print(f"   volatile plan (auto-escalated): {plan_high}")
res = sched.run(prompts)
named = sum(1 for r in res if r["named_entities"])
print(f"   probes executed: {len(res)}, named results: {named}, coverage: {sched.coverage(prompts):.2f}")
check("automation degrades per engine instead of failing", plan_low["engine_manual"] < plan_low["engine_api"])
check("sampling escalates on volatility", sum(plan_high.values()) > sum(plan_low.values()))
check("manual-mode engine still yields data", any(r["engine"] == "engine_manual" for r in res))

print("\nGAP 2 — integration contract with the v1.5 build")
b_partial = BuildBoundary(available=["credentials"])
r1 = b_partial.get("credentials", {"class": "licensed_clinical"})
r2 = b_partial.get("engagements", [])
print(f"   readiness: {b_partial.readiness()}")
print(f"   engagements (not yet built): {r2}")
check("available contract returns live data", r1["degraded"] is False)
check("missing contract degrades, does not crash", r2["degraded"] is True)
try:
    b_partial.get("some_random_table", None)
    check("undeclared access blocked", False)
except KeyError as e:
    check("undeclared table access raises", True, str(e))

print("\nGAP 3 — incremental render (no full-site rebuild)")
g = RenderGraph()
for i in range(500):
    g.register(f"/coaches/coach_{i}", [f"canonical:{i}"])
g.register("/hubs/trauma/michigan", ["canonical:7", "canonical:12", "taxonomy:trauma"])
g.register("/llms.txt", [f"canonical:{i}" for i in range(500)])
out = g.rebuild(["canonical:7"])
print(f"   changed 1 record -> rebuilt {len(out['rebuilt_pages'])} pages, skipped {out['skipped_pages']}")
print(f"   rebuilt: {out['rebuilt_pages']}")
check("single change does not trigger full rebuild", len(out["rebuilt_pages"]) < 5)
check("dependent hub page included", "/hubs/trauma/michigan" in out["rebuilt_pages"])
check("aggregate page (llms.txt) included", "/llms.txt" in out["rebuilt_pages"])

print("\nGAP 4 — cost governance + budget freeze")
led = CostLedger(daily_budget_usd=25.0)
ok_count = 0
for i in range(400):
    if led.charge("disco_visibility_panel", 0.08):
        ok_count += 1
print(f"   charges accepted: {ok_count}, spend: ${led.spent:.2f}, utilization: {led.utilization()}")
print(f"   frozen: {led.frozen} ({led.freeze_reason})")
check("spend never exceeds budget", led.spent <= 25.0)
check("freeze triggers automatically", led.frozen is True)
check("post-freeze charges rejected", led.charge("any_worker", 0.01) is False)

print("\nGAP 5 — locale routing + hreflang")
tags = LocaleRouter.hreflang_block("jane-doe", ["en", "de"])
for t in tags:
    print(f"   {t}")
check("x-default present", any(t["hreflang"] == "x-default" for t in tags))
check("unavailable locale omitted", not any(t["hreflang"] == "fr" for t in tags))
check("non-en uses locale prefix", "/de/coaches/" in LocaleRouter.url("de", "jane-doe"))

print("\nGAP 6 — worker resilience: retry, dead-letter, heartbeat")
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
print(f"   flaky worker: {r_ok}")
print(f"   failing worker: {r_bad}")
print(f"   dead letter queue: {len(rt.dead_letter)} item(s)")
stale = rt.stale_workers(["disco_drift_auditor", "disco_canonical_renderer", "disco_gbp_manager"])
print(f"   stale/never-reported workers: {stale}")
check("transient failure recovers via retry", r_ok["ok"] and r_ok["attempts"] == 3)
check("permanent failure dead-letters, no crash", r_bad.get("dead_lettered") is True)
check("silent worker detected by heartbeat", "disco_canonical_renderer" in stale)

print("\nGAP 7 — search-console ingestion into 7/30/90/180/365 memory")
# 200 days: long-term decline, recent 7-day spike (the divergence case)
series = [max(0.0, 100 - i * 0.4) for i in range(193)] + [140, 150, 160, 155, 165, 170, 168]
rows = consolidate_horizons(series)
for r in rows:
    print(f"   {r}")
action = divergence_action(rows)
print(f"   divergence rule -> {action}")
check("all five horizons computed", len(rows) == 5)
check("7d spike vs long-horizon decline opens an experiment", action.startswith("OPEN_EXPERIMENT"))

# regression: young system (60 days) must not report false stability
young = consolidate_horizons([50.0] * 60)
y180 = next(r for r in young if r["horizon_days"] == 180)
print(f"   young system 180d row: {y180}")
print(f"   young system action -> {divergence_action(young)}")
check("young horizon reports insufficient_history, not false 'stable'",
      y180["trend"] == "insufficient_history")

print("\nGAP 8 — staging/canary promotion for autonomous changes")
cp = CanaryPromoter()
print(f"   small sample:  {cp.evaluate(0.040, 0.060, 50)}")
print(f"   clear winner:  {cp.evaluate(0.040, 0.052, 1000)}")
print(f"   degradation:   {cp.evaluate(0.040, 0.030, 1000)}")
check("insufficient samples held", cp.evaluate(0.04, 0.06, 50)["decision"] == "HOLD")
check("winner promoted", cp.evaluate(0.04, 0.052, 1000)["decision"] == "PROMOTE")
check("degradation rolled back", cp.evaluate(0.04, 0.030, 1000)["decision"] == "ROLLBACK")

print("\nBONUS — register linter (worker #15) blocking proof")
coaching_bad = register_lint("Trauma treatment and psychotherapy for patients", "coaching")
coaching_ok = register_lint("Trauma-informed integration coaching and support", "coaching")
clinical_ok = register_lint("Trauma treatment and psychotherapy", "clinical")
print(f"   coaching profile w/ clinical terms: {coaching_bad}")
print(f"   coaching profile, correct register: {coaching_ok}")
print(f"   clinical profile, clinical terms:   {clinical_ok}")
check("clinical language on coaching profile is BLOCKED", coaching_bad["blocked"] is True)
check("correct coaching register allowed", coaching_ok["blocked"] is False)
check("clinical profile may use clinical terms", clinical_ok["blocked"] is False)

total = len(PASS)
passed = sum(1 for _, c in PASS if c)
print(f"\n{'='*62}\nRESULT: {passed}/{total} checks passed\n{'='*62}")
