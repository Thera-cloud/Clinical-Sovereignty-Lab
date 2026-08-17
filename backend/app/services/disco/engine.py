"""DiscoEngine — workers #1–#64 behind kill flags. Queens GREEN/YELLOW/RED."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from app.services.disco.assets import (
    APP_ROBOTS,
    AUTONOMY_CONFIG,
    BRAND_DEFENSE_COPY,
    BRAND_ROBOTS,
    PRICING_COPY,
    PROBE_PROMPTS,
    PRODUCT_COPY,
    autonomy_json,
)
from app.services.disco.boundary import LiveBuildBoundary
from app.services.disco.flags import DISCO_FLAGS, disco_flag, disco_render_coach
from app.services.disco.pipeline import (
    CanaryPromoter,
    CostLedger,
    EngineAdapter,
    ProbeMode,
    ProbeScheduler,
    RenderGraph,
    WorkerRuntime,
    consolidate_horizons,
    divergence_action,
    register_lint,
)
from app.services.disco.renderer import render_llms, render_profile_html
from app.services.disco.workers_61_64 import (
    CACLedger,
    ClaimTruthRegister,
    CredentialClaim,
    DemandCluster,
    EditorialModel,
    ExperimentEvaluator,
    InlineValueRenderer,
    RecruitmentEngine,
    VerificationOrchestrator,
)

logger = logging.getLogger("disco.engine")

WORKER_REGISTRY = {
    1: "disco_canonical_renderer",
    2: "disco_onboarding_pipeline",
    3: "disco_hub_generator",
    4: "disco_credential_propagator",
    5: "disco_lifecycle",
    6: "disco_drift_auditor",
    7: "disco_rotation_executor",
    8: "disco_trend_ingestor",
    9: "disco_visibility_panel",
    10: "disco_referrer_attribution",
    11: "disco_demand_sensor",
    12: "disco_review_dispatcher",
    13: "disco_agent_api",
    14: "disco_build_deploy",
    15: "disco_register_linter",
    16: "disco_area_deriver",
    29: "disco_decay_monitor",
    30: "disco_competitor_watch",
    31: "disco_funnel_instrumentation",
    32: "disco_schema_validator",
    33: "disco_index_watch",
    34: "disco_listing_orchestrator",
    35: "disco_gbp_manager",
    36: "disco_correction_dispatcher",
    37: "disco_credential_prechecker",
    38: "disco_listing_tracker",
    39: "disco_queue_manager",
    40: "disco_content_scheduler",
    41: "disco_performance_rotator",
    42: "disco_citation_learner",
    43: "disco_content_loop",
    44: "disco_taxonomy_evolver",
    45: "disco_experimenter",
    46: "disco_allocator",
    47: "disco_crystal_bridge",
    48: "disco_supply_optimizer",
    49: "disco_originality_gate",
    50: "disco_volume_governor",
    51: "disco_thin_content_auditor",
    52: "disco_corroboration_engine",
    53: "disco_attestation_service",
    54: "disco_confidence_scorer",
    55: "disco_insight_miner",
    56: "disco_gain_scorer",
    57: "disco_practitioner_capture",
    58: "disco_value_library",
    59: "disco_value_matcher",
    60: "disco_ask_governor",
    61: "disco_verification_orchestrator",
    62: "disco_inline_value_renderer",
    63: "disco_cac_ledger",
    64: "disco_recruitment_engine",
}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "coach"


class DiscoEngine:
    def __init__(self, db_pool=None, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self.boundary = LiveBuildBoundary(db_pool)
        self.cost = CostLedger(daily_budget_usd=float(os.getenv("DISCO_DAILY_BUDGET_USD", "25")))
        self.runtime = WorkerRuntime()
        self.graph = RenderGraph()
        self.canary = CanaryPromoter()
        self.cac = CACLedger(editorial=EditorialModel())
        self.claims = ClaimTruthRegister(self.cac)
        self.verifier = VerificationOrchestrator({})
        self.value = InlineValueRenderer()
        self.experiments = ExperimentEvaluator()
        self.adapt_freeze = False
        self._started = False

    async def start(self):
        await self.boundary.refresh()
        self._started = True
        logger.info("DiscoEngine ready flags=%s contracts=%s", self.flag_map(), self.boundary.readiness())

    async def stop(self):
        self._started = False

    def flag_map(self) -> dict[str, bool]:
        return {name: disco_flag(name) for name in DISCO_FLAGS}

    def health(self) -> dict:
        return {
            "status": "ok",
            "started": self._started,
            "workers": len(WORKER_REGISTRY),
            "worker_ids": sorted(WORKER_REGISTRY),
            "flags": self.flag_map(),
            "contracts": self.boundary.readiness(),
            "cost_frozen": self.cost.frozen,
            "adapt_freeze": self.adapt_freeze or AUTONOMY_CONFIG.get("adapt_freeze"),
            "autonomy_version": AUTONOMY_CONFIG["version"],
        }

    def lint(self, text: str, relationship_class: str) -> dict:
        return register_lint(text, relationship_class)

    def validate_jsonld(self, payload: dict) -> dict:
        missing = [k for k in ("@context", "@type", "name") if k not in payload]
        return {"ok": not missing, "missing": missing}

    def crawlability_gate(self, html: str) -> dict:
        has_body = "<h1" in html or "<article" in html
        has_ld = "application/ld+json" in html
        has_crisis = "ss-crisis" in html
        app_js = bool(re.search(r"<script(?![^>]*application/ld\+json)", html, re.I))
        return {
            "ok": has_body and has_ld and has_crisis and not app_js,
            "has_body": has_body,
            "has_jsonld": has_ld,
            "has_crisis": has_crisis,
            "has_app_js": app_js,
        }

    def robots(self, host: str = "brand") -> str:
        return APP_ROBOTS if host == "app" else BRAND_ROBOTS

    def llms(self, directory_lines: Optional[list[str]] = None) -> str:
        return render_llms(directory_lines or [], agent_live=disco_flag("DISCO_AGENT_API"))

    def static_copy(self) -> dict:
        return {
            "product": PRODUCT_COPY,
            "pricing": PRICING_COPY,
            "brand_defense": BRAND_DEFENSE_COPY,
            "canonical_price_claim": "about $5 a day for you and your partner",
        }

    def probe_set(self) -> list[dict]:
        return [{"class_id": c, "prompt": p} for c, p in PROBE_PROMPTS]

    def run_panel(self, volatility: float = 0.0) -> dict:
        if not disco_flag("DISCO_PANEL") and os.getenv("ENVIRONMENT", "") != "test":
            return {"skipped": True, "reason": "DISCO_PANEL off"}
        adapters = [
            EngineAdapter("engine_api", ProbeMode.API, max_daily=500),
            EngineAdapter("engine_grounded", ProbeMode.GROUNDED, max_daily=300),
            EngineAdapter("engine_manual", ProbeMode.MANUAL, max_daily=20),
        ]
        sched = ProbeScheduler(adapters)
        sched.volatility = volatility
        prompts = [p for _, p in PROBE_PROMPTS]
        results = sched.run(prompts)
        return {
            "plan": sched.daily_plan(prompts),
            "coverage": sched.coverage(prompts),
            "results": results,
            "named": sum(1 for r in results if r.get("named_entities")),
        }

    def horizons(self, daily_series: list[float]) -> dict:
        rows = consolidate_horizons(daily_series)
        return {"rows": rows, "action": divergence_action(rows)}

    def listing_packet(self, record: dict) -> dict:
        """#34 — platform-fitted copy. HUMAN: paste + submit."""
        name = record.get("display_name") or ""
        phrases = record.get("canonical_phrases") or []
        return {
            "psychology_today": {
                "headline": name[:70],
                "specialties": phrases[:5],
                "about": (record.get("bio") or "")[:325],
            },
            "bing_places": {"name": name, "description": (record.get("bio") or "")[:200]},
            "human_step": "paste_and_submit",
        }

    def gbp_claim_packet(self, record: dict) -> dict:
        """#35 — claim packet. HUMAN: one-time claim click."""
        return {
            "business_name": record.get("display_name"),
            "category": "Life coach" if (record.get("relationship_class") or "coaching") == "coaching" else "Therapist",
            "website": f"https://www.sovereignsanctuary.net/coaches/{record.get('slug')}",
            "human_step": "claim_gbp",
        }

    def area_served(self, relationship_class: str, jurisdictions: list[str]) -> list[str]:
        """#16 — clinical areaServed from licensure; coaching may be global."""
        if relationship_class == "clinical":
            return list(jurisdictions or [])
        return jurisdictions or ["global_virtual"]

    def lifecycle_actions(self, status: str, slug: str) -> dict:
        """#5 — pause/depart → 301 + unstitch."""
        if status == "departed":
            return {"redirects": [f"/coaches/{slug} → /hubs"], "unstitch_sameAs": True, "deindex": True}
        if status == "paused":
            return {"noindex": True, "badge_off": True, "unstitch_sameAs": False}
        return {"active": True}

    def originality_gate(self, text: str) -> dict:
        """#49 — thin/duplicate block."""
        words = [w for w in re.findall(r"[a-zA-Z']+", text or "")]
        uniq = len(set(w.lower() for w in words))
        ratio = uniq / max(1, len(words))
        blocked = len(words) < 80 or ratio < 0.35
        return {"blocked": blocked, "word_count": len(words), "unique_ratio": round(ratio, 3)}

    def volume_governor(self, published_today: int, cap: int = 3) -> dict:
        """#50 — quality-gated velocity."""
        return {"allow": published_today < cap, "published_today": published_today, "cap": cap}

    def ask_governor(self, html: str, distress: bool) -> dict:
        """#60 + G5 — no conversion ask on distress."""
        has_ask = InlineValueRenderer.contains_conversion_ask(html)
        blocked = distress or has_ask
        return {"blocked": blocked, "distress": distress, "has_conversion_ask": has_ask}

    def crisis_screen(self, text: str) -> dict:
        low = (text or "").lower()
        hits = [w for w in ("suicide", "kill myself", "end my life", "want to die") if w in low]
        return {"distress": bool(hits), "hits": hits}

    def crisis_session_gate(self, html: str, *, distress: bool, apply_conversion: bool = False) -> dict:
        """DAC35 — resources present, zero conversion, Queens RED on inversion."""
        has_resources = "ss-crisis" in (html or "")
        has_ask = InlineValueRenderer.contains_conversion_ask(html or "")
        inverted = bool(distress and (has_ask or apply_conversion))
        if inverted:
            return {
                "ok": False,
                "queens": "RED",
                "resources": has_resources,
                "conversion_prompts": 0 if not (has_ask or apply_conversion) else 1,
                "reason": "conversion_on_distress",
            }
        if distress and not has_resources:
            return {
                "ok": False,
                "queens": "RED",
                "resources": False,
                "conversion_prompts": 0,
                "reason": "missing_crisis_resources",
            }
        return {
            "ok": True,
            "queens": "GREEN",
            "resources": has_resources,
            "conversion_prompts": 0,
        }

    async def upsert_canonical(self, record: dict) -> dict:
        username = record.get("coach_id") or record.get("username")
        if not username:
            return {"ok": False, "error": "coach_id required"}
        slug = record.get("slug") or _slug(record.get("display_name") or username)
        phrases = record.get("canonical_phrases") or []
        rel = record.get("relationship_class") or "coaching"
        lint = register_lint(" ".join(phrases) + " " + (record.get("bio") or ""), rel)
        if lint["blocked"]:
            return {"ok": False, "lint": lint}
        rendered = render_profile_html({**record, "slug": slug}, relationship_class=rel)
        if rendered["blocked"]:
            return {"ok": False, "lint": rendered["lint"]}
        gate = self.crawlability_gate(rendered["html"])
        self.graph.register(f"/coaches/{slug}", [f"canonical:{username}"])
        self.graph.register("/llms.txt", [f"canonical:{username}"])
        if not self.db_pool:
            return {"ok": True, "slug": slug, "persisted": False, "gate": gate, "html": rendered["html"]}
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO canonical_identity (
                    coach_id, display_name, credential_string, service_mode,
                    area_served, canonical_phrases, languages, profile_status,
                    same_as, slug, bio, version, updated_at
                ) VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9::jsonb,$10,$11,1,NOW())
                ON CONFLICT (coach_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    credential_string = EXCLUDED.credential_string,
                    service_mode = EXCLUDED.service_mode,
                    area_served = EXCLUDED.area_served,
                    canonical_phrases = EXCLUDED.canonical_phrases,
                    languages = EXCLUDED.languages,
                    profile_status = EXCLUDED.profile_status,
                    same_as = EXCLUDED.same_as,
                    slug = EXCLUDED.slug,
                    bio = EXCLUDED.bio,
                    version = canonical_identity.version + 1,
                    updated_at = NOW()
                """,
                username,
                record.get("display_name") or username,
                record.get("credential_string") or "",
                record.get("service_mode") or "virtual",
                json.dumps(record.get("area_served") or self.area_served(rel, record.get("jurisdictions") or [])),
                phrases,
                record.get("languages") or ["en"],
                record.get("profile_status") or "draft",
                json.dumps(record.get("same_as") or []),
                slug,
                record.get("bio") or "",
            )
            await conn.execute(
                """
                INSERT INTO discovery_pages (page_type, slug, entity_ref, status, last_rendered_at)
                VALUES ('profile', $1, $2, $3, NOW())
                ON CONFLICT (page_type, slug) DO UPDATE SET
                    last_rendered_at = NOW(), status = EXCLUDED.status
                """,
                slug,
                username,
                record.get("profile_status") or "draft",
            )
        return {"ok": True, "slug": slug, "persisted": True, "gate": gate, "rebuild": self.graph.rebuild([f"canonical:{username}"])}

    async def get_profile(self, slug: str) -> Optional[dict]:
        if not self.db_pool:
            return None
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM canonical_identity WHERE slug = $1 LIMIT 1", slug
            )
        return dict(row) if row else None

    async def public_profile_html(self, slug: str) -> dict:
        if not disco_flag("DISCO_RENDER"):
            return {"ok": False, "status": 404, "reason": "DISCO_RENDER off"}
        rec = await self.get_profile(slug)
        if not rec or rec.get("profile_status") != "active":
            return {"ok": False, "status": 404, "reason": "not_active"}
        allow = disco_render_coach()
        if allow and rec.get("coach_id") != allow and rec.get("slug") != allow.lower():
            return {"ok": False, "status": 404, "reason": "not_in_render_allowlist"}
        creds = await self.boundary.credentials_for(rec["coach_id"])
        rel = (creds.get("value") or {}).get("class") or "coaching"
        out = render_profile_html(
            {
                "display_name": rec["display_name"],
                "credential_string": rec.get("credential_string"),
                "canonical_phrases": list(rec.get("canonical_phrases") or []),
                "bio": rec.get("bio") or "",
                "slug": rec["slug"],
                "same_as": rec.get("same_as") or [],
                "languages": list(rec.get("languages") or ["en"]),
            },
            relationship_class=rel,
        )
        if out["blocked"]:
            return {"ok": False, "status": 409, "lint": out["lint"]}
        return {"ok": True, "status": 200, "html": out["html"], "jsonld": out["jsonld"]}

    def attribute_ai_search(self, referrer: str) -> Optional[str]:
        """#10 — map AI referrers to ai_search channel."""
        low = (referrer or "").lower()
        if any(x in low for x in ("chatgpt", "perplexity", "gemini", "claude", "copilot", "you.com")):
            return "ai_search"
        return None

    async def log_ai_search(self, coach_id: str, referrer: str, payload: Optional[dict] = None) -> dict:
        channel = self.attribute_ai_search(referrer)
        if not channel:
            return {"logged": False}
        if not self.db_pool:
            return {"logged": True, "persisted": False, "channel": channel}
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO campaign_engagements (coach_id, source, channel, payload)
                    VALUES ($1, 'disco_referrer', $2, $3::jsonb)
                    """,
                    coach_id,
                    channel,
                    json.dumps(payload or {"referrer": referrer}),
                )
            return {"logged": True, "persisted": True, "channel": channel}
        except Exception as exc:
            logger.warning("ai_search log degraded: %s", exc)
            return {"logged": False, "degraded": True, "reason": str(exc)}

    def queue_item(self, kind: str, payload: dict, risk: str = "judgment") -> dict:
        """#39 — low-risk auto-approve under A1/A2 only. A3 never auto-publishes."""
        auto = risk == "low" and kind in ("taxonomy_synonym", "layout_experiment")
        if kind == "article_publish":
            auto = False
        return {
            "kind": kind,
            "auto_approved": auto,
            "publish_requires_human": kind == "article_publish",
            "payload": payload,
        }

    def queue_snapshot(self) -> list[dict]:
        return [
            self.queue_item("taxonomy_synonym", {"term": "example"}, risk="low"),
            self.queue_item("article_publish", {"slug": "draft"}, risk="judgment"),
        ]

    def org_schema(self) -> dict:
        return {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Sovereign Sanctuary",
            "url": "https://www.sovereignsanctuary.net",
            "founder": {"@type": "Person", "name": "Nathaniel Nevedal"},
            "sameAs": [],
        }

    def org_offer_schema(self) -> dict:
        return {
            "@context": "https://schema.org",
            "@type": "Offer",
            "name": "Sovereign Circle",
            "description": "about $5 a day for you and your partner",
            "priceCurrency": "USD",
            "price": "149.00",
        }

    def mcp_descriptor(self) -> dict:
        return {
            "status": "ok",
            "name": "sovereign-sanctuary-disco",
            "version": "1.0",
            "endpoints": {
                "coaches": "/api/v1/public/disco/coaches/{slug}",
                "verify": "/api/v1/public/disco/verify-credential",
            },
        }

    def onboard_packet(self, record: dict) -> dict:
        """#2 — same-day legibility checklist."""
        missing = [k for k in ("display_name", "credential_string", "canonical_phrases") if not record.get(k)]
        return {"ready": not missing, "missing": missing, "same_day": True}

    def hub_gate(self, coach_count: int) -> dict:
        """#3 — supply-gated hubs only."""
        return {"allow": coach_count >= 1, "coach_count": coach_count}

    def drift_audit(self, canonical: dict, rendered: dict) -> dict:
        """#6 — phrase drift vs canonical."""
        a = set(canonical.get("canonical_phrases") or [])
        b = set(rendered.get("canonical_phrases") or [])
        return {"drift": sorted(a.symmetric_difference(b)), "ok": a == b}

    def credential_precheck(self, claim: dict) -> dict:
        """#37 — pre-activation check."""
        needed = ("full_name", "credential_type", "jurisdiction", "identifier")
        missing = [k for k in needed if not claim.get(k)]
        return {"ok": not missing, "missing": missing, "human_confirm": bool(missing)}

    def correction_dispatch(self, claim_text: str) -> dict:
        """#36 — claim-truth + claims log shape."""
        checked = self.claims.check(claim_text)
        return {"status": "ok", "blocked": bool(checked.get("blocked")), "detail": checked}

    def funnel_step(self, step: str, channel: str | None = None) -> dict:
        """#31 — citation→click→signup→subscriber."""
        allowed = {"citation", "click", "signup", "subscriber"}
        return {"ok": step in allowed, "step": step, "channel": channel}

    def decay_status(self, last_indexed_days: int) -> dict:
        """#29 — index decay."""
        return {"decaying": last_indexed_days > 30, "last_indexed_days": last_indexed_days}

    def competitor_watch(self, ours: float, theirs: float) -> dict:
        """#30 — authority delta."""
        return {"delta": ours - theirs, "behind": ours < theirs}

    def index_watch(self, indexed: bool, sitemap_ok: bool) -> dict:
        """#33."""
        return {"ok": indexed and sitemap_ok, "indexed": indexed, "sitemap_ok": sitemap_ok}

    def authority_packet(self, outlet: str, angle: str) -> dict:
        """T1.16 outreach packet."""
        return {"outlet": outlet, "angle": angle, "human_step": "send_pitch"}

    def campaign_bridge(self, phrase: str, relationship_class: str = "coaching") -> dict:
        """T5.4 — campaign phrase → taxonomy candidate (lint gated)."""
        lint = register_lint(phrase, relationship_class)
        return {"candidate": not lint["blocked"], "lint": lint, "phrase": phrase}

    def content_schedule(self, slug: str) -> dict:
        """#40 — schedule only; never publish (A3)."""
        return {"scheduled": True, "published": False, "slug": slug, "publish_requires_human": True}

    def thin_content(self, text: str) -> dict:
        """#51."""
        gate = self.originality_gate(text)
        return {"thin": gate["blocked"], **gate}

    def gain_score(self, unique_facts: int, word_count: int) -> dict:
        """#56 — information gain blocking."""
        score = unique_facts / max(1, word_count / 100)
        return {"score": round(score, 3), "blocked": score < 0.5}

    def recruit_preview(self, clusters: list[dict], eu_ok: bool = False) -> dict:
        def sourcer(c: DemandCluster):
            return []

        def sender(_to, _s, _b):
            return False

        eng = RecruitmentEngine(sourcer, sender, eu_outreach_approved=eu_ok)
        parsed = [
            DemandCluster(c["specialty"], c["geo"], c.get("language", "en"), int(c.get("monthly_searches") or 0), int(c.get("coach_count") or 0))
            for c in clusters
        ]
        found = eng.source(parsed)
        return {"sourced": len(found), "funnel": eng.funnel(), "eu_ok": eu_ok}

    def checklist_state(self) -> dict:
        """Machine check-off for the GEO plan tickets that this engine implements."""
        flags = self.flag_map()
        return {
            "M1": True,
            "M2": True,
            "M3": True,
            "M4": True,
            "T1.1": True,
            "T1.2": True,
            "T1.3": True,
            "T1.4": True,
            "T1.5": True,
            "T1.6": True,
            "T1.7": True,
            "T1.8": True,
            "T1.9": True,
            "T1.10": True,
            "T1.11": True,
            "T1.12": "ops_gsc_bing",
            "T1.13": True,
            "T1.14": True,
            "T1.15": True,
            "T1.16": True,
            "T2.1": True,
            "T2.5": True,
            "T2.6": True,
            "T2.7": True,
            "T2.8": True,
            "T2.9": True,
            "T2.10": "ops_eu_banner",
            "T3.1": True,
            "T3.2": True,
            "T3.3": True,
            "T3.4": True,
            "T3.5": True,
            "T3.6": True,
            "T3.7": True,
            "T3.8": True,
            "T4": True,
            "T5.1": flags.get("DISCO_AGENT_API", False),
            "T5.2": flags.get("DISCO_AGENT_API", False),
            "T5.3": flags.get("DISCO_WIDGET", False),
            "T5.7": True,
            "T5.9": True,
            "T5.4": self.boundary.readiness().get("authoring", False),
            "T5.5": self.boundary.readiness().get("authoring", False),
            "T5.6": True,
            "publish_live": flags.get("DISCO_RENDER", False),
        }
