#!/usr/bin/env python3
"""
Crystal Factory — Distributed Autonomous Knowledge Engine

Three-node crystallization network:
  Hetzner      (CRYSTAL_ROLE=external)    — RSS, GitHub, StackOverflow
  DigitalOcean (CRYSTAL_ROLE=internal)    — PostgreSQL tables (clinical)
  Mac          (handled by bridge BLUE mode, not this script)

Two-stage synthesis pipeline:
  Stage 1 (Ollama 8B, $0):  Filter fragments by relevance, score 0-10
  Stage 2 (Grok, ~$0.003):  Synthesize top clusters into high-quality crystals

Configuration via environment variables (see .env.crystal-hetzner / .env.crystal-digitalocean):
  CRYSTAL_ROLE          — external | internal
  PRODUCTION_DB_URL     — PostgreSQL connection string for crystal storage
  OLLAMA_URL            — Ollama API for Stage 1 filtering (default: localhost:11434)
  GROK_URL              — Grok API for Stage 2 synthesis (Azure Foundry endpoint)
  GROK_API_KEY          — Grok API key
  GROK_MODEL            — Grok model name (default: grok-4-1-fast-non-reasoning)
  HARVEST_INTERVAL_SEC  — Seconds between harvest cycles (default: 1800)
  CRYSTAL_NODE_ID       — Unique node identifier (default: hostname)

Crystal write deduplication: ON CONFLICT (content_hash) DO NOTHING
Both nodes write to the same nate_intelligence_crystals table.

HIPAA: External (Hetzner) NEVER reads clinical tables. Internal (DO) keeps
raw data local — only anonymized crystals are stored.

Usage:
    CRYSTAL_ROLE=external PRODUCTION_DB_URL=postgresql://... python3 crystal_factory.py
"""

import asyncio
import hashlib
import html as html_mod
import json
import logging
import os
import platform
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("crystal_factory")

CLUSTER_MIN_ITEMS = 3
MAX_CRYSTAL_LENGTH = 3000
WATERMARK_KEY_PREFIX = "crystal_factory_watermark"
DEDUP_INTERVAL_CYCLES = 12  # run semantic dedup every 12 cycles (~6 hours)

# ─────────────────────────────────────────────────────────────────
# Source-based confidence tiers
#   PhD/peer-reviewed > clinical internal > platform ops > external
#   Meta-analyses and systematic reviews start near PROMOTED.
# ─────────────────────────────────────────────────────────────────
SOURCE_CONFIDENCE = {
    # PhD-level / peer-reviewed (highest confidence per crystal)
    "pubmed":              0.72,
    "pubmed_rct":          0.70,
    "cochrane":            0.75,
    "jmir":                0.70,
    "arxiv":               0.62,
    "arxiv_cs_lg":         0.63,
    "arxiv_cs_cr":         0.63,
    "nature_npj":          0.72,
    "frontiers":           0.68,
    "lancet_digital":      0.72,
    "apa_journal":         0.70,
    "google_patents":      0.60,
    # Clinical internal (high value)
    "wisdom_extraction":   0.65,
    "conversation_history": 0.68,
    "live_session":        0.68,
    "coach_briefing":      0.65,
    "classroom_analysis":  0.63,
    "vault_annotation":    0.60,
    "transfer_crystal":    0.62,
    "vault_document":      0.58,
    "nevedal_metrics":     0.70,
    # Platform / curated
    "rss_realpython.com":  0.58,
    "rss_simonwillison.net": 0.60,
    "rss_lilianweng.github.io": 0.62,
    "rss_blog.cloudflare.com": 0.58,
    "rss_blog.hubspot.com": 0.52,
    "rss_neilpatel.com":   0.50,
    "rss_dev.to":          0.55,
    "rss_hnrss.org":       0.53,
    "rss_mental.jmir.org": 0.70,
    "rss_www.frontiersin.org": 0.68,
    "rss_www.nature.com":  0.72,
    "rss_huggingface.co":  0.58,
    "rss_www.latent.space": 0.58,
    "rss_hbr.org":         0.55,
    "rss_blog.python.org": 0.58,
    "rss_www.hipaajournal.com": 0.60,
    "rss_nvd.nist.gov":    0.62,
    "rss_www.digitalocean.com": 0.52,
    "rss_blog.hetzner.com": 0.50,
    "rss_www.apa.org":     0.70,
    "rss_feeds.feedburner.com": 0.55,
    "rss_arxiv.org":       0.60,
    # Vendor / platform blogs
    "rss_stripe.com":      0.58,
    "rss_www.twilio.com":  0.55,
    "rss_azure.microsoft.com": 0.58,
    "rss_redis.io":        0.55,
    "rss_medium.com":      0.52,
    # Community-vetted
    "stackoverflow":       0.58,
    "stackoverflow_high":  0.62,
    "github_trending":     0.55,
    # Marketing / analytics
    "post_analytics":      0.55,
    "search_query":        0.55,
    # New internal sources
    "social_memory":       0.55,
    "content_queue":       0.52,
    "assessment_result":   0.65,
    "dojo_memory":         0.63,
    "liminal_analysis":    0.60,
    "skyeye_session":      0.55,
    "community_checkins":  0.60,
    "self_healing":        0.40,
    "login_attempts":      0.58,
    "therapeutic_prediction": 0.70,
    "cycle_detection":     0.68,
}
DEFAULT_CONFIDENCE = 0.55

# ─────────────────────────────────────────────────────────────────
# Domain affinity: related domains merge when clusters are small
# ─────────────────────────────────────────────────────────────────
DOMAIN_AFFINITY = {
    frozenset({"clinical", "research"}): "clinical",
    frozenset({"clinical", "coaching"}): "clinical",
    frozenset({"clinical", "coherence"}): "clinical",
    frozenset({"clinical", "voice"}): "clinical",
    frozenset({"clinical", "biochem"}): "clinical",
    frozenset({"clinical", "crisis"}): "clinical",
    frozenset({"coaching", "research"}): "coaching",
    frozenset({"coding", "general"}): "coding",
    frozenset({"defense", "coding"}): "defense",
    frozenset({"coherence", "research"}): "clinical",
    frozenset({"voice", "research"}): "research",
    frozenset({"legal", "business"}): "legal",
    frozenset({"business", "accounting"}): "business",
    frozenset({"pmp", "business"}): "pmp",
    frozenset({"teaching", "coaching"}): "teaching",
    frozenset({"machining", "coding"}): "machining",
    frozenset({"biochem", "research"}): "research",
    frozenset({"patent", "clinical"}): "clinical",
    frozenset({"patent", "research"}): "research",
    frozenset({"culture", "marketing"}): "marketing",
}

# ─────────────────────────────────────────────────────────────────
# External Harvest Sources (Hetzner — organized by intelligence domain)
# ─────────────────────────────────────────────────────────────────
RSS_FEEDS = [
    # ── Coding domain (highest volume) ──
    ("https://realpython.com/atom.xml", "coding", "atom"),
    ("https://dev.to/feed/tag/python", "coding", "rss"),
    ("https://dev.to/feed/tag/flutter", "coding", "rss"),
    ("https://dev.to/feed/tag/fastapi", "coding", "rss"),
    ("https://dev.to/feed/tag/websockets", "coding", "rss"),
    ("https://blog.python.org/feeds/posts/default", "coding", "atom"),
    ("https://medium.com/feed/dartlang", "coding", "rss"),
    ("https://medium.com/feed/flutter", "coding", "rss"),
    ("https://hnrss.org/best?count=15", "general", "rss"),

    # ── Clinical domain (highest value per crystal) ──
    ("https://www.apa.org/pubs/journals/releases.rss", "clinical", "rss"),
    ("https://feeds.feedburner.com/psychcentral", "clinical", "rss"),
    ("https://www.frontiersin.org/journals/psychology/rss", "clinical", "rss"),
    ("https://www.frontiersin.org/journals/psychiatry/rss", "clinical", "rss"),

    # ── Computational psychiatry & digital therapeutics ──
    ("https://mental.jmir.org/feed/atom", "clinical", "atom"),
    ("https://www.frontiersin.org/journals/digital-health/rss", "research", "rss"),
    ("https://www.nature.com/npjdigitalmed.rss", "research", "rss"),
    ("https://www.nature.com/tp.rss", "clinical", "rss"),

    # ── Security / defense ──
    ("https://nvd.nist.gov/feeds/xml/cve/misc/nvd-rss-analyzed.xml", "defense", "rss"),
    ("https://blog.cloudflare.com/rss/", "defense", "rss"),
    ("https://www.hipaajournal.com/feed/", "defense", "rss"),

    # ── Operations / deployment / platform vendors ──
    ("https://www.digitalocean.com/blog/feed", "coding", "rss"),
    ("https://blog.hetzner.com/feed/", "coding", "rss"),
    ("https://stripe.com/blog/feed.rss", "coding", "rss"),
    ("https://www.twilio.com/blog/feed", "coding", "rss"),
    ("https://azure.microsoft.com/en-us/blog/feed/", "research", "rss"),
    ("https://redis.io/blog/feed/", "coding", "rss"),

    # ── Research / AI ──
    ("https://dev.to/feed/tag/ai", "research", "rss"),
    ("https://dev.to/feed/tag/machinelearning", "research", "rss"),
    ("https://huggingface.co/blog/feed.xml", "research", "atom"),
    ("https://simonwillison.net/atom/everything/", "research", "atom"),
    ("https://lilianweng.github.io/index.xml", "research", "rss"),
    ("https://www.latent.space/feed", "research", "rss"),
    ("https://arxiv.org/rss/cs.AI", "research", "rss"),
    ("https://arxiv.org/rss/cs.CL", "research", "rss"),
    ("https://arxiv.org/rss/cs.LG", "research", "rss"),
    ("https://arxiv.org/rss/cs.IR", "research", "rss"),
    ("https://arxiv.org/rss/cs.CR", "defense", "rss"),
    ("https://arxiv.org/rss/cs.DB", "coding", "rss"),
    ("https://arxiv.org/rss/cs.SD", "research", "rss"),
    ("https://arxiv.org/rss/eess.AS", "research", "rss"),
    ("https://arxiv.org/rss/q-bio.NC", "clinical", "rss"),

    # ── Marketing / growth ──
    ("https://blog.hubspot.com/marketing/rss.xml", "marketing", "rss"),
    ("https://neilpatel.com/blog/feed/", "marketing", "rss"),

    # ── Coaching / enterprise ──
    ("https://hbr.org/topic/managing-people/feed", "coaching", "rss"),
    ("https://hbr.org/topic/emotional-intelligence/feed", "coaching", "rss"),
]

