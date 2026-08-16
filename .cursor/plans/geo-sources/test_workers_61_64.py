"""Proof harness for workers #61–#64 (§22). Each block prints verifiable evidence."""
from datetime import timedelta
from disco_workers_61_64 import *

R = []
def check(name, cond, detail=""):
    R.append((name, cond)); print(f"  {'PASS' if cond else 'FAIL'} — {name}{(' :: '+detail) if detail else ''}")

# ── #61 ──────────────────────────────────────────────────────────────────────
print("\nWORKER #61 — disco_verification_orchestrator (zero-touch verification)")

def npi_api(claim):  # official API → zero-touch eligible
    db = {"1234567890": ("Jane A Doe", "MI", "active", NOW() + timedelta(days=400))}
    if claim.identifier in db:
        n, j, s, e = db[claim.identifier]
        return SourceRecord(True, n, claim.identifier, j, s, e, SourceTier.PRIMARY_API, "NPI Registry")
    return SourceRecord(False)

def board_portal(claim):  # official but portal-only → assisted, not zero-touch
    return SourceRecord(True, "Marcus Webb", claim.identifier, claim.jurisdiction, "active",
                        NOW() + timedelta(days=200), SourceTier.PRIMARY_PORTAL, "MI LARA Portal")

def icf_api(claim):
    db = {"PCC-88221": ("Ana Ruiz Delgado", "GLOBAL", "active", NOW() + timedelta(days=500))}
    if claim.identifier in db:
        n, j, s, e = db[claim.identifier]
        return SourceRecord(True, n, claim.identifier, j, s, e, SourceTier.PRIMARY_API, "ICF Registry")
    return SourceRecord(False)

vo = VerificationOrchestrator({"NPI": npi_api, "LMFT": board_portal, "ICF-PCC": icf_api})

c_clean = CredentialClaim("coach_1", "Jane A Doe", "NPI", "MI", "1234567890")
c_portal = CredentialClaim("coach_2", "Marcus Webb", "LMFT", "MI", "LMFT-4471")
c_fuzzy = CredentialClaim("coach_3", "A. Ruiz", "ICF-PCC", "GLOBAL", "PCC-88221")
c_expiring = CredentialClaim("coach_4", "Jane A Doe", "NPI", "MI", "1234567890")
c_expiring.expires_at = NOW() + timedelta(days=10)
c_none = CredentialClaim("coach_5", "Sam Ito", "UNKNOWN-CERT", "CA", "X-1")

r1, r2, r3, r4, r5 = (vo.process(x) for x in (c_clean, c_portal, c_fuzzy, c_expiring, c_none))
print(f"   clean primary-API claim : {r1['decision']} (conf {r1['confidence']})")
print(f"   portal-only source      : {r2['decision']} {r2.get('reasons')}")
print(f"   fuzzy name              : {r3['decision']} {r3.get('reasons')}")
print(f"   expiring in 10d         : {r4['decision']} {r4.get('reasons')}")
print(f"   no machine source       : {r5['decision']} {r5.get('reasons')}")
check("zero-touch attestation for clean primary-source claim", r1["decision"] == "AUTO_ATTESTED")
check("attestation signature verifies", vo.verify_signature(r1["attestation"], r1["signature"]))
check("attestation records method + authority",
      r1["attestation"]["method"] == "primary_source_api" and r1["attestation"]["issuing_authority"] == "NPI Registry")
check("portal-only source routes to human (honest scope limit)", r2["decision"] == "HUMAN_CONFIRM")
check("fuzzy name <95% routes to human", r3["decision"] == "HUMAN_CONFIRM")
check("near-expiry routes to human", r4["decision"] == "HUMAN_CONFIRM")
check("unknown credential type routes to human", r5["decision"] == "HUMAN_CONFIRM")
tampered = dict(r1["attestation"]); tampered["status"] = "active-forever"
check("tampered attestation fails signature check", not vo.verify_signature(tampered, r1["signature"]))

