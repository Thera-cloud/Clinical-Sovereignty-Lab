"""
Sovereign Sanctuary — Workers #61–#64 reference implementations (§22).
Closes the §21 conditional passes. Pure stdlib; network boundaries stubbed.
"""
from __future__ import annotations
import hashlib, hmac, json, math, statistics, time, re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Iterable

NOW = lambda: datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# WORKER #61 — disco_verification_orchestrator  (Claim #1)
# Zero-touch verification where a primary source is machine-checkable.
# ══════════════════════════════════════════════════════════════════════════════
class SourceTier(Enum):
    PRIMARY_API = "primary_api"        # official API — zero-touch eligible
    PRIMARY_PORTAL = "primary_portal"  # official lookup, no API — assisted
    NONE = "none"                      # no machine-checkable source — human


@dataclass
class CredentialClaim:
    coach_id: str
    full_name: str
    credential_type: str      # LCSW, LMFT, ICF-PCC, NPI...
    jurisdiction: str         # MI, CA, DE-BY...
    identifier: str
    expires_at: datetime | None = None


@dataclass
class SourceRecord:
    found: bool
    name: str = ""
    identifier: str = ""
    jurisdiction: str = ""
    status: str = ""          # active | inactive | lapsed
    expires_at: datetime | None = None
    source_tier: SourceTier = SourceTier.NONE
    source_name: str = ""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def name_confidence(a: str, b: str) -> float:
    """Token-aware fuzzy match; deliberately conservative."""
    ta, tb = set(_norm(x) for x in a.split()), set(_norm(x) for x in b.split())
    if not ta or not tb:
        return 0.0
    jacc = len(ta & tb) / len(ta | tb)
    seq = sum(1 for x, y in zip(_norm(a), _norm(b)) if x == y) / max(len(_norm(a)), len(_norm(b)), 1)
    return round(0.6 * jacc + 0.4 * seq, 4)


class VerificationOrchestrator:
    """
    HONEST SCOPE: zero-touch is available only where a primary source is
    machine-checkable AND permits automated access. Registry coverage varies by
    jurisdiction and profession; connectors declare their tier, and anything
    without a PRIMARY_API source routes to human confirmation by design.
    """
    AUTO_THRESHOLD = 0.95
    EXPIRY_GUARD_DAYS = 30

    def __init__(self, connectors: dict[str, Callable[[CredentialClaim], SourceRecord]],
                 signing_key: bytes = b"demo-key"):
        self.connectors = connectors
        self.key = signing_key
        self.audit: list[dict] = []

    def _lookup(self, claim: CredentialClaim) -> SourceRecord:
        fn = self.connectors.get(claim.credential_type)
        return fn(claim) if fn else SourceRecord(found=False)

    def sign(self, payload: dict) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(self.key, body, hashlib.sha256).hexdigest()

    def verify_signature(self, payload: dict, sig: str) -> bool:
        return hmac.compare_digest(self.sign(payload), sig)

    def process(self, claim: CredentialClaim) -> dict:
        rec = self._lookup(claim)
        conf = name_confidence(claim.full_name, rec.name) if rec.found else 0.0
        id_match = rec.identifier == claim.identifier
        juris_match = rec.jurisdiction == claim.jurisdiction
        # BUGFIX (caught by test): use the EARLIEST known expiry, not the source's.
        # A stale registry record must never override a nearer expiry we hold.
        expiries = [d for d in (rec.expires_at, claim.expires_at) if d]
        earliest = min(expiries) if expiries else None
        days_left = (earliest - NOW()).days if earliest else 9999

        reasons = []
        if not rec.found:
            reasons.append("no_primary_source_record")
        if rec.source_tier != SourceTier.PRIMARY_API:
            reasons.append(f"source_tier={rec.source_tier.value}")
        if rec.found and not id_match:
            reasons.append("identifier_mismatch")
        if rec.found and not juris_match:
            reasons.append("jurisdiction_mismatch")
        if rec.found and conf < self.AUTO_THRESHOLD:
            reasons.append(f"name_confidence={conf}")
        if rec.found and rec.status != "active":
            reasons.append(f"status={rec.status}")
        if days_left <= self.EXPIRY_GUARD_DAYS:
            reasons.append(f"expiring_in_{days_left}d")

        if not reasons:
            payload = {
                "coach_id": claim.coach_id, "credential_type": claim.credential_type,
                "jurisdiction": claim.jurisdiction, "identifier": claim.identifier,
                "status": "active", "verified_at": NOW().isoformat(),
                "valid_until": (earliest or NOW() + timedelta(days=365)).isoformat(),
                "issuing_authority": rec.source_name, "method": "primary_source_api",
                "human_confirmed": False,
            }
            out = {"decision": "AUTO_ATTESTED", "attestation": payload,
                   "signature": self.sign(payload), "confidence": conf}
        else:
            out = {"decision": "HUMAN_CONFIRM", "reasons": reasons, "confidence": conf,
                   "prepared_packet": {"claim": claim.__dict__, "source": rec.__dict__}}
        self.audit.append({"coach_id": claim.coach_id, "decision": out["decision"], "reasons": reasons})
        return out

    def renewal_queue(self, claims: Iterable[CredentialClaim], horizon_days=60) -> list[str]:
        return [c.coach_id for c in claims if c.expires_at
                and (c.expires_at - NOW()).days <= horizon_days]