GITHUB_TRENDING_QUERIES = [
    # Exact stack
    ("fastapi+websocket", "coding"),
    ("flutter+web", "coding"),
    ("asyncio+patterns", "coding"),
    ("cloudflare+workers", "coding"),
    # Clinical / research
    ("therapy+AI", "research"),
    ("digital+therapeutics", "research"),
    ("voice+biometrics", "research"),
    ("emotion+detection+speech", "research"),
    ("psychotherapy+NLP", "research"),
    # Architecture
    ("knowledge+graph+llm", "research"),
    ("vector+database", "research"),
    ("memory+augmented+LLM", "research"),
]

STACKOVERFLOW_TAGS = [
    "python", "flutter", "fastapi", "postgresql",
    "python-asyncio", "websocket", "cloudflare-workers",
    "flutter-web", "docker", "nginx", "redis",
    "stripe-payments", "dart", "azure-cognitive-services",
]

SO_MIN_SCORES = {
    "fastapi": 10,
    "python-asyncio": 15,
    "flutter-web": 5,
    "websocket": 10,
    "cloudflare-workers": 5,
    "postgresql": 10,
    "python": 15,
    "flutter": 10,
    "docker": 10,
    "nginx": 10,
    "redis": 10,
    "stripe-payments": 5,
    "dart": 10,
    "azure-cognitive-services": 5,
}

# ─────────────────────────────────────────────────────────────────
# Domain-specific search queries (rotated per cycle)
# Used by external harvester when aiohttp is available.
# ─────────────────────────────────────────────────────────────────
DOMAIN_SEARCH_QUERIES = {
    "clinical": [
        "AEDP outcome research 2025 2026",
        "Internal Family Systems empirical evidence",
        "Emotionally Focused Therapy effectiveness meta-analysis",
        "Polyvagal Theory clinical application",
        "AI-assisted therapy outcomes study",
        "therapeutic alliance digital platforms research",
        "emotional coherence measurement validated scales",
        "attachment theory adult psychotherapy outcomes",
        "AEDP randomized controlled trial",
        "Internal Family Systems fMRI neuroimaging",
        "emotional coherence psychophysiological measurement",
        "therapeutic alliance rupture repair longitudinal",
        "polyvagal theory heart rate variability intervention",
        "emotional regulation neural correlates treatment",
        "psychotherapy process-outcome research meta-analysis",
        "digital mental health intervention efficacy RCT",
    ],
    "coherence": [
        "emotional coherence physiological markers measurement",
        "quantum decoherence biological systems neuroscience",
        "heart rate variability emotional regulation therapy",
        "interpersonal neural synchrony dyadic coherence",
        "vagal tone polyvagal therapeutic alliance measurement",
        "emotional contagion group therapy dynamics",
        "biometric feedback real-time therapy effectiveness",
        "interoceptive awareness body-based psychotherapy",
        "allostasis interoceptive inference mental health",
        "psychophysiological coherence HeartMath research",
    ],
    "voice": [
        "speech prosody emotional state classification deep learning",
        "pause ratio speech rate clinical depression indicators",
        "vocal pitch variance anxiety detection real-time",
        "affective computing multimodal emotion recognition 2026",
        "voice biomarker mental health screening validation",
        "speaker diarization therapy session analysis",
        "acoustic features psychiatric assessment automated",
        "whisper speech recognition clinical transcription",
    ],
    "biochem": [
        "psychopharmacology computational modeling",
        "neurotransmitter dynamics emotional state",
        "gut-brain axis mental health microbiome",
        "pharmacogenomics antidepressant response prediction",
        "biomarker therapeutic response psychotherapy",
        "neuroinflammation depression treatment resistance",
        "epigenetic changes psychotherapy trauma",
        "cortisol awakening response therapy outcomes",
        "oxytocin therapeutic alliance neurobiological",
    ],
    "research": [
        "retrieval augmented generation optimization 2026",
        "knowledge graph LLM integration",
        "function calling tool use patterns LLM",
        "small language model fine-tuning production",
        "vector database performance comparison",
        "knowledge distillation small language model",
        "continual learning catastrophic forgetting mitigation",
        "mixture of experts routing efficiency",
        "emotional coherence EEG measurement paradigm",
        "affective neuroscience interoception predictive coding",
        "default mode network emotional processing psychotherapy",
        "amygdala prefrontal connectivity therapeutic change",
        "neuroplasticity psychotherapy longitudinal MRI",
        "digital phenotyping mental health smartphone",
        "natural language processing therapy transcripts",
        "conversational AI therapeutic relationship",
    ],
    "defense": [
        "HIPAA breach 2026 telehealth",
        "websocket security vulnerabilities CVE",
        "postgresql encryption at rest best practices",
        "cloudflare workers security hardening",
        "python fastapi security middleware",
        "OWASP top 10 2025 API",
        "telehealth platform data breach case study",
    ],
    "coding": [
        "docker compose production best practices 2026",
        "nginx websocket proxy timeout tuning",
        "postgresql connection pool asyncpg optimization",
        "systemd service restart policy patterns",
        "cloudflare load balancer websocket configuration",
        "blue green deployment docker compose",
        "zero downtime deployment python",
        "Stripe webhook idempotency patterns",
        "Redis pub/sub vs streams production",
    ],
    "coaching": [
        "enterprise coaching platform ROI measurement",
        "employee wellness program AI integration",
        "workplace mental health technology adoption",
        "coaching effectiveness metrics enterprise",
        "B2B SaaS pilot to enterprise conversion",
        "staffing industry employee retention technology",
        "HR tech coaching scalability",
    ],
    "marketing": [
        "mental health app marketing strategy 2026",
        "B2B SaaS pricing psychology",
        "therapist referral network building",
        "telehealth platform user acquisition cost",
        "LinkedIn thought leadership therapy technology",
        "email drip campaign conversion optimization SaaS",
        "app store optimization mental health category",
    ],
    "culture": [
        "therapeutic voice authenticity social media",
        "mental health thought leader content strategy",
        "parasocial relationship AI companion ethics",
        "digital wellness brand voice consistency",
        "language drift detection content moderation",
        "silence and pacing in digital communication",
    ],
    "patent": [
        "artificial intelligence psychotherapy system patent",
        "emotional coherence measurement digital patent",
        "therapeutic AI memory architecture patent WIPO",
        "knowledge crystallization language model patent",
        "digital therapeutic conversational agent patent",
        "voice biomarker mental health patent filing 2025 2026",
        "biometric feedback therapy system patent",
    ],
    "predictive_intelligence": [
        "therapeutic prediction engine longitudinal outcomes",
        "behavioral cycle detection FFT autocorrelation mental health",
        "early warning relapse prediction psychotherapy",
        "time-series forecasting emotional state trajectories",
        "intervention timing optimization predictive analytics",
        "cycle convergence compound risk detection",
        "clinical risk forecasting explainable AI",
        "predictive intelligence engine healthcare orchestration",
    ],
}


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_confidence(source: str) -> float:
    """Look up initial confidence by source tag, with prefix matching fallback."""
    if source in SOURCE_CONFIDENCE:
        return SOURCE_CONFIDENCE[source]
    for key, val in SOURCE_CONFIDENCE.items():
        if source.startswith(key) or key.startswith(source.split("_")[0]):
            return val
    return DEFAULT_CONFIDENCE


# ═══════════════════════════════════════════════════════════════════
# Database Layer
# ═══════════════════════════════════════════════════════════════════