# ── #62 ──────────────────────────────────────────────────────────────────────
print("\nWORKER #62 — disco_inline_value_renderer (zero-JS value + crisis banner)")
r = InlineValueRenderer()
page = r.render_page("<p>Postpartum rage is more common than you were told…</p>",
                     "grounding_60s", region="US")
print(f"   page length: {len(page)} chars, scripts present: {'<script' in page}")
print(f"   crisis banner sample: {page[page.index('<aside'):page.index('</aside>')+8][:120]}…")
check("no <script> anywhere in rendered page", "<script" not in page)
check("crisis resources in initial HTML", "988" in page)
check("crisis banner precedes article body", page.index("ss-crisis") < page.index("ss-article"))
check("value unit present before article", page.index("ss-value") < page.index("ss-article"))
for unit in ("grounding_60s", "postpartum_selfcheck", "boundary_assessment"):
    html = r.render_page("<p>x</p>", unit, "DE")
    ok = ("<script" not in html) and ("ss-value" in html) and not r.contains_conversion_ask(html)
    check(f"unit '{unit}' is JS-free and ask-free", ok)
check("regional crisis numbers swap by locale", "08001110111" in r.render_page("<p>x</p>", "grounding_60s", "DE"))

print("\n  statistical engine (Welch's t-test auto-promotion)")
ev = ExperimentEvaluator()
import random
random.seed(7)
control = [1.0 if random.random() < 0.040 else 0.0 for _ in range(4000)]
winner  = [1.0 if random.random() < 0.058 else 0.0 for _ in range(4000)]
loser   = [1.0 if random.random() < 0.026 else 0.0 for _ in range(4000)]
noise   = [1.0 if random.random() < 0.041 else 0.0 for _ in range(4000)]
e_win, e_lose, e_noise = ev.evaluate(control, winner), ev.evaluate(control, loser), ev.evaluate(control, noise)
small = ev.evaluate(control[:100], winner[:100])
print(f"   winner: {e_win}")
print(f"   loser : {e_lose}")
print(f"   noise : {e_noise}")
print(f"   small : {small}")
check("significant winner promoted (p<0.05)", e_win["decision"] == "PROMOTE" and e_win["p_value"] < 0.05)
check("significant degradation rolled back", e_lose["decision"] == "ROLLBACK")
check("non-significant difference not promoted", e_noise["decision"] == "CONTINUE")
check("underpowered test held", small["decision"] == "HOLD")

# ── #63 ──────────────────────────────────────────────────────────────────────
print("\nWORKER #63 — disco_cac_ledger (asymptotic human cost + claim-truth gate)")
led = CACLedger(editorial=EditorialModel())
periods = [(20, 40, 6), (60, 180, 30), (150, 700, 120), (400, 2600, 460), (900, 9000, 1600)]
print(f"   {'articles':>9} {'signups':>8} {'subs':>6} {'admin$':>8} {'admin$/art':>11} {'CAC/sub':>9}")
for n, s, sub in periods:
    row = led.period(n, s, sub, compute_usd=15 + 0.22 * n)
    print(f"   {row['n_articles']:>9} {row['signups']:>8} {row['subscribers']:>6} "
          f"{row['admin_usd']:>8.2f} {row['admin_usd_per_article']:>11.4f} {row['cac_subscriber']:>9.3f}")
t = led.trend()
print(f"   trend: {t}")
apa = [e["admin_usd_per_article"] for e in led.entries]
check("admin cost per article falls as volume grows (sampling, not batching)", apa[-1] < apa[0] / 3,
      f"{apa[0]:.4f} -> {apa[-1]:.4f}")
check("CAC per subscriber declines across periods", t["trend"] == "declining",
      f"{t['first']} -> {t['last']} ({t['pct_change']}%)")
naive = EditorialModel(admin_sample_per_period=10**9)  # review everything
check("exhaustive review would NOT scale (control case)",
      naive.admin_cost(900) > led.editorial.admin_cost(900) * 5,
      f"exhaustive ${naive.admin_cost(900):.2f} vs sampled ${led.editorial.admin_cost(900):.2f}")