# ══════════════════════════════════════════════════════════════════════════════
# WORKER #62 — disco_inline_value_renderer  (Claim #2)
# Zero-JS server-side value units + crisis banner in initial HTML.
# ══════════════════════════════════════════════════════════════════════════════
CRISIS_RESOURCES = {
    "US": [("988 Suicide & Crisis Lifeline", "tel:988"),
           ("Crisis Text Line — text HOME to 741741", "sms:741741")],
    "DE": [("Telefonseelsorge", "tel:08001110111")],
    "FR": [("3114 — Numéro national de prévention du suicide", "tel:3114")],
    "EU": [("112 — European emergency number", "tel:112")],
}


class InlineValueRenderer:
    """Every unit works with JS disabled: CSS-only interactivity (details/checkbox)."""

    def crisis_banner(self, region: str) -> str:
        items = CRISIS_RESOURCES.get(region, CRISIS_RESOURCES["EU"])
        links = " · ".join(f'<a href="{href}">{label}</a>' for label, href in items)
        return (f'<aside class="ss-crisis" role="note">'
                f'<strong>If you need support right now:</strong> {links}</aside>')

    def grounding_60s(self) -> str:
        steps = [("0:00", "Sit or stand with both feet on the floor. Let your jaw unclench."),
                 ("0:10", "Breathe in for 4. Hold for 4. Out for 6. Twice."),
                 ("0:25", "Name 5 things you can see. Say them under your breath."),
                 ("0:40", "Press your feet down. Feel the floor push back."),
                 ("0:50", "One more slow breath out. Notice one thing that is a little easier.")]
        rows = "".join(
            f'<li><input type="checkbox" id="g{i}"><label for="g{i}">'
            f'<span class="t">{t}</span> {txt}</label></li>'
            for i, (t, txt) in enumerate(steps))
        return (f'<section class="ss-value" data-unit="grounding_60s">'
                f'<h2>A 60-second grounding practice</h2>'
                f'<p>No sign-up. Start now.</p><ol class="ss-steps">{rows}</ol>'
                f'<p class="ss-after">If that helped even slightly, it is worth repeating.</p>'
                f'</section>')

    def postpartum_selfcheck(self) -> str:
        qs = ["I feel unlike myself most days", "Rage or irritability surprises me",
              "I cannot rest even when the baby sleeps", "I feel disconnected from my baby or partner",
              "I am frightened by my own thoughts"]
        rows = "".join(f'<li><input type="checkbox" id="p{i}"><label for="p{i}">{q}</label></li>'
                       for i, q in enumerate(qs))
        return (f'<section class="ss-value" data-unit="postpartum_selfcheck">'
                f'<h2>A quiet self-check</h2><ul class="ss-check">{rows}</ul>'
                f'<details><summary>What these answers might mean</summary>'
                f'<p>Several of these being true is common after birth and is not a failing. '
                f'It is also a reason to talk to someone. If any thought frightens you, '
                f'reach out to the numbers above today.</p></details></section>')

    def boundary_assessment(self) -> str:
        qs = ["I say yes when I mean no", "I explain my decisions more than I want to",
              "I feel responsible for other people's moods", "I avoid conflict at my own expense"]
        rows = "".join(f'<li><input type="checkbox" id="b{i}"><label for="b{i}">{q}</label></li>'
                       for i, q in enumerate(qs))
        return (f'<section class="ss-value" data-unit="boundary_assessment">'
                f'<h2>Where are your boundaries leaking?</h2><ul class="ss-check">{rows}</ul>'
                f'<details><summary>A first step for each pattern</summary>'
                f'<p>Pick the one you checked first. This week, delay one answer by an hour '
                f'before giving it. That pause is the boundary.</p></details></section>')

    UNITS = {"grounding_60s": "grounding_60s", "postpartum_selfcheck": "postpartum_selfcheck",
             "boundary_assessment": "boundary_assessment"}

    def render_page(self, article_html: str, unit: str, region: str = "US") -> str:
        body = getattr(self, self.UNITS[unit])()
        return (f'<article>{self.crisis_banner(region)}{body}'
                f'<div class="ss-article">{article_html}</div></article>')

    @staticmethod
    def contains_conversion_ask(html: str) -> bool:
        bad = ["sign up", "create account", "enter your email", "start trial",
               "credit card", "subscribe now"]
        return any(b in html.lower() for b in bad)