class CrystalDB:
    """Manages PostgreSQL connection pool and crystal operations."""

    def __init__(self, db_url: str):
        self._db_url = db_url
        self._pool = None
        self._dedup_running = False

    async def connect(self):
        import asyncpg
        self._pool = await asyncpg.create_pool(self._db_url, min_size=1, max_size=3)
        logger.info("Connected to PostgreSQL")

    async def close(self):
        if self._pool:
            await self._pool.close()

    async def ensure_tables(self):
        """Create factory-specific tables if they don't exist.
        Gracefully handles permission errors (PG15+ restricts CREATE on public).
        """
        try:
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS crystal_factory_watermarks (
                        node_id VARCHAR(100) PRIMARY KEY,
                        last_harvest TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        crystals_total INTEGER DEFAULT 0
                    )
                """)
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS crystal_factory_heartbeats (
                        id SERIAL PRIMARY KEY,
                        node_id VARCHAR(100) NOT NULL,
                        cycle_number INTEGER NOT NULL,
                        fragments_harvested INTEGER DEFAULT 0,
                        clusters_formed INTEGER DEFAULT 0,
                        crystals_forged INTEGER DEFAULT 0,
                        crystals_deduped INTEGER DEFAULT 0,
                        stage1_filtered INTEGER DEFAULT 0,
                        stage2_synthesized INTEGER DEFAULT 0,
                        elapsed_seconds REAL DEFAULT 0,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                await conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cfh_node_created
                    ON crystal_factory_heartbeats (node_id, created_at DESC)
                """)
        except Exception as e:
            if "permission denied" in str(e).lower():
                logger.info("Tables already created by admin — skipping CREATE (%s)", e)
            else:
                raise

    async def get_watermark(self, node_id: str) -> datetime:
        key = f"{WATERMARK_KEY_PREFIX}:{node_id}"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT last_harvest FROM crystal_factory_watermarks WHERE node_id = $1",
                key,
            )
            if row:
                return row["last_harvest"]
            return datetime.now(timezone.utc) - timedelta(days=7)

    async def set_watermark(self, node_id: str, ts: datetime, crystals_added: int = 0):
        key = f"{WATERMARK_KEY_PREFIX}:{node_id}"
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO crystal_factory_watermarks (node_id, last_harvest, crystals_total)
                VALUES ($1, $2, $3)
                ON CONFLICT (node_id) DO UPDATE SET
                    last_harvest = EXCLUDED.last_harvest,
                    crystals_total = crystal_factory_watermarks.crystals_total + EXCLUDED.crystals_total
            """, key, ts, crystals_added)

    async def write_heartbeat(self, node_id: str, cycle: int, stats: Dict):
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO crystal_factory_heartbeats
                (node_id, cycle_number, fragments_harvested, clusters_formed,
                 crystals_forged, crystals_deduped, stage1_filtered,
                 stage2_synthesized, elapsed_seconds)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
                node_id, cycle,
                stats.get("fragments", 0), stats.get("clusters", 0),
                stats.get("stored", 0), stats.get("deduped", 0),
                stats.get("stage1_passed", 0), stats.get("stage2_synthesized", 0),
                stats.get("elapsed", 0.0),
            )

    async def prune_heartbeats(self, retention_days: int = 30):
        """Remove heartbeat rows older than retention_days to prevent unbounded growth."""
        async with self._pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM crystal_factory_heartbeats
                WHERE created_at < NOW() - INTERVAL '1 day' * $1
            """, retention_days)
            pruned = int(result.split()[-1]) if result else 0
            if pruned > 0:
                logger.info("Pruned %d old heartbeat rows (>%dd)", pruned, retention_days)

    async def check_factory_health(self, max_silence_minutes: int = 60) -> List[Dict]:
        """Return factory nodes and their health status.

        Designed for the bridge health gate to call. A node that hasn't
        heartbeated within max_silence_minutes is considered unhealthy.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT DISTINCT ON (node_id)
                    node_id,
                    cycle_number,
                    crystals_forged,
                    fragments_harvested,
                    elapsed_seconds,
                    created_at,
                    (created_at > NOW() - INTERVAL '1 minute' * $1) AS healthy
                FROM crystal_factory_heartbeats
                ORDER BY node_id, created_at DESC
            """, max_silence_minutes)
            return [dict(r) for r in rows]

    async def store_crystals(self, crystals: List[Dict]) -> int:
        """Write crystals with ON CONFLICT deduplication. Returns count of new crystals."""
        if not crystals:
            return 0
        stored = 0
        async with self._pool.acquire() as conn:
            for c in crystals:
                try:
                    result = await conn.execute("""
                        INSERT INTO nate_intelligence_crystals
                        (crystal_text, domain, scope, topics, source_count,
                         generation, confidence, content_hash, context_start,
                         context_end, face_path)
                        VALUES ($1, $2, $3, $4, $5, 0, $6, $7, $8, $9, $10)
                        ON CONFLICT (content_hash) DO NOTHING
                    """,
                        c["crystal_text"], c["domain"], c["scope"],
                        c.get("topics", []), c.get("source_count", 1),
                        c.get("confidence", DEFAULT_CONFIDENCE),
                        c["content_hash"],
                        c.get("context_start", datetime.now(timezone.utc)),
                        c.get("context_end", datetime.now(timezone.utc)),
                        c.get("face_path"),
                    )
                    if result and result.endswith("1"):
                        stored += 1
                        # GAP 1: Push to Vectorize for semantic search visibility
                        try:
                            from app.services.vectorize_service import index_wisdom, is_vectorize_configured
                            if is_vectorize_configured():
                                _ch = c["content_hash"]
                                await index_wisdom(
                                    user_id="nate_crystal",
                                    wisdom_id=f"crystal_{_ch[:16]}",
                                    insight_type=f"crystal_{c['domain']}",
                                    content=c["crystal_text"],
                                    source="crystal_factory",
                                    domain=c["domain"],
                                    face_path=c.get("face_path") or "",
                                )
                        except Exception as _vz_err:
                            logger.warning("Crystal factory Vectorize push failed: %s", _vz_err)
                except Exception as e:
                    logger.warning("Crystal store failed: %s", e)
        return stored

    async def find_near_duplicates(self, limit: int = 50) -> List[Tuple]:
        """Find crystals with identical domain + very similar text prefix.

        Uses first-80-chars prefix match — cheap alternative to full
        semantic similarity. Catches verbatim and near-verbatim duplicates
        across nodes but won't catch paraphrased content.
        """
        if self._dedup_running:
            return []
        self._dedup_running = True
        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("SET LOCAL statement_timeout = '30s'")
                    rows = await conn.fetch("""
                SELECT a.id AS a_id, b.id AS b_id,
                       a.confidence AS a_conf, b.confidence AS b_conf,
                       a.recall_count AS a_rc, b.recall_count AS b_rc
                FROM nate_intelligence_crystals a
                JOIN nate_intelligence_crystals b
                    ON a.domain = b.domain
                    AND a.id < b.id
                    AND a.scope = b.scope
                    AND a.superseded_by IS NULL
                    AND b.superseded_by IS NULL
                    AND LEFT(a.crystal_text, 80) = LEFT(b.crystal_text, 80)
                WHERE a.scope != 'archived' AND b.scope != 'archived'
                LIMIT $1
            """, limit)
                    return [(r["a_id"], r["b_id"], r["a_conf"], r["b_conf"],
                             r["a_rc"], r["b_rc"]) for r in rows]
        finally:
            self._dedup_running = False

    async def merge_duplicates(self, keep_id: int, remove_id: int,
                                combined_recalls: int):
        """Supersede the lower-value crystal, inherit recall count."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                UPDATE nate_intelligence_crystals
                SET recall_count = $2, updated_at = NOW()
                WHERE id = $1
            """, keep_id, combined_recalls)
            await conn.execute("""
                UPDATE nate_intelligence_crystals
                SET superseded_by = $2, scope = 'archived', updated_at = NOW()
                WHERE id = $1
            """, remove_id, keep_id)

    async def fetch_internal_fragments(self, cutoff: datetime) -> List[Dict]:
        """Harvest from PostgreSQL tables (internal role only)."""
        fragments = []
        async with self._pool.acquire() as conn:
            # ── wisdom_extractions ──
            try:
                rows = await conn.fetch("""
                    SELECT content, insight_type, extracted_at
                    FROM wisdom_extractions
                    WHERE extracted_at > $1 AND approved = true
                      AND content IS NOT NULL AND LENGTH(content) > 30
                    ORDER BY extracted_at DESC LIMIT 50
                """, cutoff)
                for r in rows:
                    fragments.append({
                        "text": f"[Wisdom] {r['content'][:1500]}",
                        "source": "wisdom_extraction",
                        "domain": _classify_domain(r.get("insight_type", "")),
                        "scope": "global",
                        "created_at": r["extracted_at"],
                    })
            except Exception as e:
                logger.warning("wisdom_extractions harvest: %s", e)

            # ── conversation_history (aggregated, never individual) ──
            try:
                rows = await conn.fetch("""
                    SELECT ai_text, session_id, created_at
                    FROM conversation_history
                    WHERE created_at > $1
                      AND ai_text IS NOT NULL AND LENGTH(ai_text) > 100
                    ORDER BY created_at DESC LIMIT 50
                """, cutoff)
                for r in rows:
                    fragments.append({
                        "text": f"[Session Insight] {r['ai_text'][:1500]}",
                        "source": "conversation_history",
                        "domain": "clinical",
                        "scope": "admin_only",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("conversation_history harvest: %s", e)

            # ── coaching_sessions (nate_summary) ──
            try:
                rows = await conn.fetch("""
                    SELECT nate_summary, status, ended_at
                    FROM coaching_sessions
                    WHERE ended_at > $1
                      AND nate_summary IS NOT NULL AND LENGTH(nate_summary) > 30
                    ORDER BY ended_at DESC LIMIT 30
                """, cutoff)
                for r in rows:
                    fragments.append({
                        "text": f"[Session Summary — {r.get('status', 'coaching')}] "
                                f"{r['nate_summary'][:1500]}",
                        "source": "live_session",
                        "domain": "clinical",
                        "scope": "admin_only",
                        "created_at": r["ended_at"],
                    })
            except Exception as e:
                logger.warning("coaching_sessions harvest: %s", e)

            # ── coach_briefings ──
            try:
                rows = await conn.fetch("""
                    SELECT briefing_data, session_datetime
                    FROM coach_briefings
                    WHERE session_datetime > $1 AND briefing_data IS NOT NULL
                    ORDER BY session_datetime DESC LIMIT 30
                """, cutoff)
                for r in rows:
                    bd = r.get("briefing_data") or {}
                    if isinstance(bd, str):
                        try: bd = json.loads(bd)
                        except Exception: bd = {}
                    parts = []
                    for key in ("recommended_focus", "risk_assessment",
                                "current_state", "trajectory"):
                        val = bd.get(key, "")
                        if val and len(val) > 10:
                            parts.append(f"{key}: {val[:300]}")
                    if parts:
                        fragments.append({
                            "text": f"[Coach Briefing] {' | '.join(parts)}"[:1500],
                            "source": "coach_briefing",
                            "domain": "coaching",
                            "scope": "admin_only",
                            "created_at": r.get("session_datetime", datetime.now(timezone.utc)),
                        })
            except Exception as e:
                logger.warning("coach_briefings harvest: %s", e)

            # ── classroom_session_analyses ──
            try:
                rows = await conn.fetch("""
                    SELECT payload, metrics, analyzed_at
                    FROM classroom_session_analyses
                    WHERE analyzed_at > $1
                      AND payload IS NOT NULL
                    ORDER BY analyzed_at DESC LIMIT 30
                """, cutoff)
                for r in rows:
                    payload = r.get("payload") or {}
                    if isinstance(payload, str):
                        try: payload = json.loads(payload)
                        except Exception: payload = {}
                    summary = payload.get("summary", "") or json.dumps(payload)[:600]
                    if len(summary) > 30:
                        fragments.append({
                            "text": f"[Classroom Analysis] {summary[:1500]}",
                            "source": "classroom_analysis",
                            "domain": "coaching",
                            "scope": "admin_only",
                            "created_at": r.get("analyzed_at", datetime.now(timezone.utc)),
                        })
            except Exception as e:
                logger.warning("classroom_session_analyses harvest: %s", e)

            # ── vault_item_annotations (photo analysis) ──
            try:
                rows = await conn.fetch("""
                    SELECT content, user_id, created_at
                    FROM vault_item_annotations
                    WHERE created_at > $1 AND content IS NOT NULL AND LENGTH(content) > 30
                    ORDER BY created_at DESC LIMIT 50
                """, cutoff)
                for r in rows:
                    fragments.append({
                        "text": f"[Photo Analysis] {r['content'][:500]}",
                        "source": "vault_annotation",
                        "domain": "clinical",
                        "scope": f"user:{r['user_id']}" if r.get("user_id") else "admin_only",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("vault_item_annotations harvest: %s", e)

            # ── transfer_crystals (ChatGPT/Claude imports) ──
            try:
                rows = await conn.fetch("""
                    SELECT member_id, crystal, created_at
                    FROM transfer_crystals
                    WHERE created_at > $1
                    ORDER BY created_at DESC LIMIT 20
                """, cutoff)
                for r in rows:
                    cr = r.get("crystal") or {}
                    if isinstance(cr, str):
                        try: cr = json.loads(cr)
                        except Exception: cr = {}
                    for key, label in [("core_identity_summary", "Identity"),
                                       ("active_therapeutic_themes", "Themes"),
                                       ("communication_profile", "Communication")]:
                        text = cr.get(key, "")
                        if text and len(text) > 20:
                            fragments.append({
                                "text": f"[Transfer Crystal — {label}] {text[:800]}",
                                "source": "transfer_crystal",
                                "domain": "clinical",
                                "scope": f"user:{r['member_id']}",
                                "created_at": r["created_at"],
                            })
            except Exception as e:
                logger.warning("transfer_crystals harvest: %s", e)

            # ── vault_items (uploaded documents) ──
            try:
                rows = await conn.fetch("""
                    SELECT display_name, extracted_text_preview, member_id, created_at
                    FROM vault_items
                    WHERE created_at > $1
                      AND extracted_text_preview IS NOT NULL
                      AND LENGTH(extracted_text_preview) > 50
                    ORDER BY created_at DESC LIMIT 30
                """, cutoff)
                for r in rows:
                    fragments.append({
                        "text": f"[Vault Doc: {r.get('display_name', 'untitled')}] "
                                f"{r['extracted_text_preview'][:1500]}",
                        "source": "vault_document",
                        "domain": "clinical",
                        "scope": f"user:{r['member_id']}" if r.get("member_id") else "admin_only",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("vault_items harvest: %s", e)

            # ── skyeye_post_analytics ──
            try:
                rows = await conn.fetch("""
                    SELECT platform, post_id, likes, reposts, comments, impressions, captured_at
                    FROM skyeye_post_analytics
                    WHERE captured_at > $1
                    ORDER BY captured_at DESC LIMIT 50
                """, cutoff)
                for r in rows:
                    fragments.append({
                        "text": (f"[Post Analytics] {r.get('platform', '')} post {r.get('post_id', '')}: "
                                 f"likes={r.get('likes', 0)}, reposts={r.get('reposts', 0)}, "
                                 f"comments={r.get('comments', 0)}, impressions={r.get('impressions', 0)}"),
                        "source": "post_analytics",
                        "domain": "marketing",
                        "scope": "global",
                        "created_at": r["captured_at"],
                    })
            except Exception as e:
                logger.warning("skyeye_post_analytics harvest: %s", e)

            # ── nevedal_metrics (aggregated coherence data) ──
            try:
                rows = await conn.fetch("""
                    SELECT c_emo, p_ent, gamma_env, recorded_at
                    FROM nevedal_metrics
                    WHERE recorded_at > $1
                    ORDER BY recorded_at DESC LIMIT 30
                """, cutoff)
                if len(rows) >= 5:
                    avg_cemo = sum(float(r.get("c_emo", 0) or 0) for r in rows) / len(rows)
                    avg_pent = sum(float(r.get("p_ent", 0) or 0) for r in rows) / len(rows)
                    fragments.append({
                        "text": (f"[Coherence Aggregate] {len(rows)} sessions: "
                                 f"avg C_emo={avg_cemo:.4f}, avg p_ent={avg_pent:.4f}"),
                        "source": "nevedal_metrics",
                        "domain": "clinical",
                        "scope": "admin_only",
                        "created_at": rows[0]["recorded_at"],
                    })
            except Exception as e:
                logger.warning("nevedal_metrics harvest: %s", e)

            # ── skyeye_social_memory (engagement intelligence) ──
            try:
                rows = await conn.fetch("""
                    SELECT platform_handle, platform, interaction_count, interests,
                           tone_notes, updated_at
                    FROM skyeye_social_memory
                    WHERE updated_at > $1 AND interaction_count >= 2
                    ORDER BY updated_at DESC LIMIT 30
                """, cutoff)
                for r in rows:
                    parts = [f"@{r.get('platform_handle', '?')} on {r.get('platform', '?')}",
                             f"interactions={r.get('interaction_count', 0)}"]
                    if r.get("interests"):
                        parts.append(f"interests={r['interests'][:200]}")
                    if r.get("tone_notes"):
                        parts.append(f"tone={r['tone_notes'][:200]}")
                    fragments.append({
                        "text": f"[Social Memory] {' | '.join(parts)}",
                        "source": "social_memory",
                        "domain": "marketing",
                        "scope": "global",
                        "created_at": r["updated_at"],
                    })
            except Exception as e:
                logger.warning("skyeye_social_memory harvest: %s", e)

            # ── skyeye_content_queue (content generation learning) ──
            try:
                rows = await conn.fetch("""
                    SELECT platform, content_text, status, error_message,
                           created_at
                    FROM skyeye_content_queue
                    WHERE created_at > $1 AND content_text IS NOT NULL
                      AND LENGTH(content_text) > 30
                    ORDER BY created_at DESC LIMIT 30
                """, cutoff)
                for r in rows:
                    status = r.get("status", "")
                    text = r["content_text"][:600]
                    reason = r.get("error_message", "")
                    label = f"[Content {status}] {r.get('platform', '')}: {text}"
                    if reason:
                        label += f" | error: {reason[:200]}"
                    fragments.append({
                        "text": label[:1500],
                        "source": "content_queue",
                        "domain": "marketing",
                        "scope": "global",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("skyeye_content_queue harvest: %s", e)

            # ── dynamic_assessments (AI-generated client assessments) ──
            try:
                rows = await conn.fetch("""
                    SELECT category, insights, nate_reflection, created_at
                    FROM dynamic_assessments
                    WHERE created_at > $1
                      AND (nate_reflection IS NOT NULL OR insights IS NOT NULL)
                    ORDER BY created_at DESC LIMIT 30
                """, cutoff)
                for r in rows:
                    text_parts = []
                    reflection = r.get("nate_reflection", "")
                    if reflection and len(reflection) > 20:
                        text_parts.append(reflection[:600])
                    insights = r.get("insights") or {}
                    if isinstance(insights, str):
                        try: insights = json.loads(insights)
                        except Exception: insights = {}
                    if insights:
                        text_parts.append(json.dumps(insights)[:400])
                    if text_parts:
                        fragments.append({
                            "text": f"[Assessment: {r.get('category', 'unknown')}] {' '.join(text_parts)}",
                            "source": "assessment_result",
                            "domain": "clinical",
                            "scope": "admin_only",
                            "created_at": r["created_at"],
                        })
            except Exception as e:
                logger.warning("dynamic_assessments harvest: %s", e)

            # ── dojo_mentor_interactions (DOJO scenario outcomes) ──
            try:
                rows = await conn.fetch("""
                    SELECT dojo_lens, content, interaction_type, created_at
                    FROM dojo_mentor_interactions
                    WHERE created_at > $1
                      AND content IS NOT NULL AND LENGTH(content) > 30
                    ORDER BY created_at DESC LIMIT 30
                """, cutoff)
                for r in rows:
                    lens = r.get("dojo_lens", "unknown")
                    itype = r.get("interaction_type", "")
                    fragments.append({
                        "text": f"[DOJO {lens}/{itype}] {r['content'][:1000]}",
                        "source": "dojo_memory",
                        "domain": "coaching",
                        "scope": "admin_only",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("dojo_mentor_interactions harvest: %s", e)

            # ── liminal_presence_analysis (cultural intelligence) ──
            try:
                rows = await conn.fetch("""
                    SELECT agent, signal, detail, created_at
                    FROM liminal_presence_analysis
                    WHERE created_at > $1
                    ORDER BY created_at DESC LIMIT 20
                """, cutoff)
                for r in rows:
                    fragments.append({
                        "text": (f"[Liminal: {r.get('agent', '')}] "
                                 f"signal={r.get('signal', '')} | "
                                 f"{(r.get('detail', '') or '')[:600]}"),
                        "source": "liminal_analysis",
                        "domain": "marketing",
                        "scope": "admin_only",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("liminal_presence_analysis harvest: %s", e)

            # ── skyeye_sessions (session strategy learning) ──
            try:
                rows = await conn.fetch("""
                    SELECT notes, platforms_visited, total_actions, session_end
                    FROM skyeye_sessions
                    WHERE session_end > $1
                      AND notes IS NOT NULL AND LENGTH(notes) > 30
                    ORDER BY session_end DESC LIMIT 20
                """, cutoff)
                for r in rows:
                    platforms = r.get("platforms_visited") or []
                    if isinstance(platforms, list):
                        platforms = ",".join(platforms)
                    fragments.append({
                        "text": (f"[SkyEye Session] actions={r.get('total_actions', 0)} "
                                 f"platforms={platforms} | "
                                 f"{r['notes'][:800]}"),
                        "source": "skyeye_session",
                        "domain": "marketing",
                        "scope": "admin_only",
                        "created_at": r["session_end"],
                    })
            except Exception as e:
                logger.warning("skyeye_sessions harvest: %s", e)

            # ── community_check_ins (client self-reported state) ──
            try:
                rows = await conn.fetch("""
                    SELECT mood_valence, check_in_time
                    FROM community_check_ins
                    WHERE check_in_time > $1
                      AND mood_valence IS NOT NULL
                    ORDER BY check_in_time DESC LIMIT 40
                """, cutoff)
                if len(rows) >= 5:
                    avg_mood = sum(float(r.get("mood_valence", 0) or 0) for r in rows) / len(rows)
                    fragments.append({
                        "text": (f"[Check-In Aggregate] {len(rows)} check-ins: "
                                 f"avg mood_valence={avg_mood:.2f}"),
                        "source": "community_checkins",
                        "domain": "clinical",
                        "scope": "admin_only",
                        "created_at": rows[0]["check_in_time"],
                    })
            except Exception as e:
                logger.warning("community_check_ins harvest: %s", e)

            # ── nate_intelligence_crystals self-healing (low confidence) ──
            try:
                rows = await conn.fetch("""
                    SELECT id, crystal_text, domain, confidence
                    FROM nate_intelligence_crystals
                    WHERE scope != 'archived'
                      AND superseded_by IS NULL
                      AND confidence < 0.45
                    ORDER BY confidence ASC LIMIT 10
                """)
                for r in rows:
                    fragments.append({
                        "text": (f"[Weak Crystal — {r.get('domain', 'general')} "
                                 f"conf={r.get('confidence', 0):.2f}] "
                                 f"{r['crystal_text'][:600]}"),
                        "source": "self_healing",
                        "domain": r.get("domain", "general"),
                        "scope": "global",
                        "created_at": datetime.now(timezone.utc),
                    })
            except Exception as e:
                logger.warning("self-healing crystal harvest: %s", e)

            # ── login_attempts (defense intelligence) ──
            try:
                rows = await conn.fetch("""
                    SELECT identifier, success, ip_address, created_at
                    FROM login_attempts
                    WHERE created_at > $1 AND NOT success
                    ORDER BY created_at DESC LIMIT 30
                """, cutoff)
                if len(rows) >= 3:
                    unique_ips = len(set(r.get("ip_address", "") for r in rows))
                    unique_ids = len(set(r.get("identifier", "") for r in rows))
                    fragments.append({
                        "text": (f"[Failed Logins] {len(rows)} failures from "
                                 f"{unique_ips} IPs targeting {unique_ids} accounts"),
                        "source": "login_attempts",
                        "domain": "defense",
                        "scope": "admin_only",
                        "created_at": rows[0]["created_at"],
                    })
            except Exception as e:
                logger.warning("login_attempts harvest: %s", e)

            # ── therapeutic_predictions (Predictive Intelligence Engine) ──
            try:
                rows = await conn.fetch("""
                    SELECT goal_type, success_probability, confidence_score,
                           key_amplifiers, key_resistances, created_at
                    FROM therapeutic_predictions
                    WHERE created_at > $1
                    ORDER BY created_at DESC LIMIT 40
                """, cutoff)
                for r in rows:
                    amps = r.get("key_amplifiers") or []
                    resists = r.get("key_resistances") or []
                    if isinstance(amps, str):
                        try:
                            amps = json.loads(amps)
                        except Exception:
                            amps = []
                    if isinstance(resists, str):
                        try:
                            resists = json.loads(resists)
                        except Exception:
                            resists = []
                    fragments.append({
                        "text": (
                            f"[Predictive Intelligence] goal={r.get('goal_type', 'general')} "
                            f"p={float(r.get('success_probability') or 0):.2f} "
                            f"conf={float(r.get('confidence_score') or 0):.2f} "
                            f"amplifiers={str(amps)[:250]} resistances={str(resists)[:250]}"
                        ),
                        "source": "therapeutic_prediction",
                        "domain": "research",
                        "scope": "admin_only",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("therapeutic_predictions harvest: %s", e)

            # ── cycle_detections (Cycle Detection Engine) ──
            try:
                rows = await conn.fetch("""
                    SELECT domain, detected_period_days, amplitude, confidence, detected_at
                    FROM cycle_detections
                    WHERE detected_at > $1
                    ORDER BY detected_at DESC LIMIT 40
                """, cutoff)
                for r in rows:
                    fragments.append({
                        "text": (
                            f"[Cycle Detection] domain={r.get('domain', 'unknown')} "
                            f"period={float(r.get('detected_period_days') or 0):.2f}d "
                            f"amp={float(r.get('amplitude') or 0):.4f} "
                            f"conf={float(r.get('confidence') or 0):.2f}"
                        ),
                        "source": "cycle_detection",
                        "domain": "research",
                        "scope": "admin_only",
                        "created_at": r["detected_at"],
                    })
            except Exception as e:
                logger.warning("cycle_detections harvest: %s", e)

        return fragments


# ═══════════════════════════════════════════════════════════════════
# External Harvester (Hetzner)
# ═══════════════════════════════════════════════════════════════════

class ExternalHarvester:
    """Harvests from RSS feeds, GitHub trending, StackOverflow."""

    def __init__(self):
        self._session = None
        self._full_harvest_every_cycles = max(
            1, int(os.environ.get("FULL_HARVEST_EVERY_CYCLES", "180"))
        )
        self._queries_per_cycle = max(
            1, int(os.environ.get("SEARCH_QUERIES_PER_CYCLE", "1"))
        )
        self._query_rotation: List[Tuple[str, str]] = []
        for domain in sorted(DOMAIN_SEARCH_QUERIES.keys()):
            for query in DOMAIN_SEARCH_QUERIES.get(domain, []):
                self._query_rotation.append((domain, query))
        self._query_cursor = 0

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "CrystalFactory/1.0"},
            )

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def harvest(self, cutoff: datetime, cycle: int = 0) -> List[Dict]:
        await self._ensure_session()
        fragments = []
        # Internet research queries run every cycle for high-cadence learning.
        sq = await self._harvest_search_queries(cycle)
        fragments.extend(sq)
        # High-cost harvesters run on a slower cadence to avoid API abuse.
        if cycle % self._full_harvest_every_cycles == 1:
            rss = await self._harvest_rss(cutoff)
            fragments.extend(rss)
            gh = await self._harvest_github(cutoff)
            fragments.extend(gh)
            so = await self._harvest_stackoverflow()
            fragments.extend(so)
        return fragments

    async def harvest_search_only(self, cycle: int = 0) -> List[Dict]:
        await self._ensure_session()
        return await self._harvest_search_queries(cycle)

    async def _harvest_rss(self, cutoff: datetime) -> List[Dict]:
        fragments = []
        for url, domain, fmt in RSS_FEEDS:
            try:
                async with self._session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
                root = ElementTree.fromstring(text)
                items = self._parse_feed(root, fmt)
                for item in items[:10]:
                    title = item.get("title", "")
                    summary = item.get("summary", "")
                    if not title or len(title) < 10:
                        continue
                    frag_text = f"{title}. {summary[:500]}" if summary else title
                    host = url.split("/")[2]
                    fragments.append({
                        "text": f"[RSS: {host}] {frag_text[:1500]}",
                        "source": f"rss_{host}",
                        "domain": domain,
                        "scope": "global",
                        "created_at": datetime.now(timezone.utc),
                    })
            except Exception as e:
                logger.debug("RSS %s failed: %s", url, e)
        logger.info("RSS harvest: %d fragments from %d feeds", len(fragments), len(RSS_FEEDS))
        return fragments

    @staticmethod
    def _parse_feed(root, fmt: str) -> List[Dict]:
        items = []
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        if fmt == "atom":
            for entry in root.findall("atom:entry", ns):
                title_el = entry.find("atom:title", ns)
                summary_el = entry.find("atom:summary", ns)
                items.append({
                    "title": title_el.text if title_el is not None else "",
                    "summary": summary_el.text if summary_el is not None else "",
                })
        else:
            for item_el in root.iter("item"):
                title_el = item_el.find("title")
                desc_el = item_el.find("description")
                items.append({
                    "title": title_el.text if title_el is not None else "",
                    "summary": (desc_el.text or "")[:500] if desc_el is not None else "",
                })
        return items

    async def _harvest_github(self, cutoff: datetime) -> List[Dict]:
        fragments = []
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        for lang, domain in GITHUB_TRENDING_QUERIES:
            try:
                url = (
                    f"https://api.github.com/search/repositories"
                    f"?q=language:{lang}+created:>{week_ago}"
                    f"&sort=stars&order=desc&per_page=5"
                )
                async with self._session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                for repo in (data.get("items") or [])[:5]:
                    name = repo.get("full_name", "")
                    desc = repo.get("description", "") or ""
                    stars = repo.get("stargazers_count", 0)
                    if not desc or len(desc) < 10:
                        continue
                    fragments.append({
                        "text": f"[GitHub Trending] {name} ({stars} stars): {desc[:500]}",
                        "source": "github_trending",
                        "domain": domain,
                        "scope": "global",
                        "created_at": datetime.now(timezone.utc),
                    })
            except Exception as e:
                logger.debug("GitHub %s failed: %s", lang, e)
        logger.info("GitHub harvest: %d fragments", len(fragments))
        return fragments

    async def _harvest_stackoverflow(self) -> List[Dict]:
        """Harvest hot questions per tag with per-tag score thresholds."""
        fragments = []
        for tag in STACKOVERFLOW_TAGS:
            min_score = SO_MIN_SCORES.get(tag, 5)
            try:
                url = (
                    f"https://api.stackexchange.com/2.3/questions"
                    f"?order=desc&sort=hot&site=stackoverflow"
                    f"&tagged={tag}&pagesize=10&filter=withbody"
                )
                async with self._session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                for q in (data.get("items") or [])[:10]:
                    title = q.get("title", "")
                    score = q.get("score", 0)
                    if not title or score < min_score:
                        continue
                    title = html_mod.unescape(title)
                    source = "stackoverflow_high" if score >= 15 else "stackoverflow"
                    domain = "defense" if tag == "cloudflare-workers" else "coding"
                    fragments.append({
                        "text": f"[StackOverflow [{tag}] score:{score}] {title}",
                        "source": source,
                        "domain": domain,
                        "scope": "global",
                        "created_at": datetime.now(timezone.utc),
                    })
            except Exception as e:
                logger.debug("StackOverflow [%s] failed: %s", tag, e)
        logger.info("StackOverflow harvest: %d fragments across %d tags",
                     len(fragments), len(STACKOVERFLOW_TAGS))
        return fragments

    async def _harvest_search_queries(self, cycle: int) -> List[Dict]:
        """Run domain-specific DuckDuckGo searches with full round-robin rotation."""
        fragments = []
        if not self._query_rotation:
            return fragments
        runs = min(self._queries_per_cycle, len(self._query_rotation))
        used_domains = set()
        for _ in range(runs):
            domain, query = self._query_rotation[self._query_cursor % len(self._query_rotation)]
            self._query_cursor = (self._query_cursor + 1) % len(self._query_rotation)
            used_domains.add(domain)
            try:
                url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
                async with self._session.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; CrystalFactory/1.0)"
                }) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
                results = self._parse_ddg_html(text)
                for title, snippet in results[:3]:
                    if len(snippet) > 30:
                        fragments.append({
                            "text": f"[Search: {query[:60]}] {title}. {snippet[:500]}",
                            "source": "search_query",
                            "domain": domain,
                            "scope": "global",
                            "created_at": datetime.now(timezone.utc),
                        })
            except Exception as e:
                logger.debug("Search query '%s' failed: %s", query[:40], e)
        if fragments:
            logger.info("Search harvest: %d fragments from %d domain(s)",
                        len(fragments), len(used_domains))
        return fragments

    @staticmethod
    def _parse_ddg_html(html_text: str) -> List[Tuple[str, str]]:
        """Extract (title, snippet) pairs from DuckDuckGo HTML results."""
        results = []
        try:
            import re
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html_text)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|span)',
                                  html_text, re.DOTALL)
            for t, s in zip(titles[:5], snippets[:5]):
                clean_t = html_mod.unescape(re.sub(r'<[^>]+>', '', t)).strip()
                clean_s = html_mod.unescape(re.sub(r'<[^>]+>', '', s)).strip()
                if clean_t and clean_s:
                    results.append((clean_t, clean_s))
        except Exception:
            pass
        return results


# ═══════════════════════════════════════════════════════════════════
# Two-Stage Synthesis Pipeline
# ═══════════════════════════════════════════════════════════════════

class SynthesisPipeline:
    """
    Stage 1 (Ollama 8B, $0): Score each fragment 0-10 for relevance.
        Filters out generic/trivial content before expensive synthesis.
    Stage 2 (Grok, ~$0.0001/crystal): Synthesize top clusters into
        high-quality, specific, recallable crystal text.

    Falls back gracefully: no Ollama → skip filtering, no Grok → Ollama synthesis.
    """

    def __init__(self, ollama_url: str, grok_url: str, grok_key: str, grok_model: str):
        self._ollama_url = ollama_url
        self._grok_url = grok_url
        self._grok_key = grok_key
        self._grok_model = grok_model
        self._session: Optional["aiohttp.ClientSession"] = None

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60),
            )

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def stage1_filter(self, fragments: List[Dict]) -> List[Dict]:
        """Use Ollama 8B to score fragments 0-10 and keep score >= 6."""
        if not self._ollama_url or not fragments:
            return fragments

        await self._ensure_session()
        passed = []
        batch_size = 10
        for i in range(0, len(fragments), batch_size):
            batch = fragments[i:i + batch_size]
            batch_text = "\n".join(
                f"{j+1}. {f['text'][:200]}" for j, f in enumerate(batch)
            )
            prompt = (
                "Score each fragment 0-10 for knowledge value to a therapy AI "
                "platform built with FastAPI, Flutter, PostgreSQL, WebSockets, "
                "and Cloudflare Workers. Domains: clinical psychotherapy (AEDP, "
                "IFS, EFT, polyvagal), emotional coherence measurement, "
                "HIPAA security, voice biometrics, crystal memory systems, "
                "enterprise coaching, and digital therapeutics.\n"
                "10 = specific actionable insight for this platform, "
                "0 = generic/obvious/unrelated. "
                "Return ONLY comma-separated scores. "
                "Example for 3 fragments: 7,3,8\n\n"
                f"{batch_text}"
            )
            try:
                payload = {
                    "model": os.getenv("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M"),
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 50},
                }
                async with self._session.post(
                    f"{self._ollama_url}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Stage 1 Ollama returned %d, passing batch unfiltered", resp.status)
                        passed.extend(batch)
                        continue
                    data = await resp.json()
                response = data.get("response", "").strip()
                scores = self._parse_scores(response, len(batch))
                for frag, score in zip(batch, scores):
                    if score >= 6:
                        frag["relevance_score"] = score
                        passed.append(frag)
            except Exception as e:
                logger.warning("Stage 1 filter batch failed, passing all: %s", e)
                passed.extend(batch)

        logger.info("Stage 1 filter: %d/%d fragments passed (score >= 6)",
                     len(passed), len(fragments))
        return passed

    @staticmethod
    def _parse_scores(response: str, expected: int) -> List[int]:
        """Parse comma-separated scores from Ollama response."""
        scores = []
        for part in response.replace("\n", ",").split(","):
            part = part.strip().rstrip(".")
            try:
                s = int(part)
                scores.append(max(0, min(10, s)))
            except ValueError:
                continue
        while len(scores) < expected:
            scores.append(7)
        return scores[:expected]

    async def stage2_synthesize(self, cluster: Dict) -> str:
        """Use Grok for high-quality crystal synthesis. Falls back to Ollama."""
        await self._ensure_session()
        items = cluster["items"]
        texts = sorted(set(i["text"][:500] for i in items))
        joined = "\n---\n".join(texts[:8])

        synthesis_prompt = (
            "You are a knowledge crystallizer. Distill these related fragments "
            "into a SPECIFIC, ACTIONABLE insight. Include:\n"
            "- Concrete patterns, code paths, or techniques\n"
            "- Failure modes or edge cases when relevant\n"
            "- Domain: " + cluster["domain"] + "\n\n"
            "Be precise (3-6 sentences). No generic platitudes. "
            "A crystal saying 'FastAPI uses async' is worthless. "
            "A crystal saying 'bridge_server.py handlers modifying session state "
            "must acquire the lock before reading _cli_session_cache' is valuable.\n\n"
            + joined
        )

        # Try Grok first (high quality)
        if self._grok_url and self._grok_key:
            try:
                payload = {
                    "model": self._grok_model,
                    "messages": [
                        {"role": "system", "content": "You are a knowledge crystallizer."},
                        {"role": "user", "content": synthesis_prompt},
                    ],
                    "max_completion_tokens": 400,
                    "temperature": 0.3,
                }
                headers = {
                    "Content-Type": "application/json",
                    "api-key": self._grok_key,
                }
                async with self._session.post(
                    self._grok_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=45),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            text = choices[0].get("message", {}).get("content", "").strip()
                            if text and len(text) > 40:
                                return text[:MAX_CRYSTAL_LENGTH]
                    else:
                        body = await resp.text()
                        logger.warning("Grok returned %d: %s", resp.status, body[:200])
            except Exception as e:
                logger.warning("Grok synthesis failed, falling back to Ollama: %s", e)

        # Fallback: Ollama synthesis (lower quality but free)
        if self._ollama_url:
            try:
                payload = {
                    "model": os.getenv("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M"),
                    "prompt": synthesis_prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 400},
                }
                async with self._session.post(
                    f"{self._ollama_url}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        text = data.get("response", "").strip()
                        if text and len(text) > 40:
                            return text[:MAX_CRYSTAL_LENGTH]
                    else:
                        logger.warning("Ollama synthesis returned %d", resp.status)
            except Exception as e:
                logger.warning("Ollama synthesis fallback failed: %s", e)

        logger.warning("Both Grok and Ollama synthesis failed — using raw concatenation")
        return "\n".join(texts)[:MAX_CRYSTAL_LENGTH]


# ═══════════════════════════════════════════════════════════════════
# Clustering
# ═══════════════════════════════════════════════════════════════════

def cluster_fragments(fragments: List[Dict]) -> List[Dict]:
    """Domain-based clustering with affinity merging."""
    domain_groups: Dict[str, List[Dict]] = {}
    for f in fragments:
        d = f.get("domain", "general")
        domain_groups.setdefault(d, []).append(f)

    merged: set = set()
    for pair, target in DOMAIN_AFFINITY.items():
        d1, d2 = tuple(pair)
        if d1 in merged or d2 in merged:
            continue
        g1 = domain_groups.get(d1, [])
        g2 = domain_groups.get(d2, [])
        if not g1 or not g2:
            continue
        if len(g1) < CLUSTER_MIN_ITEMS or len(g2) < CLUSTER_MIN_ITEMS:
            combined = g1 + g2
            if len(combined) >= CLUSTER_MIN_ITEMS:
                domain_groups[target] = combined
                if d1 != target and d1 in domain_groups:
                    del domain_groups[d1]
                if d2 != target and d2 in domain_groups:
                    del domain_groups[d2]
                merged.add(d1)
                merged.add(d2)

    clusters = []
    for domain, items in domain_groups.items():
        if len(items) < CLUSTER_MIN_ITEMS:
            continue
        scope = items[0].get("scope", "global")
        clusters.append({
            "domain": domain,
            "scope": scope,
            "items": items,
        })
    return clusters


# ═══════════════════════════════════════════════════════════════════
# Main Factory Loop
# ═══════════════════════════════════════════════════════════════════

class CrystalFactory:
    """Orchestrates harvest → filter → cluster → synthesize → store."""

    def __init__(self):
        self.role = os.getenv("CRYSTAL_ROLE", "external")
        self.node_id = os.getenv("CRYSTAL_NODE_ID", platform.node())
        self.interval = int(os.getenv("HARVEST_INTERVAL_SEC", "10"))
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.grok_url = os.getenv("GROK_URL", os.getenv("NATE_CHAT_URL", ""))
        self.grok_key = os.getenv("GROK_API_KEY", os.getenv("NATE_CHAT_KEY", ""))
        self.grok_model = os.getenv("GROK_MODEL", os.getenv(
            "NATE_CHAT_MODEL", "grok-4-1-fast-non-reasoning"))
        self.enable_search_queries = os.getenv("ENABLE_SEARCH_QUERIES", "true").lower() in ("1", "true", "yes")
        self.db_url = (os.getenv("PRODUCTION_DB_URL", "")
                       or os.getenv("PRODUCTION_DATABASE_URL", "")
                       or os.getenv("DATABASE_URL", ""))
        self._running = True
        self._db = None
        self._external = None
        self._pipeline = None
        self._cycles = 0
        self._total_crystals = 0

    async def start(self):
        if not self.db_url:
            logger.error("No DB URL found (checked PRODUCTION_DB_URL, PRODUCTION_DATABASE_URL, DATABASE_URL). Exiting.")
            return

        self._db = CrystalDB(self.db_url)
        await self._db.connect()
        await self._db.ensure_tables()

        if self.role == "external" or self.enable_search_queries:
            self._external = ExternalHarvester()

        self._pipeline = SynthesisPipeline(
            ollama_url=self.ollama_url,
            grok_url=self.grok_url,
            grok_key=self.grok_key,
            grok_model=self.grok_model,
        )

        grok_status = "CONFIGURED" if self.grok_key else "DISABLED (Ollama-only)"

        logger.info(
            "╔══════════════════════════════════════════════════════╗\n"
            "║   Crystal Factory — ONLINE                          ║\n"
            "║   Node:    %-40s ║\n"
            "║   Role:    %-40s ║\n"
            "║   Cycle:   every %4d seconds                        ║\n"
            "║   Stage 1: Ollama 8B filter                         ║\n"
            "║   Stage 2: Grok %-36s ║\n"
            "╚══════════════════════════════════════════════════════╝",
            self.node_id[:40],
            self.role[:40],
            self.interval,
            grok_status[:36],
        )

        while self._running:
            try:
                await self._cycle()
            except Exception as e:
                logger.error("Cycle failed: %s", e)
            if self._running:
                await asyncio.sleep(self.interval)

        if self._external:
            await self._external.close()
        if self._pipeline:
            await self._pipeline.close()
        await self._db.close()
        logger.info("Crystal Factory shut down. Total crystals: %d", self._total_crystals)

    async def _cycle(self):
        self._cycles += 1
        cycle_start = time.monotonic()
        now = datetime.now(timezone.utc)
        cutoff = await self._db.get_watermark(self.node_id)
        logger.info("── Cycle %d (%s) ── cutoff: %s",
                     self._cycles, self.role, cutoff.isoformat())

        # ── Harvest ──
        if self.role == "external":
            fragments = await self._external.harvest(cutoff, cycle=self._cycles)
        elif self.role == "internal":
            fragments = await self._db.fetch_internal_fragments(cutoff)
            if self.enable_search_queries and self._external:
                search_frags = await self._external.harvest_search_only(cycle=self._cycles)
                fragments.extend(search_frags)
        else:
            logger.error("Unknown CRYSTAL_ROLE: %s", self.role)
            return

        if not fragments:
            logger.info("No new fragments. Sleeping.")
            await self._db.set_watermark(self.node_id, now, 0)
            await self._db.write_heartbeat(self.node_id, self._cycles, {
                "fragments": 0, "elapsed": time.monotonic() - cycle_start,
            })
            return

        logger.info("Harvested %d fragments", len(fragments))

        # ── Stage 1: Ollama 8B relevance filter ──
        filtered = await self._pipeline.stage1_filter(fragments)

        # ── Cluster ──
        clusters = cluster_fragments(filtered)
        if not clusters:
            logger.info("No clusters formed (need %d+ fragments per domain).",
                        CLUSTER_MIN_ITEMS)
            await self._db.write_heartbeat(self.node_id, self._cycles, {
                "fragments": len(fragments), "stage1_passed": len(filtered),
                "elapsed": time.monotonic() - cycle_start,
            })
            return

        logger.info("Formed %d clusters from %d filtered fragments",
                     len(clusters), len(filtered))

        # ── Stage 2: Grok synthesis ──
        crystals_to_store = []
        stage2_count = 0
        for cluster in clusters:
            crystal_text = await self._pipeline.stage2_synthesize(cluster)
            stage2_count += 1
            if not crystal_text or len(crystal_text) < 30:
                continue

            h = _content_hash(crystal_text)
            context_times = [i["created_at"] for i in cluster["items"]
                             if i.get("created_at")]
            ctx_start = min(context_times) if context_times else now
            ctx_end = max(context_times) if context_times else now

            source_scores = [_source_confidence(i.get("source", ""))
                             for i in cluster["items"]]
            base_confidence = sum(source_scores) / len(source_scores)
            cluster_bonus = min(len(cluster["items"]) * 0.01, 0.10)
            confidence = min(base_confidence + cluster_bonus, 0.85)

            crystals_to_store.append({
                "crystal_text": crystal_text,
                "domain": cluster["domain"],
                "scope": cluster["scope"],
                "topics": [],
                "source_count": len(cluster["items"]),
                "confidence": confidence,
                "content_hash": h,
                "context_start": ctx_start,
                "context_end": ctx_end,
                "face_path": f"factory:{self.node_id}",
            })

        stored = await self._db.store_crystals(crystals_to_store)
        self._total_crystals += stored
        elapsed = time.monotonic() - cycle_start

        await self._db.set_watermark(self.node_id, now, stored)

        stats = {
            "fragments": len(fragments),
            "stage1_passed": len(filtered),
            "clusters": len(clusters),
            "stage2_synthesized": stage2_count,
            "stored": stored,
            "deduped": len(crystals_to_store) - stored,
            "elapsed": elapsed,
        }
        await self._db.write_heartbeat(self.node_id, self._cycles, stats)

        logger.info(
            "Cycle %d: %d harvested → %d filtered → %d clusters → "
            "%d synthesized → %d stored (%d dedup) in %.1fs. Total: %d",
            self._cycles, len(fragments), len(filtered), len(clusters),
            stage2_count, stored, len(crystals_to_store) - stored,
            elapsed, self._total_crystals,
        )

        # ── Periodic maintenance ──
        if self._cycles % DEDUP_INTERVAL_CYCLES == 0:
            await self._semantic_dedup()
            await self._db.prune_heartbeats(retention_days=30)

    async def _semantic_dedup(self):
        """Merge near-duplicate crystals (same domain, same 80-char prefix)."""
        try:
            pairs = await self._db.find_near_duplicates(limit=30)
            if not pairs:
                logger.info("Prefix dedup: no near-duplicates found")
                return
            merged = 0
            for a_id, b_id, a_conf, b_conf, a_rc, b_rc in pairs:
                combined = (a_rc or 0) + (b_rc or 0)
                if a_conf >= b_conf:
                    keep, remove = a_id, b_id
                else:
                    keep, remove = b_id, a_id
                await self._db.merge_duplicates(keep, remove, combined)
                merged += 1
                logger.info("Dedup: keep #%d, archive #%d (recalls=%d)",
                            keep, remove, combined)
            logger.info("Prefix dedup: merged %d near-duplicate pairs", merged)
        except Exception as e:
            logger.warning("Prefix dedup failed: %s", e)

    def stop(self):
        self._running = False


# ═══════════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════════

def _classify_domain(insight_type: str) -> str:
    it = (insight_type or "").lower()
    if any(k in it for k in ("coherence", "c_emo", "p_ent", "nevedal",
                               "biometric", "hrv", "vagal tone",
                               "psychophysiol", "heartmath")):
        return "clinical"
    if any(k in it for k in ("voice", "prosody", "pitch", "acoustic",
                               "speech rate", "pause ratio", "whisper",
                               "diarization", "vocal")):
        return "research"
    if any(k in it for k in ("cortisol", "epigenetic", "pharmacol",
                               "neurotransmitter", "microbiome",
                               "oxytocin", "neuroinflammation",
                               "gut-brain", "pharmacogenomic")):
        return "research"
    if any(k in it for k in ("clinical", "therapy", "emotional",
                               "aedp", "ifs", "eft", "polyvagal",
                               "attachment", "psychotherapy",
                               "therapeutic", "trauma")):
        return "clinical"
    if any(k in it for k in ("coaching", "technique", "approach",
                               "enterprise", "workplace", "wellness")):
        return "coaching"
    if any(k in it for k in ("marketing", "growth", "engagement",
                               "funnel", "acquisition", "seo")):
        return "marketing"
    if any(k in it for k in ("security", "hipaa", "cve", "breach",
                               "defense", "owasp")):
        return "defense"
    if any(k in it for k in ("neuroscience", "fmri", "neural", "brain")):
        return "research"
    if any(k in it for k in ("predictive intelligence", "therapeutic prediction",
                               "cycle detection", "forecast", "temporal intelligence")):
        return "research"
    if any(k in it for k in ("patent", "wipo", "ip filing")):
        return "research"
    if any(k in it for k in ("code", "deploy", "bug", "fix", "api",
                               "docker", "nginx", "asyncio", "stripe",
                               "redis", "flutter", "fastapi")):
        return "coding"
    return "general"


# ═══════════════════════════════════════════════════════════════════
# Network Status Dashboard
# ═══════════════════════════════════════════════════════════════════

NODE_META = {
    "hetzner-finland": {
        "label": "Hetzner",
        "hours": "24",
        "sources": "RSS, GitHub, SO",
        "est_crystals": "50-150",
    },
    "digitalocean-primary": {
        "label": "DigitalOcean",
        "hours": "24",
        "sources": "10 PG tables",
        "est_crystals": "30-80",
    },
    "mac-blue": {
        "label": "Mac (BLUE)",
        "hours": "8-12",
        "sources": "Local dev",
        "est_crystals": "20-40",
    },
}


async def _print_status(db_url: str):
    """Query production DB and print the unified crystal network dashboard."""
    import asyncpg

    conn = await asyncpg.connect(db_url)

    heartbeat_rows: List[Dict] = []
    watermark_rows: List[Dict] = []
    crystal_rows: List[Dict] = []

    try:
        crystal_rows = await conn.fetch("""
            SELECT
                CASE
                    WHEN face_path LIKE 'factory:hetzner%'       THEN 'hetzner-finland'
                    WHEN face_path LIKE 'factory:digitalocean%'  THEN 'digitalocean-primary'
                    ELSE 'mac-blue'
                END AS node,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') AS last_24h,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days')  AS last_7d,
                array_agg(DISTINCT domain) AS domains
            FROM nate_intelligence_crystals
            WHERE scope != 'archived' AND superseded_by IS NULL
            GROUP BY 1
            ORDER BY 1
        """)

        try:
            heartbeat_rows = await conn.fetch("""
                SELECT DISTINCT ON (node_id)
                    node_id,
                    cycle_number,
                    fragments_harvested,
                    stage1_filtered AS passed_filter,
                    crystals_forged,
                    elapsed_seconds,
                    created_at,
                    (created_at > NOW() - INTERVAL '60 minutes') AS healthy
                FROM crystal_factory_heartbeats
                ORDER BY node_id, created_at DESC
            """)
        except Exception:
            pass

        try:
            watermark_rows = await conn.fetch("""
                SELECT node_id, last_harvest, crystals_total
                FROM crystal_factory_watermarks
                ORDER BY last_harvest DESC
            """)
        except Exception:
            pass

    finally:
        await conn.close()

    # ── Build lookup dicts ──
    crystals_by_node: Dict[str, Dict] = {}
    for r in crystal_rows:
        crystals_by_node[r["node"]] = {
            "total": r["total"],
            "last_24h": r["last_24h"],
            "last_7d": r["last_7d"],
            "domains": sorted(set(d for d in (r["domains"] or []) if d)),
        }

    heartbeat_by_node: Dict[str, Dict] = {}
    for r in heartbeat_rows:
        key = r["node_id"].replace("crystal_factory_watermark:", "")
        for nid in NODE_META:
            if nid in key:
                heartbeat_by_node[nid] = dict(r)
                break

    watermark_by_node: Dict[str, int] = {}
    for r in watermark_rows:
        key = r["node_id"].replace("crystal_factory_watermark:", "")
        for nid in NODE_META:
            if nid in key:
                watermark_by_node[nid] = r.get("crystals_total", 0)
                break

    # ── Print Dashboard ──
    W = 100
    print()
    print(f"╔{'═' * W}╗")
    print(f"║{'Crystal Factory Network — Live Status':^{W}}║")
    print(f"╠{'═' * W}╣")
    print(f"║{'':{W}}║")

    hdr = f"  {'Node':<16} {'Hrs/day':>7}  {'Sources':<16} {'24h':>5} {'7d':>6} {'Total':>7}  {'Domains':<24} {'Status'}"
    print(f"║{hdr:<{W}}║")
    print(f"║  {'─' * (W - 4):<{W}}║")

    grand_24h = 0
    grand_7d = 0
    grand_total = 0

    for node_id, meta in NODE_META.items():
        c = crystals_by_node.get(node_id, {})
        n24 = c.get("last_24h", 0)
        n7d = c.get("last_7d", 0)
        ntot = c.get("total", 0)
        doms = c.get("domains", [])
        domains = ", ".join(doms) if doms else "-"

        # BLUE crystals often get deduped against Hetzner/DO (same content_hash),
        # so face_path-based counts undercount BLUE's true production.
        # Use watermark total (reported by BLUE during sync) when higher.
        wm_total = watermark_by_node.get(node_id)
        if wm_total is not None and wm_total > ntot:
            ntot = wm_total

        grand_24h += n24
        grand_7d += n7d
        grand_total += ntot

        hb = heartbeat_by_node.get(node_id)
        if node_id == "mac-blue":
            if hb and hb.get("healthy"):
                status = "● ONLINE"
            elif c or (wm_total is not None and wm_total > 0):
                status = "● LOCAL"
            else:
                status = "○ IDLE"
        elif hb and hb.get("healthy"):
            status = "● ONLINE"
        elif hb:
            status = "⚠ STALE"
        else:
            status = "○ NO DATA"

        line = f"  {meta['label']:<16} {meta['hours']:>7}  {meta['sources']:<16} {n24:>5} {n7d:>6} {ntot:>7}  {domains:<24} {status}"
        print(f"║{line:<{W}}║")

    print(f"║  {'─' * (W - 4):<{W}}║")
    total_line = f"  {'TOTAL':<16} {'':>7}  {'':>16} {grand_24h:>5} {grand_7d:>6} {grand_total:>7}  {'All domains':<24}"
    print(f"║{total_line:<{W}}║")
    print(f"║{'':{W}}║")
    print(f"╚{'═' * W}╝")

    # ── Factory Heartbeat Details ──
    if heartbeat_rows:
        print()
        print("  Factory Heartbeats (most recent cycle per node):")
        print(f"  {'Node':<30} {'Cycle':>6} {'Harvest':>8} {'Filter':>7} {'Forged':>7} {'Secs':>6}  {'Last Beat'}")
        print(f"  {'─'*90}")
        for r in heartbeat_rows:
            age_min = "?"
            if r["created_at"]:
                delta = datetime.now(timezone.utc) - r["created_at"].replace(tzinfo=timezone.utc) \
                    if r["created_at"].tzinfo is None else datetime.now(timezone.utc) - r["created_at"]
                age_min = f"{int(delta.total_seconds() / 60)}m ago"
            status = "✅" if r.get("healthy") else "⚠️"
            print(f"  {r['node_id']:<30} {r['cycle_number']:>6} {r['fragments_harvested']:>8} "
                  f"{r['passed_filter'] or 0:>7} {r['crystals_forged']:>7} {r['elapsed_seconds']:>6.1f}  "
                  f"{age_min} {status}")

    # ── Watermarks ──
    if watermark_rows:
        print()
        print("  Watermarks (last harvest timestamp per node):")
        for r in watermark_rows:
            print(f"    {r['node_id']:<45} {str(r['last_harvest'])[:19]}  total={r['crystals_total']}")

    print()


# ═══════════════════════════════════════════════════════════════════
# Entry Point
# ═══════════════════════════════════════════════════════════════════

def main():
    if "--status" in sys.argv:
        db_url = (os.getenv("PRODUCTION_DB_URL", "")
                  or os.getenv("PRODUCTION_DATABASE_URL", "")
                  or os.getenv("DATABASE_URL", ""))
        if not db_url:
            pg_host = os.getenv("POSTGRES_HOST", "")
            pg_user = os.getenv("POSTGRES_USER", "nate_admin")
            pg_pass = os.getenv("POSTGRES_PASSWORD", "")
            pg_db = os.getenv("POSTGRES_DB", "little_nate")
            pg_port = os.getenv("POSTGRES_PORT", "5432")
            if pg_host and pg_pass:
                from urllib.parse import quote
                db_url = f"postgresql://{pg_user}:{quote(pg_pass, safe='')}@{pg_host}:{pg_port}/{pg_db}"
        if not db_url:
            print("Set PRODUCTION_DB_URL or POSTGRES_HOST+POSTGRES_PASSWORD.")
            print("Usage: python3 crystal_factory.py --status")
            sys.exit(1)
        asyncio.run(_print_status(db_url))
        return

    factory = CrystalFactory()

    def _shutdown(sig, frame):
        logger.info("Received signal %s, shutting down...", sig)
        factory.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    asyncio.run(factory.start())


if __name__ == "__main__":
    main()