ctr = ClaimTruthRegister(led)
bad1 = ctr.check("Our system delivers near-zero cost acquisition with zero CAC.")
bad2 = ctr.check(f"We acquire subscribers at a CAC of $0.05.")
good = ctr.check("Our acquisition costs decline as organic authority compounds.")
print(f"   absolute claim : {bad1}")
print(f"   understated CAC: {bad2}")
print(f"   honest claim   : {good}")
check("absolute 'zero CAC' claim blocked", bad1["blocked"])
check("claim below measured CAC blocked", bad2["blocked"])
check("honest directional claim allowed", not good["blocked"])

# ── #64 ──────────────────────────────────────────────────────────────────────
print("\nWORKER #64 — disco_recruitment_engine (closed demand→supply loop)")
clusters = [DemandCluster("Somatic Trauma", "Detroit MI", "en", 142, 0),
            DemandCluster("Perinatal", "Lyon FR", "fr", 96, 0),
            DemandCluster("ADHD", "Austin TX", "en", 210, 4)]

def sourcer(c):
    if c.geo.endswith("FR"):
        return [Candidate("c_fr", "Camille Roux", "Psychologue", "FR", "c@ex.fr", "public_dir", region="EU")]
    return [Candidate("c_us1", "Dana Ellis", "LMSW", "MI", "d@ex.com", "public_dir"),
            Candidate("c_us2", "Rob Kane", "LPC", "MI", "r@ex.com", "public_dir")]

sent_log = []
def sender(to, subj, body):
    sent_log.append((to, subj, body)); return True

eng = RecruitmentEngine(sourcer, sender, eu_outreach_approved=False)
found = eng.source(clusters)
print(f"   zero-supply clusters processed: 2, candidates sourced: {len(found)}")
check("supplied cluster (ADHD Austin) not sourced", all("Austin" not in h for c in found for h in c.history))

zs = clusters[0]
o1 = eng.outreach(eng.pipeline["c_us1"], zs)
o2 = eng.outreach(eng.pipeline["c_fr"], clusters[1])
print(f"   US outreach subject: {o1.get('subject')}")
print(f"   EU outreach result : {o2}")
check("outreach carries exact localized demand data", "142" in o1["subject"] and "Detroit MI" in o1["subject"])
check("EU candidate blocked pending legitimate-interest approval", not o2["sent"])
check("outreach body passes register lint (coaching register)", o1["sent"] is True)
check("opt-out present in outreach", "STOP" in sent_log[0][2])

eng.outreach(eng.pipeline["c_us2"], zs)
eng.handle_reply("c_us1", "Yes — interested, send times", credential_ok=True)
eng.handle_reply("c_us2", "Not interested, please stop", credential_ok=True)
f = eng.funnel()
print(f"   funnel: {f}")
print(f"   booked: {eng.booked}")
check("qualified candidate auto-booked to closer", f["booked_meetings"] == 1)
check("opt-out reply marked declined, no further contact", f["declined"] == 1)
check("full state history retained for audit", len(eng.pipeline["c_us1"].history) >= 3)

print("\n  closed-loop proof: onboarding a recruited coach unblocks the hub")
from disco_pipeline import RenderGraph
g = RenderGraph()
g.register("/hubs/somatic-trauma/detroit-mi", ["canonical:c_us1", "taxonomy:somatic"])
before = g.affected([])
after = g.rebuild(["canonical:c_us1"])
print(f"   hub pages rebuilt on coach activation: {after['rebuilt_pages']}")
check("new coach activation unblocks the localized hub", "/hubs/somatic-trauma/detroit-mi" in after["rebuilt_pages"])

total, passed = len(R), sum(1 for _, c in R if c)
print(f"\n{'='*66}\nRESULT: {passed}/{total} checks passed\n{'='*66}")