# ── Statistical engine for #31: Welch's t-test + auto-promotion ───────────────
def welch_t(a: list[float], b: list[float]) -> tuple[float, float, float]:
    """Returns (t, dof, two-sided p) — normal approximation for p."""
    na, nb = len(a), len(b)
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    se = math.sqrt(va / na + vb / nb)
    if se == 0:
        return 0.0, 0.0, 1.0
    t = (mb - ma) / se
    dof = (va / na + vb / nb) ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
    return round(t, 4), round(dof, 1), round(p, 6)


class ExperimentEvaluator:
    def __init__(self, alpha=0.05, min_n=200, degrade=-0.10):
        self.alpha, self.min_n, self.degrade = alpha, min_n, degrade

    def evaluate(self, control: list[float], variant: list[float]) -> dict:
        n = min(len(control), len(variant))
        if n < self.min_n:
            return {"decision": "HOLD", "reason": "insufficient_samples", "n": n}
        t, dof, p = welch_t(control, variant)
        mc, mv = statistics.fmean(control), statistics.fmean(variant)
        lift = (mv - mc) / mc if mc else 0.0
        if lift <= self.degrade and p < self.alpha:
            d = "ROLLBACK"
        elif lift > 0 and p < self.alpha:
            d = "PROMOTE"
        else:
            d = "CONTINUE"
        return {"decision": d, "lift": round(lift, 4), "p_value": p, "t": t, "dof": dof, "n": n}


# ══════════════════════════════════════════════════════════════════════════════
# WORKER #63 — disco_cac_ledger  (Claim #3)
# ARCHITECTURAL CORRECTION vs. the submitted spec — see docstring.
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class EditorialModel:
    """
    The submitted spec proposed 'batch approval of 50 articles' to reach O(1)
    human cost. Batching lowers the CONSTANT but the cost is still O(N) — an
    admin reviewing batches still reviews every item.

    TWO mechanisms actually break the linear tie, and both are used here:
      1. DISTRIBUTED SUBSTANCE — the per-article human contribution (byline,
         quote, review) comes from the BYLINE COACH, not the admin. That cost
         scales with the roster, which is revenue-generating, not with admin
         headcount. §19.2's editorial standard is preserved, not weakened.
      2. RISK-BASED SAMPLING — admin QA reviews a CONSTANT sample per period
         (plus 100% of gate-flagged items), independent of volume. That is
         genuinely O(1) admin labor, with statistical confidence instead of
         exhaustive review.
    """
    admin_sample_per_period: int = 30      # constant, regardless of N
    admin_seconds_per_item: float = 20.0
    admin_hourly_usd: float = 60.0
    coach_minutes_per_article: float = 12.0   # distributed, roster-scaled
    flag_rate: float = 0.06                   # gate-flagged items get 100% review

    def admin_cost(self, n_articles: int) -> float:
        reviewed = min(n_articles, self.admin_sample_per_period) + n_articles * self.flag_rate
        return reviewed * self.admin_seconds_per_item / 3600 * self.admin_hourly_usd


