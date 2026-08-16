"""Port of geo-sources/test_workers_61_64.py — 35/35 §22 proof."""

import random
from datetime import timedelta

from app.services.disco.pipeline import RenderGraph
from app.services.disco.workers_61_64 import (
    CACLedger,
    Candidate,
    ClaimTruthRegister,
    CredentialClaim,
    DemandCluster,
    EditorialModel,
    ExperimentEvaluator,
    InlineValueRenderer,
    NOW,
    RecruitmentEngine,
    SourceRecord,
    SourceTier,
    VerificationOrchestrator,
)

R = []


def check(name, cond, detail=""):
    R.append((name, cond))
    assert cond, f"{name}{(' :: ' + detail) if detail else ''}"


def test_disco_workers_61_64_35():
    R.clear()

    def npi_api(claim):
        db = {"1234567890": ("Jane A Doe", "MI", "active", NOW() + timedelta(days=400))}
        if claim.identifier in db:
            n, j, s, e = db[claim.identifier]
            return SourceRecord(True, n, claim.identifier, j, s, e, SourceTier.PRIMARY_API, "NPI Registry")
        return SourceRecord(False)

    def board_portal(claim):
        return SourceRecord(
            True, "Marcus Webb", claim.identifier, claim.jurisdiction, "active",
            NOW() + timedelta(days=200), SourceTier.PRIMARY_PORTAL, "MI LARA Portal",
        )

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
    check("zero-touch attestation for clean primary-source claim", r1["decision"] == "AUTO_ATTESTED")
    check("attestation signature verifies", vo.verify_signature(r1["attestation"], r1["signature"]))
    check(
        "attestation records method + authority",
        r1["attestation"]["method"] == "primary_source_api" and r1["attestation"]["issuing_authority"] == "NPI Registry",
    )
    check("portal-only source routes to human (honest scope limit)", r2["decision"] == "HUMAN_CONFIRM")
    check("fuzzy name <95% routes to human", r3["decision"] == "HUMAN_CONFIRM")
    check("near-expiry routes to human", r4["decision"] == "HUMAN_CONFIRM")
    check("unknown credential type routes to human", r5["decision"] == "HUMAN_CONFIRM")
    tampered = dict(r1["attestation"])
    tampered["status"] = "active-forever"
    check("tampered attestation fails signature check", not vo.verify_signature(tampered, r1["signature"]))

    r = InlineValueRenderer()
    page = r.render_page("<p>Postpartum rage is more common than you were told…</p>", "grounding_60s", region="US")
    check("no <script> anywhere in rendered page", "<script" not in page)
    check("crisis resources in initial HTML", "988" in page)
    check("crisis banner precedes article body", page.index("ss-crisis") < page.index("ss-article"))
    check("value unit present before article", page.index("ss-value") < page.index("ss-article"))
    for unit in ("grounding_60s", "postpartum_selfcheck", "boundary_assessment"):
        html = r.render_page("<p>x</p>", unit, "DE")
        ok = ("<script" not in html) and ("ss-value" in html) and not r.contains_conversion_ask(html)
        check(f"unit '{unit}' is JS-free and ask-free", ok)
    check("regional crisis numbers swap by locale", "08001110111" in r.render_page("<p>x</p>", "grounding_60s", "DE"))

    ev = ExperimentEvaluator()
    random.seed(7)
    control = [1.0 if random.random() < 0.040 else 0.0 for _ in range(4000)]
    winner = [1.0 if random.random() < 0.058 else 0.0 for _ in range(4000)]
    loser = [1.0 if random.random() < 0.026 else 0.0 for _ in range(4000)]
    noise = [1.0 if random.random() < 0.041 else 0.0 for _ in range(4000)]
    e_win, e_lose, e_noise = ev.evaluate(control, winner), ev.evaluate(control, loser), ev.evaluate(control, noise)
    small = ev.evaluate(control[:100], winner[:100])
    check("significant winner promoted (p<0.05)", e_win["decision"] == "PROMOTE" and e_win["p_value"] < 0.05)
    check("significant degradation rolled back", e_lose["decision"] == "ROLLBACK")
    check("non-significant difference not promoted", e_noise["decision"] == "CONTINUE")
    check("underpowered test held", small["decision"] == "HOLD")

    led = CACLedger(editorial=EditorialModel())
    periods = [(20, 40, 6), (60, 180, 30), (150, 700, 120), (400, 2600, 460), (900, 9000, 1600)]
    for n, s, sub in periods:
        led.period(n, s, sub, compute_usd=15 + 0.22 * n)
    t = led.trend()
    apa = [e["admin_usd_per_article"] for e in led.entries]
    check(
        "admin cost per article falls as volume grows (sampling, not batching)",
        apa[-1] < apa[0] / 3,
        f"{apa[0]:.4f} -> {apa[-1]:.4f}",
    )
    check("CAC per subscriber declines across periods", t["trend"] == "declining", f"{t['first']} -> {t['last']}")
    naive = EditorialModel(admin_sample_per_period=10**9)
    check(
        "exhaustive review would NOT scale (control case)",
        naive.admin_cost(900) > led.editorial.admin_cost(900) * 5,
    )

    ctr = ClaimTruthRegister(led)
    bad1 = ctr.check("Our system delivers near-zero cost acquisition with zero CAC.")
    bad2 = ctr.check("We acquire subscribers at a CAC of $0.05.")
    good = ctr.check("Our acquisition costs decline as organic authority compounds.")
    check("absolute 'zero CAC' claim blocked", bad1["blocked"])
    check("claim below measured CAC blocked", bad2["blocked"])
    check("honest directional claim allowed", not good["blocked"])

    clusters = [
        DemandCluster("Somatic Trauma", "Detroit MI", "en", 142, 0),
        DemandCluster("Perinatal", "Lyon FR", "fr", 96, 0),
        DemandCluster("ADHD", "Austin TX", "en", 210, 4),
    ]

    def sourcer(c):
        if c.geo.endswith("FR"):
            return [Candidate("c_fr", "Camille Roux", "Psychologue", "FR", "c@ex.fr", "public_dir", region="EU")]
        return [
            Candidate("c_us1", "Dana Ellis", "LMSW", "MI", "d@ex.com", "public_dir"),
            Candidate("c_us2", "Rob Kane", "LPC", "MI", "r@ex.com", "public_dir"),
        ]

    sent_log = []

    def sender(to, subj, body):
        sent_log.append((to, subj, body))
        return True

    eng = RecruitmentEngine(sourcer, sender, eu_outreach_approved=False)
    found = eng.source(clusters)
    check("supplied cluster (ADHD Austin) not sourced", all("Austin" not in h for c in found for h in c.history))
    zs = clusters[0]
    o1 = eng.outreach(eng.pipeline["c_us1"], zs)
    o2 = eng.outreach(eng.pipeline["c_fr"], clusters[1])
    check("outreach carries exact localized demand data", "142" in o1["subject"] and "Detroit MI" in o1["subject"])
    check("EU candidate blocked pending legitimate-interest approval", not o2["sent"])
    check("outreach body passes register lint (coaching register)", o1["sent"] is True)
    check("opt-out present in outreach", "STOP" in sent_log[0][2])
    eng.outreach(eng.pipeline["c_us2"], zs)
    eng.handle_reply("c_us1", "Yes — interested, send times", credential_ok=True)
    eng.handle_reply("c_us2", "Not interested, please stop", credential_ok=True)
    f = eng.funnel()
    check("qualified candidate auto-booked to closer", f["booked_meetings"] == 1)
    check("opt-out reply marked declined, no further contact", f["declined"] == 1)
    check("full state history retained for audit", len(eng.pipeline["c_us1"].history) >= 3)

    g = RenderGraph()
    g.register("/hubs/somatic-trauma/detroit-mi", ["canonical:c_us1", "taxonomy:somatic"])
    after = g.rebuild(["canonical:c_us1"])
    check("new coach activation unblocks the localized hub", "/hubs/somatic-trauma/detroit-mi" in after["rebuilt_pages"])

    assert sum(1 for _, c in R if c) == 35
    assert len(R) == 35