@dataclass
class CACLedger:
    compute_fixed_usd: float = 0.0          # per period
    compute_marginal_usd: float = 0.0       # per article/probe
    editorial: EditorialModel = field(default_factory=EditorialModel)
    entries: list[dict] = field(default_factory=list)

    def period(self, n_articles: int, signups: int, subscribers: int,
               compute_usd: float, human_admin_hours: float | None = None) -> dict:
        admin = (human_admin_hours * self.editorial.admin_hourly_usd
                 if human_admin_hours is not None
                 else self.editorial.admin_cost(n_articles))
        total = compute_usd + admin
        row = {
            "n_articles": n_articles, "signups": signups, "subscribers": subscribers,
            "compute_usd": round(compute_usd, 2), "admin_usd": round(admin, 2),
            "total_usd": round(total, 2),
            "cac_signup": round(total / signups, 4) if signups else None,
            "cac_subscriber": round(total / subscribers, 4) if subscribers else None,
            "admin_usd_per_article": round(admin / n_articles, 4) if n_articles else None,
        }
        self.entries.append(row)
        return row

    def trend(self) -> dict:
        cs = [e["cac_subscriber"] for e in self.entries if e["cac_subscriber"]]
        if len(cs) < 2:
            return {"trend": "insufficient_history"}
        return {"trend": "declining" if cs[-1] < cs[0] else "rising",
                "first": cs[0], "last": cs[-1],
                "pct_change": round((cs[-1] - cs[0]) / cs[0] * 100, 1)}


class ClaimTruthRegister:
    """G2 blocking gate: public claims may not exceed measured ledger values."""
    def __init__(self, ledger: CACLedger):
        self.ledger = ledger

    def check(self, copy: str) -> dict:
        violations = []
        low = copy.lower()
        if any(p in low for p in ["zero cac", "near-zero cost", "no acquisition cost",
                                  "free customer acquisition"]):
            violations.append("absolute_cac_claim_unsupported")
        m = re.search(r"cac[^0-9]{0,20}\$?([0-9]+(?:\.[0-9]+)?)", low)
        if m and self.ledger.entries:
            claimed = float(m.group(1))
            actual = self.ledger.entries[-1]["cac_subscriber"] or float("inf")
            if claimed < actual:
                violations.append(f"claimed_cac_{claimed}_below_measured_{actual}")
        for pat in [r"(\d+)\s*%\s*(?:higher|more|lift|increase)"]:
            if re.search(pat, low) and not self.ledger.entries:
                violations.append("uplift_claim_without_measurement")
        return {"blocked": bool(violations), "violations": violations,
                "action": "BLOCK_PUBLISH+QUEENS_RED(G2)" if violations else "ALLOW"}


# ══════════════════════════════════════════════════════════════════════════════
# WORKER #64 — disco_recruitment_engine  (Claim #4)
# ══════════════════════════════════════════════════════════════════════════════
class RecruitState(Enum):
    SOURCED = "sourced"; OUTREACH_SENT = "outreach_sent"; REPLIED = "replied"
    QUALIFIED = "qualified"; BOOKED = "booked"; DECLINED = "declined"; DISQUALIFIED = "disqualified"


@dataclass
class DemandCluster:
    specialty: str; geo: str; language: str
    monthly_searches: int; coach_count: int
    @property
    def is_zero_supply(self) -> bool: return self.coach_count == 0


@dataclass
class Candidate:
    cid: str; name: str; credential_type: str; jurisdiction: str
    email: str; source: str; region: str = "US"
    state: RecruitState = RecruitState.SOURCED
    history: list[str] = field(default_factory=list)


class RecruitmentEngine:
    """
    Compliance note (binding): US B2B professional outreach proceeds with
    opt-out; EU/UK candidates require a documented legitimate-interest basis and
    are gated behind `eu_outreach_approved`. Outreach uses PROSPECT rails
    (SendGrid) only — never client rails (P2).
    """
    def __init__(self, sourcer: Callable[[DemandCluster], list[Candidate]],
                 sender: Callable[[str, str, str], bool],
                 eu_outreach_approved: bool = False):
        self.sourcer, self.sender = sourcer, sender
        self.eu_ok = eu_outreach_approved
        self.pipeline: dict[str, Candidate] = {}
        self.booked: list[dict] = []

    def source(self, clusters: list[DemandCluster]) -> list[Candidate]:
        found = []
        for c in (x for x in clusters if x.is_zero_supply):
            for cand in self.sourcer(c):
                cand.history.append(f"sourced:{c.specialty}@{c.geo}")
                self.pipeline[cand.cid] = cand
                found.append(cand)
        return found

    def compose(self, cand: Candidate, cluster: DemandCluster) -> tuple[str, str]:
        subj = f"{cluster.monthly_searches} people in {cluster.geo} searched for {cluster.specialty} support this month"
        body = (
            f"Hi {cand.name.split()[0]},\n\n"
            f"We track what people in {cluster.geo} are actually searching for when they look "
            f"for help. Last month, {cluster.monthly_searches} searches were for "
            f"{cluster.specialty} support — and there is currently no verified practitioner "
            f"on our network serving that need there.\n\n"
            f"Sovereign Sanctuary pairs verified coaches and licensed professionals with an AI "
            f"companion that supports clients between sessions. We verify every credential "
            f"before activation, we build and maintain your public profile and listings, and "
            f"we route that local demand to you.\n\n"
            f"Worth a 20-minute conversation? Reply and I'll send times.\n\n"
            f"— Sovereign Sanctuary\n"
            f"Reply STOP to receive nothing further.")
        return subj, body

    def outreach(self, cand: Candidate, cluster: DemandCluster) -> dict:
        if cand.region in ("EU", "UK") and not self.eu_ok:
            cand.state = RecruitState.DISQUALIFIED
            cand.history.append("blocked:eu_outreach_not_approved")
            return {"sent": False, "reason": "EU_LEGITIMATE_INTEREST_NOT_APPROVED"}
        subj, body = self.compose(cand, cluster)
        # register/claim safety before any send
        from app.services.disco.pipeline import register_lint  # reuse worker #15
        lint = register_lint(body, "coaching")
        if lint["blocked"]:
            cand.state = RecruitState.DISQUALIFIED
            return {"sent": False, "reason": "REGISTER_VIOLATION", "detail": lint}
        ok = self.sender(cand.email, subj, body)
        cand.state = RecruitState.OUTREACH_SENT if ok else cand.state
        cand.history.append("outreach_sent" if ok else "send_failed")
        return {"sent": ok, "subject": subj}

    def handle_reply(self, cid: str, text: str, credential_ok: bool) -> dict:
        cand = self.pipeline[cid]
        cand.state = RecruitState.REPLIED
        cand.history.append("replied")
        low = text.lower()
        if any(w in low for w in ["stop", "unsubscribe", "not interested", "no thanks"]):
            cand.state = RecruitState.DECLINED
            cand.history.append("declined")
            return {"state": cand.state.value}
        # Little Nate pre-qualification
        interested = any(w in low for w in ["yes", "interested", "times", "call", "tell me more"])
        if interested and credential_ok:
            cand.state = RecruitState.QUALIFIED
            slot = (NOW() + timedelta(days=2)).replace(hour=15, minute=0, second=0, microsecond=0)
            self.booked.append({"cid": cid, "name": cand.name, "slot": slot.isoformat()})
            cand.state = RecruitState.BOOKED
            cand.history.append("booked")
        elif interested and not credential_ok:
            cand.state = RecruitState.DISQUALIFIED
            cand.history.append("credential_precheck_failed")
        return {"state": cand.state.value}

    def funnel(self) -> dict:
        out = {s.value: 0 for s in RecruitState}
        for c in self.pipeline.values():
            out[c.state.value] += 1
        out["booked_meetings"] = len(self.booked)
        return out
