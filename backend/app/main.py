"""
LITTLE NATE — Main API Server Entry Point
Clinical Sovereignty Lab
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

_REDIS_URL_EARLY = os.environ.get("REDIS_URL", "")
_REDIS_PW_EARLY = os.environ.get("REDIS_PASSWORD", "")
_REDIS_HOST_EARLY = os.environ.get("REDIS_HOST", "redis")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncpg

from app.config import settings
# NOTE:
# - `app/routers/__init__.py` provides base auth + user CRUD endpoints
#   (login, register, list users, get user by id, nevedal status, night-school versions).
# - Dedicated routers in `app/routers/*.py` expose specialized `router` objects.
# Import them explicitly to avoid name collisions.
from app.routers import auth, users  # base auth & user routers
import app.routers.admin as admin_api
import app.routers.billing as billing_api
import app.routers.coach as coach_api
import app.routers.sessions as sessions_api
import app.routers.zoom as zoom_api
import app.routers.dojo_api as dojo_api
import app.routers.twilio_webhook as twilio_webhook

# Drip Campaign routers
import app.routers.campaign_api as campaign_api
import app.routers.quiz_api as quiz_api
import app.routers.prospect_api as prospect_api
import app.routers.response_api as response_api
import app.routers.golden_ticket_api as golden_ticket_api
import app.routers.analytics_api as analytics_api
import app.routers.webhook_api as webhook_api
from app.routers.webhook_api import meta_webhook_router
import app.routers.skyeye_api as skyeye_api
import app.routers.marketing_api as marketing_api
import app.routers.coherence_api as coherence_api
import app.routers.client_data_api as client_data_api
import app.routers.high_risk_crisis_api as high_risk_crisis_api  # QUANTUM-CRYSTAL-ARCH
import app.routers.fibre_api as fibre_api
import app.routers.approval_api as approval_api
import app.routers.strategic_memory_api as strategic_memory_api
import app.routers.pattern_api as pattern_api
import app.routers.legacy_vault_api as legacy_vault_api
import app.routers.swarm_teams_api as swarm_teams_api
import app.routers.immunity_api as immunity_api
import app.routers.foresight_api as foresight_api
import app.routers.ai_modes_api as ai_modes_api
import app.routers.nevedal_reports_api as nevedal_reports_api
import app.routers.big_nate_chat as big_nate_chat
import app.routers.night_school_api as night_school_api_router
import app.routers.zefcp_api as zefcp_api
import app.routers.quakete_api as quakete_api
import app.routers.counter_intelligence_api as counter_intelligence_api
import app.routers.me2me as me2me_api
import app.routers.hive_defense_api as hive_defense_api
import app.routers.assessments as assessments_api
import app.routers.trust_enforcer_api as trust_enforcer_api


# =============================================================================
# DATABASE CONNECTION POOL
# =============================================================================

logger = logging.getLogger(__name__)

db_pool: asyncpg.Pool = None


async def get_db_pool() -> asyncpg.Pool:
    """Get database connection pool."""
    global db_pool
    if db_pool is None:
        _db_url = os.environ.get("DATABASE_URL", "")
        _db_host = "postgres" if "@postgres:" in _db_url else settings.POSTGRES_HOST
        db_pool = await asyncpg.create_pool(
            host=_db_host,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB,
            min_size=5,
            max_size=30,
            max_inactive_connection_lifetime=300,
        )
    return db_pool


# =============================================================================
# LIFESPAN (Startup/Shutdown)
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown."""
    # Startup
    _is_clone = os.environ.get("IS_CLONE", "").lower() in ("true", "1", "yes")
    print(f"🚀 Starting Little Nate API Server...")
    print(f"   Environment: {settings.ENVIRONMENT}")
    print(f"   Server: {settings.SERVER_HOST}:{settings.SERVER_PORT}")
    if _is_clone:
        print("   ⚡ CLONE MODE — background agents and email-sending services will be skipped")
    
    # Connect to database
    global db_pool
    # Use individual parameters to avoid special character issues
    # (e.g. & in passwords) with DATABASE_URL parsing.
    # Docker sets POSTGRES_HOST to the LAN IP but from inside the
    # container we need the Docker service name ("postgres").
    # Detect Docker by checking if DATABASE_URL contains @postgres:
    _db_url = os.environ.get("DATABASE_URL", "")
    _db_host = "postgres" if "@postgres:" in _db_url else settings.POSTGRES_HOST
    db_pool = await asyncpg.create_pool(
        host=_db_host,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        database=settings.POSTGRES_DB,
        min_size=5,
        max_size=30,
        max_inactive_connection_lifetime=300,
    )
    print(f"   ✅ Database connected (host={_db_host})")
    
    # Store pool in app state
    app.state.db_pool = db_pool

    # QUANTUM-CRYSTAL-ARCH: SecureSearchProxy for clinical directory enrich + related APIs
    try:
        from app.services.search_proxy import SecureSearchProxy
        import os as _os_sp
        from pathlib import Path as _Path_sp

        _sp_dir = _os_sp.getenv("DATA_DIR") or str(_Path_sp("/app/data"))
        app.state.search_proxy = SecureSearchProxy(
            _sp_dir, _os_sp.getenv("BING_SEARCH_API_KEY", "")
        )
        print("   ✅ search_proxy on app.state")
    except Exception as _sp_err:
        app.state.search_proxy = None
        print(f"   ⚠️  search_proxy init failed: {_sp_err}")

    # Share db_pool with twilio_webhook and sendgrid_inbound routers
    twilio_webhook.router._db_pool = db_pool
    try:
        from app.routers.sendgrid_inbound import router as _sg_router
        _sg_router._db_pool = db_pool
    except Exception as _sg_err:
        print(f"   ⚠️  SendGrid inbound router db_pool injection failed: {_sg_err}")

    # Public trial funnel: bootstrap this process's copy of the module-level
    # pool so the unsubscribe REST router and db_maintenance_agent's follow-up
    # cycle can reach it (bridge_server.py bootstraps its own copy separately).
    try:
        from app.services.public_trial_gate import bootstrap as _trial_gate_bootstrap
        _trial_gate_bootstrap(db_pool)
    except Exception as _trial_gate_err:
        print(f"   ⚠️  public_trial_gate bootstrap failed: {_trial_gate_err}")

    # Register Stripe billing router (needs db_pool at creation time)
    try:
        from app.services.stripe_integration import create_billing_router
        stripe_billing_router = create_billing_router(db_pool)
        app.include_router(stripe_billing_router)
        print("   ✅ Stripe billing router registered (8 endpoints)")
    except Exception as e:
        print(f"   ⚠️  Stripe billing router failed: {e}")

    # Register Sovereign Vault API (needs db_pool at creation time)
    try:
        from app.routers.vault_api import create_vault_router
        vault_router = create_vault_router(db_pool)
        app.include_router(vault_router)
        print("   ✅ Sovereign Vault API registered")
    except Exception as e:
        print(f"   ⚠️  Sovereign Vault API failed: {e}")

    # Initialize Night School API (must be called before endpoints are served)
    try:
        from app.routers.night_school_api import init_night_school
        _vault_root = Path(os.environ.get("DATA_DIR", "/app/data")) / "night_school"
        _vault_root.mkdir(parents=True, exist_ok=True)
        init_night_school(_vault_root, db_pool)
        print("   ✅ Night School API initialized")
    except Exception as e:
        print(f"   ⚠️  Night School API failed to init: {e}")

    # Seed standing_orders table from config/standing_orders_seed.json (if empty)
    try:
        import json as _json
        _so_count = await db_pool.fetchval("SELECT COUNT(*) FROM standing_orders")
        if _so_count == 0:
            _seed_paths = [
                Path(__file__).resolve().parent.parent.parent / "config" / "standing_orders_seed.json",
                Path("/app/config/standing_orders_seed.json"),
            ]
            _seed_file = next((p for p in _seed_paths if p.is_file()), None)
            if _seed_file:
                _seed = _json.loads(_seed_file.read_text())
                _inserted = 0
                for _section, _content in _seed.items():
                    if _section.startswith("_"):
                        continue  # skip metadata keys like _comment, _version
                    await db_pool.execute(
                        """INSERT INTO standing_orders (title, directive, origin, domain_tags, priority, created_by, metadata)
                           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        _section,
                        f"Birth configuration for {_section}",
                        "seed_file",
                        [_section],
                        10,
                        "system_seed",
                        _json.dumps(_content),
                    )
                    _inserted += 1
                print(f"   ✅ Standing orders seeded ({_inserted} sections from {_seed_file.name})")
            else:
                print("   ⚠️  standing_orders_seed.json not found, skipping seed")
        else:
            print(f"   ✅ Standing orders already populated ({_so_count} rows)")
    except Exception as e:
        print(f"   ⚠️  Standing orders seed failed: {e}")

    # Start drip campaign scheduler
    drip_scheduler = None
    if settings.ENABLE_DRIP_CAMPAIGN:
        try:
            from app.services.drip_scheduler import DripScheduler
            drip_scheduler = DripScheduler(db_pool)
            drip_scheduler.start()
            app.state.drip_scheduler = drip_scheduler
            print(f"   ✅ Drip campaign scheduler started")
        except Exception as e:
            print(f"   ⚠️  Drip scheduler failed to start: {e}")
    
    # Start SkyEye autonomous session engine
    skyeye_engine = None
    linkedin_campaign_scheduler = None
    if getattr(settings, "ENABLE_SKYEYE_SESSIONS", False):
        try:
            from app.services.skyeye_session_engine import SkyEyeSessionEngine
            skyeye_engine = SkyEyeSessionEngine(db_pool)
            await skyeye_engine.start()
            app.state.skyeye_engine = skyeye_engine
            print(f"   ✅ SkyEye session engine started")
        except Exception as e:
            print(f"   ⚠️  SkyEye session engine failed to start: {e}")
        # QUANTUM-CRYSTAL-ARCH: LinkedIn campaign publish is production GREEN-only
        # Staging shares LinkedIn OAuth tokens and was double-posting live creatives.
        _env = (os.environ.get("ENVIRONMENT") or getattr(settings, "ENVIRONMENT", "") or "").lower()
        _skip_li_campaign = _is_clone or _env in ("staging", "test", "development")
        if not _skip_li_campaign:
            try:
                from app.services.linkedin_campaign_scheduler import LinkedInCampaignScheduler
                linkedin_campaign_scheduler = LinkedInCampaignScheduler(db_pool)
                linkedin_campaign_scheduler.start()
                app.state.linkedin_campaign_scheduler = linkedin_campaign_scheduler
                print(f"   ✅ LinkedIn campaign scheduler started")
                try:
                    from app.services.linkedin_campaign_coach_portal import (
                        bootstrap_coach_portal_campaign_if_enabled,
                    )
                    boot_msg = await bootstrap_coach_portal_campaign_if_enabled(db_pool)
                    if boot_msg:
                        print(f"   ✅ Coach Portal LinkedIn campaign: {boot_msg[:120]}")
                except Exception as boot_e:
                    print(f"   ⚠️  Coach Portal campaign bootstrap: {boot_e}")
            except Exception as e:
                print(f"   ⚠️  LinkedIn campaign scheduler failed to start: {e}")
        else:
            print(f"   ⏭️  LinkedIn campaign scheduler skipped (clone/staging env={_env or 'clone'})")
    
    # Start Marketing Automation Worker
    marketing_worker = None
    if getattr(settings, "ENABLE_SKYEYE_SESSIONS", False):
        try:
            from app.workers.marketing_automation_worker import MarketingAutomationWorker
            marketing_worker = MarketingAutomationWorker(db_pool, interval=600)
            await marketing_worker.start()
            app.state.marketing_worker = marketing_worker
            print(f"   ✅ Marketing automation worker started (10min interval)")
        except Exception as e:
            print(f"   ⚠️  Marketing automation worker failed to start: {e}")

    # Initialize Sovereign Swarm services
    _workers = []  # Track all background workers for shutdown (must be outside if-block for shutdown access)
    if getattr(settings, "ENABLE_SOVEREIGN_SWARM", False):
        try:
            from app.services.identity_chain import IdentityChainService
            from app.services.wisdom_mesh import WisdomMeshService
            from app.services.sovereign_immunity import SovereignImmunityService
            from app.services.fibre_manager import FibreManager
            from app.fibres import FIBRE_REGISTRY
            from app.models.fibre import FibreType

            # Identity Chain
            identity_service = IdentityChainService(db_pool=db_pool)
            master_key = getattr(settings, "SOVEREIGN_MIND_MASTER_KEY", "")

            # Key persistence: env var > file > generate new
            master_key_file = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "data", "sovereign_master_key.pem"
            )
            if master_key:
                identity_service.load_master_key(master_key)
                print("   ✅ Master key loaded from env var")
            elif os.path.isfile(master_key_file):
                with open(master_key_file, "r") as f:
                    identity_service.load_master_key(f.read())
                print(f"   ✅ Master key loaded from {master_key_file}")
            else:
                new_pem = identity_service.initialize_master_key()
                # Persist for next restart
                try:
                    os.makedirs(os.path.dirname(master_key_file), exist_ok=True)
                    with open(master_key_file, "w") as f:
                        f.write(new_pem)
                    os.chmod(master_key_file, 0o600)
                    print(f"   ✅ Master key generated and saved to {master_key_file}")
                except Exception as kf_err:
                    print(f"   ⚠️  Master key generated but could not persist: {kf_err}")
            app.state.identity_service = identity_service

            # Load existing Fibre identities from DB
            loaded = await identity_service.load_identities_from_db()
            if loaded:
                print(f"   ✅ Loaded {loaded} Fibre identities from database")

            # Sovereign Immunity
            immunity = SovereignImmunityService(
                db_pool=db_pool, identity_service=identity_service
            )
            app.state.sovereign_immunity = immunity

            # Wisdom Mesh (with immunity guard)
            wisdom_mesh = WisdomMeshService(
                db_pool=db_pool, immunity_service=immunity
            )
            try:
                await wisdom_mesh.connect(settings.redis_url)
                # ── HIVE DEFENSE v4.3: Verify Redis connection with explicit ping (GAP S2) ──
                _wm_redis = getattr(wisdom_mesh, '_redis', None)
                if _wm_redis:
                    await _wm_redis.ping()
                    print("   ✅ Wisdom Mesh Redis connection verified (ping OK)")
                else:
                    print("   ⚠️  Wisdom Mesh connected but no Redis handle available")
            except Exception as e:
                print(f"   ⚠️  Wisdom Mesh Redis connection failed: {e}")
            app.state.wisdom_mesh = wisdom_mesh

            # Fibre Manager (with immunity integration)
            fibre_manager = FibreManager(
                db_pool=db_pool,
                identity_service=identity_service,
                wisdom_mesh=wisdom_mesh,
                sovereign_immunity=immunity,
            )
            # Register all Fibre types
            for type_name, fibre_cls in FIBRE_REGISTRY.items():
                try:
                    fibre_type = FibreType(type_name)
                    fibre_manager.register_fibre_type(fibre_type, fibre_cls)
                except ValueError:
                    pass
            app.state.fibre_manager = fibre_manager

            # Foresight Engine
            foresight_engine = None
            try:
                from app.services.foresight_engine import ForesightEngine
                foresight_engine = ForesightEngine(db_pool=db_pool)
                app.state.foresight_engine = foresight_engine
                print("   ✅ Foresight Engine initialized")
            except Exception as fe_err:
                print(f"   ⚠️  Foresight Engine failed to init: {fe_err}")

            # Coherence Engine (shared instance)
            coherence_engine = None
            try:
                from app.services.coherence_engine import CoherenceEngine
                coherence_engine = CoherenceEngine(db_pool=db_pool)
                app.state.coherence_engine = coherence_engine
                print("   ✅ Coherence Engine initialized")
            except Exception as ce_err:
                print(f"   ⚠️  Coherence Engine failed to init: {ce_err}")

            # Pattern Engine
            pattern_engine = None
            try:
                from app.services.pattern_engine import TransgenerationalPatternEngine
                pattern_engine = TransgenerationalPatternEngine(db_pool=db_pool)
                app.state.pattern_engine = pattern_engine
                print("   ✅ Pattern Engine initialized")
            except Exception as pe_err:
                print(f"   ⚠️  Pattern Engine failed to init: {pe_err}")

            # Strategic Memory
            strategic_memory = None
            try:
                from app.services.strategic_memory import StrategicMemoryService
                strategic_memory = StrategicMemoryService(db_pool=db_pool)
                app.state.strategic_memory = strategic_memory
                print("   ✅ Strategic Memory initialized")
            except Exception as sm_err:
                print(f"   ⚠️  Strategic Memory failed to init: {sm_err}")

            # Lived Wisdom Service (Azure-enhanced + heuristic fallback)
            try:
                from app.services.lived_wisdom import LivedWisdomService
                azure_client = {
                    "endpoint": settings.AZURE_OPENAI_ENDPOINT,
                    "api_key": settings.AZURE_API_KEY,
                    "chat_deployment": settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                } if settings.AZURE_API_KEY else None
                lived_wisdom = LivedWisdomService(db_pool=db_pool, azure_client=azure_client)
                app.state.lived_wisdom = lived_wisdom
                print(f"   ✅ Lived Wisdom Service initialized (Azure: {'yes' if azure_client else 'heuristic only'})")
            except Exception as lw_err:
                print(f"   ⚠️  Lived Wisdom failed to init: {lw_err}")

            # =========================================================
            # ZEFCP Layer 1 — Physical Transport Services
            # =========================================================
            try:
                from app.services.zefcp.fragment_buffer import FragmentBuffer
                from app.services.zefcp.metrics import ZEFCPMetrics
                from app.services.zefcp.nfc_provisioner import NFCProvisioner
                from app.services.zefcp.spider_web import SpiderWebDetector
                from app.services.zefcp.bridge import ZEFCPBridge

                # Derive swarm secret from master key (deterministic)
                import hashlib
                _swarm_secret_seed = getattr(settings, "SWARM_SECRET", "") or ""
                _master_privkey = getattr(identity_service, '_master_private_key', None)
                if _swarm_secret_seed:
                    swarm_secret = hashlib.sha256(_swarm_secret_seed.encode()).digest()
                elif _master_privkey:
                    # Derive from the master key's public bytes (deterministic, no secret leakage)
                    _pub_bytes = _master_privkey.public_key().public_bytes_raw()
                    swarm_secret = hashlib.sha256(_pub_bytes).digest()
                else:
                    swarm_secret = hashlib.sha256(b"sovereign-swarm-default-secret").digest()

                fragment_buffer = FragmentBuffer(swarm_secret=swarm_secret)
                zefcp_metrics = ZEFCPMetrics(endpoint_id="primary")
                spider_web = SpiderWebDetector(
                    swarm_secret=swarm_secret,
                    fragment_buffer=fragment_buffer,
                )
                zefcp_bridge = ZEFCPBridge(
                    mesh_client=wisdom_mesh,
                    endpoint_id="primary",
                )

                # Derive sovereign mind private key for NFC provisioning
                _sm_privkey = getattr(identity_service, '_master_private_key', None)
                _sm_privkey_bytes = swarm_secret  # Default fallback
                if _sm_privkey:
                    try:
                        from cryptography.hazmat.primitives import serialization
                        _sm_privkey_bytes = _sm_privkey.private_bytes(
                            encoding=serialization.Encoding.Raw,
                            format=serialization.PrivateFormat.Raw,
                            encryption_algorithm=serialization.NoEncryption(),
                        )
                    except Exception:
                        pass  # Keep swarm_secret fallback
                nfc_provisioner = NFCProvisioner(
                    swarm_secret=swarm_secret,
                    sovereign_mind_private_key=_sm_privkey_bytes,
                )

                app.state.zefcp_fragment_buffer = fragment_buffer
                app.state.zefcp_assembly_buffers = {"primary": fragment_buffer}
                app.state.zefcp_metrics_store = {"primary": zefcp_metrics}
                app.state.zefcp_spider_web = spider_web
                app.state.zefcp_bridge = zefcp_bridge
                app.state.zefcp_nfc_provisioner = nfc_provisioner
                app.state.swarm_secret = swarm_secret
                print("   ✅ ZEFCP Layer 1 services initialized")
            except Exception as zefcp_err:
                print(f"   ⚠️  ZEFCP services failed to init: {zefcp_err}")

            # =========================================================
            # Quakete Layer 8 — Swarm Solidarity Services
            # =========================================================
            try:
                from app.services.quakete.resonance import QuaketeResonanceEngine
                from app.services.quakete.cosmic_ring import CosmicRingManager
                from app.services.quakete.trail_map import FibreTrailMap
                from app.services.quakete.ion import QuaketeIonPool
                from app.services.quakete.lorentz import LorentzForceAccelerator
                from app.services.quakete.wave_particle import WaveParticleResonance
                from app.services.quakete.reconnection import MagneticReconnectionEngine
                from app.services.quakete.particle_beam import ParticleBeamGenerator
                from app.services.quakete.memorial import MemorialService
                from app.services.quakete.transfer_service import QuaketeTransferService
                from app.services.quakete.ring_formation import RingFormationService
                from app.services.quakete.ring_circulator import RingCirculator

                resonance_engine = QuaketeResonanceEngine()
                ring_manager = CosmicRingManager(resonance_engine=resonance_engine)
                trail_map = FibreTrailMap()
                ion_pool = QuaketeIonPool()
                lorentz = LorentzForceAccelerator()
                wave_particle = WaveParticleResonance()
                reconnection_engine = MagneticReconnectionEngine(resonance_engine=resonance_engine)
                particle_beam_generator = ParticleBeamGenerator(lorentz=lorentz)
                memorial_service = MemorialService(ring_manager=ring_manager)
                ring_formation_service = RingFormationService(
                    resonance_engine=resonance_engine,
                    ring_manager=ring_manager,
                )
                ring_circulator = RingCirculator(
                    ring_manager=ring_manager,
                    trail_map=trail_map,
                    wave_particle=wave_particle,
                    ion_pool=ion_pool,
                )
                transfer_service = QuaketeTransferService(
                    ring_manager=ring_manager,
                    trail_map=trail_map,
                    resonance_engine=resonance_engine,
                    reconnection_engine=reconnection_engine,
                    wave_particle=wave_particle,
                    lorentz=lorentz,
                    ion_pool=ion_pool,
                    particle_beam_generator=particle_beam_generator,
                )

                app.state.quakete_resonance_engine = resonance_engine
                app.state.cosmic_ring_manager = ring_manager
                app.state.trail_map = trail_map
                app.state.quakete_ion_pool = ion_pool
                app.state.quakete_lorentz = lorentz
                app.state.quakete_wave_particle = wave_particle
                app.state.quakete_reconnection = reconnection_engine
                app.state.particle_beam_generator = particle_beam_generator
                app.state.memorial_service = memorial_service
                app.state.ring_formation_service = ring_formation_service
                app.state.quakete_ring_circulator = ring_circulator
                app.state.quakete_transfer_service = transfer_service
                print("   ✅ Quakete Layer 8 services initialized")
            except Exception as qk_err:
                print(f"   ⚠️  Quakete services failed to init: {qk_err}")

            # =========================================================
            # Sovereign Mind — Central Intelligence (Patent Claim 1)
            # =========================================================
            try:
                from app.services.sovereign_mind import SovereignMind
                sovereign_mind = SovereignMind(
                    db_pool=db_pool,
                    redis=None,
                    fibre_manager=fibre_manager,
                    wisdom_mesh=wisdom_mesh,
                    coherence_engine=coherence_engine,
                    foresight_engine=foresight_engine,
                    pattern_engine=pattern_engine,
                    immunity=immunity,
                    identity_chain=identity_service,
                    strategic_memory=strategic_memory,
                    trail_map=getattr(app.state, 'trail_map', None),
                    ring_manager=getattr(app.state, 'cosmic_ring_manager', None),
                    memorial_service=getattr(app.state, 'memorial_service', None),
                )
                app.state.sovereign_mind = sovereign_mind
                print("   ✅ Sovereign Mind initialized")
            except Exception as sm_err:
                print(f"   ⚠️  Sovereign Mind failed to init: {sm_err}")

            # =========================================================
            # Nevedal-to-Quakete Bridge — connect coherence to solidarity
            # =========================================================
            try:
                from app.services.nevedal_engine import create_nevedal_engine
                _qk_res = getattr(app.state, 'quakete_resonance_engine', None)
                _qk_trail = getattr(app.state, 'trail_map', None)
                nevedal_engine_shared = create_nevedal_engine(
                    quakete_resonance_engine=_qk_res,
                    quakete_trail_map=_qk_trail,
                    db_pool=db_pool,
                )
                app.state.nevedal_engine = nevedal_engine_shared
                if _qk_res:
                    print("   ✅ Nevedal→Quakete bridge connected")
                else:
                    print("   ✅ Nevedal Engine initialized (Quakete not available)")
            except Exception as ne_err:
                print(f"   ⚠️  Nevedal Engine failed to init: {ne_err}")

            # =========================================================
            # Memory Tiering — Hot / Warm / Cold (Patent Claim 13)
            # =========================================================
            try:
                from app.services.memory.hot import HotMemoryTier
                from app.services.memory.warm import WarmMemoryTier
                from app.services.memory.cold import ColdMemoryTier

                # Wire Pipeline Drum Redis monitoring into HotMemoryTier.
                # Uses a lazy closure so the tap resolves at first call,
                # after hive_v4 is populated later in startup.
                def _lazy_drum_tap(op, key, latency_ms, success=True):
                    try:
                        hv4 = getattr(app.state, 'hive_v4', None)
                        if hv4:
                            drum = hv4.get('pipeline_drum')
                            if drum:
                                drum.tap_redis(op, key, latency_ms, success)
                    except Exception:
                        pass

                hot_memory = HotMemoryTier(
                    redis_client=getattr(wisdom_mesh, '_redis', None),
                    drum_tap=_lazy_drum_tap,
                )
                warm_memory = WarmMemoryTier(
                    connection_string=getattr(settings, 'AZURE_STORAGE_CONNECTION_STRING', None)
                )
                cold_memory = ColdMemoryTier(
                    connection_string=getattr(settings, 'AZURE_STORAGE_CONNECTION_STRING', None)
                )
                app.state.hot_memory = hot_memory
                app.state.warm_memory = warm_memory
                app.state.cold_memory = cold_memory
                print("   ✅ Memory Tiering initialized (Hot/Warm/Cold)")
            except Exception as mem_err:
                print(f"   ⚠️  Memory Tiering failed to init: {mem_err}")

            try:
                from app.services.session_memory_store import SessionMemoryStore
                _sms_root = Path(os.environ.get("DATA_DIR", "/app/data"))
                app.state.session_memory_store = SessionMemoryStore(storage_root=_sms_root)
                print("   ✅ Session Memory Store initialized")
            except Exception as sms_err:
                print(f"   ⚠️  Session Memory Store failed to init: {sms_err}")

            print(f"   ✅ Sovereign Swarm initialized "
                  f"({len(FIBRE_REGISTRY)} Fibre types registered)")

            # =========================================================
            # Background Workers — Periodic Swarm Maintenance
            # =========================================================
            try:
                from app.workers import (
                    BLEAssemblyWorker, CoherenceWorker, ConvergenceWorker,
                    FibreLifecycleWorker, ForesightWorker, PatternWorker,
                    RingWorker, TrailWorker,
                )

                # BLE Assembly Worker — ZEFCP fragment assembly maintenance
                if getattr(app.state, 'zefcp_fragment_buffer', None):
                    w_ble = BLEAssemblyWorker(
                        fragment_buffer=app.state.zefcp_fragment_buffer,
                        zefcp_bridge=getattr(app.state, 'zefcp_bridge', None),
                    )
                    await w_ble.start()
                    _workers.append(w_ble)

                # Coherence Worker — periodic coherence monitoring
                if coherence_engine:
                    w_coh = CoherenceWorker(
                        coherence_engine=coherence_engine,
                        db_pool=db_pool,
                    )
                    await w_coh.start()
                    _workers.append(w_coh)

                # Convergence Worker — cross-Fibre convergence detection
                _sov_mind = getattr(app.state, 'sovereign_mind', None)
                if wisdom_mesh and _sov_mind:
                    w_conv = ConvergenceWorker(
                        wisdom_mesh=wisdom_mesh,
                        sovereign_mind=_sov_mind,
                    )
                    await w_conv.start()
                    _workers.append(w_conv)

                # Fibre Lifecycle Worker — alignment checks, spawn/prune
                if fibre_manager and immunity:
                    w_fibre = FibreLifecycleWorker(
                        fibre_manager=fibre_manager,
                        immunity=immunity,
                    )
                    await w_fibre.start()
                    _workers.append(w_fibre)

                # Foresight Worker — prediction cycles
                if foresight_engine and pattern_engine and strategic_memory:
                    w_fore = ForesightWorker(
                        foresight_engine=foresight_engine,
                        pattern_engine=pattern_engine,
                        strategic_memory=strategic_memory,
                    )
                    await w_fore.start()
                    _workers.append(w_fore)

                # Pattern Worker — transgenerational pattern detection
                if pattern_engine:
                    w_pat = PatternWorker(
                        pattern_engine=pattern_engine,
                        db_pool=db_pool,
                    )
                    await w_pat.start()
                    _workers.append(w_pat)

                # Ring Worker — Quakete ring circulation and health
                _ring_circ = getattr(app.state, 'quakete_ring_circulator', None)
                _ring_mgr = getattr(app.state, 'cosmic_ring_manager', None)
                _ring_form = getattr(app.state, 'ring_formation_service', None)
                if _ring_circ and _ring_mgr and _ring_form:
                    w_ring = RingWorker(
                        ring_circulator=_ring_circ,
                        ring_manager=_ring_mgr,
                        ring_formation_service=_ring_form,
                    )
                    await w_ring.start()
                    _workers.append(w_ring)

                # Trail Worker — Quakete trail aggregation and transfers
                _trail_map = getattr(app.state, 'trail_map', None)
                _memorial = getattr(app.state, 'memorial_service', None)
                _xfer = getattr(app.state, 'quakete_transfer_service', None)
                if _trail_map and _ring_mgr and _memorial and _xfer:
                    w_trail = TrailWorker(
                        trail_map=_trail_map,
                        ring_manager=_ring_mgr,
                        memorial_service=_memorial,
                        transfer_service=_xfer,
                    )
                    await w_trail.start()
                    _workers.append(w_trail)

                print(f"   ✅ {len(_workers)} background workers started")
            except Exception as wk_err:
                print(f"   ⚠️  Workers failed to start: {wk_err}")

            # Swarm Relay — allows the bridge process to trigger swarm services via Redis
            try:
                from app.services.swarm_relay import SwarmRelayServer
                relay = SwarmRelayServer(app.state, redis_url=settings.redis_url)
                await relay.start()
                app.state.swarm_relay = relay
                print("   ✅ Swarm Relay Server started (bridge ↔ API)")
            except Exception as relay_err:
                print(f"   ⚠️  Swarm Relay failed to start: {relay_err}")

        except Exception as e:
            print(f"   ⚠️  Sovereign Swarm failed to start: {e}")

    # Configure Counter-Intelligence API services
    try:
        from app.services.counter_intelligence.threat_db import ThreatIntelligenceDB
        from app.services.counter_intelligence.fingerprinter import AttackFingerprinter
        from app.services.counter_intelligence.reverse_mapper import ReverseMapper
        from app.services.counter_intelligence.beacon_listener import BeaconListener
        from app.services.counter_intelligence.orchestrator import ImmuneResponseOrchestrator

        ci_threat_db = ThreatIntelligenceDB(db_pool=db_pool)
        ci_fingerprinter = AttackFingerprinter(threat_db=ci_threat_db)
        ci_reverse_mapper = ReverseMapper(threat_db=ci_threat_db, fingerprinter=ci_fingerprinter)
        ci_beacon_listener = BeaconListener(threat_db=ci_threat_db, reverse_mapper=ci_reverse_mapper)
        ci_orchestrator = ImmuneResponseOrchestrator(
            db_pool=db_pool,
            fingerprinter=ci_fingerprinter,
            threat_db=ci_threat_db,
            beacon_listener=ci_beacon_listener,
            reverse_mapper=ci_reverse_mapper,
        )
        counter_intelligence_api.configure(
            orchestrator=ci_orchestrator,
            threat_db=ci_threat_db,
            fingerprinter=ci_fingerprinter,
            reverse_mapper=ci_reverse_mapper,
            beacon_listener=ci_beacon_listener,
        )
        app.state.ci_orchestrator = ci_orchestrator
        print("   ✅ Counter-Intelligence API configured")
    except Exception as ci_err:
        print(f"   ⚠️  Counter-Intelligence configuration failed: {ci_err}")

    # =========================================================
    # PLATINUM FINISH LINE — Applied Solutions, Governance,
    # Billing, Coach Experience, Night School, Me-2-Me, Onboarding
    # =========================================================
    try:
        # Grab shared services already on app.state
        _sovereign_mind = getattr(app.state, "sovereign_mind", None)
        _nevedal_engine = getattr(app.state, "nevedal_engine", None)
        _trail_map = getattr(app.state, "trail_map", None)
        _ion_pool = getattr(app.state, "quakete_ion_pool", None)
        _ring_mgr = getattr(app.state, "cosmic_ring_manager", None)
        _fibre_manager = getattr(app.state, "fibre_manager", None)
        _coherence_engine = getattr(app.state, "coherence_engine", None)
        _foresight_engine = getattr(app.state, "foresight_engine", None)
        _pattern_engine = getattr(app.state, "pattern_engine", None)
        _memorial_service = getattr(app.state, "memorial_service", None)
        _ramp_up = None
        try:
            from app.services.quakete.ramp_up import QuaketeRampUp
            if _trail_map and _ion_pool:
                _ramp_up = QuaketeRampUp(trail_map=_trail_map, ion_pool=_ion_pool)
        except Exception as _ramp_err:
            print(f"   ⚠️  QuaketeRampUp init failed: {_ramp_err}")

        # --- Notifications Service (shared adapter) ---
        # The Platinum services call notifications.send_notification(user_id, ...)
        # Wrap the existing EmailService into a lightweight adapter.
        from app.services.notifications_service import EmailService

        class _NotificationAdapter:
            """Thin adapter so Platinum services can call send_notification()."""
            def __init__(self, db_pool):
                self._db = db_pool
                self._email = EmailService()
                self._log = __import__("structlog").get_logger("notifications_adapter")

            async def send_notification(self, *, user_id=None, notification_type="generic",
                                        title="", body="", channel="push", **kwargs):
                self._log.info("notification", user_id=str(user_id), type=notification_type, channel=channel)
                # Persist to audit log for traceability
                try:
                    await self._db.execute(
                        "INSERT INTO audit_log (action_type, target_id, details) VALUES ($1, $2, $3)",
                        f"NOTIFICATION_{notification_type.upper()}", user_id,
                        f"{title}: {body[:200]}",
                    )
                except Exception:
                    pass  # Best-effort logging

        notifications_svc = _NotificationAdapter(db_pool=db_pool)
        app.state.notifications = notifications_svc

        # --- Governance Services ---
        from app.services.governance.scope_of_practice import ScopeOfPracticeService
        from app.services.governance.mandatory_reporting import MandatoryReportingService
        from app.services.governance.record_keeping import RecordKeepingService

        scope_of_practice = ScopeOfPracticeService(db_pool=db_pool, notifications=notifications_svc)
        mandatory_reporting = MandatoryReportingService(db_pool=db_pool, notifications=notifications_svc)
        record_keeping = RecordKeepingService(db_pool=db_pool)
        app.state.scope_of_practice = scope_of_practice
        app.state.mandatory_reporting = mandatory_reporting
        app.state.record_keeping = record_keeping
        print("   ✅ Governance services initialized (Scope, Reporting, Records)")

        # --- Billing Services ---
        from app.services.billing.metered_billing import MeteredBillingService
        from app.services.billing.cost_threshold_monitor import CostThresholdMonitor
        from app.services.billing.legacy_vault_billing import LegacyVaultBillingService

        stripe_svc = getattr(app.state, "stripe_service", None)
        metered_billing = MeteredBillingService(stripe_service=stripe_svc, notifications=notifications_svc, db_pool=db_pool)
        cost_threshold_monitor = CostThresholdMonitor(db_pool=db_pool, notifications=notifications_svc)
        legacy_vault_billing = LegacyVaultBillingService(stripe_service=stripe_svc, db_pool=db_pool)
        app.state.metered_billing = metered_billing
        app.state.cost_threshold_monitor = cost_threshold_monitor
        app.state.legacy_vault_billing = legacy_vault_billing
        print("   ✅ Billing services initialized (Metered, Cost Monitor, Vault Billing)")

        # --- Coach Experience Services ---
        from app.services.coach_experience.session_interface import SessionInterface
        from app.services.coach_experience.briefing_renderer import BriefingRenderer
        from app.services.coach_experience.caseload_manager import CaseloadManager

        session_interface = SessionInterface()
        briefing_renderer = BriefingRenderer()
        caseload_manager = CaseloadManager(db_pool=db_pool, notifications=notifications_svc)
        app.state.session_interface = session_interface
        app.state.briefing_renderer = briefing_renderer
        app.state.caseload_manager = caseload_manager
        print("   ✅ Coach Experience services initialized (Session, Briefing, Caseload)")

        # --- Applied Solutions Services (S1-S10) ---
        from app.services.silent_fibre_detector import SilentFibreDetector
        from app.services.autonomy_manager import AutonomyManager
        from app.services.emotional_weather import EmotionalWeatherService
        from app.services.briefing_generator import BriefingGenerator
        from app.services.member_matching import MemberMatchingService
        from app.services.community_warning import CommunityWarningService
        from app.services.quakete_rescue import QuaketeRescueService
        from app.services.couple_resonance import CoupleResonanceService
        from app.services.coach_recruitment import CoachRecruitmentService

        silent_detector = SilentFibreDetector(
            trail_map=_trail_map, ramp_up_engine=_ramp_up,
            sovereign_mind=_sovereign_mind, notifications=notifications_svc, db_pool=db_pool,
        )
        autonomy_mgr = AutonomyManager(fibre_manager=_fibre_manager, db_pool=db_pool)
        emotional_weather = EmotionalWeatherService(nevedal_engine=_nevedal_engine, sovereign_mind=_sovereign_mind, db_pool=db_pool)
        briefing_gen = BriefingGenerator(
            coherence_engine=_coherence_engine, nevedal_engine=_nevedal_engine,
            foresight_engine=_foresight_engine, pattern_engine=_pattern_engine,
            sovereign_mind=_sovereign_mind, db_pool=db_pool,
        )
        member_matching = MemberMatchingService(db_pool=db_pool, sovereign_mind=_sovereign_mind)
        community_warning = CommunityWarningService(
            member_matching=member_matching, notifications=notifications_svc,
            sovereign_mind=_sovereign_mind, db_pool=db_pool,
        )
        quakete_rescue = QuaketeRescueService(
            trail_map=_trail_map, ion_pool=_ion_pool, ring_manager=_ring_mgr,
            session_interface=session_interface, nevedal_engine=_nevedal_engine,
        )
        couple_resonance = CoupleResonanceService(nevedal_engine=_nevedal_engine, trail_map=_trail_map)
        coach_recruitment = CoachRecruitmentService(
            sovereign_mind=_sovereign_mind, autonomy_manager=autonomy_mgr,
            notifications=notifications_svc, db_pool=db_pool,
        )
        app.state.silent_detector = silent_detector
        app.state.autonomy_manager = autonomy_mgr
        app.state.emotional_weather = emotional_weather
        app.state.briefing_generator = briefing_gen
        app.state.member_matching = member_matching
        app.state.community_warning = community_warning
        app.state.quakete_rescue = quakete_rescue
        app.state.couple_resonance = couple_resonance
        app.state.coach_recruitment = coach_recruitment
        print("   ✅ Applied Solutions S1-S10 initialized")

        # --- Night School Services ---
        from app.services.night_school.content_parser import ContentParser
        from app.services.night_school.modality_selector import ModalitySelector
        from app.services.night_school.rag_indexer import RAGIndexer
        from app.services.night_school.curriculum_pipeline import CurriculumPipeline

        content_parser = ContentParser(sovereign_mind=_sovereign_mind)
        modality_selector = ModalitySelector()
        rag_indexer = RAGIndexer(db_pool=db_pool)
        curriculum_pipeline = CurriculumPipeline(
            content_parser=content_parser, modality_selector=modality_selector,
            rag_indexer=rag_indexer, sovereign_mind=_sovereign_mind, db_pool=db_pool,
        )
        app.state.content_parser = content_parser
        app.state.modality_selector = modality_selector
        app.state.rag_indexer = rag_indexer
        app.state.curriculum_pipeline = curriculum_pipeline
        print("   ✅ Night School services initialized (Parser, Modality, RAG, Pipeline)")

        # --- Me-2-Me Platinum Services ---
        from app.services.me2me.me2me_consent import Me2MeConsentService
        from app.services.me2me.legacy_vault_me2me import LegacyVaultMe2Me
        from app.services.me2me.imprint_accumulator import ImprintAccumulator
        from app.services.me2me.identity_crystallizer import IdentityCrystallizer
        from app.services.me2me.avatar_core import AvatarCoreService
        from app.services.me2me.ancestral_interaction import AncestralInteractionEngine
        from app.services.me2me.growth_engine import GrowthEngine
        from app.services.me2me.family_fabric import FamilyFabricService
        from app.services.me2me.migration_service import MigrationService
        from app.services.me2me.trust_manager import TrustManager
        from app.services.me2me.ingestion_safety import IngestionSafetyService

        me2me_consent = Me2MeConsentService(db_pool=db_pool, notifications=notifications_svc)
        me2me_vault = LegacyVaultMe2Me(consent_service=me2me_consent, db_pool=db_pool)
        ingestion_safety = IngestionSafetyService(notifications=notifications_svc, mandatory_reporting=mandatory_reporting)
        imprint_accumulator = ImprintAccumulator(
            consent_service=me2me_consent, vault=me2me_vault, db_pool=db_pool,
            ingestion_safety=ingestion_safety,
        )
        identity_crystallizer = IdentityCrystallizer(
            consent_service=me2me_consent, vault=me2me_vault,
            sovereign_mind=_sovereign_mind, db_pool=db_pool,
        )
        avatar_core = AvatarCoreService(
            consent_service=me2me_consent, vault=me2me_vault,
            sovereign_mind=_sovereign_mind, db_pool=db_pool,
        )
        ancestral_interaction = AncestralInteractionEngine(
            avatar_service=avatar_core, consent_service=me2me_consent, db_pool=db_pool,
        )
        growth_engine = GrowthEngine(db_pool=db_pool, sovereign_mind=_sovereign_mind)
        family_fabric = FamilyFabricService(consent_service=me2me_consent, db_pool=db_pool)
        migration_svc = MigrationService(
            consent_service=me2me_consent, vault=me2me_vault,
            crystallizer=identity_crystallizer, avatar_service=avatar_core, db_pool=db_pool,
        )
        trust_manager = TrustManager(consent_service=me2me_consent, notifications=notifications_svc, db_pool=db_pool)

        app.state.me2me_consent = me2me_consent
        app.state.me2me_vault = me2me_vault
        app.state.imprint_accumulator = imprint_accumulator
        app.state.identity_crystallizer = identity_crystallizer
        app.state.avatar_core = avatar_core
        app.state.ancestral_interaction = ancestral_interaction
        app.state.growth_engine = growth_engine
        app.state.family_fabric = family_fabric
        app.state.migration_service = migration_svc
        app.state.trust_manager = trust_manager
        app.state.ingestion_safety = ingestion_safety
        print("   ✅ Me-2-Me Platinum services initialized (11 services)")

        # --- Onboarding Services ---
        from app.services.onboarding.welcome_conversation import WelcomeConversationService
        from app.services.onboarding.cold_start_nevedal import ColdStartNevedalService
        from app.services.onboarding.coach_matching import OnboardingCoachMatchingService
        from app.services.onboarding.onboarding_orchestrator import OnboardingOrchestrator

        welcome_conversation = WelcomeConversationService(sovereign_mind=_sovereign_mind)
        cold_start_nevedal = ColdStartNevedalService(nevedal_engine=_nevedal_engine)
        onboarding_coach_match = OnboardingCoachMatchingService(db_pool=db_pool)
        onboarding_orchestrator = OnboardingOrchestrator(
            welcome_service=welcome_conversation, cold_start_service=cold_start_nevedal,
            coach_matching_service=onboarding_coach_match, fibre_manager=_fibre_manager,
            drip_scheduler=getattr(app.state, "drip_scheduler", None),
            notifications=notifications_svc, db_pool=db_pool,
        )
        app.state.welcome_conversation = welcome_conversation
        app.state.cold_start_nevedal = cold_start_nevedal
        app.state.onboarding_coach_match = onboarding_coach_match
        app.state.onboarding_orchestrator = onboarding_orchestrator
        print("   ✅ Onboarding services initialized (Welcome, ColdStart, Coach Match, Orchestrator)")

        # =========================================================
        # Platinum Finish Line — Background Workers (14)
        # =========================================================
        from app.workers import (
            OnboardingWorker, SilentDetectorWorker, AutonomyReviewWorker,
            WeatherWorker, BriefingWorker, CommunityWarningWorker,
            NightSchoolWorker, BillingWorker, ImprintAccumulatorWorker,
            CrystalSynthesizerWorker, GrowthEngineWorker, MigrationWorker,
            VaultIntegrityWorker, IngestionSafetyWorker,
        )

        w_onboarding = OnboardingWorker(db_pool=db_pool, notifications=notifications_svc, sovereign_mind=_sovereign_mind)
        await w_onboarding.start()
        _workers.append(w_onboarding)

        w_silent = SilentDetectorWorker(silent_detector=silent_detector)
        await w_silent.start()
        _workers.append(w_silent)

        w_autonomy = AutonomyReviewWorker(autonomy_manager=autonomy_mgr, fibre_manager=_fibre_manager)
        await w_autonomy.start()
        _workers.append(w_autonomy)

        w_weather = WeatherWorker(emotional_weather=emotional_weather, session_interface=session_interface)
        await w_weather.start()
        _workers.append(w_weather)

        w_briefing = BriefingWorker(briefing_generator=briefing_gen, db_pool=db_pool, notifications=notifications_svc)
        await w_briefing.start()
        _workers.append(w_briefing)

        w_community = CommunityWarningWorker(community_warning=community_warning, db_pool=db_pool)
        await w_community.start()
        _workers.append(w_community)

        w_night_school = NightSchoolWorker(curriculum_pipeline=curriculum_pipeline, db_pool=db_pool)
        await w_night_school.start()
        _workers.append(w_night_school)

        w_billing = BillingWorker(
            metered_billing=metered_billing, cost_monitor=cost_threshold_monitor,
            vault_billing=legacy_vault_billing, db_pool=db_pool,
        )
        await w_billing.start()
        _workers.append(w_billing)

        w_imprint = ImprintAccumulatorWorker(accumulator=imprint_accumulator)
        await w_imprint.start()
        _workers.append(w_imprint)

        w_crystal = CrystalSynthesizerWorker(
            crystallizer=identity_crystallizer, consent_service=me2me_consent, db_pool=db_pool,
        )
        await w_crystal.start()
        _workers.append(w_crystal)

        w_growth = GrowthEngineWorker(growth_engine=growth_engine, db_pool=db_pool)
        await w_growth.start()
        _workers.append(w_growth)

        w_migration = MigrationWorker(migration_service=migration_svc, db_pool=db_pool)
        await w_migration.start()
        _workers.append(w_migration)

        w_vault_int = VaultIntegrityWorker(vault=me2me_vault, db_pool=db_pool)
        await w_vault_int.start()
        _workers.append(w_vault_int)

        w_ingestion = IngestionSafetyWorker(ingestion_safety=ingestion_safety, db_pool=db_pool)
        await w_ingestion.start()
        _workers.append(w_ingestion)

        print(f"   ✅ 14 Platinum workers started")
    except Exception as plat_err:
        print(f"   ⚠️  Platinum Finish Line services/workers failed: {plat_err}")

    # =========================================================================
    # DEPENDENCY GUARDIAN — Daily dependency & API key health audit
    # =========================================================================
    try:
        from app.workers.dependency_guardian import DependencyGuardian
        _dep_guardian = DependencyGuardian(
            settings=settings,
            notifications=getattr(app.state, 'notifications', None),
        )
        await _dep_guardian.start()
        app.state.dependency_guardian = _dep_guardian
        _workers.append(_dep_guardian)
        print("   ✅ Dependency Guardian started (daily audit)")
    except Exception as dg_err:
        print(f"   ⚠️  Dependency Guardian failed to start: {dg_err}")

    # =========================================================================
    # PHASE 8: HIVE DEFENSE PROTOCOL INITIALIZATION
    # Patent-Pending — Claims 30-56
    # =========================================================================
    _hive_defense = {}
    _hive_workers = []
    try:
        # ── Phase 8A: Foundation Layer ────────────────────────────────────
        from app.services.security.forensic_logger import ForensicLogger
        from app.services.security.heartbeat import HeartbeatRegistry
        from app.services.security.coherence_gate import CoherenceGate
        from app.services.security.mirror_reflection import MirrorReflectionManager
        from app.services.security.curiosity_protocol import CuriosityProtocol
        from app.services.security.mesh_isolation import MeshIsolation
        from app.services.security.mirror_shell import MirrorShell
        from app.services.security.attacker_fingerprint import AttackerFingerprintDB
        from app.services.security.penetrator import Penetrator
        from app.services.security.infinite_mirror_trap import InfiniteMirrorTrap

        # ── Phase 8B: Hardened Immune System ──────────────────────────────
        from app.services.security.defcon_controller import DefconController
        from app.services.security.key_sharding import KeySharding
        from app.services.security.ephemeral_certificates import EphemeralCertificateAuthority
        from app.services.security.entropy_forge import EntropyForge
        from app.services.security.cumulative_drift_scorer import CumulativeDriftScorer
        from app.services.security.content_sentinel import ContentSentinel
        from app.services.security.temporal_jitter import TemporalJitter
        from app.services.security.queens_guard import QueensGuard
        from app.services.security.ghost_swarm import GhostSwarm
        from app.services.security.forensic_assembler import ForensicAssembler
        from app.services.security.verisimilitude_engine import VerisimilitudeEngine
        from app.services.security.watermark_engine import WatermarkEngine
        from app.services.security.behavioral_analytics import BehavioralAnalytics
        from app.services.security.dependency_quarantine import DependencyQuarantine
        from app.services.security.canary_credentials import CanaryCredentialManager
        from app.services.security.cert_pinning import CertPinningConfig
        from app.services.security.backup_encryption import BackupEncryptionManager

        # ── Phase 8C: Three Cords Doctrine ────────────────────────────────
        from app.services.security.ring_membership_validator import RingMembershipValidator
        from app.services.security.conservation_ledger_audit import ConservationLedgerAudit
        from app.services.security.birth_rate_anomaly import BirthRateAnomalyDetector
        from app.services.security.post_birth_quarantine import PostBirthQuarantine
        from app.services.security.cert_usage_audit import CertUsageAudit
        from app.services.security.behavioral_snapshot import BehavioralSnapshotManager
        from app.services.security.payload_entropy_analyzer import PayloadEntropyAnalyzer
        from app.services.security.output_differential_monitor import OutputDifferentialMonitor
        from app.services.security.request_path_randomizer import RequestPathRandomizer
        from app.services.security.adaptive_load_simulator import AdaptiveLoadSimulator
        from app.services.security.recursive_containment import RecursiveContainment
        from app.services.security.network_topology_fingerprint import NetworkTopologyFingerprint
        from app.services.security.tripwire_network import TripwireNetwork
        from app.services.security.cross_ref_consistency import CrossRefConsistencyEngine
        from app.services.security.auto_triage import AutoTriage
        from app.services.security.progressive_data_gating import ProgressiveDataGating
        from app.services.security.differential_privacy import DifferentialPrivacy
        from app.services.security.ct_monitor import CTMonitor
        from app.services.security.backup_access_anomaly import BackupAccessAnomaly
        from app.services.security.duress_code import DuressCodeManager
        from app.services.security.remote_wipe import RemoteWipe
        from app.services.security.process_isolation import ProcessIsolation
        from app.services.security.prompt_segmentation import PromptSegmentation
        from app.services.security.constant_time_crypto import ConstantTimeCrypto
        from app.services.security.response_normalization import ResponseNormalization

        # ── Phase 8D: Trinity Helix ───────────────────────────────────────
        from app.services.security.trinity_helix import TrinityHelix
        from app.services.security.helix_rotation_engine import HelixRotationEngine
        from app.services.security.triangular_inversion import TriangularMirrorInversion
        from app.services.security.triangle_wall_a_human import HumanJudgmentMirrorWall
        from app.services.security.triangle_wall_b_algo import AlgorithmicMirrorWallA
        from app.services.security.triangle_wall_c_behavioral import AlgorithmicMirrorWallB
        from app.services.security.cross_reflection_engine import CrossReflectionEngine
        from app.services.security.helix_sub_cord_router import HelixSubCordRouter
        from app.services.security.inversion_forensic_logger import InversionForensicLogger

        # ── Phase 8E: Projected Helix (Offensive) ─────────────────────────
        from app.services.security.offensive.projected_helix import ProjectedHelix
        from app.services.security.offensive.protocol_mirror import AttackerProtocolMirror
        from app.services.security.offensive.topology_mirror import AttackerTopologyMirror
        from app.services.security.offensive.behavior_mirror import AttackerBehaviorMirror
        from app.services.security.offensive.recursive_projection import RecursiveProjection
        from app.services.security.offensive.command_interceptor import CommandInterceptor
        from app.services.security.offensive.agent_redirection import AgentRedirection
        from app.services.security.offensive.attacker_model import AttackerBehavioralModel
        from app.services.security.offensive.projection_authorization import ProjectionAuthorization
        from app.services.security.offensive.projection_forensics import ProjectionForensics

        # ── Workers ───────────────────────────────────────────────────────
        from app.workers.heartbeat_monitor_worker import HeartbeatMonitorWorker
        from app.workers.curiosity_scanner_worker import CuriosityScannerWorker
        from app.workers.trap_monitor_worker import TrapMonitorWorker
        from app.workers.cds_computation_worker import CdsComputationWorker
        from app.workers.defcon_evaluator_worker import DefconEvaluatorWorker
        from app.workers.canary_monitor_worker import CanaryMonitorWorker
        from app.workers.backup_audit_worker import BackupAuditWorker
        from app.workers.birth_rate_monitor_worker import BirthRateMonitorWorker
        from app.workers.quarantine_evaluator_worker import QuarantineEvaluatorWorker
        from app.workers.snapshot_comparison_worker import SnapshotComparisonWorker
        from app.workers.ct_monitor_worker import CTMonitorWorker
        from app.workers.conservation_audit_worker import ConservationAuditWorker
        from app.workers.helix_rotation_worker import HelixRotationWorker
        from app.workers.triangle_monitor_worker import TriangleMonitorWorker
        from app.workers.projection_monitor_worker import ProjectionMonitorWorker
        from app.workers.recursive_learning_worker import RecursiveLearningWorker

        # ================================================================
        # INSTANTIATE SERVICES
        # ================================================================

        # -- Phase 8A Core --
        forensic_logger = ForensicLogger()
        heartbeat_registry = HeartbeatRegistry(db_pool=db_pool)
        coherence_gate = CoherenceGate(heartbeat_registry=heartbeat_registry)
        mirror_reflection = MirrorReflectionManager(forensic_logger=forensic_logger)
        mesh_isolation = MeshIsolation(db_pool=db_pool, forensic_logger=forensic_logger)
        curiosity_protocol = CuriosityProtocol(
            db_pool=db_pool,
            mirror_manager=mirror_reflection,
            forensic_logger=forensic_logger,
            mesh_isolation=mesh_isolation,
        )
        mirror_shell = MirrorShell(
            coherence_gate=coherence_gate,
            forensic_logger=forensic_logger,
        )
        attacker_db = AttackerFingerprintDB()
        # Penetrator + InfiniteMirrorTrap are spawned per-incident, not singletons.
        # We store factory references for the API/workers to use.
        _penetrator_factory = lambda zone: Penetrator(
            parent_fibre_id=None, containment_zone=zone,
            forensic_logger=forensic_logger, fingerprint_db=attacker_db,
        )
        _trap_factory = lambda: InfiniteMirrorTrap(forensic_logger=forensic_logger)

        # -- Phase 8B --
        defcon_controller = DefconController(db_pool=db_pool)
        key_sharding = KeySharding(db_pool=db_pool)
        ephemeral_ca = EphemeralCertificateAuthority(db_pool=db_pool)
        entropy_forge = EntropyForge()
        drift_scorer = CumulativeDriftScorer(db_pool=db_pool)
        content_sentinel = ContentSentinel(db_pool=db_pool)
        temporal_jitter = TemporalJitter()
        queens_guard = QueensGuard(db_pool=db_pool)
        ghost_swarm = GhostSwarm(forensic_logger=forensic_logger)
        forensic_assembler = ForensicAssembler()
        verisimilitude_engine = VerisimilitudeEngine()
        watermark_engine = WatermarkEngine()
        behavioral_analytics = BehavioralAnalytics(db_pool=db_pool)
        dependency_quarantine = DependencyQuarantine(db_pool=db_pool, forensic_logger=forensic_logger)
        canary_manager = CanaryCredentialManager(db_pool=db_pool)
        cert_pinning = CertPinningConfig(db_pool=db_pool, forensic_logger=forensic_logger)
        backup_encryption = BackupEncryptionManager(db_pool=db_pool, forensic_logger=forensic_logger)

        # -- Phase 8C: Third Cord Services --
        # Shared event callback (fires to forensic logger + logs)
        async def _hive_event(topic, payload=None):
            forensic_logger.log_event(topic, evidence=payload or {})

        ring_validator = RingMembershipValidator(db_pool=db_pool, forensic_logger=forensic_logger)
        conservation_ledger = ConservationLedgerAudit(
            db_pool=db_pool, forensic_logger=forensic_logger, defcon_controller=defcon_controller,
        )
        birth_rate_detector = BirthRateAnomalyDetector(
            db_pool=db_pool, forensic_logger=forensic_logger, defcon_controller=defcon_controller,
        )
        post_birth_quarantine = PostBirthQuarantine(
            db_pool=db_pool, forensic_logger=forensic_logger, defcon_controller=defcon_controller,
        )
        cert_usage_audit = CertUsageAudit(
            db_pool=db_pool, forensic_logger=forensic_logger, defcon_controller=defcon_controller,
        )
        behavioral_snapshot = BehavioralSnapshotManager(db_pool=db_pool, forensic_logger=forensic_logger)
        payload_entropy = PayloadEntropyAnalyzer(
            db_pool=db_pool, forensic_logger=forensic_logger, defcon_controller=defcon_controller,
        )
        output_diff_monitor = OutputDifferentialMonitor(
            db_pool=db_pool, forensic_logger=forensic_logger, defcon_controller=defcon_controller,
        )
        request_path_randomizer = RequestPathRandomizer()
        adaptive_load_sim = AdaptiveLoadSimulator()
        recursive_containment = RecursiveContainment()
        network_topo_fingerprint = NetworkTopologyFingerprint()
        tripwire_network = TripwireNetwork()
        cross_ref_engine = CrossRefConsistencyEngine()
        auto_triage = AutoTriage()
        progressive_gating = ProgressiveDataGating(db_pool=db_pool)
        differential_privacy = DifferentialPrivacy()
        ct_monitor = CTMonitor(db_pool=db_pool)
        backup_access_anomaly = BackupAccessAnomaly(db_pool=db_pool)
        duress_code_mgr = DuressCodeManager(
            db_pool=db_pool, defcon_controller=defcon_controller, forensic_logger=forensic_logger,
        )
        remote_wipe = RemoteWipe(db_pool=db_pool, defcon_controller=defcon_controller)
        process_isolation = ProcessIsolation()
        prompt_segmentation = PromptSegmentation(db_pool=db_pool)
        constant_time_crypto = ConstantTimeCrypto()
        response_normalization = ResponseNormalization()

        # -- Phase 8D: Trinity Helix --
        wall_a = HumanJudgmentMirrorWall()
        wall_b = AlgorithmicMirrorWallA()
        wall_c = AlgorithmicMirrorWallB()
        cross_reflection = CrossReflectionEngine()
        helix_rotation = HelixRotationEngine()
        triangular_inversion = TriangularMirrorInversion(
            wall_a=wall_a, wall_b=wall_b, wall_c=wall_c,
            cross_reflection_engine=cross_reflection,
            forensic_logger=forensic_logger, db_pool=db_pool,
        )
        trinity_helix = TrinityHelix()
        helix_sub_cord_router = HelixSubCordRouter(
            curiosity_protocol=curiosity_protocol,
            mirror_reflection=mirror_reflection,
            cumulative_drift_scorer=drift_scorer,
            heartbeat_registry=heartbeat_registry,
            coherence_gate=coherence_gate,
            payload_entropy_analyzer=payload_entropy,
            content_sentinel=content_sentinel,
            conservation_ledger=conservation_ledger,
            temporal_jitter=temporal_jitter,
            response_normalization=response_normalization,
            network_topology_fingerprint=network_topo_fingerprint,
            behavioral_snapshot=behavioral_snapshot,
        )

        # -- Phase 8E: Projected Helix (Offensive — requires human auth) --
        command_interceptor = CommandInterceptor()
        agent_redirection = AgentRedirection()
        projection_auth = ProjectionAuthorization(db_pool=db_pool)
        projection_forensics = ProjectionForensics(db_pool=db_pool)

        # Per-incident factories (spawned per attacker engagement, not singletons)
        _inversion_forensic_factory = lambda space_id: InversionForensicLogger(space_id=space_id)
        _projected_helix_factory = lambda report, profile, dep_id=None: ProjectedHelix(
            penetrator_report=report, attacker_profile=profile,
            forensic_logger=forensic_logger, deployment_id=dep_id,
        )
        _protocol_mirror_factory = lambda spec=None: AttackerProtocolMirror(protocol_spec=spec)
        _topology_mirror_factory = lambda spec=None: AttackerTopologyMirror(topology_spec=spec)
        _behavior_mirror_factory = lambda profile=None: AttackerBehaviorMirror(behavioral_profile=profile)
        _recursive_projection_factory = lambda dep_id, p_mirror, t_mirror, b_mirror, profile: RecursiveProjection(
            deployment_id=dep_id, protocol_mirror=p_mirror,
            topology_mirror=t_mirror, behavior_mirror=b_mirror,
            attacker_profile=profile,
        )
        _attacker_model_factory = lambda profile: AttackerBehavioralModel(attacker_profile=profile)

        # ================================================================
        # REGISTER ALL SERVICES
        # ================================================================
        _hive_defense = {
            # Phase 8A
            "forensic_logger": forensic_logger,
            "heartbeat_registry": heartbeat_registry,
            "coherence_gate": coherence_gate,
            "mirror_reflection": mirror_reflection,
            "curiosity_protocol": curiosity_protocol,
            "mesh_isolation": mesh_isolation,
            "mirror_shell": mirror_shell,
            "attacker_db": attacker_db,
            "penetrator_factory": _penetrator_factory,
            "trap_factory": _trap_factory,
            # Phase 8B
            "defcon_controller": defcon_controller,
            "key_sharding": key_sharding,
            "ephemeral_ca": ephemeral_ca,
            "entropy_forge": entropy_forge,
            "drift_scorer": drift_scorer,
            "content_sentinel": content_sentinel,
            "temporal_jitter": temporal_jitter,
            "queens_guard": queens_guard,
            "ghost_swarm": ghost_swarm,
            "forensic_assembler": forensic_assembler,
            "verisimilitude_engine": verisimilitude_engine,
            "watermark_engine": watermark_engine,
            "behavioral_analytics": behavioral_analytics,
            "dependency_quarantine": dependency_quarantine,
            "canary_manager": canary_manager,
            "cert_pinning": cert_pinning,
            "backup_encryption": backup_encryption,
            # Phase 8C
            "ring_validator": ring_validator,
            "conservation_ledger": conservation_ledger,
            "birth_rate_detector": birth_rate_detector,
            "post_birth_quarantine": post_birth_quarantine,
            "cert_usage_audit": cert_usage_audit,
            "behavioral_snapshot": behavioral_snapshot,
            "payload_entropy": payload_entropy,
            "output_diff_monitor": output_diff_monitor,
            "request_path_randomizer": request_path_randomizer,
            "adaptive_load_sim": adaptive_load_sim,
            "recursive_containment": recursive_containment,
            "network_topo_fingerprint": network_topo_fingerprint,
            "tripwire_network": tripwire_network,
            "cross_ref_engine": cross_ref_engine,
            "auto_triage": auto_triage,
            "progressive_gating": progressive_gating,
            "differential_privacy": differential_privacy,
            "ct_monitor": ct_monitor,
            "backup_access_anomaly": backup_access_anomaly,
            "duress_code_mgr": duress_code_mgr,
            "remote_wipe": remote_wipe,
            "process_isolation": process_isolation,
            "prompt_segmentation": prompt_segmentation,
            "constant_time_crypto": constant_time_crypto,
            "response_normalization": response_normalization,
            # Phase 8D
            "wall_a": wall_a,
            "wall_b": wall_b,
            "wall_c": wall_c,
            "cross_reflection": cross_reflection,
            "helix_rotation": helix_rotation,
            "triangular_inversion": triangular_inversion,
            "trinity_helix": trinity_helix,
            "helix_sub_cord_router": helix_sub_cord_router,
            # Phase 8E
            "command_interceptor": command_interceptor,
            "agent_redirection": agent_redirection,
            "projection_auth": projection_auth,
            "projection_forensics": projection_forensics,
            # Phase 8D/8E factories (per-incident, not singletons)
            "inversion_forensic_factory": _inversion_forensic_factory,
            "projected_helix_factory": _projected_helix_factory,
            "protocol_mirror_factory": _protocol_mirror_factory,
            "topology_mirror_factory": _topology_mirror_factory,
            "behavior_mirror_factory": _behavior_mirror_factory,
            "recursive_projection_factory": _recursive_projection_factory,
            "attacker_model_factory": _attacker_model_factory,
        }
        app.state.hive_defense = _hive_defense

        # Share Hive Defense with the WebSocket bridge
        try:
            from app.websocket.bridge_server import set_hive_defense
            set_hive_defense(_hive_defense)
        except Exception:
            pass  # Bridge may not be loaded yet in all deployment modes

        # Share SovereignMind with the WebSocket bridge for HoH observation wisdom feed
        try:
            from app.websocket.bridge_server import set_sovereign_mind
            _sm_ref = getattr(app.state, "sovereign_mind", None)
            if _sm_ref:
                set_sovereign_mind(_sm_ref)
        except Exception:
            pass

        # ================================================================
        # START PHASE 8 WORKERS
        # ================================================================
        _defcon_provider = lambda: defcon_controller.get_state()

        hw_heartbeat = HeartbeatMonitorWorker(
            heartbeat_registry=heartbeat_registry,
            curiosity_protocol=curiosity_protocol,
            db_pool=db_pool, defcon_provider=_defcon_provider,
        )
        await hw_heartbeat.start()
        _hive_workers.append(hw_heartbeat)

        hw_curiosity = CuriosityScannerWorker(
            curiosity_protocol=curiosity_protocol,
            heartbeat_registry=heartbeat_registry,
            db_pool=db_pool, defcon_provider=_defcon_provider,
        )
        await hw_curiosity.start()
        _hive_workers.append(hw_curiosity)

        hw_trap = TrapMonitorWorker(
            trap_registry={}, event_bus=_hive_event, db_pool=db_pool,
        )
        await hw_trap.start()
        _hive_workers.append(hw_trap)

        hw_cds = CdsComputationWorker(
            db_pool=db_pool, curiosity_protocol=curiosity_protocol,
            defcon_provider=_defcon_provider,
        )
        await hw_cds.start()
        _hive_workers.append(hw_cds)

        hw_defcon = DefconEvaluatorWorker(
            db_pool=db_pool, forensic_logger=forensic_logger,
            canary_manager=canary_manager,
        )
        await hw_defcon.start()
        _hive_workers.append(hw_defcon)

        hw_canary = CanaryMonitorWorker(
            canary_manager=canary_manager, db_pool=db_pool,
            forensic_logger=forensic_logger, defcon_provider=_defcon_provider,
        )
        await hw_canary.start()
        _hive_workers.append(hw_canary)

        hw_backup = BackupAuditWorker(
            backup_manager=backup_encryption, db_pool=db_pool,
            forensic_logger=forensic_logger,
        )
        await hw_backup.start()
        _hive_workers.append(hw_backup)

        hw_birth = BirthRateMonitorWorker(
            db_pool=db_pool, defcon_provider=_defcon_provider,
        )
        await hw_birth.start()
        _hive_workers.append(hw_birth)

        hw_quarantine = QuarantineEvaluatorWorker(
            db_pool=db_pool, heartbeat_registry=heartbeat_registry,
            defcon_provider=_defcon_provider,
        )
        await hw_quarantine.start()
        _hive_workers.append(hw_quarantine)

        hw_snapshot = SnapshotComparisonWorker(
            db_pool=db_pool, defcon_provider=_defcon_provider,
        )
        await hw_snapshot.start()
        _hive_workers.append(hw_snapshot)

        hw_ct = CTMonitorWorker(
            ct_monitor=ct_monitor, db_pool=db_pool,
            defcon_provider=_defcon_provider,
        )
        await hw_ct.start()
        _hive_workers.append(hw_ct)

        hw_conservation = ConservationAuditWorker(
            db_pool=db_pool, defcon_provider=_defcon_provider,
        )
        await hw_conservation.start()
        _hive_workers.append(hw_conservation)

        hw_helix = HelixRotationWorker(
            trinity_helix=trinity_helix, rotation_engine=helix_rotation,
            event_bus=_hive_event, db_pool=db_pool,
        )
        await hw_helix.start()
        _hive_workers.append(hw_helix)

        hw_triangle = TriangleMonitorWorker(
            triangular_inversion=triangular_inversion,
            inversion_forensic_logger=None,
            event_bus=_hive_event, db_pool=db_pool,
        )
        await hw_triangle.start()
        _hive_workers.append(hw_triangle)

        hw_projection = ProjectionMonitorWorker(
            projection_registry={}, event_bus=_hive_event, db_pool=db_pool,
        )
        await hw_projection.start()
        _hive_workers.append(hw_projection)

        hw_recursive = RecursiveLearningWorker(
            projection_registry={}, event_bus=_hive_event, db_pool=db_pool,
        )
        await hw_recursive.start()
        _hive_workers.append(hw_recursive)

        print(f"   ✅ Hive Defense Protocol initialized ({len(_hive_defense)} services, {len(_hive_workers)} workers)")
        print(f"      Patent Claims 30-56 | 23 attack vectors | Three Cords Doctrine")
    except Exception as hive_err:
        import traceback
        print(f"   ⚠️  Hive Defense initialization failed: {hive_err}")
        traceback.print_exc()
        app.state.hive_defense = {}

    # ─── Hive Defense v4.0-v4.3: All Windows Closed ──────────────────────────
    try:
        from app.services.billing import WebhookFortress, BillingMonitor, TrialGuard, UsageMeter, CoachFinancialGuard
        from app.services.guardian_fibre import GuardianFibre
        from app.services.login_guardian import MemberLoginGuardian, CoachLoginGuardian
        from app.services.mirror_prediction import MirrorPredictionEngine
        from app.services.transit_guardian import TransitGuardian
        from app.services.infiltrator_trap import InfiltratorTrap
        from app.services.family_data_guardian import FamilyDataGuardian
        from app.services.sentinel_mesh import SentinelMesh
        from app.services.pipeline_drum import PipelineDrum
        from app.services.hepa_filter import HEPAFilter
        from app.services.sovereign_layer import SovereignKeyManager
        from app.services.anonymization_proxy import AnonymizationProxy
        from app.services.therapeutic_integrity import TherapeuticIntegrityMonitor
        from app.services.model_stability import ModelStabilityLayer
        from app.services.succession_protocol import SuccessionProtocol
        from app.services.recovery_drill import RecoveryDrillFramework
        from app.services.coach_integrity_shield import CoachIntegrityShield
        from app.services.legal_compulsion import LegalCompulsionProtocol
        from app.services.sovereign_stripe_proxy import SovereignStripeProxy
        from app.services.family_session_guardian import FamilySessionGuardian
        from app.services.zero_knowledge import ZeroKnowledgeVault
        from app.services.multi_cloud_heritage_vault import MultiCloudHeritageVault

        # Initialize all v4 services
        _guardian_fibre = GuardianFibre(db_pool)
        _sentinel_mesh = SentinelMesh(db_pool, _guardian_fibre)
        _pipeline_drum = PipelineDrum(db_pool)
        _hepa_filter = HEPAFilter(db_pool)
        _billing_monitor = BillingMonitor(db_pool)
        _sovereign_keys = SovereignKeyManager()
        _sovereign_keys.initialize()
        _succession = SuccessionProtocol(db_pool)
        _recovery = RecoveryDrillFramework(db_pool, _sovereign_keys, _succession, _hepa_filter)

        # Start background services
        await _sentinel_mesh.start()
        await _pipeline_drum.start()
        await _hepa_filter.start()
        await _billing_monitor.start()
        await _recovery.start()

        # Store in app state
        app.state.hive_v4 = {
            "webhook_fortress": WebhookFortress(db_pool),
            "guardian_fibre": _guardian_fibre,
            "member_login_guardian": MemberLoginGuardian(db_pool),
            "coach_login_guardian": CoachLoginGuardian(db_pool),
            "mirror_prediction": MirrorPredictionEngine(),
            "transit_guardian": TransitGuardian(db_pool),
            "infiltrator_trap": InfiltratorTrap(db_pool, _guardian_fibre),
            "family_data_guardian": FamilyDataGuardian(db_pool),
            "sentinel_mesh": _sentinel_mesh,
            "pipeline_drum": _pipeline_drum,
            "hepa_filter": _hepa_filter,
            "billing_monitor": _billing_monitor,
            "trial_guard": TrialGuard(db_pool),
            "usage_meter": UsageMeter(db_pool),
            "coach_financial_guard": CoachFinancialGuard(db_pool),
            "sovereign_keys": _sovereign_keys,
            "anonymization_proxy": AnonymizationProxy(),
            "therapeutic_integrity": TherapeuticIntegrityMonitor(db_pool),
            "model_stability": ModelStabilityLayer(),
            "succession_protocol": _succession,
            "recovery_drill": _recovery,
            "coach_integrity_shield": CoachIntegrityShield(db_pool),
            "legal_compulsion": LegalCompulsionProtocol(db_pool),
            "sovereign_stripe_proxy": SovereignStripeProxy(db_pool),
            "family_session_guardian": FamilySessionGuardian(db_pool),
            "zero_knowledge_vault": ZeroKnowledgeVault(db_pool),
        }

        # ── Castle Defense Layers 0-8 ──
        try:
            from app.services.security.yubikey_gate import get_yubikey_gate
            from app.services.security.sase_controller import get_sase
            from app.services.security.zta_gatekeeper import get_zta
            from app.services.security.zta_bug_fibre import get_zta_bug
            from app.services.security.skeptic_guard import get_skeptic
            from app.services.security.critic_guard import get_critic
            from app.services.security.endpoint_shield import get_endpoint_shield
            from app.services.security.mirror_gateway import get_mirror_gateway
            from app.services.security.sovereign_fall_command import get_fall_command

            _yubikey_gate = get_yubikey_gate()
            _sase = get_sase()
            _zta = get_zta(guardian_fibre=_guardian_fibre)
            _zta_bug = get_zta_bug()
            _skeptic = get_skeptic()
            _critic = get_critic()
            _endpoint_shield = get_endpoint_shield()
            _mirror_gateway = get_mirror_gateway()
            _fall_command = get_fall_command()

            # Wire ZTA Bug to guards and Drum
            _zta_bug.attach_guards(_skeptic, _critic)
            _zta_bug.attach_sentinel_mesh(_sentinel_mesh)
            _pipeline_drum._zta_bug = _zta_bug

            app.state.hive_v4["yubikey_gate"] = _yubikey_gate
            app.state.hive_v4["sase_controller"] = _sase
            app.state.hive_v4["zta_gatekeeper"] = _zta
            app.state.hive_v4["zta_bug"] = _zta_bug
            app.state.hive_v4["skeptic_guard"] = _skeptic
            app.state.hive_v4["critic_guard"] = _critic
            app.state.hive_v4["endpoint_shield"] = _endpoint_shield
            app.state.hive_v4["mirror_gateway"] = _mirror_gateway
            app.state.hive_v4["fall_command"] = _fall_command

            _yk_mode = "active" if _yubikey_gate.available else "passthrough (no hardware)"
            print("   ✅ Castle Defense Layers 0-8 initialized")
            print(f"      YubiKey Gate: {_yk_mode} | SASE: {_sase.stats['enabled']} | ZTA: active")
            print(f"      ZTA Bug: guards attached | Endpoint Shield: active")
            print(f"      Mirror Gateway: active | Fall Command: armed")
        except Exception as _cd_err:
            print(f"   ⚠️  Castle Defense init (non-fatal): {_cd_err}")

        # ── Multi-Cloud Heritage Vault (Section 13.10.7) ──
        try:
            _heritage_vault = MultiCloudHeritageVault(db_pool)
            _heritage_status = await _heritage_vault.initialize()
            app.state.hive_v4["heritage_vault"] = _heritage_vault
            print(f"   ✅ Multi-Cloud Heritage Vault initialized: {_heritage_status}")
        except Exception as _hv_err:
            print(f"   ⚠️  Heritage Vault init failed: {_hv_err}")

        # NOTE: Middleware registration moved to module level (after CORS).
        # Starlette does not allow app.add_middleware() after the app has started.
        # The middleware classes use lazy lookup via app.state to find their services.

        # ── Upstream Canary Network (Section 13.10.8) ──
        try:
            from app.services.upstream_canary import UpstreamCanaryNetwork

            import logging as _logging
            _canary_logger = _logging.getLogger("upstream_canary")

            async def _canary_alert(topic, payload):
                _canary_logger.warning("CANARY ALERT: %s — %s", topic, payload)

            _upstream_canary = UpstreamCanaryNetwork(
                db_pool=db_pool,
                check_interval=3600,
                alert_callback=_canary_alert,
            )
            await _upstream_canary.start()
            app.state.hive_v4["upstream_canary"] = _upstream_canary
            print("   ✅ Upstream Canary Network started (Azure, Stripe, SendGrid, Anthropic)")
        except Exception as uc_err:
            print(f"   ⚠️  Upstream Canary Network failed: {uc_err}")

        # ── Therapeutic Integrity Background Loop ──
        _therapeutic_task = None
        try:
            _therapeutic_monitor = app.state.hive_v4.get("therapeutic_integrity")
            if _therapeutic_monitor:
                import asyncio as _asyncio
                _therapeutic_task = _asyncio.create_task(
                    _therapeutic_monitor.start_background_loop(interval_seconds=86400)
                )
                app.state._therapeutic_integrity_task = _therapeutic_task
                print("   ✅ Therapeutic Integrity Monitor background loop started (24h interval)")
        except Exception as ti_err:
            print(f"   ⚠️  Therapeutic Integrity background failed: {ti_err}")

        # ── Deadman Switch — Client Silence Monitor ──
        _deadman_task = None
        try:
            from app.services.deadman_switch import DeadmanSwitchService
            import asyncio as _asyncio

            _deadman_switch = DeadmanSwitchService(db_pool)
            app.state.hive_v4["deadman_switch"] = _deadman_switch

            async def _deadman_loop():
                """Run client silence, coach gap, and suspicious account checks every 4 hours."""
                while True:
                    try:
                        # 1. Client silence monitor
                        result = await _deadman_switch.check_all_clients()
                        checked = result.get("clients_checked", 0)
                        alerts = result.get("alerts_generated", 0)
                        skipped = result.get("skipped_no_engagement", 0)
                        if alerts > 0:
                            print(f">>> [DEADMAN] {alerts} silence alert(s) generated ({checked} clients checked, {skipped} skipped)")

                        # 2. Coach session gap monitor
                        coach_result = await _deadman_switch.check_coaches_without_sessions()
                        coach_alerts = coach_result.get("alerts_generated", 0)
                        if coach_alerts > 0:
                            print(f">>> [DEADMAN] {coach_alerts} coach gap alert(s) ({coach_result.get('coaches_checked', 0)} coaches checked)")

                        # 3. Suspicious / probe account detection
                        suspicious = await _deadman_switch.check_suspicious_accounts()
                        flagged = suspicious.get("flagged", 0)
                        if flagged > 0:
                            print(f">>> [DEADMAN] {flagged} suspicious account(s) flagged")

                    except Exception as _dm_err:
                        print(f">>> [DEADMAN] Check failed: {_dm_err}")
                    await _asyncio.sleep(4 * 3600)  # 4 hours

            _deadman_task = _asyncio.create_task(_deadman_loop())
            app.state._deadman_switch_task = _deadman_task
            print("   ✅ Deadman Switch started (client silence monitor, 4h interval)")
        except Exception as dm_err:
            print(f"   ⚠️  Deadman Switch init failed: {dm_err}")

        # ── Account Purge Job — Destroys data for expired staged_deletions ──
        _purge_task = None
        try:
            import asyncio as _asyncio_purge

            async def _account_purge_loop():
                """Every 6 hours, check for staged_deletions past their cooling period and purge."""
                while True:
                    try:
                        if db_pool:
                            async with db_pool.acquire() as _pc:
                                # Find deletions whose cooling period has expired
                                expired = await _pc.fetch(
                                    """SELECT id, user_id, data_type, data_id
                                    FROM staged_deletions
                                    WHERE NOT executed AND NOT cancelled
                                      AND executes_at <= NOW()"""
                                )

                                for row in expired:
                                    _del_uid = row["user_id"]
                                    _del_type = row["data_type"]

                                    if _del_type == "account":
                                        # Hard purge: remove user data from DB
                                        try:
                                            await _pc.execute(
                                                "DELETE FROM sessions WHERE user_id = (SELECT id FROM users WHERE hardware_id = $1)",
                                                _del_uid,
                                            )
                                            await _pc.execute(
                                                "DELETE FROM nate_nudges WHERE user_id = (SELECT id FROM users WHERE hardware_id = $1)",
                                                _del_uid,
                                            )
                                            await _pc.execute(
                                                "DELETE FROM nevedal_metrics WHERE user_id = (SELECT id FROM users WHERE hardware_id = $1)",
                                                _del_uid,
                                            )
                                            await _pc.execute(
                                                "UPDATE users SET deleted_at = NOW(), name = 'Deleted User', "
                                                "email = NULL, phone = NULL, profile_data = '{}' "
                                                "WHERE hardware_id = $1",
                                                _del_uid,
                                            )
                                        except Exception as _purge_db_err:
                                            print(f">>> [PURGE] DB cleanup error for {_del_uid}: {_purge_db_err}")

                                        # Send final notification (best effort)
                                        try:
                                            from app.websocket.bridge_server import load_registry
                                            _reg = load_registry()
                                            for _rk, _rv in _reg.items():
                                                if _rv.get("profile", {}).get("hardware_id") == _del_uid:
                                                    _p_email = _rv["profile"].get("email", "")
                                                    _p_phone = _rv["profile"].get("phone", "")
                                                    _p_name = _rv["profile"].get("name", "")
                                                    if _p_email:
                                                        from app.websocket.notification_system import NotificationSystem
                                                        import os as _os_purge
                                                        _ns = NotificationSystem(
                                                            _rv.get("data_dir", _os_purge.getenv("DATA_DIR", "/app/data")),
                                                            _os_purge.getenv("SENDGRID_API_KEY")
                                                        )
                                                        await _ns.send_account_permanently_deleted(
                                                            _p_email, _p_name, _p_phone or None
                                                        )
                                                    break
                                        except Exception:
                                            pass

                                    # Mark as executed
                                    await _pc.execute(
                                        "UPDATE staged_deletions SET executed = TRUE, executed_at = NOW() WHERE id = $1",
                                        row["id"],
                                    )

                                    # Audit log
                                    await _pc.execute(
                                        """INSERT INTO audit_log
                                            (action_type, target_id, description, ip_address)
                                        VALUES ('ACCOUNT_PURGED', $1, $2, '0.0.0.0'::inet)""",
                                        _del_uid,
                                        f"Account data permanently purged after 30-day cooling period",
                                    )

                                if expired:
                                    print(f">>> [PURGE] Purged {len(expired)} expired staged deletion(s)")

                            # Also send cooling check-in reminders
                            async with db_pool.acquire() as _cc:
                                # 24h check-in (requested_at ~ 24h ago, not yet checked in)
                                _24h_due = await _cc.fetch(
                                    """SELECT sd.id, sd.user_id FROM staged_deletions sd
                                    WHERE NOT sd.executed AND NOT sd.cancelled
                                      AND NOT sd.checkin_24h
                                      AND sd.requested_at <= NOW() - INTERVAL '24 hours'"""
                                )
                                for _ci in _24h_due:
                                    await _cc.execute(
                                        "UPDATE staged_deletions SET checkin_24h = TRUE WHERE id = $1",
                                        _ci["id"],
                                    )

                                # Midpoint check-in (15 days)
                                _mid_due = await _cc.fetch(
                                    """SELECT sd.id, sd.user_id FROM staged_deletions sd
                                    WHERE NOT sd.executed AND NOT sd.cancelled
                                      AND NOT sd.checkin_midpoint
                                      AND sd.requested_at <= NOW() - INTERVAL '15 days'"""
                                )
                                for _ci in _mid_due:
                                    await _cc.execute(
                                        "UPDATE staged_deletions SET checkin_midpoint = TRUE WHERE id = $1",
                                        _ci["id"],
                                    )

                                # Final check-in (27 days = 3 days before purge)
                                _final_due = await _cc.fetch(
                                    """SELECT sd.id, sd.user_id FROM staged_deletions sd
                                    WHERE NOT sd.executed AND NOT sd.cancelled
                                      AND NOT sd.checkin_final
                                      AND sd.requested_at <= NOW() - INTERVAL '27 days'"""
                                )
                                for _ci in _final_due:
                                    await _cc.execute(
                                        "UPDATE staged_deletions SET checkin_final = TRUE WHERE id = $1",
                                        _ci["id"],
                                    )

                    except Exception as _purge_err:
                        print(f">>> [PURGE] Background purge check failed: {_purge_err}")
                    await _asyncio_purge.sleep(6 * 3600)  # 6 hours

            _purge_task = _asyncio_purge.create_task(_account_purge_loop())
            app.state._purge_task = _purge_task
            print("   ✅ Account Purge Job started (6h interval, 30-day cooling enforcement)")
        except Exception as purge_err:
            print(f"   ⚠️  Account Purge Job init failed: {purge_err}")

        print("   ✅ Hive Defense v4.0-v4.3 initialized (25 services, 9 background loops)")
        print("      All 8 Windows Closed | Billing Fortress | Guardian Fibre | Sentinel Mesh")
        print("      Pipeline Drum | HEPA Filter | Sovereign Layer | Zero Knowledge")
        print("      Upstream Canary | Webhook Rate Limit | Therapeutic Integrity | Deadman Switch")
    except Exception as v4_err:
        import traceback
        print(f"   ⚠️  Hive Defense v4.x initialization failed: {v4_err}")
        traceback.print_exc()
        app.state.hive_v4 = {}

    # ── Token Guardian — keeps all social media OAuth tokens alive ──
    _token_guardian = None
    try:
        from app.services.token_guardian import TokenGuardian
        _token_guardian = TokenGuardian(db_pool, interval_seconds=2700)
        await _token_guardian.start()
        app.state.token_guardian = _token_guardian
        print("   ✅ Token Guardian started (45-min sweep, proactive refresh)")
    except Exception as tg_err:
        print(f"   ⚠️  Token Guardian init failed: {tg_err}")

    # ── Token Renewal Agent — notifies admin on token failures, validates after renewal ──
    _token_renewal_agent = None
    try:
        from app.services.token_renewal_agent import TokenRenewalAgent
        from app.config import settings as _tra_settings
        _notify_sys = getattr(app.state, "notification_system", None)
        if _notify_sys is None:
            from app.websocket.notification_system import NotificationSystem
            _notify_sys = NotificationSystem(
                data_dir=os.environ.get("DATA_DIR", "/app/data"),
                sendgrid_key=os.environ.get("SENDGRID_API_KEY"),
            )
            app.state.notification_system = _notify_sys
        _admin_phone = _tra_settings.ADMIN_ALERT_PHONE or os.environ.get("ADMIN_VERIFY_PHONE", "")
        _admin_email = (_tra_settings.ADMIN_ALERT_EMAILS or "").split(",")[0].strip()
        _token_renewal_agent = TokenRenewalAgent(
            db_pool,
            notification_system=_notify_sys,
            admin_phone=_admin_phone,
            admin_email=_admin_email,
            interval_seconds=900,
        )
        await _token_renewal_agent.start()
        app.state.token_renewal_agent = _token_renewal_agent
        print("   ✅ Token Renewal Agent started (15-min sweep, SMS/email notify)")
    except Exception as tra_err:
        print(f"   ⚠️  Token Renewal Agent init failed: {tra_err}")

    # ── Token Audit Agent — independently audits the Renewal Agent ──
    _token_audit_agent = None
    try:
        from app.services.token_audit_agent import TokenAuditAgent
        from app.config import settings as _taa_settings
        _audit_phone = _taa_settings.ADMIN_ALERT_PHONE or os.environ.get("ADMIN_VERIFY_PHONE", "")
        _audit_email = (_taa_settings.ADMIN_ALERT_EMAILS or "").split(",")[0].strip()
        _audit_notify = getattr(app.state, "notification_system", None)
        if _audit_notify is None:
            _audit_notify = _notify_sys if _token_renewal_agent else None
        _token_audit_agent = TokenAuditAgent(
            db_pool,
            interval_seconds=1800,
            notification_system=_audit_notify,
            admin_phone=_audit_phone,
            admin_email=_audit_email,
        )
        await _token_audit_agent.start()
        app.state.token_audit_agent = _token_audit_agent
        print("   ✅ Token Audit Agent started (30-min audit cycle)")
    except Exception as taa_err:
        print(f"   ⚠️  Token Audit Agent init failed: {taa_err}")

    # ── Content Queue Janitor — archives exhausted posts, detects error patterns ──
    _content_janitor = None
    try:
        from app.services.content_queue_janitor import ContentQueueJanitor
        _content_janitor = ContentQueueJanitor(db_pool, interval_seconds=21600)
        await _content_janitor.start()
        app.state.content_queue_janitor = _content_janitor
        print("   ✅ ContentQueueJanitor started (6h cycle, stagger 70s)")
    except Exception as cqj_err:
        print(f"   ⚠️  ContentQueueJanitor init failed: {cqj_err}")

    # ── Token Lifecycle Predictor — early warning for expiring tokens ──
    _token_predictor = None
    try:
        from app.services.token_lifecycle_predictor import TokenLifecyclePredictor
        _tlp_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _tlp_phone = _admin_phone if '_admin_phone' in dir() else os.environ.get("ADMIN_VERIFY_PHONE", "")
        _tlp_email = _admin_email if '_admin_email' in dir() else os.environ.get("ADMIN_ALERT_EMAILS", "").split(",")[0].strip()
        _token_predictor = TokenLifecyclePredictor(
            db_pool,
            notification_system=_tlp_notify,
            admin_phone=_tlp_phone,
            admin_email=_tlp_email,
            interval_seconds=43200,
        )
        await _token_predictor.start()
        app.state.token_lifecycle_predictor = _token_predictor
        print("   ✅ TokenLifecyclePredictor started (12h scan, stagger 80s)")
    except Exception as tlp_err:
        print(f"   ⚠️  TokenLifecyclePredictor init failed: {tlp_err}")

    # ── Database Maintenance Agent — prunes stale rows, tracks DB health ──
    _db_maintenance = None
    try:
        from app.services.db_maintenance_agent import DatabaseMaintenanceAgent
        _db_maintenance = DatabaseMaintenanceAgent(db_pool, interval_seconds=86400)
        await _db_maintenance.start()
        app.state.db_maintenance_agent = _db_maintenance
        print("   ✅ DatabaseMaintenanceAgent started (24h cycle, stagger 90s)")
    except Exception as dbm_err:
        print(f"   ⚠️  DatabaseMaintenanceAgent init failed: {dbm_err}")

    # ── Crystal PHI Auditor — standing sweep of ownerless crystals against
    # the live client-name roster; auto-quarantines matches. See
    # docs/INCIDENT_MEMO_CRYSTAL_SCOPE_PHI_EXPOSURE_2026-07-09.md for the
    # incident this agent exists to prevent from recurring. Closes the
    # failure class at the READ side on a schedule, independent of
    # crystal_phi_guard.py's write-time gate. ──
    _crystal_phi_auditor = None
    try:
        from app.services.crystal_phi_auditor import CrystalPhiAuditor
        _cpa_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _cpa_email = _audit_email if '_audit_email' in dir() else os.environ.get("ADMIN_ALERT_EMAILS", "").split(",")[0].strip()
        _crystal_phi_auditor = CrystalPhiAuditor(
            db_pool,
            interval_seconds=21600,
            notification_system=_cpa_notify,
            admin_email=_cpa_email,
        )
        await _crystal_phi_auditor.start()
        app.state.crystal_phi_auditor = _crystal_phi_auditor
        print("   ✅ CrystalPhiAuditor started (6h sweep, stagger 150s)")
    except Exception as cpa_err:
        print(f"   ⚠️  CrystalPhiAuditor init failed: {cpa_err}")

    # ── Session Recovery Agent — retries failed AI session summaries ──
    _session_recovery = None
    try:
        from app.services.session_recovery_agent import SessionRecoveryAgent
        _session_recovery = SessionRecoveryAgent(db_pool, interval_seconds=7200)
        await _session_recovery.start()
        app.state.session_recovery_agent = _session_recovery
        print("   ✅ SessionRecoveryAgent started (2h cycle, stagger 100s)")
    except Exception as sra_err:
        print(f"   ⚠️  SessionRecoveryAgent init failed: {sra_err}")

    # ── Expose worker lists on app.state for digest visibility ──
    app.state._workers_list = _workers
    app.state._hive_workers_list = _hive_workers

    # ── Agent Status Digest — 3x daily trust report covering all agents ──
    _agent_digest = None
    if _is_clone:
        # QUANTUM-CRYSTAL-ARCH — truthy sentinel so clone health stays NOMINAL
        _agent_digest = "skipped_clone"
        app.state.agent_status_digest = "skipped_clone"
        print("   ⏭️  AgentStatusDigest skipped (clone mode)")
    else:
        try:
            from app.services.agent_status_digest import AgentStatusDigest
            _digest_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
            _agent_digest = AgentStatusDigest(
                app_state=app.state,
                db_pool=db_pool,
                notification_system=_digest_notify,
            )
            await _agent_digest.start()
            app.state.agent_status_digest = _agent_digest
            print("   ✅ AgentStatusDigest started (5am/5pm/11pm UTC, stagger 110s)")
        except Exception as asd_err:
            print(f"   ⚠️  AgentStatusDigest init failed: {asd_err}")

    # ── Public Trial Daily Digest — try.html funnel (08:00 ET) ──
    _public_trial_digest = None
    if _is_clone:
        # QUANTUM-CRYSTAL-ARCH — truthy sentinel so clone health stays NOMINAL
        _public_trial_digest = "skipped_clone"
        app.state.public_trial_digest = "skipped_clone"
        print("   ⏭️  PublicTrialDigest skipped (clone mode)")
    else:
        try:
            from app.services.public_trial_digest import PublicTrialDigest
            _ptd_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
            _public_trial_digest = PublicTrialDigest(
                db_pool=db_pool,
                notification_system=_ptd_notify,
                redis_url=_REDIS_URL_EARLY,
            )
            await _public_trial_digest.start()
            app.state.public_trial_digest = _public_trial_digest
            print("   ✅ PublicTrialDigest started (daily 12:00 UTC / 08:00 ET)")
        except Exception as ptd_err:
            print(f"   ⚠️  PublicTrialDigest init failed: {ptd_err}")

    # ── SkyEye Tab Auditor — 3x daily endpoint trust scorecard ──
    _tab_auditor = None
    try:
        from app.services.skyeye_tab_auditor import SkyEyeTabAuditor
        _tab_audit_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _tab_auditor = SkyEyeTabAuditor(
            db_pool=db_pool,
            notification_system=_tab_audit_notify,
            app_state=app.state,
        )
        if not _is_clone: await _tab_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.skyeye_tab_auditor = _tab_auditor
        print("   ✅ SkyEyeTabAuditor started (5am/5pm/11pm UTC, stagger 120s)")
    except Exception as sta_err:
        print(f"   ⚠️  SkyEyeTabAuditor init failed: {sta_err}")

    # ── Sovereign Command Tab Auditor — 3x daily command dashboard trust scorecard ──
    _cmd_auditor = None
    try:
        from app.services.command_tab_auditor import SovereignCommandAuditor
        _cmd_audit_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _cmd_auditor = SovereignCommandAuditor(
            db_pool=db_pool,
            notification_system=_cmd_audit_notify,
            app_state=app.state,
        )
        if not _is_clone: await _cmd_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.command_tab_auditor = _cmd_auditor
        print("   ✅ SovereignCommandAuditor started (5am/5pm/11pm UTC, stagger 130s)")
    except Exception as cta_err:
        print(f"   ⚠️  SovereignCommandAuditor init failed: {cta_err}")

    # ── The Eye Auditor — 3x daily surveillance & analytics trust scorecard ──
    _eye_auditor = None
    try:
        from app.services.the_eye_auditor import TheEyeAuditor
        _eye_audit_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _eye_auditor = TheEyeAuditor(
            db_pool=db_pool,
            notification_system=_eye_audit_notify,
            app_state=app.state,
        )
        if not _is_clone: await _eye_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.the_eye_auditor = _eye_auditor
        print("   ✅ TheEyeAuditor started (5am/5pm/11pm UTC, stagger 140s)")
    except Exception as tea_err:
        print(f"   ⚠️  TheEyeAuditor init failed: {tea_err}")

    # ── Login Auditor — 3x daily blind WebSocket login test ──
    _login_auditor = None
    try:
        from app.services.login_auditor import LoginAuditor
        _login_audit_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _login_auditor = LoginAuditor(
            db_pool=db_pool,
            notification_system=_login_audit_notify,
            app_state=app.state,
        )
        if not _is_clone: await _login_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.login_auditor = _login_auditor
        print("   ✅ LoginAuditor started (5am/5pm/11pm UTC, stagger 150s)")
    except Exception as la_err:
        print(f"   ⚠️  LoginAuditor init failed: {la_err}")

    # ── Client App Auditor — 3x daily client-facing endpoint trust scorecard ──
    _client_auditor = None
    try:
        from app.services.client_app_auditor import ClientAppAuditor
        _client_audit_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _client_auditor = ClientAppAuditor(
            db_pool=db_pool,
            notification_system=_client_audit_notify,
            app_state=app.state,
        )
        if not _is_clone: await _client_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.client_app_auditor = _client_auditor
        print("   ✅ ClientAppAuditor started (5am/5pm/11pm UTC, stagger 160s)")
    except Exception as caa_err:
        print(f"   ⚠️  ClientAppAuditor init failed: {caa_err}")

    # ── Coach & DOJO Auditor — 3x daily coach/DOJO endpoint trust scorecard ──
    _coach_dojo_auditor = None
    try:
        from app.services.coach_dojo_auditor import CoachDojoAuditor
        _cd_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _coach_dojo_auditor = CoachDojoAuditor(
            db_pool=db_pool, notification_system=_cd_notify, app_state=app.state,
        )
        if not _is_clone: await _coach_dojo_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.coach_dojo_auditor = _coach_dojo_auditor
        print("   ✅ CoachDojoAuditor started (5am/5pm/11pm UTC, stagger 170s)")
    except Exception as cd_err:
        print(f"   ⚠️  CoachDojoAuditor init failed: {cd_err}")

    # ── Billing Pipeline Auditor — 3x daily billing endpoint trust scorecard ──
    _billing_auditor = None
    try:
        from app.services.billing_auditor import BillingPipelineAuditor
        _ba_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _billing_auditor = BillingPipelineAuditor(
            db_pool=db_pool, notification_system=_ba_notify, app_state=app.state,
        )
        if not _is_clone: await _billing_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.billing_auditor = _billing_auditor
        print("   ✅ BillingPipelineAuditor started (5am/5pm/11pm UTC, stagger 180s)")
    except Exception as ba_err:
        print(f"   ⚠️  BillingPipelineAuditor init failed: {ba_err}")

    # ── Defense Health Auditor — 3x daily defense subsystem trust scorecard ──
    _defense_auditor = None
    try:
        from app.services.defense_auditor import DefenseHealthAuditor
        _da_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _defense_auditor = DefenseHealthAuditor(
            db_pool=db_pool, notification_system=_da_notify, app_state=app.state,
        )
        if not _is_clone: await _defense_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.defense_auditor = _defense_auditor
        print("   ✅ DefenseHealthAuditor started (5am/5pm/11pm UTC, stagger 190s)")
    except Exception as da_err:
        print(f"   ⚠️  DefenseHealthAuditor init failed: {da_err}")

    # ── AI Pipeline Auditor — 3x daily Azure OpenAI/TTS/Nevedal trust scorecard ──
    _ai_pipeline_auditor = None
    try:
        from app.services.ai_pipeline_auditor import AIPipelineAuditor
        _ap_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _ai_pipeline_auditor = AIPipelineAuditor(
            db_pool=db_pool, notification_system=_ap_notify, app_state=app.state,
        )
        if not _is_clone: await _ai_pipeline_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.ai_pipeline_auditor = _ai_pipeline_auditor
        print("   ✅ AIPipelineAuditor started (5am/5pm/11pm UTC, stagger 200s)")
    except Exception as ap_err:
        print(f"   ⚠️  AIPipelineAuditor init failed: {ap_err}")

    # ── WebSocket Flow Auditor — 3x daily WS flow trust scorecard ──
    _ws_flow_auditor = None
    try:
        from app.services.ws_flow_auditor import WebSocketFlowAuditor
        _wf_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _ws_flow_auditor = WebSocketFlowAuditor(
            db_pool=db_pool, notification_system=_wf_notify, app_state=app.state,
        )
        if not _is_clone: await _ws_flow_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.ws_flow_auditor = _ws_flow_auditor
        print("   ✅ WebSocketFlowAuditor started (5am/5pm/11pm UTC, stagger 210s)")
    except Exception as wf_err:
        print(f"   ⚠️  WebSocketFlowAuditor init failed: {wf_err}")

    # ── Tier Gating Auditor — 3x daily tier feature gate trust scorecard ──
    _tier_gating_auditor = None
    try:
        from app.services.tier_gating_auditor import TierGatingAuditor
        _tg_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _tier_gating_auditor = TierGatingAuditor(
            db_pool=db_pool, notification_system=_tg_notify, app_state=app.state,
        )
        if not _is_clone: await _tier_gating_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.tier_gating_auditor = _tier_gating_auditor
        print("   ✅ TierGatingAuditor started (5am/5pm/11pm UTC, stagger 220s)")
    except Exception as tg_err:
        print(f"   ⚠️  TierGatingAuditor init failed: {tg_err}")

    # ── Nevedal Research Lab Auditor — 3x daily Nevedal Lab endpoint trust scorecard ──
    _nevedal_lab_auditor = None
    try:
        from app.services.nevedal_lab_auditor import NevedalLabAuditor
        _nl_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _nevedal_lab_auditor = NevedalLabAuditor(
            db_pool=db_pool, notification_system=_nl_notify, app_state=app.state,
        )
        if not _is_clone: await _nevedal_lab_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.nevedal_lab_auditor = _nevedal_lab_auditor
        print("   ✅ NevedalLabAuditor started (5am/5pm/11pm UTC, stagger 230s)")
    except Exception as nl_err:
        print(f"   ⚠️  NevedalLabAuditor init failed: {nl_err}")

    # ── Hardware Security Auditor — 3x daily admin MFA posture trust scorecard ──
    _hw_security_auditor = None
    try:
        from app.services.hardware_security_auditor import HardwareSecurityAuditor
        _hs_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _hw_security_auditor = HardwareSecurityAuditor(
            db_pool=db_pool, notification_system=_hs_notify, app_state=app.state,
        )
        if not _is_clone: await _hw_security_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.hw_security_auditor = _hw_security_auditor
        print("   ✅ HardwareSecurityAuditor started (5am/5pm/11pm UTC, stagger 240s)")
    except Exception as hs_err:
        print(f"   ⚠️  HardwareSecurityAuditor init failed: {hs_err}")

    # ── System Integrity Auditor — preventive security/billing/sync checks ──
    _system_integrity_auditor = None
    try:
        from app.services.system_integrity_auditor import SystemIntegrityAuditor
        _si_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _system_integrity_auditor = SystemIntegrityAuditor(
            db_pool=db_pool, notification_system=_si_notify, app_state=app.state,
        )
        if not _is_clone: await _system_integrity_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.system_integrity_auditor = _system_integrity_auditor
        print("   ✅ SystemIntegrityAuditor started (5am/5pm/11pm UTC, stagger 250s)")
    except Exception as si_err:
        print(f"   ⚠️  SystemIntegrityAuditor init failed: {si_err}")

    # ── DOJO Session Auditor — 3x daily DOJO/Zoom session trust scorecard ──
    _dojo_session_auditor = None
    try:
        from app.services.dojo_session_auditor import DojoSessionAuditor
        _ds_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _dojo_session_auditor = DojoSessionAuditor(
            db_pool=db_pool, notification_system=_ds_notify, app_state=app.state,
        )
        if not _is_clone: await _dojo_session_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.dojo_session_auditor = _dojo_session_auditor
        print("   ✅ DojoSessionAuditor started (5am/5pm/11pm UTC, stagger 260s)")
    except Exception as ds_err:
        print(f"   ⚠️  DojoSessionAuditor init failed: {ds_err}")

    # ── Wisdom Pipeline Auditor — 3x daily knowledge learning loop trust scorecard ──
    _wisdom_pipeline_auditor = None
    try:
        from app.services.wisdom_pipeline_auditor import WisdomPipelineAuditor
        _wp_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _wisdom_pipeline_auditor = WisdomPipelineAuditor(
            db_pool=db_pool, notification_system=_wp_notify, app_state=app.state,
        )
        if not _is_clone: await _wisdom_pipeline_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.wisdom_pipeline_auditor = _wisdom_pipeline_auditor
        print("   ✅ WisdomPipelineAuditor started (5am/5pm/11pm UTC, stagger 270s)")
    except Exception as wp_err:
        print(f"   ⚠️  WisdomPipelineAuditor init failed: {wp_err}")

    # ── Settings Tab Auditor — 3x daily settings feature trust scorecard ──
    _settings_tab_auditor = None
    try:
        from app.services.settings_tab_auditor import SettingsTabAuditor
        _st_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _settings_tab_auditor = SettingsTabAuditor(
            db_pool=db_pool, notification_system=_st_notify, app_state=app.state,
        )
        if not _is_clone: await _settings_tab_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.settings_tab_auditor = _settings_tab_auditor
        print("   ✅ SettingsTabAuditor started (5am/5pm/11pm UTC, stagger 280s)")
    except Exception as st_err:
        print(f"   ⚠️  SettingsTabAuditor init failed: {st_err}")

    # ── Notification Observer — polls social engagement every 30min ──
    _notif_observer = None
    try:
        from app.services.notification_observer import NotificationObserver
        _no_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _notif_observer = NotificationObserver(
            db_pool=db_pool, notification_system=_no_notify, app_state=app.state,
        )
        await _notif_observer.start()
        app.state.notification_observer = _notif_observer
        print("   ✅ NotificationObserver started (every 30min, stagger 260s)")
    except Exception as no_err:
        print(f"   ⚠️  NotificationObserver init failed: {no_err}")

    # ── Sentinel Defense Orchestrator — House of Mirrors wiring ──
    _sentinel_orchestrator = None
    try:
        from app.services.security.sentinel_defense_orchestrator import SentinelDefenseOrchestrator
        from app.services.security.defcon_recon_reporter import DefconReconReporter

        _sdo_sase = getattr(app.state, "hive_v4", {}).get("sase_controller")
        _sdo_defcon = _hive_defense.get("defcon_controller") if _hive_defense else None
        _sdo_mirror = _hive_defense.get("mirror_shell") if _hive_defense else None
        _sdo_notify = getattr(app.state, "notification_system", None)
        _sdo_shield = None
        try:
            from app.services.security.admin_contact_shield import get_shield
            _sdo_shield = get_shield()
            if _sdo_notify:
                _sdo_shield.set_notification_system(_sdo_notify)
        except Exception as _shield_err:
            print(f"   ⚠️  AdminContactShield init failed: {_shield_err}")

        _sdo_recon = DefconReconReporter(db_pool=db_pool, notification_system=_sdo_notify)

        _sentinel_orchestrator = SentinelDefenseOrchestrator(
            db_pool=db_pool,
            sase_controller=_sdo_sase,
            defcon_controller=_sdo_defcon,
            mirror_shell=_sdo_mirror,
            notification_system=_sdo_notify,
            admin_contact_shield=_sdo_shield,
            recon_reporter=_sdo_recon,
        )
        app.state.sentinel_orchestrator = _sentinel_orchestrator

        _loaded_bans = await _sentinel_orchestrator.load_persistent_bans()
        print(f"   ✅ SentinelDefenseOrchestrator initialized ({_loaded_bans} persistent bans loaded)")
    except Exception as sdo_err:
        print(f"   ⚠️  SentinelDefenseOrchestrator init failed: {sdo_err}")

    # ── Community Mesh Engine — Nate-to-Nate group wisdom ──
    _community_mesh = None
    try:
        from app.services.community_mesh_engine import CommunityMeshEngine
        _cm_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
        _community_mesh = CommunityMeshEngine(
            db_pool=db_pool, notification_system=_cm_notify, app_state=app.state,
        )
        await _community_mesh.start()
        app.state.community_mesh_engine = _community_mesh
        print("   ✅ CommunityMeshEngine started (6h convergence, stagger 300s)")
    except Exception as cm_err:
        print(f"   ⚠️  CommunityMeshEngine init failed: {cm_err}")

    # ── Liminal Coaching Engine — external conversation coaching ──
    _liminal_engine = None
    try:
        from app.services.liminal_coaching_engine import LiminalCoachingEngine
        _liminal_engine = LiminalCoachingEngine(db_pool=db_pool, app_state=app.state)
        app.state.liminal_coaching_engine = _liminal_engine
        print("   ✅ LiminalCoachingEngine initialized")
    except Exception as lce_err:
        print(f"   ⚠️  LiminalCoachingEngine init failed: {lce_err}")

    # ── DOJO Mentor Engine — multi-DOJO AI mentorship ──
    _dojo_mentor = None
    try:
        from app.services.dojo_mentor_engine import DojoMentorEngine
        _dojo_mentor = DojoMentorEngine(db_pool=db_pool, app_state=app.state)
        app.state.dojo_mentor_engine = _dojo_mentor
        print("   ✅ DojoMentorEngine initialized")
    except Exception as dme_err:
        print(f"   ⚠️  DojoMentorEngine init failed: {dme_err}")

    # ── DOJO Mentor Zoom — Zoom meeting integration for mentored sessions ──
    _dojo_zoom = None
    try:
        from app.services.dojo_mentor_zoom import DojoMentorZoom
        _dojo_zoom = DojoMentorZoom(db_pool=db_pool, app_state=app.state)
        app.state.dojo_mentor_zoom = _dojo_zoom
        print("   ✅ DojoMentorZoom initialized")
    except Exception as dmz_err:
        print(f"   ⚠️  DojoMentorZoom init failed: {dmz_err}")

    # ── Coach Hierarchy Auditor — 16-check trust scorecard ──
    _coach_hierarchy_auditor = None
    try:
        from app.services.coach_hierarchy_auditor import CoachHierarchyAuditor
        _coach_hierarchy_auditor = CoachHierarchyAuditor(
            db_pool=db_pool,
            notification_system=_notify_sys if _token_renewal_agent else None,
            auth_token=os.environ.get("SKYEYE_AUDIT_TOKEN", ""),
            app_state=app.state,
        )
        if not _is_clone: await _coach_hierarchy_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.coach_hierarchy_auditor = _coach_hierarchy_auditor
        print("   ✅ CoachHierarchyAuditor started (3x daily, stagger 290s)")
    except Exception as cha_err:
        print(f"   ⚠️  CoachHierarchyAuditor init failed: {cha_err}")

    # ── Classroom Learning Auditor — classroom / lived-wisdom DB scorecard (15 checks)
    _classroom_learning_auditor = None
    try:
        from app.services.classroom_learning_auditor import ClassroomLearningAuditor
        _classroom_learning_auditor = ClassroomLearningAuditor(
            db_pool=db_pool,
            notification_system=_notify_sys if _token_renewal_agent else None,
            app_state=app.state,
        )
        if not _is_clone: await _classroom_learning_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.classroom_learning_auditor = _classroom_learning_auditor
        print("   ✅ ClassroomLearningAuditor started (3x daily, stagger 283s)")
    except Exception as _cla_err:
        print(f"   ⚠️  ClassroomLearningAuditor init failed: {_cla_err}")

    # ── Stance Loop Auditor — witness-loop regression DB scorecard (3 checks)  # QUANTUM-CRYSTAL-ARCH
    _stance_loop_auditor = None
    try:
        from app.services.stance_loop_auditor import StanceLoopAuditor
        _stance_loop_auditor = StanceLoopAuditor(
            db_pool=db_pool,
            notification_system=_notify_sys if _token_renewal_agent else None,
            app_state=app.state,
        )
        if not _is_clone: await _stance_loop_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.stance_loop_auditor = _stance_loop_auditor
        print("   ✅ StanceLoopAuditor started (3x daily, stagger 300s)")
    except Exception as _sla_err:
        print(f"   ⚠️  StanceLoopAuditor init failed: {_sla_err}")

    # ── Coaching Mesh Engine — BLE group training sessions ──
    _coaching_mesh = None
    try:
        from app.services.coaching_mesh_engine import CoachingMeshEngine
        _coaching_mesh = CoachingMeshEngine(db_pool=db_pool, app_state=app.state)
        app.state.coaching_mesh_engine = _coaching_mesh
        print("   ✅ CoachingMeshEngine initialized")
    except Exception as cme2_err:
        print(f"   ⚠️  CoachingMeshEngine init failed: {cme2_err}")

    # ── Call Coaching Engine — Twilio Media Stream processing ──
    _call_coaching = None
    try:
        from app.services.call_coaching_engine import CallCoachingEngine
        _call_coaching = CallCoachingEngine(db_pool=db_pool, app_state=app.state)
        app.state.call_coaching_engine = _call_coaching
        print("   ✅ CallCoachingEngine initialized")
    except Exception as cce_err:
        print(f"   ⚠️  CallCoachingEngine init failed: {cce_err}")

    # ── Trust Enforcer — Meta-agent enforcing 100% trust across all 16 auditors ──
    _trust_enforcer = None
    if _is_clone:
        # QUANTUM-CRYSTAL-ARCH — truthy sentinel so clone health stays NOMINAL
        _trust_enforcer = "skipped_clone"
        app.state.trust_enforcer = "skipped_clone"
        print("   ⏭️  TrustEnforcer skipped (clone mode)")
    else:
        try:
            from app.services.trust_enforcer import TrustEnforcer
            _te_notify = getattr(app.state, "notification_system", None) or (_notify_sys if _token_renewal_agent else None)
            _trust_enforcer = TrustEnforcer(
                db_pool=db_pool, notification_system=_te_notify, app_state=app.state,
                redis_url=_REDIS_URL_EARLY,
                redis_password=_REDIS_PW_EARLY,
            )
            await _trust_enforcer.start()
            app.state.trust_enforcer = _trust_enforcer
            print("   ✅ TrustEnforcer started (5:10am/5:10pm/11:10pm UTC, 10min stagger)")
        except Exception as te_err:
            print(f"   ⚠️  TrustEnforcer init failed: {te_err}")

    # ── Assessment Engine — AI-driven dynamic assessments for clients ──
    _assessment_engine = None
    try:
        from app.services.assessment_engine import AssessmentEngine
        _assessment_engine = AssessmentEngine(db_pool=db_pool)
        app.state.assessment_engine = _assessment_engine
        print("   ✅ AssessmentEngine initialized")
    except Exception as ae_err:
        print(f"   ⚠️  AssessmentEngine init failed: {ae_err}")

    # ── Liminal Presence Agents — protect Little Nate's voice and presence quality ──
    _silence_sentinel = None
    try:
        from app.services.silence_sentinel import SilenceSentinel
        _silence_sentinel = SilenceSentinel(db_pool=db_pool)
        await _silence_sentinel.start()
        app.state.silence_sentinel = _silence_sentinel
        print("   ✅ SilenceSentinel started (every 30min, stagger 290s)")
    except Exception as ss_err:
        print(f"   ⚠️  SilenceSentinel init failed: {ss_err}")

    _language_drift_monitor = None
    try:
        from app.services.language_drift_monitor import LanguageDriftMonitor
        _language_drift_monitor = LanguageDriftMonitor(db_pool=db_pool)
        await _language_drift_monitor.start()
        app.state.language_drift_monitor = _language_drift_monitor
        print("   ✅ LanguageDriftMonitor started (every 6h, stagger 300s)")
    except Exception as ldm_err:
        print(f"   ⚠️  LanguageDriftMonitor init failed: {ldm_err}")

    _field_response_parser = None
    try:
        from app.services.field_response_parser import FieldResponseParser
        _field_response_parser = FieldResponseParser(db_pool=db_pool)
        await _field_response_parser.start()
        app.state.field_response_parser = _field_response_parser
        print("   ✅ FieldResponseParser started (every 2h, stagger 310s)")
    except Exception as frp_err:
        print(f"   ⚠️  FieldResponseParser init failed: {frp_err}")

    _liminal_presence_auditor = None
    try:
        from app.services.liminal_presence_auditor import LiminalPresenceAuditor
        _liminal_presence_auditor = LiminalPresenceAuditor(
            db_pool=db_pool, app_state=app.state,
        )
        if not _is_clone: await _liminal_presence_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.liminal_presence_auditor = _liminal_presence_auditor
        print("   ✅ LiminalPresenceAuditor started (3x daily, stagger 320s)")
    except Exception as lpa_err:
        print(f"   ⚠️  LiminalPresenceAuditor init failed: {lpa_err}")

    _pmb_auditor = None
    try:
        from app.services.pmb_command_center_auditor import PmbCommandCenterAuditor
        _pmb_auditor = PmbCommandCenterAuditor(
            db_pool=db_pool, app_state=app.state,
        )
        if not _is_clone: await _pmb_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.pmb_command_center_auditor = _pmb_auditor
        print("   ✅ PmbCommandCenterAuditor started (3x daily, stagger 110s)")
    except Exception as pmb_err:
        print(f"   ⚠️  PmbCommandCenterAuditor init failed: {pmb_err}")

    _data_uniformity_tracer = None
    try:
        from app.services.data_uniformity_tracer import DataUniformityTracer
        _data_uniformity_tracer = DataUniformityTracer(
            db_pool=db_pool, app_state=app.state,
        )
        if not _is_clone: await _data_uniformity_tracer.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.data_uniformity_tracer = _data_uniformity_tracer
        print("   ✅ DataUniformityTracer started (3x daily, stagger 300s)")
    except Exception as dut_err:
        print(f"   ⚠️  DataUniformityTracer init failed: {dut_err}")

    _token_lab_auditor = None
    try:
        from app.services.token_lab_auditor import TokenLabAuditor
        _token_lab_auditor = TokenLabAuditor(
            db_pool=db_pool,
            notification_system=None,
            auth_token=os.environ.get("SKYEYE_AUDIT_TOKEN", ""),
            app_state=app.state,
        )
        if not _is_clone: await _token_lab_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.token_lab_auditor = _token_lab_auditor
        print("   ✅ TokenLabAuditor started (3x daily, stagger 100s)")
    except Exception as tla_err:
        print(f"   ⚠️  TokenLabAuditor init failed: {tla_err}")

    # ── GKM Ministry Auditor — 3x daily GKM endpoint trust scorecard ──
    _gkm_auditor = None
    try:
        from app.services.gkm_auditor import GkmAuditor
        _gkm_auditor = GkmAuditor(
            db_pool=db_pool,
            notification_system=None,
            auth_token=os.environ.get("SKYEYE_AUDIT_TOKEN", ""),
            app_state=app.state,
        )
        if not _is_clone: await _gkm_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.gkm_auditor = _gkm_auditor
        print("   ✅ GkmAuditor started (3x daily, stagger 110s)")
    except Exception as gkm_err:
        print(f"   ⚠️  GkmAuditor init failed: {gkm_err}")

    # ── Nate Check-In Auditor — 3x daily check-in system trust scorecard ──
    _nate_checkin_auditor = None
    try:
        from app.services.nate_checkin_auditor import NateCheckInAuditor
        _nate_checkin_auditor = NateCheckInAuditor(
            db_pool=db_pool,
            notification_system=None,
            app_state=app.state,
        )
        if not _is_clone: await _nate_checkin_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.nate_checkin_auditor = _nate_checkin_auditor
        print("   ✅ NateCheckInAuditor started (3x daily, stagger 330s)")
    except Exception as nca_err:
        print(f"   ⚠️  NateCheckInAuditor init failed: {nca_err}")

    # QUANTUM-CRYSTAL-ARCH: High-risk occupational crisis auditor (8 checks)
    _high_risk_crisis_auditor = None
    try:
        from app.services.high_risk_crisis_auditor import HighRiskCrisisAuditor
        _high_risk_crisis_auditor = HighRiskCrisisAuditor(
            db_pool=db_pool, redis_url=_REDIS_URL_EARLY, app_state=app.state,
        )
        if not _is_clone:
            await _high_risk_crisis_auditor.start()
        app.state.high_risk_crisis_auditor = _high_risk_crisis_auditor
        print("   ✅ HighRiskCrisisAuditor started (stagger 298s)")
    except Exception as _hrc_err:
        print(f"   ⚠️  HighRiskCrisisAuditor init failed: {_hrc_err}")

    # ── Sensitive Bridge Auditor — 3x daily v1.3 contract surface scorecard ──
    _sensitive_bridge_auditor = None
    try:
        from app.services.sensitive_bridge_auditor import SensitiveBridgeAuditor
        _sensitive_bridge_auditor = SensitiveBridgeAuditor(
            db_pool=db_pool,
            notification_system=None,
            app_state=app.state,
        )
        if not _is_clone: await _sensitive_bridge_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.sensitive_bridge_auditor = _sensitive_bridge_auditor
        print("   ✅ SensitiveBridgeAuditor started (3x daily, stagger 300s)")
    except Exception as sba_err:
        print(f"   ⚠️  SensitiveBridgeAuditor init failed: {sba_err}")

    # ── Sensitive Bridge Telemetry Agent — auto-disable trigger w/ Note 1 safeguards
    # Plan v1.3 Phase 5 Note 1: ships PAUSED (app_settings.paused=true). The
    # 30-minute admin-override countdown + multi-window agreement (24h/72h/7d)
    # + resolved-telemetry re-enable gate live in the agent + REST router.
    _sensitive_bridge_telemetry_agent = None
    try:
        from app.services.sensitive_bridge_telemetry_agent import (
            SensitiveBridgeTelemetryAgent,
        )
        _telem_notify = getattr(app.state, "notification_system", None)
        _sensitive_bridge_telemetry_agent = SensitiveBridgeTelemetryAgent(
            db_pool=db_pool,
            notification_system=_telem_notify,
            app_state=app.state,
        )
        await _sensitive_bridge_telemetry_agent.start()
        app.state.sensitive_bridge_telemetry_agent = (
            _sensitive_bridge_telemetry_agent
        )
        print(
            "   ✅ SensitiveBridgeTelemetryAgent started "
            "(PAUSED by default; admin must unpause via app_settings)"
        )
    except Exception as sbt_err:
        print(f"   ⚠️  SensitiveBridgeTelemetryAgent init failed: {sbt_err}")

    # ── Token Usage Agent — daily/monthly reset, per-source snapshots ──
    _token_usage_agent = None
    try:
        from app.services.token_usage_agent import TokenUsageAgent
        _token_usage_agent = TokenUsageAgent(
            db_pool=db_pool, app_state=app.state,
        )
        await _token_usage_agent.start()
        app.state.token_usage_agent = _token_usage_agent
        print("   ✅ TokenUsageAgent started (30min cycle, daily/monthly reset)")
    except Exception as tua_err:
        print(f"   ⚠️  TokenUsageAgent init failed: {tua_err}")

    # QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch (feature-flagged)
    _newsletter_agent = None
    _newsletter_auditor = None
    try:
        from app.services.newsletter_agent import (
            NewsletterAgent,
            newsletter_enabled,
            newsletter_learning_enabled,
        )
        from app.services.newsletter_auditor import NewsletterAuditor
        _newsletter_agent = NewsletterAgent(db_pool=db_pool, app_state=app.state)
        # QUANTUM-CRYSTAL-ARCH — start for compose and/or +72h learning
        if (newsletter_enabled() or newsletter_learning_enabled()) and not _is_clone:
            await _newsletter_agent.start()
        app.state.newsletter_agent = _newsletter_agent
        _newsletter_auditor = NewsletterAuditor(
            db_pool=db_pool,
            notification_system=getattr(app.state, "notification_system", None),
            auth_token=os.environ.get("SKYEYE_AUDIT_TOKEN", ""),
            app_state=app.state,
        )
        if not _is_clone:
            await _newsletter_auditor.start()
        app.state.newsletter_auditor = _newsletter_auditor
        print(
            "   ✅ NewsletterAgent/Auditor ready "
            f"(compose={newsletter_enabled()} learning={newsletter_learning_enabled()})"
        )
    except Exception as _nl_err:
        print(f"   ⚠️  Newsletter init failed: {_nl_err}")

    # ── Account Event Reconciler — flags orphaned user INSERTs (no email path) ──
    # Feature-flagged via ENABLE_USER_CREATION_HOOK (default OFF). Even when
    # the flag is off the agent loop runs but is a no-op, so the service-health
    # registration is stable across the rollout.
    _account_event_reconciler = None
    try:
        from app.services.account_event_reconciler import AccountEventReconciler
        _account_event_reconciler = AccountEventReconciler(
            db_pool=db_pool,
            notification_system=getattr(app.state, "notification_system", None),
        )
        await _account_event_reconciler.start()
        app.state.account_event_reconciler = _account_event_reconciler
        print("   ✅ AccountEventReconciler started (60s cycle, support@ orphan alerts)")
    except Exception as aer_err:
        print(f"   ⚠️  AccountEventReconciler init failed: {aer_err}")

    # QUANTUM-CRYSTAL-ARCH — CLI Dual-COO Chief + gated crystal outcome apply
    _cli_task_bus_consumer = None
    try:
        from app.services.cli_task_bus_consumer import CliTaskBusConsumer
        _cli_task_bus_consumer = CliTaskBusConsumer(app_state=app.state)
        await _cli_task_bus_consumer.start()
        app.state.cli_task_bus_consumer = _cli_task_bus_consumer
        print("   ✅ CliTaskBusConsumer started (Dual-COO Chief of Staff)")
    except Exception as _ctbc_err:
        print(f"   ⚠️  CliTaskBusConsumer init failed: {_ctbc_err}")

    _crystal_outcome_apply = None
    try:
        from app.services.crystal_outcome_apply import CrystalOutcomeApplyAgent
        _crystal_outcome_apply = CrystalOutcomeApplyAgent(db_pool, app_state=app.state)
        await _crystal_outcome_apply.start()
        app.state.crystal_outcome_apply = _crystal_outcome_apply
        print("   ✅ CrystalOutcomeApplyAgent started (GREEN domains only)")
    except Exception as _coa_err:
        print(f"   ⚠️  CrystalOutcomeApplyAgent init failed: {_coa_err}")

    # QUANTUM-CRYSTAL-ARCH — Dual-COO loop closer (briefs/prior-art/compliance/failover)
    _dual_coo_loop_closer = None
    try:
        from app.services.dual_coo_loop_closer import DualCooLoopCloser
        _dual_coo_loop_closer = DualCooLoopCloser(db_pool, app_state=app.state)
        await _dual_coo_loop_closer.start()
        app.state.dual_coo_loop_closer = _dual_coo_loop_closer
        print("   ✅ DualCooLoopCloser started (close-the-loop cycles)")
    except Exception as _dcl_err:
        print(f"   ⚠️  DualCooLoopCloser init failed: {_dcl_err}")

    # QUANTUM-CRYSTAL-ARCH — Six-Quotient Battery (weekly / admin trigger; flag-gated)
    _six_q_battery_agent = None
    try:
        from app.services.six_quotient_battery_agent import SixQuotientBatteryAgent
        _six_q_battery_agent = SixQuotientBatteryAgent(db_pool, app_state=app.state)
        await _six_q_battery_agent.start()
        app.state.six_quotient_battery_agent = _six_q_battery_agent
        print("   ✅ SixQuotientBatteryAgent started (ENABLE_SIX_QUOTIENT_BATTERY)")
    except Exception as _sqb_err:
        print(f"   ⚠️  SixQuotientBatteryAgent init failed: {_sqb_err}")

    # QUANTUM-CRYSTAL-ARCH — Six-Quotient Standards Index (allowlisted professional feeds)
    _six_q_standards = None
    try:
        from app.services.six_quotient_standards_index import SixQuotientStandardsIndex
        _six_q_standards = SixQuotientStandardsIndex(db_pool, app_state=app.state)
        await _six_q_standards.start()
        app.state.six_quotient_standards_index = _six_q_standards
        print("   ✅ SixQuotientStandardsIndex started (ENABLE_SIX_QUOTIENT_STANDARDS_INDEX)")
    except Exception as _sqs_err:
        print(f"   ⚠️  SixQuotientStandardsIndex init failed: {_sqs_err}")

    # QUANTUM-CRYSTAL-ARCH — Six-Quotient Battery Auditor (12 checks, stagger 298s)
    _six_q_battery_auditor = None
    try:
        from app.services.six_quotient_battery_auditor import SixQuotientBatteryAuditor
        _six_q_battery_auditor = SixQuotientBatteryAuditor(
            db_pool,
            notification_system=getattr(app.state, "notification_system", None),
            app_state=app.state,
        )
        if not _is_clone:
            await _six_q_battery_auditor.start()
        app.state.six_quotient_battery_auditor = _six_q_battery_auditor
        print("   ✅ SixQuotientBatteryAuditor started")
    except Exception as _sqba_err:
        print(f"   ⚠️  SixQuotientBatteryAuditor init failed: {_sqba_err}")

    # QUANTUM-CRYSTAL-ARCH — bi-weekly self-dev proposals → CEO YELLOW inbox
    _six_q_self_dev_agent = None
    try:
        from app.services.six_quotient_self_development_agent import (
            SixQuotientSelfDevelopmentAgent,
        )
        _six_q_self_dev_agent = SixQuotientSelfDevelopmentAgent(db_pool, app_state=app.state)
        await _six_q_self_dev_agent.start()
        app.state.six_quotient_self_dev_agent = _six_q_self_dev_agent
        print("   ✅ SixQuotientSelfDevelopmentAgent started (ENABLE_SIX_QUOTIENT_SELF_DEV)")
    except Exception as _sqsd_err:
        print(f"   ⚠️  SixQuotientSelfDevelopmentAgent init failed: {_sqsd_err}")

    # QUANTUM-CRYSTAL-ARCH — LN Sandbox DOJO (clinical + engineering practice; no auto-promote)
    _ln_sandbox_engine = None
    try:
        from app.services.ln_sandbox_engine import LNSandboxEngine
        _ln_sandbox_engine = LNSandboxEngine(db_pool, app_state=app.state)
        await _ln_sandbox_engine.start()
        app.state.ln_sandbox_engine = _ln_sandbox_engine
        print("   ✅ LNSandboxEngine started (ENABLE_LN_SANDBOX)")
    except Exception as _ln_sb_err:
        print(f"   ⚠️  LNSandboxEngine init failed: {_ln_sb_err}")

    # QUANTUM-CRYSTAL-ARCH — LN Sandbox auditor (8 checks, stagger 287s)
    _ln_sandbox_auditor = None
    try:
        from app.services.ln_sandbox_auditor import LNSandboxAuditor
        _ln_sandbox_auditor = LNSandboxAuditor(
            db_pool,
            auth_token=os.environ.get("SKYEYE_AUDIT_TOKEN", ""),
            app_state=app.state,
        )
        if not _is_clone:
            await _ln_sandbox_auditor.start()
        app.state.ln_sandbox_auditor = _ln_sandbox_auditor
        print("   ✅ LNSandboxAuditor started (3x daily, stagger 287s)")
    except Exception as _ln_sba_err:
        print(f"   ⚠️  LNSandboxAuditor init failed: {_ln_sba_err}")

    # QUANTUM-CRYSTAL-ARCH — LN-Observer auditor (11 checks, stagger 289s)
    _ln_observer_auditor = None
    try:
        from app.services.ln_observer_auditor import LNObserverAuditor
        _ln_observer_auditor = LNObserverAuditor(
            db_pool,
            auth_token=os.environ.get("SKYEYE_AUDIT_TOKEN", ""),
            app_state=app.state,
        )
        if not _is_clone:
            await _ln_observer_auditor.start()
        app.state.ln_observer_auditor = _ln_observer_auditor
        print("   ✅ LNObserverAuditor started (3x daily, stagger 289s)")
    except Exception as _ln_oa_err:
        print(f"   ⚠️  LNObserverAuditor init failed: {_ln_oa_err}")

    # ── Nate Check-In Agent — 72h inactivity outreach for clients + coaches ──
    _nate_checkin_agent = None
    try:
        from app.services.nate_checkin_agent import NateCheckInAgent
        _checkin_notify = getattr(app.state, "notification_system", None)
        if _checkin_notify is None:
            from app.websocket.notification_system import NotificationSystem
            _checkin_notify = NotificationSystem(
                data_dir=os.environ.get("DATA_DIR", "/app/data"),
                sendgrid_key=os.environ.get("SENDGRID_API_KEY"),
            )
            app.state.notification_system = _checkin_notify
        _nate_checkin_agent = NateCheckInAgent(
            db_pool=db_pool,
            notification_system=_checkin_notify,
            app_state=app.state,
        )
        await _nate_checkin_agent.start()
        app.state.nate_checkin_agent = _nate_checkin_agent
        print("   ✅ NateCheckInAgent started (30min cycle, stagger 310s)")
    except Exception as nca_err:
        print(f"   ⚠️  NateCheckInAgent init failed: {nca_err}")

    # QUANTUM-CRYSTAL-ARCH — PGSDHeartbeatAgent (nightly baseline, primary-only)
    _pgsd_heartbeat_agent = None
    try:
        from app.services.pgsd_heartbeat_agent import PGSDHeartbeatAgent

        _pgsd_redis = getattr(app.state, "redis", None) or getattr(app.state, "redis_client", None)
        _pgsd_heartbeat_agent = PGSDHeartbeatAgent(
            db_pool=db_pool,
            redis_client=_pgsd_redis,
            app_state=app.state,
        )
        await _pgsd_heartbeat_agent.start()
        app.state.pgsd_heartbeat_agent = _pgsd_heartbeat_agent
        print("   ✅ PGSDHeartbeatAgent registered (ENABLE_PGSD_HEARTBEAT)")
    except Exception as _pgsd_hb_err:
        print(f"   ⚠️  PGSDHeartbeatAgent init failed: {_pgsd_hb_err}")

    # QUANTUM-CRYSTAL-ARCH — PGSD ACCESS/FIELD service handles (optional constructs)
    _pgsd_discernment_scorer = None
    _pgsd_field_engine = None
    try:
        if os.environ.get("PGSD_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"):
            from app.services.pgsd_discernment_scorer import PGSDDiscernmentScorer
            from app.services.pgsd_field_engine import PGSDFieldEngine

            _pgsd_discernment_scorer = PGSDDiscernmentScorer(db_pool=db_pool)
            _pgsd_field_engine = PGSDFieldEngine(db_pool=db_pool)
            app.state.pgsd_discernment_scorer = _pgsd_discernment_scorer
            app.state.pgsd_field_engine = _pgsd_field_engine
            print("   ✅ PGSD discernment + field engines registered")
    except Exception as _pgsd_svc_err:
        print(f"   ⚠️  PGSD ACCESS/FIELD services init failed: {_pgsd_svc_err}")

    # QUANTUM-CRYSTAL-ARCH: Nate Commitment Agent — proactive commitment touches (Phase 1)
    _nate_commitment_agent = None
    try:
        from app.services.nate_commitment_agent import (
            NateCommitmentAgent,
            publish_commitment_touch_fanout,
        )

        async def _commitment_ws_push(hw_id: str, payload: dict):
            body = dict(payload or {})
            body.setdefault("hardware_id", hw_id)
            await publish_commitment_touch_fanout(body)

        app.state.commitment_ws_push = _commitment_ws_push
        _nate_commitment_agent = NateCommitmentAgent(
            db_pool=db_pool,
            notification_system=getattr(app.state, "notification_system", None),
            app_state=app.state,
        )
        await _nate_commitment_agent.start()
        app.state.nate_commitment_agent = _nate_commitment_agent
        print("   ✅ NateCommitmentAgent registered (30min cycle, stagger 320s)")
    except Exception as ncm_err:
        print(f"   ⚠️  NateCommitmentAgent init failed: {ncm_err}")

    # QUANTUM-CRYSTAL-ARCH: Nate Self-Monitor Agent — daily engagement trends (Phase 4)
    _nate_self_monitor_agent = None
    try:
        from app.services.nate_self_monitor_agent import NateSelfMonitorAgent
        _nate_self_monitor_agent = NateSelfMonitorAgent(db_pool=db_pool, app_state=app.state)
        await _nate_self_monitor_agent.start()
        app.state.nate_self_monitor_agent = _nate_self_monitor_agent
        print("   ✅ NateSelfMonitorAgent registered (daily cycle, stagger 330s)")
    except Exception as nsm_err:
        print(f"   ⚠️  NateSelfMonitorAgent init failed: {nsm_err}")

    # ── F-Code Engine — ICD-10-CM suggestion service (request-response, no background loop) ──
    _fcode_engine = None
    try:
        from app.services.fcode_engine import FCodeEngine
        _fcode_engine = FCodeEngine(db_pool=db_pool)
        app.state.fcode_engine = _fcode_engine
        print("   ✅ FCodeEngine initialized")
    except Exception as fce_err:
        print(f"   ⚠️  FCodeEngine init failed: {fce_err}")

    # ── Session Payment Agent — 72h advance payment collection ──
    _session_payment_agent = None
    try:
        from app.services.session_payment_agent import SessionPaymentAgent
        _session_payment_agent = SessionPaymentAgent(db_pool=db_pool, app_state=app.state)
        await _session_payment_agent.start()
        app.state.session_payment_agent = _session_payment_agent
        print("   ✅ SessionPaymentAgent started (30min cycle)")
    except Exception as spa_err:
        print(f"   ⚠️  SessionPaymentAgent init failed: {spa_err}")

    # ── Signup Sharing Agent — daily revenue sharing calculation ──
    _signup_sharing_agent = None
    try:
        from app.services.signup_sharing_agent import SignupSharingAgent
        _signup_sharing_agent = SignupSharingAgent(db_pool=db_pool, app_state=app.state)
        await _signup_sharing_agent.start()
        app.state.signup_sharing_agent = _signup_sharing_agent
        print("   ✅ SignupSharingAgent started (daily at 2AM UTC)")
    except Exception as ssa_err:
        print(f"   ⚠️  SignupSharingAgent init failed: {ssa_err}")

    # ── QuickBooks Sync Agent — syncs financial data to QB Online every 6h ──
    _qb_sync_agent = None
    try:
        from app.services.quickbooks_sync_agent import QuickBooksSyncAgent
        _qb_sync_agent = QuickBooksSyncAgent(db_pool=db_pool, app_state=app.state)
        await _qb_sync_agent.start()
        app.state.quickbooks_sync_agent = _qb_sync_agent
        print("   ✅ QuickBooksSyncAgent started (6h cycle)")
    except Exception as qb_err:
        print(f"   ⚠️  QuickBooksSyncAgent init failed: {qb_err}")

    # ── Google Calendar Sync Agent — pulls Google events every 5 min for all connected users ──
    _google_calendar_sync_agent = None
    try:
        from app.services.google_calendar_sync_agent import GoogleCalendarSyncAgent
        _google_calendar_sync_agent = GoogleCalendarSyncAgent(db_pool=db_pool, app_state=app.state)
        await _google_calendar_sync_agent.start()
        app.state.google_calendar_sync_agent = _google_calendar_sync_agent
        print("   ✅ GoogleCalendarSyncAgent started (5min cycle)")
    except Exception as gcsa_err:
        print(f"   ⚠️  GoogleCalendarSyncAgent init failed: {gcsa_err}")

    # ── QuickBooks Auditor — 3x daily 10-check trust scorecard ──
    _qb_auditor = None
    try:
        from app.services.quickbooks_auditor import QuickBooksAuditor
        _qb_auditor = QuickBooksAuditor(db_pool=db_pool, app_state=app.state)
        if not _is_clone: await _qb_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.quickbooks_auditor = _qb_auditor
        print("   ✅ QuickBooksAuditor started (stagger 105s)")
    except Exception as qba_err:
        print(f"   ⚠️  QuickBooksAuditor init failed: {qba_err}")

    # ── Corporate Command Auditor — 3x daily 12-check trust scorecard ──
    _corp_auditor = None
    try:
        from app.services.corporate_command_auditor import CorporateCommandAuditor
        _corp_auditor = CorporateCommandAuditor(db_pool=db_pool, app_state=app.state)
        if not _is_clone: await _corp_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.corporate_command_auditor = _corp_auditor
        print("   ✅ CorporateCommandAuditor started (stagger 115s)")
    except Exception as cca_err:
        print(f"   ⚠️  CorporateCommandAuditor init failed: {cca_err}")

    # ── Six-Quotient Growth Engine — lived wisdom measurement + crystal learning ── # QUANTUM-CRYSTAL-ARCH
    _growth_engine = None
    try:
        from app.services.six_quotient_growth_engine import SixQuotientGrowthEngine
        _growth_engine = SixQuotientGrowthEngine(db_pool)
        await _growth_engine.start()
        app.state.six_quotient_growth_engine = _growth_engine
        print("   ✅ Six-Quotient Growth Engine started (6h synthesis, per-interaction assessment)")
    except Exception as sqg_err:
        print(f"   ⚠️  Six-Quotient Growth Engine init failed: {sqg_err}")

    # ── Insight Accumulator — unifies all wisdom sources into coherent intelligence ──
    _insight_accumulator = None
    try:
        from app.services.insight_accumulator import InsightAccumulator
        _insight_accumulator = InsightAccumulator(db_pool)
        await _insight_accumulator.start()
        app.state.insight_accumulator = _insight_accumulator
        print("   ✅ Insight Accumulator started (1h synthesis, daily reflection)")
    except Exception as ia_err:
        print(f"   ⚠️  Insight Accumulator init failed: {ia_err}")

    # ── Web Content Reader — Little Nate reads external articles ──
    _web_reader = None
    try:
        from app.services.web_content_reader import WebContentReader
        _web_reader = WebContentReader(db_pool)
        await _web_reader.start()
        app.state.web_content_reader = _web_reader
        print("   ✅ Web Content Reader started (6 feeds, 4h cycle)")
    except Exception as wr_err:
        print(f"   ⚠️  Web Content Reader init failed: {wr_err}")

    # ── Register SKYEYE_AUDIT_TOKEN in Redis for auditor auth ──
    # Uses _REDIS_URL_EARLY captured at module scope before load_dotenv clobbers it.
    _audit_token = os.environ.get("SKYEYE_AUDIT_TOKEN", "")
    if _audit_token:
        try:
            import redis as _sync_redis
            if _REDIS_URL_EARLY:
                _audit_r = _sync_redis.from_url(
                    _REDIS_URL_EARLY, decode_responses=True,
                    socket_connect_timeout=10, socket_timeout=10,
                )
            else:
                _audit_r = _sync_redis.Redis(
                    host=_REDIS_HOST_EARLY,
                    port=int(os.environ.get("REDIS_PORT", "6379")),
                    password=_REDIS_PW_EARLY or None,
                    decode_responses=True,
                    socket_connect_timeout=10, socket_timeout=10,
                )
            _env = os.environ.get("ENVIRONMENT", "production")
            _audit_key = f"nate:{_env}:auth:{_audit_token}"
            _audit_profile = json.dumps({
                "role": "ADMIN",
                "name": "DrNevedal1",
                "username": "DrNevedal1",
                "hardware_id": "ADMIN_DRNEVEDAL1_ID",
                "email": "admin_nevedalnj@sovereignsanctuary.net",
                "is_audit_token": True,
            })
            _audit_r.setex(_audit_key, 86400 * 365, _audit_profile)
            _audit_r.close()
            print("   ✅ SKYEYE_AUDIT_TOKEN registered in Redis (365-day TTL)")
        except Exception as _at_err:
            print(f"   ⚠️  SKYEYE_AUDIT_TOKEN registration failed: {_at_err}")
    else:
        print("   ⚠️  SKYEYE_AUDIT_TOKEN not set — auditors will fall back to Redis scan")

    # QUANTUM-CRYSTAL-ARCH: optional orchestrator wiring (feature-flagged)
    _quantum_orchestrator = None
    # QUANTUM-CRYSTAL-ARCH: fail-closed fallback — a renamed/missing settings
    # attribute must never silently activate a dormant system in production.
    if getattr(settings, "ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR", False):
        try:
            from app.services.quantum_crystal_orchestrator import QuantumCrystalOrchestrator
            _quantum_orchestrator = QuantumCrystalOrchestrator(db_pool=db_pool)
            app.state.quantum_crystal_orchestrator = _quantum_orchestrator
            # QUANTUM-CRYSTAL-ARCH: fail-closed fallback (see above)
            if getattr(settings, "ENABLE_TIME_CRYSTAL_FORGE", False):
                await _quantum_orchestrator.start_forge_scheduler()
            print("   ✅ QuantumCrystalOrchestrator initialized")
        except Exception as _qc_err:
            print(f"   ⚠️  QuantumCrystalOrchestrator init failed: {_qc_err}")

    # QUANTUM-CRYSTAL-ARCH: inference router on app.state — CrystalGraph meta-crystal
    # synthesis reads app.state.inference_router; without it synthesis silently falls
    # back to a template instead of calling a model.
    if not getattr(app.state, "inference_router", None):
        try:
            from app.services.nate_inference_router import NateInferenceRouter
            app.state.inference_router = NateInferenceRouter(app_state=app.state)
            print("   ✅ NateInferenceRouter on app.state")
        except Exception as _ir_err:
            print(f"   ⚠️  NateInferenceRouter init failed: {_ir_err}")

    # QUANTUM-CRYSTAL-ARCH: Vectorize metadata indexes are required for native
    # user_id filtering. Not retroactive — create indexes, then re-upsert a cap
    # of crystals so nate-wisdom becomes filterable. Post-filter fallback covers
    # the gap until reindex finishes (see DEFECT_MEMO_VECTORIZE_METADATA_FILTER).
    try:
        from app.services import vectorize_service as _vz_meta
        if _vz_meta.is_vectorize_configured():
            async def _vectorize_metadata_bootstrap():
                try:
                    report = await _vz_meta.ensure_metadata_indexes()
                    missing = [k for k, v in report.items() if not v.get("ok")]
                    ok_n = len(report) - len(missing)
                    print(f"   ✅ Vectorize metadata indexes: {ok_n}/{len(report)} indexes ready")
                    if missing:
                        logger.warning("Vectorize metadata indexes incomplete: %s", missing)
                    if db_pool:
                        _lim = int(os.getenv("CRYSTAL_GRAPH_MAX_EDGE_NODES", "20000") or 20000)
                        stats = await _vz_meta.reindex_wisdom_crystals(db_pool, limit=_lim)
                        print(
                            f"   ✅ Vectorize crystal reindex: "
                            f"{stats.get('upserted', 0)}/{stats.get('selected', 0)} upserted"
                        )
                except Exception as _vz_boot_err:
                    logger.warning("Vectorize metadata bootstrap failed: %s", _vz_boot_err)

            asyncio.create_task(_vectorize_metadata_bootstrap())
            print("   ✅ Vectorize metadata bootstrap scheduled")
    except Exception as _vz_meta_err:
        print(f"   ⚠️  Vectorize metadata bootstrap failed: {_vz_meta_err}")

    # QUANTUM-CRYSTAL-ARCH: CrystalGraph — relationship edges + meta-crystal synthesis
    _crystal_graph = None
    if db_pool and getattr(settings, "ENABLE_CRYSTAL_GRAPH", False):
        try:
            from app.services.crystal_graph import CrystalGraph
            _crystal_graph = CrystalGraph(db_pool=db_pool, app_state=app.state)
            app.state.crystal_graph = _crystal_graph

            async def _crystal_graph_rebuild_loop():
                # Wait for metadata bootstrap + partial reindex before first rebuild.
                await asyncio.sleep(300)
                while True:
                    try:
                        await _crystal_graph.rebuild()
                    except Exception as _cg_err:
                        logger.warning("CrystalGraph rebuild failed: %s", _cg_err)
                    await asyncio.sleep(4 * 3600)

            asyncio.create_task(_crystal_graph_rebuild_loop())
            print("   ✅ CrystalGraph initialized (rebuild every 4h)")
        except Exception as _cg_err:
            print(f"   ⚠️  CrystalGraph init failed: {_cg_err}")

    # QUANTUM-CRYSTAL-ARCH: wire cognitive stack services (Gaps 6/7/9)
    try:
        from app.services.nate_memory_crystallizer import NateMemoryCrystallizer
        from app.services.helix_orchestrator import HelixOrchestrator
        from app.services.littlenate_inference import LittleNateInference
        app.state.nate_memory_crystallizer = NateMemoryCrystallizer(db_pool=db_pool, app_state=app.state)
        # SOVEREIGN-VOICE: ODPE engine + L1 taxonomy wiring
        _odpe = None
        try:
            from app.services.odpe_engine import ODPEEngine
            from app.services.odpe_l1_taxonomy import ODPEL1Taxonomy
            _odpe = ODPEEngine(db_pool=db_pool)
            app.state.odpe_engine = _odpe
            _l1_tax = ODPEL1Taxonomy(db_pool=db_pool)
            app.state.odpe_l1_taxonomy = _l1_tax
            _seeded = await _l1_tax.seed_to_db(db_pool)
            print(f"   ✅ ODPEEngine + L1 Taxonomy wired ({_l1_tax.get_face_count()} faces, {_seeded} seeded to DB)")
        except Exception as _odpe_err:
            print(f"   ⚠️  ODPE engine init: {_odpe_err}")
        app.state.helix_orchestrator = HelixOrchestrator(
            db_pool=db_pool, app_state=app.state,
            fibre_manager=getattr(app.state, 'fibre_manager', None),
            odpe_engine=_odpe,
        )
        _lni = LittleNateInference(app_state=app.state, db_pool=db_pool)
        _lni.bind(app.state)
        app.state.littlenate_inference = _lni
        from app.services.quantum_knowledge_field import FederatedSearchCoordinator
        app.state.federated_search = FederatedSearchCoordinator(db_pool=db_pool, app_state=app.state)
        print("   ✅ NateMemoryCrystallizer + HelixOrchestrator + LittleNateInference + FederatedSearch wired")
        # QUANTUM-CRYSTAL-ARCH — crystallizer background loop: harvest 30m,
        # cluster+synthesize+supersede on cadence, decay 6h. Backend only, so the
        # bridge's own instance never double-harvests. Flag-off by default.
        if (os.environ.get("ENABLE_CRYSTALLIZER_LOOP", "false") or "").strip().lower() in ("1", "true", "yes", "on"):
            try:
                await app.state.nate_memory_crystallizer.start()
                print("   ✅ Crystallizer loop started (harvest 30m, cluster/decay on cadence)")
            except Exception as _cz_err:
                print(f"   ⚠️  Crystallizer loop start failed: {_cz_err}")
        # QUANTUM-CRYSTAL-ARCH — 6 self-learning domain agents. Temperatures and
        # domain scoping are governed by nate_agent_template.DOMAIN_TEMPERATURES.
        app.state.nate_domain_agents = {}
        if (os.environ.get("ENABLE_DOMAIN_AGENTS", "false") or "").strip().lower() in ("1", "true", "yes", "on"):
            try:
                from app.services.nate_agent_template import (
                    MarketingIntelligenceAgent, ClinicalPatternAgent, CoachDiscoveryAgent,
                    ThreatIntelligenceAgent, CulturalIntelligenceAgent, ResearchSynthesisAgent,
                )
                for _AgentCls in (MarketingIntelligenceAgent, ClinicalPatternAgent,
                                  CoachDiscoveryAgent, ThreatIntelligenceAgent,
                                  CulturalIntelligenceAgent, ResearchSynthesisAgent):
                    _a = _AgentCls(db_pool=db_pool, app_state=app.state)
                    await _a.start()
                    app.state.nate_domain_agents[_a.domain] = _a
                print(f"   ✅ Domain agents started: {', '.join(sorted(app.state.nate_domain_agents))}")
            except Exception as _da_err:
                print(f"   ⚠️  Domain agents start failed: {_da_err}")
        # QUANTUM-CRYSTAL-ARCH — LN-Observer engine (feature-flagged)
        if getattr(settings, "ENABLE_LN_OBSERVER", False):
            from app.services.ln_observer_engine import ln_observer_engine as _lnobs
            # QUANTUM-CRYSTAL-ARCH — shared validator for Observer crystallize gate
            if not getattr(app.state, "nate_response_validator", None):
                try:
                    from app.services.nate_response_validator import NateResponseValidator
                    app.state.nate_response_validator = NateResponseValidator()
                except Exception:
                    pass
            _lnobs.bind(db_pool=db_pool, app_state=app.state)
            await _lnobs.start()
            app.state.ln_observer_engine = _lnobs
            print("   ✅ LNObserverEngine wired")
    except Exception as _cog_err:
        print(f"   ⚠️  Cognitive stack wiring failed: {_cog_err}")

    # SOVEREIGN-VOICE: CycleDetectionEngine + PredictiveEngine wiring
    try:
        from app.services.cycle_detection_engine import CycleDetectionEngine
        _cde = CycleDetectionEngine(db_pool=db_pool, app_state=app.state)
        app.state.cycle_detection_engine = _cde
        print("   ✅ CycleDetectionEngine wired")
    except Exception as _cde_err:
        print(f"   ⚠️  CycleDetectionEngine: {_cde_err}")
    try:
        from app.services.sovereign_predictive_engine import SovereignPredictiveEngine
        _spe = SovereignPredictiveEngine(db_pool=db_pool, app_state=app.state)
        app.state.predictive_engine = _spe
        print("   ✅ SovereignPredictiveEngine wired")
    except Exception as _spe_err:
        print(f"   ⚠️  SovereignPredictiveEngine: {_spe_err}")
    try:
        from app.services.code_cycle_detector import CodeCycleDetector
        _ccd = CodeCycleDetector(db_pool=db_pool)
        app.state.code_cycle_detector = _ccd
        print("   ✅ CodeCycleDetector wired")
    except Exception as _ccd_err:
        print(f"   ⚠️  CodeCycleDetector: {_ccd_err}")

    # QUANTUM-CRYSTAL-ARCH: ExaCrystallizationHook for real ExaFLOPS measurement
    try:
        from app.services.exa_crystallization_hook import ExaCrystallizationHook
        _exa = ExaCrystallizationHook(db_pool=db_pool, app_state=app.state)
        app.state.exa_crystallization_hook = _exa
        print("   ✅ ExaCrystallizationHook wired (real ExaFLOPS methodology)")
    except Exception as _exa_err:
        print(f"   ⚠️  ExaCrystallizationHook: {_exa_err}")

    # SOVEREIGN-VOICE: prepaid voice billing system
    _voice_billing = None
    try:
        from app.services.voice_billing import VoiceBillingSystem
        _voice_billing = VoiceBillingSystem(db_pool=db_pool)
        await _voice_billing.start()
        app.state.voice_billing = _voice_billing
        print("   ✅ VoiceBillingSystem started (PAUSED cleanup loop)")
    except Exception as _vb_err:
        print(f"   ⚠️  VoiceBillingSystem init failed: {_vb_err}")

    # SOVEREIGN-VOICE: Distributed Voice Pool (request-response, no start/stop)
    _voice_pool = None
    try:
        from app.services.distributed_voice_pool import DistributedVoicePool
        _voice_pool = DistributedVoicePool(redis_client=getattr(wisdom_mesh, '_redis', None))
        app.state.voice_pool = _voice_pool
        print("   ✅ DistributedVoicePool initialized")
    except Exception as _vp_err:
        print(f"   ⚠️  DistributedVoicePool init failed: {_vp_err}")

    # SOVEREIGN-VOICE: Voice Router (request-response, uses voice_pool)
    _voice_router = None
    try:
        from app.services.voice_router import VoiceRouter
        _voice_router = VoiceRouter(db_pool=db_pool, app_state=app.state)
        app.state.voice_router = _voice_router
        print("   ✅ VoiceRouter initialized")
    except Exception as _vr_err:
        print(f"   ⚠️  VoiceRouter init failed: {_vr_err}")

    # SOVEREIGN-VOICE: Voice Pipeline Optimizer (request-response)
    _voice_optimizer = None
    try:
        from app.services.voice_pipeline_optimizer import VoicePipelineOptimizer
        _voice_optimizer = VoicePipelineOptimizer()
        app.state.voice_pipeline_optimizer = _voice_optimizer
        print("   ✅ VoicePipelineOptimizer initialized")
    except Exception as _vo_err:
        print(f"   ⚠️  VoicePipelineOptimizer init failed: {_vo_err}")

    # SOVEREIGN-VOICE: Voice Call Center Agent (background, callback queue + outreach)
    _voice_call_center = None
    try:
        from app.services.voice_call_center_agent import VoiceCallCenterAgent
        _voice_call_center = VoiceCallCenterAgent(db_pool=db_pool, app_state=app.state)
        await _voice_call_center.start()
        app.state.voice_call_center_agent = _voice_call_center
        print("   ✅ VoiceCallCenterAgent started (callback queue + outreach jitter)")
    except Exception as _vcc_err:
        print(f"   ⚠️  VoiceCallCenterAgent init failed: {_vcc_err}")

    # SOVEREIGN-VOICE: Voice Infrastructure Auditor (3x daily, 10 checks)
    _voice_infra_auditor = None
    try:
        from app.services.voice_infrastructure_auditor import VoiceInfrastructureAuditor
        _voice_infra_auditor = VoiceInfrastructureAuditor(db_pool=db_pool, app_state=app.state)
        if not _is_clone: await _voice_infra_auditor.start()  # QUANTUM-CRYSTAL-ARCH: auditors GREEN-only
        app.state.voice_infra_auditor = _voice_infra_auditor
        print("   ✅ VoiceInfrastructureAuditor started (stagger 295s)")
    except Exception as _via_err:
        print(f"   ⚠️  VoiceInfrastructureAuditor init failed: {_via_err}")

    # QUANTUM-CRYSTAL-ARCH — CEO Dual-COO auditor (6 checks, stagger 288s)
    _ceo_dual_coo_auditor = None
    try:
        from app.services.ceo_dual_coo_auditor import CeoDualCooAuditor
        _ceo_dual_coo_auditor = CeoDualCooAuditor(db_pool=db_pool, app_state=app.state)
        if not _is_clone:
            await _ceo_dual_coo_auditor.start()
        app.state.ceo_dual_coo_auditor = _ceo_dual_coo_auditor
        print("   ✅ CeoDualCooAuditor started (stagger 288s)")
    except Exception as _cda_err:
        print(f"   ⚠️  CeoDualCooAuditor init failed: {_cda_err}")

    # QUANTUM-CRYSTAL-ARCH — Little Nate 7 identity + harness (request-response, no background loop)
    _ln7_engine_ok = False
    try:
        from app.services.little_nate_7 import ln7_enabled, PRODUCT_NAME
        from app.websocket import ln7_harness as _ln7_harness_mod  # noqa: F401
        _ln7_engine_ok = True
        app.state.ln7_engine = {"product": PRODUCT_NAME, "enabled": ln7_enabled()}
        print(f"   ✅ {PRODUCT_NAME} identity + harness ready (enabled={ln7_enabled()})")
    except Exception as _ln7_err:
        print(f"   ⚠️  Little Nate 7 init failed: {_ln7_err}")
        app.state.ln7_engine = None

    # QUANTUM-CRYSTAL-ARCH — LN7 continuous gated self-improvement (flagged; GREEN orchestrates only)
    try:
        from app.services.ln7_train_queue import continuous_enabled as _ln7_cont_on
        if _ln7_cont_on():
            from app.services.ln7_continuous_agent import maybe_start_continuous_agent
            await maybe_start_continuous_agent(app.state, db_pool)
            print("   ✅ Ln7ContinuousAgent started (ENABLE_LN7_CONTINUOUS)")
        else:
            app.state.ln7_continuous_agent = "disabled"
    except Exception as _ln7c_err:
        print(f"   ⚠️  Ln7ContinuousAgent init failed: {_ln7c_err}")
        app.state.ln7_continuous_agent = "init_failed"  # truthy — do not tank service count

    # QUANTUM-CRYSTAL-ARCH — Multi-LoRA flywheel agents (W13 boot fence + R1/R2/W15)
    try:
        from app.services.ln7_frozen_config import boot_fence_check

        _fence = await boot_fence_check(db_pool)
        app.state.ln7_fence = _fence
        print(f"   ✅ LN7 fence boot check ok={_fence.get('ok')}")
    except Exception as _fence_err:
        print(f"   ⚠️  LN7 fence boot check failed: {_fence_err}")
        app.state.ln7_fence = {"ok": False, "error": str(_fence_err)}
    try:
        from app.services.ln7_living_packs import LivingPackAgent

        _living = LivingPackAgent(db_pool)
        if not _is_clone:
            await _living.start()
        app.state.ln7_living_pack_agent = _living
        print("   ✅ LivingPackAgent started")
    except Exception as _lp_err:
        print(f"   ⚠️  LivingPackAgent init failed: {_lp_err}")
        app.state.ln7_living_pack_agent = None
    try:
        from app.services.phase_h_predicate_poller import PhaseHPredicatePoller

        _php = PhaseHPredicatePoller(db_pool)
        if not _is_clone:
            await _php.start()
        app.state.phase_h_predicate_poller = _php
        print("   ✅ PhaseHPredicatePoller started")
    except Exception as _php_err:
        print(f"   ⚠️  PhaseHPredicatePoller init failed: {_php_err}")
        app.state.phase_h_predicate_poller = None
    try:
        from app.services.goodhart_drift_sentinel import GoodhartDriftSentinel

        _gds = GoodhartDriftSentinel(db_pool)
        if not _is_clone:
            await _gds.start()
        app.state.goodhart_drift_sentinel = _gds
        print("   ✅ GoodhartDriftSentinel started")
    except Exception as _gds_err:
        print(f"   ⚠️  GoodhartDriftSentinel init failed: {_gds_err}")
        app.state.goodhart_drift_sentinel = None
    try:
        # QUANTUM-CRYSTAL-ARCH — R5 quarterly fallback drill (no G2 flip)
        from app.services.ln7_fallback_drill import FallbackDrillAgent

        _fbd = FallbackDrillAgent(db_pool)
        if not _is_clone:
            await _fbd.start()
        app.state.ln7_fallback_drill_agent = _fbd
        print("   ✅ FallbackDrillAgent started")
    except Exception as _fbd_err:
        print(f"   ⚠️  FallbackDrillAgent init failed: {_fbd_err}")
        app.state.ln7_fallback_drill_agent = None

    # QUANTUM-CRYSTAL-ARCH — Nate clinical coevolution bakeoff (flags default OFF)
    try:
        from app.services.nate_clinical_bakeoff_agent import NateClinicalBakeoffAgent
        _nate_clin_agent = NateClinicalBakeoffAgent(db_pool, app_state=app.state)
        await _nate_clin_agent.start()
        app.state.nate_clinical_bakeoff_agent = _nate_clin_agent
        print("   ✅ NateClinicalBakeoffAgent started (ENABLE_NATE_CLINICAL_BAKEOFF gated)")
    except Exception as _nca_err:
        print(f"   ⚠️  NateClinicalBakeoffAgent init failed: {_nca_err}")
        app.state.nate_clinical_bakeoff_agent = None  # QUANTUM-CRYSTAL-ARCH — not truthy fake

    # QUANTUM-CRYSTAL-ARCH — Adaptive Growth Engine (scheduler + content factory)
    try:
        from app.services.growth import (
            bwas_enabled,
            content_factory_enabled,
            growth_diagnostics_enabled,
            growth_engine_enabled,
            outreach_engine_enabled,
        )
        from app.services.growth.sender_guard import startup_hard_fail_if_needed
        if outreach_engine_enabled():
            startup_hard_fail_if_needed()
        if growth_engine_enabled() and db_pool is not None:
            from app.services.growth.scheduler_worker import GrowthSchedulerWorker
            _growth_sched = GrowthSchedulerWorker(db_pool)
            await _growth_sched.start()
            app.state.growth_scheduler = _growth_sched
            print("   ✅ GrowthSchedulerWorker started (ENABLE_GROWTH_ENGINE)")
        else:
            app.state.growth_scheduler = "disabled"
            print("   ℹ️  GrowthSchedulerWorker disabled (ENABLE_GROWTH_ENGINE=false)")
        if content_factory_enabled() and db_pool is not None:
            from app.services.growth.content_factory_worker import ContentFactoryWorker
            _growth_factory = ContentFactoryWorker(
                db_pool, redis=getattr(app.state, "redis", None), app_state=app.state
            )
            await _growth_factory.start()
            app.state.content_factory = _growth_factory
            print("   ✅ ContentFactoryWorker started (ENABLE_CONTENT_FACTORY)")
        else:
            app.state.content_factory = "disabled"
            print("   ℹ️  ContentFactoryWorker disabled (ENABLE_CONTENT_FACTORY=false)")
        # QUANTUM-CRYSTAL-ARCH — Phase 3 Instantly outreach health worker
        if outreach_engine_enabled() and db_pool is not None:
            from app.services.growth.outreach_worker import OutreachWorker
            _outreach_w = OutreachWorker(db_pool)
            await _outreach_w.start()
            app.state.outreach_worker = _outreach_w
            print("   ✅ OutreachWorker started (ENABLE_OUTREACH_ENGINE)")
        else:
            app.state.outreach_worker = "disabled"
            print("   ℹ️  OutreachWorker disabled (ENABLE_OUTREACH_ENGINE=false)")
        # QUANTUM-CRYSTAL-ARCH — Phase 4 BWAS weekly rollup
        if bwas_enabled() and db_pool is not None:
            from app.services.growth.bwas_worker import BwasWorker
            _bwas_w = BwasWorker(db_pool)
            await _bwas_w.start()
            app.state.bwas_worker = _bwas_w
            print("   ✅ BwasWorker started (ENABLE_BWAS)")
        else:
            app.state.bwas_worker = "disabled"
            print("   ℹ️  BwasWorker disabled (ENABLE_BWAS=false)")
        # QUANTUM-CRYSTAL-ARCH — Phase 5 growth diagnostics (propose-only)
        if growth_diagnostics_enabled() and db_pool is not None:
            from app.services.growth.diagnostics_worker import GrowthDiagnosticsWorker
            _gd = GrowthDiagnosticsWorker(db_pool)
            await _gd.start()
            app.state.growth_diagnostics = _gd
            print("   ✅ GrowthDiagnosticsWorker started (ENABLE_GROWTH_DIAGNOSTICS)")
        else:
            app.state.growth_diagnostics = "disabled"
            print("   ℹ️  GrowthDiagnosticsWorker disabled (ENABLE_GROWTH_DIAGNOSTICS=false)")
    except Exception as _growth_err:
        print(f"   ⚠️  Growth engine init failed: {_growth_err}")
        app.state.growth_scheduler = getattr(app.state, "growth_scheduler", None) or "init_failed"
        app.state.content_factory = getattr(app.state, "content_factory", None) or "init_failed"
        app.state.outreach_worker = getattr(app.state, "outreach_worker", None) or "init_failed"
        app.state.bwas_worker = getattr(app.state, "bwas_worker", None) or "init_failed"
        app.state.growth_diagnostics = getattr(app.state, "growth_diagnostics", None) or "init_failed"

    # SSE: Sovereign Story Engine Orchestrator
    _sse_orchestrator = None
    try:
        from app.sse.layer0_orchestrator import SSEOrchestrator
        import os as _os
        if _os.environ.get("DISABLE_SSE_SCHEDULER", "0") == "1":
            app.state.sse_orchestrator = "disabled"  # truthy sentinel — no duplicate scheduler on this node
            print("   ℹ️  SSEOrchestrator DISABLED on this node (DISABLE_SSE_SCHEDULER=1)")
        else:
            _sse_orchestrator = SSEOrchestrator(db_pool=db_pool)
            await _sse_orchestrator.start()
            app.state.sse_orchestrator = _sse_orchestrator
            print("   ✅ SSEOrchestrator started (daily panels + weekly clips + monthly recaps + group monthly videos)")
    except Exception as _sse_err:
        print(f"   ⚠️  SSEOrchestrator init failed: {_sse_err}")

    # QUANTUM-CRYSTAL-ARCH: Therapeutic Identity Inference Engine
    _identity_engine_ok = False
    try:
        from app.services.consent_privacy import ConsentPrivacyManager
        app.state.consent_privacy = ConsentPrivacyManager(db_pool=db_pool)
        from app.services.institutional_deployment import InstitutionalDeploymentManager
        app.state.institutional_deployment = InstitutionalDeploymentManager(db_pool=db_pool)
        _identity_engine_ok = True
        print("   ✅ Therapeutic Identity Engine initialized (consent + institutional)")
    except Exception as _tie_err:
        print(f"   ⚠️  Therapeutic Identity Engine init failed: {_tie_err}")

    # ── HIVE DEFENSE v4.3: Startup Health Summary ──
    _healthy_count = 0
    _degraded_list = []
    _service_checks = [
        ("db_pool", db_pool is not None),
        ("wisdom_mesh", getattr(app.state, "wisdom_mesh", None) is not None),
        ("fibre_manager", getattr(app.state, "fibre_manager", None) is not None),
        ("coherence_engine", getattr(app.state, "coherence_engine", None) is not None),
        ("foresight_engine", getattr(app.state, "foresight_engine", None) is not None),
        ("session_memory", getattr(app.state, "session_memory_store", None) is not None),
        ("skyeye", skyeye_engine is not None),
        ("drip_scheduler", drip_scheduler is not None),
        ("swarm_relay", getattr(app.state, "swarm_relay", None) is not None),
        ("token_guardian", _token_guardian is not None),
        ("token_renewal_agent", _token_renewal_agent is not None),
        ("token_audit_agent", _token_audit_agent is not None),
        ("six_quotient_growth_engine", _growth_engine is not None),  # QUANTUM-CRYSTAL-ARCH
        ("insight_accumulator", _insight_accumulator is not None),
        ("web_content_reader", _web_reader is not None),
        ("content_queue_janitor", _content_janitor is not None),
        ("token_lifecycle_predictor", _token_predictor is not None),
        ("db_maintenance_agent", _db_maintenance is not None),
        ("crystal_phi_auditor", _crystal_phi_auditor is not None),
        ("session_recovery_agent", _session_recovery is not None),
        ("agent_status_digest", _agent_digest is not None),
        ("public_trial_digest", _public_trial_digest is not None),
        ("skyeye_tab_auditor", _tab_auditor is not None),
        ("command_tab_auditor", _cmd_auditor is not None),
        ("the_eye_auditor", _eye_auditor is not None),
        ("login_auditor", _login_auditor is not None),
        ("client_app_auditor", _client_auditor is not None),
        ("coach_dojo_auditor", _coach_dojo_auditor is not None),
        ("billing_auditor", _billing_auditor is not None),
        ("defense_auditor", _defense_auditor is not None),
        ("ai_pipeline_auditor", _ai_pipeline_auditor is not None),
        ("ws_flow_auditor", _ws_flow_auditor is not None),
        ("tier_gating_auditor", _tier_gating_auditor is not None),
        ("nevedal_lab_auditor", _nevedal_lab_auditor is not None),
        ("hw_security_auditor", _hw_security_auditor is not None),
        ("system_integrity_auditor", _system_integrity_auditor is not None),
        ("dojo_session_auditor", _dojo_session_auditor is not None),
        ("wisdom_pipeline_auditor", _wisdom_pipeline_auditor is not None),
        ("settings_tab_auditor", _settings_tab_auditor is not None),
        ("notification_observer", _notif_observer is not None),
        ("community_mesh_engine", _community_mesh is not None),
        ("liminal_coaching_engine", _liminal_engine is not None),
        ("dojo_mentor_engine", _dojo_mentor is not None),
        ("dojo_mentor_zoom", _dojo_zoom is not None),
        ("coach_hierarchy_auditor", _coach_hierarchy_auditor is not None),
        ("classroom_learning_auditor", _classroom_learning_auditor is not None),
        ("stance_loop_auditor", _stance_loop_auditor is not None),  # QUANTUM-CRYSTAL-ARCH
        ("coaching_mesh_engine", _coaching_mesh is not None),
        ("call_coaching_engine", _call_coaching is not None),
        ("trust_enforcer", _trust_enforcer is not None),
        ("assessment_engine", _assessment_engine is not None),
        ("silence_sentinel", _silence_sentinel is not None),
        ("language_drift_monitor", _language_drift_monitor is not None),
        ("field_response_parser", _field_response_parser is not None),
        ("liminal_presence_auditor", _liminal_presence_auditor is not None),
        ("pmb_command_center_auditor", _pmb_auditor is not None),
        ("data_uniformity_tracer", _data_uniformity_tracer is not None),
        ("token_lab_auditor", _token_lab_auditor is not None),
        ("gkm_auditor", _gkm_auditor is not None),
        ("token_usage_agent", _token_usage_agent is not None),
        ("newsletter_agent", _newsletter_agent is not None),  # QUANTUM-CRYSTAL-ARCH
        ("newsletter_auditor", _newsletter_auditor is not None),  # QUANTUM-CRYSTAL-ARCH
        ("account_event_reconciler", _account_event_reconciler is not None),
        ("cli_task_bus_consumer", _cli_task_bus_consumer is not None),  # QUANTUM-CRYSTAL-ARCH
        ("crystal_outcome_apply", _crystal_outcome_apply is not None),  # QUANTUM-CRYSTAL-ARCH
        ("dual_coo_loop_closer", _dual_coo_loop_closer is not None),  # QUANTUM-CRYSTAL-ARCH
        ("six_quotient_battery_agent", _six_q_battery_agent is not None),  # QUANTUM-CRYSTAL-ARCH
        ("six_quotient_standards_index", _six_q_standards is not None),  # QUANTUM-CRYSTAL-ARCH
        ("six_quotient_battery_auditor", _six_q_battery_auditor is not None),  # QUANTUM-CRYSTAL-ARCH
        ("six_quotient_self_dev_agent", _six_q_self_dev_agent is not None),  # QUANTUM-CRYSTAL-ARCH
        ("ln_sandbox_engine", _ln_sandbox_engine is not None),  # QUANTUM-CRYSTAL-ARCH
        ("ln_sandbox_auditor", _ln_sandbox_auditor is not None),  # QUANTUM-CRYSTAL-ARCH
        ("ln_observer_auditor", _ln_observer_auditor is not None),  # QUANTUM-CRYSTAL-ARCH
        ("nate_checkin_agent", _nate_checkin_agent is not None),
        ("pgsd_heartbeat_agent", _pgsd_heartbeat_agent is not None),  # QUANTUM-CRYSTAL-ARCH
        ("pgsd_discernment_scorer", (os.environ.get("PGSD_ENABLED", "").strip().lower() not in ("1", "true", "yes", "on")) or (_pgsd_discernment_scorer is not None)),  # QUANTUM-CRYSTAL-ARCH
        ("pgsd_field_engine", (os.environ.get("PGSD_ENABLED", "").strip().lower() not in ("1", "true", "yes", "on")) or (_pgsd_field_engine is not None)),  # QUANTUM-CRYSTAL-ARCH
        ("nate_commitment_agent", _nate_commitment_agent is not None),
        ("nate_self_monitor_agent", _nate_self_monitor_agent is not None),
        ("nate_checkin_auditor", _nate_checkin_auditor is not None),
        ("high_risk_crisis_auditor", _high_risk_crisis_auditor is not None),  # QUANTUM-CRYSTAL-ARCH
        ("sensitive_bridge_auditor", _sensitive_bridge_auditor is not None),
        ("sensitive_bridge_telemetry_agent",
         _sensitive_bridge_telemetry_agent is not None),
        ("fcode_engine", _fcode_engine is not None),
        ("session_payment_agent", _session_payment_agent is not None),
        ("signup_sharing_agent", _signup_sharing_agent is not None),
        ("quickbooks_sync_agent", _qb_sync_agent is not None),
        ("google_calendar_sync_agent", _google_calendar_sync_agent is not None),
        ("quickbooks_auditor", _qb_auditor is not None),
        ("corporate_command_auditor", _corp_auditor is not None),
        ("hot_memory", getattr(app.state, "hot_memory", None) is not None),
        ("warm_memory", getattr(app.state, "warm_memory", None) is not None),
        ("cold_memory", getattr(app.state, "cold_memory", None) is not None),
        ("sentinel_orchestrator", _sentinel_orchestrator is not None),
        ("quantum_crystal_orchestrator", (not getattr(settings, "ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR", False)) or (_quantum_orchestrator is not None)),
        ("crystal_graph", (not getattr(settings, "ENABLE_CRYSTAL_GRAPH", False)) or (_crystal_graph is not None)),  # QUANTUM-CRYSTAL-ARCH
        ("voice_billing", _voice_billing is not None),  # SOVEREIGN-VOICE
        ("voice_pool", _voice_pool is not None),  # SOVEREIGN-VOICE
        ("voice_router", _voice_router is not None),  # SOVEREIGN-VOICE
        ("voice_pipeline_optimizer", _voice_optimizer is not None),  # SOVEREIGN-VOICE
        ("voice_call_center_agent", _voice_call_center is not None),  # SOVEREIGN-VOICE
        ("voice_infra_auditor", _voice_infra_auditor is not None),  # SOVEREIGN-VOICE
        ("ceo_dual_coo_auditor", _ceo_dual_coo_auditor is not None),  # QUANTUM-CRYSTAL-ARCH
        ("ln7_engine", _ln7_engine_ok),  # QUANTUM-CRYSTAL-ARCH — Little Nate 7
        ("ln7_continuous_agent", getattr(app.state, "ln7_continuous_agent", None) is not None),  # QUANTUM-CRYSTAL-ARCH
        ("ln7_fence", getattr(app.state, "ln7_fence", None) is not None),  # QUANTUM-CRYSTAL-ARCH
        ("ln7_living_pack_agent", getattr(app.state, "ln7_living_pack_agent", None) is not None),  # QUANTUM-CRYSTAL-ARCH
        ("phase_h_predicate_poller", getattr(app.state, "phase_h_predicate_poller", None) is not None),  # QUANTUM-CRYSTAL-ARCH
        ("goodhart_drift_sentinel", getattr(app.state, "goodhart_drift_sentinel", None) is not None),  # QUANTUM-CRYSTAL-ARCH
        ("ln7_fallback_drill_agent", getattr(app.state, "ln7_fallback_drill_agent", None) is not None),  # QUANTUM-CRYSTAL-ARCH
        ("nate_clinical_bakeoff_agent", callable(getattr(getattr(app.state, "nate_clinical_bakeoff_agent", None), "run_night", None))),  # QUANTUM-CRYSTAL-ARCH
        ("growth_scheduler", getattr(app.state, "growth_scheduler", None) is not None),  # QUANTUM-CRYSTAL-ARCH
        ("content_factory", getattr(app.state, "content_factory", None) is not None),  # QUANTUM-CRYSTAL-ARCH
        ("outreach_worker", getattr(app.state, "outreach_worker", None) is not None),  # QUANTUM-CRYSTAL-ARCH
        ("bwas_worker", getattr(app.state, "bwas_worker", None) is not None),  # QUANTUM-CRYSTAL-ARCH
        ("growth_diagnostics", getattr(app.state, "growth_diagnostics", None) is not None),  # QUANTUM-CRYSTAL-ARCH
        ("identity_engine", _identity_engine_ok),  # QUANTUM-CRYSTAL-ARCH
        ("littlenate_inference", getattr(app.state, "littlenate_inference", None) is not None),
        ("nate_memory_crystallizer", getattr(app.state, "nate_memory_crystallizer", None) is not None),
        ("helix_orchestrator", getattr(app.state, "helix_orchestrator", None) is not None),
        ("federated_search", getattr(app.state, "federated_search", None) is not None),
        ("odpe_engine", getattr(app.state, "odpe_engine", None) is not None),
        ("cycle_detection_engine", getattr(app.state, "cycle_detection_engine", None) is not None),
        ("exa_crystallization_hook", getattr(app.state, "exa_crystallization_hook", None) is not None),
        ("sse_orchestrator", getattr(app.state, "sse_orchestrator", None) is not None),
    ]
    _hv4 = getattr(app.state, "hive_v4", {})
    _hive_services = [
        "webhook_fortress", "guardian_fibre", "sentinel_mesh", "pipeline_drum",
        "hepa_filter", "billing_monitor", "trial_guard", "usage_meter",
        "coach_financial_guard", "anonymization_proxy", "therapeutic_integrity",
        "model_stability", "transit_guardian", "infiltrator_trap", "family_data_guardian",
        "mirror_prediction", "coach_integrity_shield", "legal_compulsion",
        "sovereign_stripe_proxy", "family_session_guardian", "zero_knowledge_vault",
        "sovereign_keys", "succession_protocol", "recovery_drill", "heritage_vault",
        "upstream_canary", "deadman_switch",
    ]
    for svc_name in _hive_services:
        _service_checks.append((f"hive:{svc_name}", _hv4.get(svc_name) is not None))
    for svc_name, ok in _service_checks:
        if ok:
            _healthy_count += 1
        else:
            _degraded_list.append(svc_name)
    _total_count = len(_service_checks)
    print(f"\n{'='*60}")
    print(f"  STARTUP COMPLETE: {_healthy_count}/{_total_count} services healthy")
    if _degraded_list:
        print(f"  DEGRADED ({len(_degraded_list)}): {', '.join(_degraded_list)}")
    else:
        print("  ALL SYSTEMS NOMINAL")
    print(f"{'='*60}\n")

    yield
    
    # Shutdown
    print("👋 Shutting down...")

    # QUANTUM-CRYSTAL-ARCH — LN-Observer sweep stop
    _lnobs_h = getattr(app.state, "ln_observer_engine", None)
    if _lnobs_h:
        try:
            await _lnobs_h.stop()
            print("   ✅ LNObserverEngine stopped")
        except Exception as _lnobs_stop:
            print(f"   ⚠️  LNObserverEngine shutdown: {_lnobs_stop}")
    _ln_observer_auditor_h = getattr(app.state, "ln_observer_auditor", None)
    if _ln_observer_auditor_h:
        try:
            await _ln_observer_auditor_h.stop()
            print("   ✅ LNObserverAuditor stopped")
        except Exception as _ln_oa_stop:
            print(f"   ⚠️  LNObserverAuditor shutdown: {_ln_oa_stop}")

    # QUANTUM-CRYSTAL-ARCH — stop crystallizer loop + domain agents
    _cz_h = getattr(app.state, "nate_memory_crystallizer", None)
    if _cz_h and getattr(_cz_h, "_running", False):
        try:
            await _cz_h.stop()
            print("   ✅ Crystallizer loop stopped")
        except Exception as _cz_stop:
            print(f"   ⚠️  Crystallizer shutdown: {_cz_stop}")
    for _dom, _da_h in (getattr(app.state, "nate_domain_agents", None) or {}).items():
        try:
            await _da_h.stop()
            print(f"   ✅ Domain agent stopped: {_dom}")
        except Exception as _da_stop:
            print(f"   ⚠️  Domain agent {_dom} shutdown: {_da_stop}")

    # SOVEREIGN-VOICE: stop voice background agents
    if _voice_call_center:
        try:
            await _voice_call_center.stop()
            print("   ✅ VoiceCallCenterAgent stopped")
        except Exception as _vcc_stop:
            print(f"   ⚠️  VoiceCallCenterAgent shutdown: {_vcc_stop}")
    if _voice_infra_auditor:
        try:
            await _voice_infra_auditor.stop()
            print("   ✅ VoiceInfrastructureAuditor stopped")
        except Exception as _via_stop:
            print(f"   ⚠️  VoiceInfrastructureAuditor shutdown: {_via_stop}")
    _ceo_dual_coo_auditor_h = getattr(app.state, "ceo_dual_coo_auditor", None)
    if _ceo_dual_coo_auditor_h:
        try:
            await _ceo_dual_coo_auditor_h.stop()
            print("   ✅ CeoDualCooAuditor stopped")
        except Exception as _cda_stop:
            print(f"   ⚠️  CeoDualCooAuditor shutdown: {_cda_stop}")
    # QUANTUM-CRYSTAL-ARCH — LN7 continuous agent
    try:
        _ln7c = getattr(app.state, "ln7_continuous_agent", None)
        if _ln7c is not None and _ln7c != "disabled" and hasattr(_ln7c, "stop"):
            await _ln7c.stop()
            print("   ✅ Ln7ContinuousAgent stopped")
    except Exception as _ln7c_stop:
        print(f"   ⚠️  Ln7ContinuousAgent shutdown: {_ln7c_stop}")
    for _fly_attr in (
        "ln7_living_pack_agent",
        "phase_h_predicate_poller",
        "goodhart_drift_sentinel",
        "ln7_fallback_drill_agent",
    ):
        try:
            _fly = getattr(app.state, _fly_attr, None)
            if _fly is not None and hasattr(_fly, "stop"):
                await _fly.stop()
                print(f"   ✅ {_fly_attr} stopped")
        except Exception as _fly_stop:
            print(f"   ⚠️  {_fly_attr} shutdown: {_fly_stop}")
    try:
        _nca = getattr(app.state, "nate_clinical_bakeoff_agent", None)
        if _nca is not None and _nca != "init_failed" and hasattr(_nca, "stop"):
            await _nca.stop()
            print("   ✅ NateClinicalBakeoffAgent stopped")
    except Exception as _nca_stop:
        print(f"   ⚠️  NateClinicalBakeoffAgent shutdown: {_nca_stop}")
    # QUANTUM-CRYSTAL-ARCH — Adaptive Growth scheduler + factory
    try:
        _gs = getattr(app.state, "growth_scheduler", None)
        if _gs is not None and _gs not in ("disabled", "init_failed") and hasattr(_gs, "stop"):
            await _gs.stop()
            print("   ✅ GrowthSchedulerWorker stopped")
    except Exception as _gs_stop:
        print(f"   ⚠️  GrowthSchedulerWorker shutdown: {_gs_stop}")
    try:
        _cf = getattr(app.state, "content_factory", None)
        if _cf is not None and _cf not in ("disabled", "init_failed") and hasattr(_cf, "stop"):
            await _cf.stop()
            print("   ✅ ContentFactoryWorker stopped")
    except Exception as _cf_stop:
        print(f"   ⚠️  ContentFactoryWorker shutdown: {_cf_stop}")
    try:
        _ow = getattr(app.state, "outreach_worker", None)
        if _ow is not None and _ow not in ("disabled", "init_failed") and hasattr(_ow, "stop"):
            await _ow.stop()
            print("   ✅ OutreachWorker stopped")
    except Exception as _ow_stop:
        print(f"   ⚠️  OutreachWorker shutdown: {_ow_stop}")
    try:
        _bw = getattr(app.state, "bwas_worker", None)
        if _bw is not None and _bw not in ("disabled", "init_failed") and hasattr(_bw, "stop"):
            await _bw.stop()
            print("   ✅ BwasWorker stopped")
    except Exception as _bw_stop:
        print(f"   ⚠️  BwasWorker shutdown: {_bw_stop}")
    try:
        _gd = getattr(app.state, "growth_diagnostics", None)
        if _gd is not None and _gd not in ("disabled", "init_failed") and hasattr(_gd, "stop"):
            await _gd.stop()
            print("   ✅ GrowthDiagnosticsWorker stopped")
    except Exception as _gd_stop:
        print(f"   ⚠️  GrowthDiagnosticsWorker shutdown: {_gd_stop}")
    _classroom_learning_auditor = getattr(app.state, "classroom_learning_auditor", None)
    if _classroom_learning_auditor:
        try:
            await _classroom_learning_auditor.stop()
            print("   ✅ ClassroomLearningAuditor stopped")
        except Exception as _cla_stop:
            print(f"   ⚠️  ClassroomLearningAuditor shutdown: {_cla_stop}")
    _stance_loop_auditor = getattr(app.state, "stance_loop_auditor", None)  # QUANTUM-CRYSTAL-ARCH
    if _stance_loop_auditor:
        try:
            await _stance_loop_auditor.stop()
            print("   ✅ StanceLoopAuditor stopped")
        except Exception as _sla_stop:
            print(f"   ⚠️  StanceLoopAuditor shutdown: {_sla_stop}")
    _hrc_auditor = getattr(app.state, "high_risk_crisis_auditor", None)  # QUANTUM-CRYSTAL-ARCH
    if _hrc_auditor and hasattr(_hrc_auditor, "stop"):
        try:
            await _hrc_auditor.stop()
            print("   ✅ HighRiskCrisisAuditor stopped")
        except Exception as _hrc_stop:
            print(f"   ⚠️  HighRiskCrisisAuditor shutdown: {_hrc_stop}")
    _account_event_reconciler_h = getattr(app.state, "account_event_reconciler", None)
    if _account_event_reconciler_h:
        try:
            await _account_event_reconciler_h.stop()
            print("   ✅ AccountEventReconciler stopped")
        except Exception as _aer_stop:
            print(f"   ⚠️  AccountEventReconciler shutdown: {_aer_stop}")
    _cli_task_bus_consumer_h = getattr(app.state, "cli_task_bus_consumer", None)  # QUANTUM-CRYSTAL-ARCH
    if _cli_task_bus_consumer_h:
        try:
            await _cli_task_bus_consumer_h.stop()
            print("   ✅ CliTaskBusConsumer stopped")
        except Exception as _ctbc_stop:
            print(f"   ⚠️  CliTaskBusConsumer shutdown: {_ctbc_stop}")
    _crystal_outcome_apply_h = getattr(app.state, "crystal_outcome_apply", None)  # QUANTUM-CRYSTAL-ARCH
    if _crystal_outcome_apply_h:
        try:
            await _crystal_outcome_apply_h.stop()
            print("   ✅ CrystalOutcomeApplyAgent stopped")
        except Exception as _coa_stop:
            print(f"   ⚠️  CrystalOutcomeApplyAgent shutdown: {_coa_stop}")
    _dual_coo_loop_closer_h = getattr(app.state, "dual_coo_loop_closer", None)  # QUANTUM-CRYSTAL-ARCH
    if _dual_coo_loop_closer_h:
        try:
            await _dual_coo_loop_closer_h.stop()
            print("   ✅ DualCooLoopCloser stopped")
        except Exception as _dcl_stop:
            print(f"   ⚠️  DualCooLoopCloser shutdown: {_dcl_stop}")
    _six_q_battery_h = getattr(app.state, "six_quotient_battery_agent", None)  # QUANTUM-CRYSTAL-ARCH
    if _six_q_battery_h:
        try:
            await _six_q_battery_h.stop()
            print("   ✅ SixQuotientBatteryAgent stopped")
        except Exception as _sqb_stop:
            print(f"   ⚠️  SixQuotientBatteryAgent shutdown: {_sqb_stop}")
    _six_q_standards_h = getattr(app.state, "six_quotient_standards_index", None)  # QUANTUM-CRYSTAL-ARCH
    if _six_q_standards_h:
        try:
            await _six_q_standards_h.stop()
            print("   ✅ SixQuotientStandardsIndex stopped")
        except Exception as _sqs_stop:
            print(f"   ⚠️  SixQuotientStandardsIndex shutdown: {_sqs_stop}")
    _six_q_auditor_h = getattr(app.state, "six_quotient_battery_auditor", None)  # QUANTUM-CRYSTAL-ARCH
    if _six_q_auditor_h:
        try:
            await _six_q_auditor_h.stop()
            print("   ✅ SixQuotientBatteryAuditor stopped")
        except Exception as _sqba_stop:
            print(f"   ⚠️  SixQuotientBatteryAuditor shutdown: {_sqba_stop}")
    _six_q_self_dev_h = getattr(app.state, "six_quotient_self_dev_agent", None)  # QUANTUM-CRYSTAL-ARCH
    if _six_q_self_dev_h:
        try:
            await _six_q_self_dev_h.stop()
            print("   ✅ SixQuotientSelfDevelopmentAgent stopped")
        except Exception as _sqsd_stop:
            print(f"   ⚠️  SixQuotientSelfDevelopmentAgent shutdown: {_sqsd_stop}")
    _ln_sandbox_h = getattr(app.state, "ln_sandbox_engine", None)  # QUANTUM-CRYSTAL-ARCH
    if _ln_sandbox_h:
        try:
            await _ln_sandbox_h.stop()
            print("   ✅ LNSandboxEngine stopped")
        except Exception as _ln_sb_stop:
            print(f"   ⚠️  LNSandboxEngine shutdown: {_ln_sb_stop}")
    _ln_sandbox_a = getattr(app.state, "ln_sandbox_auditor", None)  # QUANTUM-CRYSTAL-ARCH
    if _ln_sandbox_a:
        try:
            await _ln_sandbox_a.stop()
            print("   ✅ LNSandboxAuditor stopped")
        except Exception as _ln_sba_stop:
            print(f"   ⚠️  LNSandboxAuditor shutdown: {_ln_sba_stop}")
    if _sse_orchestrator:
        try:
            await _sse_orchestrator.stop()
            print("   ✅ SSEOrchestrator stopped")
        except Exception as _sse_stop:
            print(f"   ⚠️  SSEOrchestrator shutdown: {_sse_stop}")

    # QUANTUM-CRYSTAL-ARCH: stop optional forge scheduler cleanly
    _quantum_orchestrator = getattr(app.state, "quantum_crystal_orchestrator", None)
    if _quantum_orchestrator and hasattr(_quantum_orchestrator, "stop_forge_scheduler"):
        try:
            await _quantum_orchestrator.stop_forge_scheduler()
            print("   ✅ QuantumCrystalOrchestrator forge scheduler stopped")
        except Exception as _qco_stop_err:
            print(f"   ⚠️  QuantumCrystalOrchestrator shutdown: {_qco_stop_err}")

    # Stop Upstream Canary Network
    _hive_v4 = getattr(app.state, "hive_v4", {})
    _uc = _hive_v4.get("upstream_canary")
    if _uc:
        try:
            _uc.stop()
            print("   ✅ Upstream Canary Network stopped")
        except Exception:
            pass

    # Stop Therapeutic Integrity background loop
    _ti = _hive_v4.get("therapeutic_integrity")
    if _ti and hasattr(_ti, "stop_background_loop"):
        _ti.stop_background_loop()
    _ti_task = getattr(app.state, "_therapeutic_integrity_task", None)
    if _ti_task and not _ti_task.done():
        _ti_task.cancel()
        print("   ✅ Therapeutic Integrity Monitor stopped")

    # ── HIVE DEFENSE v4.3: Shutdown Sentinel Mesh, Pipeline Drum, HEPA Filter ──
    _sm = _hive_v4.get("sentinel_mesh")
    if _sm and hasattr(_sm, "stop"):
        try:
            await _sm.stop()
            print("   ✅ Sentinel Mesh stopped")
        except Exception as _sm_err:
            print(f"   ⚠️  Sentinel Mesh shutdown: {_sm_err}")

    _pd = _hive_v4.get("pipeline_drum")
    if _pd and hasattr(_pd, "stop"):
        try:
            await _pd.stop()
            print("   ✅ Pipeline Drum stopped")
        except Exception as _pd_err:
            print(f"   ⚠️  Pipeline Drum shutdown: {_pd_err}")

    _hf = _hive_v4.get("hepa_filter")
    if _hf and hasattr(_hf, "stop"):
        try:
            await _hf.stop()
            print("   ✅ HEPA Filter stopped")
        except Exception as _hf_err:
            print(f"   ⚠️  HEPA Filter shutdown: {_hf_err}")

    _bm = _hive_v4.get("billing_monitor")
    if _bm and hasattr(_bm, "stop"):
        try:
            await _bm.stop()
            print("   ✅ Billing Monitor stopped")
        except Exception as _bm_err:
            print(f"   ⚠️  Billing Monitor shutdown: {_bm_err}")

    _rd = _hive_v4.get("recovery_drill")
    if _rd and hasattr(_rd, "stop"):
        try:
            await _rd.stop()
            print("   ✅ Recovery Drill stopped")
        except Exception as _rd_err:
            print(f"   ⚠️  Recovery Drill shutdown: {_rd_err}")

    # Stop Deadman Switch background loop
    _dm_task = getattr(app.state, "_deadman_switch_task", None)
    if _dm_task and not _dm_task.done():
        _dm_task.cancel()
        print("   ✅ Deadman Switch stopped")

    # Stop Account Purge background loop
    _pg_task = getattr(app.state, "_purge_task", None)
    if _pg_task and not _pg_task.done():
        _pg_task.cancel()
        print("   ✅ Account Purge Job stopped")

    # Stop Token Guardian
    _tg = getattr(app.state, "token_guardian", None)
    if _tg:
        _tg.stop()
        print("   ✅ Token Guardian stopped")

    # Stop Token Renewal Agent
    _tra = getattr(app.state, "token_renewal_agent", None)
    if _tra:
        await _tra.stop()
        print("   ✅ Token Renewal Agent stopped")

    # Stop Token Audit Agent
    _taa = getattr(app.state, "token_audit_agent", None)
    if _taa:
        await _taa.stop()
        print("   ✅ Token Audit Agent stopped")

    # Stop Content Queue Janitor
    _cqj = getattr(app.state, "content_queue_janitor", None)
    if _cqj:
        await _cqj.stop()
        print("   ✅ ContentQueueJanitor stopped")

    # Stop Token Lifecycle Predictor
    _tlp = getattr(app.state, "token_lifecycle_predictor", None)
    if _tlp:
        await _tlp.stop()
        print("   ✅ TokenLifecyclePredictor stopped")

    # Stop Database Maintenance Agent
    _dbm = getattr(app.state, "db_maintenance_agent", None)
    if _dbm:
        await _dbm.stop()
        print("   ✅ DatabaseMaintenanceAgent stopped")

    # Stop Crystal PHI Auditor
    _cpa_shutdown = getattr(app.state, "crystal_phi_auditor", None)
    if _cpa_shutdown:
        try:
            await _cpa_shutdown.stop()
            print("   ✅ CrystalPhiAuditor stopped")
        except Exception as _cpa_stop_err:
            print(f"   ⚠️  CrystalPhiAuditor shutdown: {_cpa_stop_err}")

    # Stop Session Recovery Agent
    _sra = getattr(app.state, "session_recovery_agent", None)
    if _sra:
        await _sra.stop()
        print("   ✅ SessionRecoveryAgent stopped")

    # Stop Session Payment Agent
    _spa = getattr(app.state, "session_payment_agent", None)
    if _spa:
        await _spa.stop()
        print("   ✅ SessionPaymentAgent stopped")

    # Stop Signup Sharing Agent
    _ssa = getattr(app.state, "signup_sharing_agent", None)
    if _ssa:
        await _ssa.stop()
        print("   ✅ SignupSharingAgent stopped")

    # Stop Agent Status Digest
    _asd = getattr(app.state, "agent_status_digest", None)
    if _asd is not None and _asd != "skipped_clone" and hasattr(_asd, "stop"):
        await _asd.stop()
        print("   ✅ AgentStatusDigest stopped")

    _ptd = getattr(app.state, "public_trial_digest", None)
    if _ptd is not None and _ptd != "skipped_clone" and hasattr(_ptd, "stop"):
        await _ptd.stop()
        print("   ✅ PublicTrialDigest stopped")

    # Stop SkyEye Tab Auditor
    _sta = getattr(app.state, "skyeye_tab_auditor", None)
    if _sta:
        await _sta.stop()
        print("   ✅ SkyEyeTabAuditor stopped")

    # Stop Sovereign Command Tab Auditor
    _cta = getattr(app.state, "command_tab_auditor", None)
    if _cta:
        await _cta.stop()
        print("   ✅ SovereignCommandAuditor stopped")

    # Stop The Eye Auditor
    _tea = getattr(app.state, "the_eye_auditor", None)
    if _tea:
        await _tea.stop()
        print("   ✅ TheEyeAuditor stopped")

    # Stop Login Auditor
    _la = getattr(app.state, "login_auditor", None)
    if _la:
        await _la.stop()
        print("   ✅ LoginAuditor stopped")

    # Stop Client App Auditor
    _caa = getattr(app.state, "client_app_auditor", None)
    if _caa:
        await _caa.stop()
        print("   ✅ ClientAppAuditor stopped")

    # Stop new auditors
    for _attr, _label in [
        ("coach_dojo_auditor", "CoachDojoAuditor"),
        ("billing_auditor", "BillingPipelineAuditor"),
        ("defense_auditor", "DefenseHealthAuditor"),
        ("ai_pipeline_auditor", "AIPipelineAuditor"),
        ("ws_flow_auditor", "WebSocketFlowAuditor"),
        ("tier_gating_auditor", "TierGatingAuditor"),
        ("nevedal_lab_auditor", "NevedalLabAuditor"),
        ("hw_security_auditor", "HardwareSecurityAuditor"),
        ("system_integrity_auditor", "SystemIntegrityAuditor"),
        ("notification_observer", "NotificationObserver"),
        ("community_mesh_engine", "CommunityMeshEngine"),
        ("trust_enforcer", "TrustEnforcer"),
        ("silence_sentinel", "SilenceSentinel"),
        ("language_drift_monitor", "LanguageDriftMonitor"),
        ("field_response_parser", "FieldResponseParser"),
        ("liminal_presence_auditor", "LiminalPresenceAuditor"),
        ("pmb_command_center_auditor", "PmbCommandCenterAuditor"),
        ("data_uniformity_tracer", "DataUniformityTracer"),
        ("token_lab_auditor", "TokenLabAuditor"),
        ("gkm_auditor", "GkmAuditor"),
        ("token_usage_agent", "TokenUsageAgent"),
        ("newsletter_agent", "NewsletterAgent"),  # QUANTUM-CRYSTAL-ARCH
        ("newsletter_auditor", "NewsletterAuditor"),  # QUANTUM-CRYSTAL-ARCH
        ("nate_checkin_agent", "NateCheckInAgent"),
        ("pgsd_heartbeat_agent", "PGSDHeartbeatAgent"),  # QUANTUM-CRYSTAL-ARCH
        ("nate_commitment_agent", "NateCommitmentAgent"),
        ("nate_self_monitor_agent", "NateSelfMonitorAgent"),
        ("nate_checkin_auditor", "NateCheckInAuditor"),
        ("sensitive_bridge_auditor", "SensitiveBridgeAuditor"),
        ("sensitive_bridge_telemetry_agent", "SensitiveBridgeTelemetryAgent"),
    ]:
        _agent = getattr(app.state, _attr, None)
        # QUANTUM-CRYSTAL-ARCH — skip clone sentinels / non-agents
        if _agent is not None and _agent != "skipped_clone" and hasattr(_agent, "stop"):
            await _agent.stop()
            print(f"   ✅ {_label} stopped")

    # Stop Six-Quotient Growth Engine  # QUANTUM-CRYSTAL-ARCH
    _sqg = getattr(app.state, "six_quotient_growth_engine", None)
    if _sqg:
        await _sqg.stop()
        print("   ✅ Six-Quotient Growth Engine stopped")

    # Stop Insight Accumulator
    _ia = getattr(app.state, "insight_accumulator", None)
    if _ia:
        await _ia.stop()
        print("   ✅ Insight Accumulator stopped")

    # Stop Web Content Reader
    _wr = getattr(app.state, "web_content_reader", None)
    if _wr:
        await _wr.stop()
        print("   ✅ Web Content Reader stopped")

    # SECURITY: Persist in-memory sessions and memory index BEFORE stopping anything
    # This prevents data loss on restart/crash.
    
    # 1. Persist active Organizer sessions to PostgreSQL
    try:
        from app.services.vault.document_organizer import OrgSessionManager
        org_mgr = OrgSessionManager(db_pool)
        active_sessions = list(org_mgr._sessions.values()) if hasattr(org_mgr, '_sessions') else []
        for session in active_sessions:
            try:
                await org_mgr._persist_to_db(session)
            except Exception:
                pass
        if active_sessions:
            print(f"   ✅ {len(active_sessions)} organizer sessions persisted")
    except Exception as org_err:
        print(f"   ⚠️  Organizer session persistence failed: {org_err}")
    
    # 2. Persist session memory index
    try:
        mem_store = getattr(app.state, "session_memory_store", None)
        if mem_store:
            mem_store._save_index()
            print("   ✅ Session memory index saved")
        else:
            print("   ⚠️  Session memory store was not initialized, skipping index save")
    except Exception as mem_err:
        print(f"   ⚠️  Session memory index save failed: {mem_err}")
    
    if skyeye_engine:
        try:
            await skyeye_engine.stop()
        except Exception:
            pass
    if linkedin_campaign_scheduler:
        try:
            linkedin_campaign_scheduler.stop()
        except Exception:
            pass
    if marketing_worker:
        try:
            await marketing_worker.stop()
        except Exception:
            pass
    if drip_scheduler:
        drip_scheduler.shutdown()
    # Stop background workers
    for w in _workers:
        try:
            _stop = w.stop()
            if hasattr(_stop, '__await__'):
                await _stop
        except Exception:
            pass
    if _workers:
        print(f"   ✅ {len(_workers)} background workers stopped")
    # Stop Hive Defense workers
    for hw in _hive_workers:
        try:
            _stop = hw.stop()
            if hasattr(_stop, '__await__'):
                await _stop
        except Exception:
            pass
    if _hive_workers:
        print(f"   ✅ {len(_hive_workers)} Hive Defense workers stopped")
    # Flush forensic logs
    if _hive_defense.get("forensic_logger"):
        try:
            await _hive_defense["forensic_logger"].flush_to_db(db_pool)
        except Exception:
            pass
    # Stop Swarm Relay
    swarm_relay = getattr(app.state, "swarm_relay", None)
    if swarm_relay:
        try:
            await swarm_relay.stop()
        except Exception:
            pass
    # Disconnect Wisdom Mesh (Redis cleanup)
    wisdom_mesh_ref = getattr(app.state, "wisdom_mesh", None)
    if wisdom_mesh_ref:
        try:
            await wisdom_mesh_ref.disconnect()
            print("   ✅ Wisdom Mesh disconnected")
        except Exception:
            pass
    # Stop QB Sync Agent, QB Auditor, Corp Command Auditor
    for _agent_name, _agent_var in [
        ("QuickBooksSyncAgent", _qb_sync_agent),
        ("GoogleCalendarSyncAgent", _google_calendar_sync_agent),
        ("QuickBooksAuditor", _qb_auditor),
        ("CorporateCommandAuditor", _corp_auditor),
    ]:
        if _agent_var:
            try:
                await _agent_var.stop()
            except Exception:
                pass

    # SOVEREIGN-VOICE: stop voice billing cleanup loop
    _vb_ref = getattr(app.state, "voice_billing", None)
    if _vb_ref:
        try:
            await _vb_ref.stop()
        except Exception:
            pass

    if db_pool:
        await db_pool.close()
    print("   ✅ Database disconnected")


# =============================================================================
# CREATE APP
# =============================================================================

app = FastAPI(
    title="Little Nate API",
    description="Clinical Sovereignty Lab — AI Therapy Platform",
    version="1.0.0",
    lifespan=lifespan
)


# =============================================================================
# CORS MIDDLEWARE
# =============================================================================

app.add_middleware(
    CORSMiddleware,
    # Strip whitespace: .env CORS list often has ", https://..." and breaks allow_origin exact match
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    # Allow local Flutter web dev server origins (random port) to call REST endpoints.
    # WebSockets are separate; this is specifically for /api/* fetches (e.g. schedule session).
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# HIVE DEFENSE MIDDLEWARE (registered at module level — Starlette requirement)
# Services are resolved lazily via app.state during request processing.
# =============================================================================
from app.middleware.transit_inspection import TransitInspectionMiddleware
from app.middleware.drum_tap import DrumTapMiddleware
from app.middleware.webhook_rate_limit import WebhookRateLimitMiddleware

from app.middleware.cache_control import CacheControlMiddleware

app.add_middleware(TransitInspectionMiddleware, app_state=app.state)
app.add_middleware(DrumTapMiddleware, app_state=app.state)
app.add_middleware(WebhookRateLimitMiddleware, max_requests=120, window_seconds=60)
app.add_middleware(CacheControlMiddleware)


# =============================================================================
# ROUTES
# =============================================================================

# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "little-nate-api",
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT
    }


# API routes
app.include_router(auth)
app.include_router(users)
app.include_router(sessions_api.router)
app.include_router(sessions_api.classroom_router)
app.include_router(sessions_api.public_router)  # email one-click approve/decline (HMAC token auth)
app.include_router(admin_api.router)
app.include_router(admin_api.sse_router)
app.include_router(admin_api.sse_client_router)
app.include_router(coach_api.router)
app.include_router(billing_api.router)
app.include_router(billing_api.public_router)
try:
    from app.routers.registration_checkout import public_router as registration_checkout_router
    from app.routers.registration_checkout import upgrade_router as registration_upgrade_router
    app.include_router(registration_checkout_router)
    app.include_router(registration_upgrade_router)
    print("   ✅ Registration checkout + upgrade router registered")
except Exception as _reg_err:
    print(f"   ⚠️  Registration checkout router failed: {_reg_err}")
try:
    from app.routers.public_trial_api import router as public_trial_router
    app.include_router(public_trial_router)
    print("   ✅ Public trial unsubscribe router registered")
except Exception as _pt_err:
    print(f"   ⚠️  Public trial unsubscribe router failed: {_pt_err}")
try:
    from app.routers.scholarship_api import router as scholarship_router
    app.include_router(scholarship_router)
except Exception as _sch_err:
    print(f"   ⚠️  Scholarship router failed: {_sch_err}")
app.include_router(dojo_api.router)
app.include_router(twilio_webhook.router)

# Drip Campaign routes
app.include_router(campaign_api.router)
app.include_router(quiz_api.router)
app.include_router(prospect_api.router)
app.include_router(response_api.router)
app.include_router(golden_ticket_api.router)
app.include_router(analytics_api.router)
if hasattr(analytics_api, "public_router"):
    app.include_router(analytics_api.public_router)  # QUANTUM-CRYSTAL-ARCH — growth beacon
app.include_router(webhook_api.router)
app.include_router(meta_webhook_router)

# Zoom endpoints are additive and gated behind ENABLE_ZOOM (and missing env checks inside the router)
if settings.ENABLE_ZOOM:
    app.include_router(zoom_api.router)

# SkyEye Social Media Hub
if settings.ENABLE_SKYEYE:
    app.include_router(skyeye_api.router)
    app.include_router(skyeye_api.oauth_router)

# Marketing Brain (always enabled when SkyEye is enabled)
if settings.ENABLE_SKYEYE:
    app.include_router(marketing_api.router)
    # QUANTUM-CRYSTAL-ARCH — HMAC preview for growth CEO emails (no admin auth)
    if hasattr(marketing_api, "public_router"):
        app.include_router(marketing_api.public_router)
# QUANTUM-CRYSTAL-ARCH — LN-Observer (Coach Command)
if getattr(settings, "ENABLE_LN_OBSERVER", False):
    from app.routers.ln_observer_api import router as ln_observer_router
    app.include_router(ln_observer_router)

# QUANTUM-CRYSTAL-ARCH — LN Sandbox DOJO (always register; engine flag-gates work)
try:
    from app.routers.ln_sandbox_api import router as ln_sandbox_router
    app.include_router(ln_sandbox_router)
except Exception as _ln_sb_rerr:
    print(f"   ⚠️  LN Sandbox router failed: {_ln_sb_rerr}")

# QUANTUM-CRYSTAL-ARCH — Little Nate 7 sovereign coding API
try:
    from app.routers.ln7_api import router as ln7_router
    app.include_router(ln7_router)
except Exception as _ln7_rerr:
    print(f"   ⚠️  LN7 router failed: {_ln7_rerr}")

# QUANTUM-CRYSTAL-ARCH — Nate clinical coevolution admin API
try:
    from app.routers.nate_clinical_api import router as nate_clinical_router
    app.include_router(nate_clinical_router)
except Exception as _ncr_err:
    print(f"   ⚠️  Nate clinical router failed: {_ncr_err}")

# Coherence Engine (Sovereign Swarm)
app.include_router(coherence_api.router)
app.include_router(client_data_api.router)
app.include_router(high_risk_crisis_api.router)  # QUANTUM-CRYSTAL-ARCH

# Fibre & Mesh API (Sovereign Swarm)
app.include_router(fibre_api.router)

# Approval Protocol API (Sovereign Swarm)
app.include_router(approval_api.router)

# Strategic Memory API (Sovereign Swarm — 6 layers)
app.include_router(strategic_memory_api.router)

# Pattern Engine API (Sovereign Swarm — transgenerational analysis)
app.include_router(pattern_api.router)

# Legacy Vault API (Sovereign Swarm — consent & vault entries)
app.include_router(legacy_vault_api.router)

# Swarm Teams & Templates API (Sovereign Swarm — Human-Swarm teams)
app.include_router(swarm_teams_api.router)

# Sovereign Immunity API (quarantine, threats, audit)
app.include_router(immunity_api.router)

# Foresight Engine API (predictions, forecast, accuracy)
app.include_router(foresight_api.router)

# AI Modes API (Sovereign Swarm — TriCorder, Archivist, Guardian, Supervisor)
app.include_router(ai_modes_api.router)

# Nevedal Research Reports API (individual, dyad, family, longitudinal, coach efficacy)
app.include_router(nevedal_reports_api.router)

# Big Nate Chat — Human–AI command interface (Patent Claim 11)
app.include_router(big_nate_chat.router)

# Night School API — Wisdom curriculum and training endpoints
app.include_router(night_school_api_router.router)

# ZEFCP — Layer 1 Physical Transport (Patent Claim 25)
app.include_router(zefcp_api.router)

# Quakete — Layer 8 Swarm Solidarity (Patent Claim 26)
app.include_router(quakete_api.router)

# Counter-Intelligence — Phase 8 Reverse Osmosis Defense
app.include_router(counter_intelligence_api.router)

# Me-2-Me Platinum — Legacy Architecture endpoints
app.include_router(me2me_api.router)

# Phase 8: Hive Defense Protocol
app.include_router(hive_defense_api.router)
try:
    app.include_router(hive_defense_api.helix_public_router)
except Exception as _helix_pub_err:
    print(f"   ⚠️  Helix public router failed: {_helix_pub_err}")
app.include_router(assessments_api.router)
app.include_router(trust_enforcer_api.router)

# Coach Hierarchy & Coaching Mesh API
try:
    from app.routers.coach_hierarchy_api import router as coach_hierarchy_router
    app.include_router(coach_hierarchy_router)
except Exception as _ch_err:
    print(f"   ⚠️  Coach Hierarchy router failed: {_ch_err}")

# Community Mesh — Nate-to-Nate group wisdom + attendance
try:
    from app.routers.community_api import router as community_router
    app.include_router(community_router)
except Exception as _cm_err:
    print(f"   ⚠️  Community API router failed: {_cm_err}")

# Data Export — GDPR/CCPA user data download
try:
    from app.routers.data_export import router as data_export_router
    app.include_router(data_export_router)
except Exception as _de_err:
    print(f"   ⚠️  Data Export router failed: {_de_err}")

# Receipt Validation — Apple/Google IAP receipt verification
try:
    from app.routers.receipt_validation import router as receipt_router
    app.include_router(receipt_router)
except Exception as _rv_err:
    print(f"   ⚠️  Receipt Validation router failed: {_rv_err}")

# Twilio Voice — Live call coaching (/api/calls/*)
try:
    from app.routers.twilio_voice import router as twilio_voice_router
    app.include_router(twilio_voice_router)
except Exception as _tv_err:
    print(f"   ⚠️  Twilio Voice router failed: {_tv_err}")

# SOVEREIGN-VOICE — Coach-requested Nate check-in (outbound + callback verify)
try:
    from app.routers.coach_nate_checkin_api import router as coach_nate_checkin_router
    app.include_router(coach_nate_checkin_router)
except Exception as _cnc_err:
    print(f"   ⚠️  Coach Nate check-in router failed: {_cnc_err}")

# Twilio Media Stream WebSocket — /ws/nate-media-stream
try:
    from app.routers.littlenate_api import twilio_ws_router
    app.include_router(twilio_ws_router)
except Exception as _tws_err:
    print(f"   ⚠️  Twilio WS Media Stream router failed: {_tws_err}")

# Nate Agent API — crystal network push/status + CLI governance
try:
    from app.routers.nate_agent_api import router as nate_agent_router, cli_router as nate_cli_router, exa_public_router as nate_exa_router
    app.include_router(nate_agent_router)
    app.include_router(nate_cli_router)
    app.include_router(nate_exa_router)
except Exception as _na_err:
    print(f"   ⚠️  Nate Agent router failed: {_na_err}")

# PMB Reports — Globe Command Center
try:
    from app.routers.pmb_reports_api import router as pmb_reports_router
    app.include_router(pmb_reports_router)
except Exception as _pmb_err:
    print(f"   ⚠️  PMB Reports router failed: {_pmb_err}")

try:
    from app.routers.token_lab_api import router as token_lab_router
    app.include_router(token_lab_router)
except Exception as _tl_err:
    print(f"   ⚠️  Token Lab router failed: {_tl_err}")

try:
    from app.routers.gkm_api import router as gkm_router
    app.include_router(gkm_router)
except Exception as _gkm_err:
    print(f"   ⚠️  GKM router failed: {_gkm_err}")

try:
    from app.routers.studio_api import studio_router
    app.include_router(studio_router)
except Exception as _studio_err:
    print(f"   ⚠️  Studio router failed: {_studio_err}")

# QUANTUM-CRYSTAL-ARCH: 30s journey recap (transcript + panels + Ask Nate → stitched video)
try:
    from app.routers.journey_recap_api import journey_recap_router
    app.include_router(journey_recap_router)
except Exception as _jr_err:
    print(f"   ⚠️  Journey Recap router failed: {_jr_err}")

try:
    from app.routers.sendgrid_inbound import router as sendgrid_inbound_router
    app.include_router(sendgrid_inbound_router)
except Exception as _sg_err:
    print(f"   ⚠️  SendGrid Inbound router failed: {_sg_err}")

try:
    from app.routers.bulk_import import router as bulk_import_router
    app.include_router(bulk_import_router)
except Exception as _bi_err:
    print(f"   ⚠️  Bulk Import router failed: {_bi_err}")

# Coach FOLDER API
try:
    from app.routers.folder_api import router as folder_router
    app.include_router(folder_router)
except Exception as _fl_err:
    print(f"   ⚠️  Folder API router failed: {_fl_err}")

try:
    from app.routers.training_ground_coach_api import router as training_ground_coach_router
    app.include_router(training_ground_coach_router)
except Exception as _tg_err:
    print(f"   ⚠️  Training Ground coach router failed: {_tg_err}")

# Coach Forms API (templates, PDF/Excel generation, email distribution)
try:
    from app.routers.forms_api import router as forms_router
    app.include_router(forms_router)
except Exception as _fm_err:
    print(f"   ⚠️  Forms API router failed: {_fm_err}")

# F-Code API (ICD-10-CM suggestions, coach assignments, transgenerational)
try:
    from app.routers.fcode_api import router as fcode_router
    app.include_router(fcode_router)
except Exception as _fc_err:
    print(f"   ⚠️  F-Code API router failed: {_fc_err}")

# Coach Directory API (public coach listing for client discovery)
try:
    from app.routers.coach_directory_api import router as coach_directory_router
    app.include_router(coach_directory_router)
except Exception as _cd_err:
    print(f"   ⚠️  Coach Directory API router failed: {_cd_err}")

# Coach Schedule API (availability, calendar sync)
try:
    from app.routers.schedule_api import router as schedule_router
    app.include_router(schedule_router)
except Exception as _sc_err:
    print(f"   ⚠️  Schedule API router failed: {_sc_err}")

# Coach Sign-Up Code API (revenue sharing)
try:
    from app.routers.signup_code_api import router as signup_code_router
    app.include_router(signup_code_router)
except Exception as _su_err:
    print(f"   ⚠️  Sign-Up Code API router failed: {_su_err}")

# School Discount Code API (student verification & enrollment)
try:
    from app.routers.school_code_api import router as school_code_router
    app.include_router(school_code_router)
except Exception as _sc_err:
    print(f"   ⚠️  School Code API router failed: {_sc_err}")

# QuickBooks Integration API (admin-only auth-gated + public OAuth callback)
try:
    from app.routers.quickbooks_api import router as quickbooks_router, oauth_router as quickbooks_oauth_router
    app.include_router(quickbooks_router)
    app.include_router(quickbooks_oauth_router)
except Exception as _qb_err:
    print(f"   ⚠️  QuickBooks router failed: {_qb_err}")

# Corp QuickBooks API (CORP_ADMIN auth-gated + public OAuth callback)
try:
    from app.routers.corp_quickbooks_api import router as corp_qb_router, oauth_router as corp_qb_oauth_router
    app.include_router(corp_qb_router)
    app.include_router(corp_qb_oauth_router)
except Exception as _cqb_err:
    print(f"   ⚠️  Corp QuickBooks router failed: {_cqb_err}")

# Coach QuickBooks API (coach auth-gated + public OAuth callback)
try:
    from app.routers.coach_quickbooks_api import router as coach_qb_router, oauth_router as coach_qb_oauth_router
    app.include_router(coach_qb_router)
    app.include_router(coach_qb_oauth_router)
except Exception as _coqb_err:
    print(f"   ⚠️  Coach QuickBooks router failed: {_coqb_err}")

# Google Calendar API (per-user auth-gated + public OAuth callback)
try:
    from app.routers.google_calendar_api import router as google_calendar_router, oauth_router as google_calendar_oauth_router
    app.include_router(google_calendar_router)
    app.include_router(google_calendar_oauth_router)
except Exception as _gcal_err:
    print(f"   ⚠️  Google Calendar router failed: {_gcal_err}")

# Corporate Command API (CORP_ADMIN dashboard)
try:
    from app.routers.corporate_command_api import router as corporate_command_router
    app.include_router(corporate_command_router)
except Exception as _cc_err:
    print(f"   ⚠️  Corporate Command API router failed: {_cc_err}")

try:
    from app.routers.access_control_api import router as access_control_router
    app.include_router(access_control_router)
except Exception as _ac_err:
    print(f"   ⚠️  Access Control API router failed: {_ac_err}")

# QUANTUM-CRYSTAL-ARCH — Universal Summon doorways (3 Queries in a Bottle)
try:
    from app.routers.summon_api import router as summon_router
    app.include_router(summon_router)
except Exception as _sm_err:
    print(f"   ⚠️  Summon API router failed: {_sm_err}")

# QUANTUM-CRYSTAL-ARCH — Little Nate Dispatch
try:
    from app.routers.newsletter_api import router as newsletter_router
    from app.routers.newsletter_api import admin_router as newsletter_admin_router
    app.include_router(newsletter_router)
    app.include_router(newsletter_admin_router)
except Exception as _nlr_err:
    print(f"   ⚠️  Newsletter API router failed: {_nlr_err}")

try:
    from app.routers.voice_assistant_api import router as voice_assistant_router
    app.include_router(voice_assistant_router)
except Exception as _va_err:
    print(f"   ⚠️  Voice Assistant API router failed: {_va_err}")

try:
    from app.routers.telegram_webhook import router as telegram_router
    app.include_router(telegram_router)
except Exception as _tg_err:
    print(f"   ⚠️  Telegram webhook router failed: {_tg_err}")

try:
    from app.routers.mcp_server import router as mcp_router
    app.include_router(mcp_router)
except Exception as _mcp_err:
    print(f"   ⚠️  MCP server router failed: {_mcp_err}")

# SOVEREIGN-VOICE: voice billing inbound call + Stripe webhook + balance API
try:
    from app.routers.voice_billing_api import router as voice_billing_router
    app.include_router(voice_billing_router)
except Exception as _vbr_err:
    print(f"   ⚠️  Voice billing router failed: {_vbr_err}")

# QUANTUM-CRYSTAL-ARCH: voice identity enrollment, consent, drift review
try:
    from app.routers.voice_identity_api import router as voice_identity_router
    app.include_router(voice_identity_router)
except Exception as _vid_err:
    print(f"   ⚠️  Voice identity router failed: {_vid_err}")

try:
    from app.routers.voice_edge_api import router as voice_edge_router  # SOVEREIGN-VOICE
    app.include_router(voice_edge_router)
except Exception as _ve_err:
    print(f"   ⚠️  Voice edge router failed: {_ve_err}")

# QUANTUM-CRYSTAL-ARCH: Sensitive Clinical Bridge clinician portal (Phase 4b)
# Two routers: coach_router (require_clinician_for_user gate) + admin_router (require_admin + WebAuthn).
# Fail-soft: if import fails, dependent screens show empty state but rest of API stays up.
try:
    from app.routers.sensitive_profile_api import (
        coach_router as sensitive_profile_coach_router,
        admin_router as sensitive_profile_admin_router,
        AUDITOR_SELF_CHECK_RESULTS as _sensitive_profile_self_check,
    )
    app.include_router(sensitive_profile_coach_router)
    app.include_router(sensitive_profile_admin_router)
    if not all(_sensitive_profile_self_check.values()):
        _failed = [k for k, v in _sensitive_profile_self_check.items() if not v]
        print(f"   ⚠️  sensitive_profile_api boot self-check FAILED: {_failed}")
    else:
        print(f"   ✅ sensitive_profile_api boot self-check OK ({len(_sensitive_profile_self_check)}/{len(_sensitive_profile_self_check)})")
except Exception as _sp_err:
    print(f"   ⚠️  sensitive_profile_api router failed: {_sp_err}")


# QUANTUM-CRYSTAL-ARCH: Sensitive Bridge Telemetry — admin auto-disable controls
# (Phase 5 Note 1). Endpoints:
#   POST /api/admin/sensitive-bridge/auto-disable/{gap_flag}/cancel
#   POST /api/admin/sensitive-bridge/feature-flag    (re-enable gate enforced)
#   GET  /api/admin/sensitive-bridge/auto-disable
# Fail-soft: import failure leaves bridge auto-disable controls dormant; the
# agent itself ships PAUSED so nothing auto-disables anyway.
try:
    from app.routers.sensitive_bridge_telemetry_api import (
        router as sensitive_bridge_telemetry_router,
    )
    app.include_router(sensitive_bridge_telemetry_router)
    print("   ✅ sensitive_bridge_telemetry_api router mounted")
except Exception as _sbt_err:
    print(f"   ⚠️  sensitive_bridge_telemetry_api router failed: {_sbt_err}")

# QUANTUM-CRYSTAL-ARCH — Tier 2 coach PGSD REST (ACCESS/FIELD + pack)
try:
    from app.routers.pgsd_coach_api import router as pgsd_coach_router
    app.include_router(pgsd_coach_router)
    print("   ✅ pgsd_coach_api router mounted")
except Exception as _pgsd_coach_err:
    print(f"   ⚠️  pgsd_coach_api router failed: {_pgsd_coach_err}")


# QUANTUM-CRYSTAL-ARCH: Client Data Export (HIPAA 45 CFR 164.524 Right of Access)
# Phase 5 Gap N — survivor-facing sensitive-bridge data export with three
# redaction layers (SQL-filter access_classification + canonical PII screen +
# atomic single-download). Two routers:
#   - router       → /api/client/sensitive-data-export/{request,/{id}/status,/download/{token}}
#   - admin_router → /api/admin/sensitive-data-export/_synthetic_test
# Fail-soft: if import fails, survivors see an empty state but the rest of
# the API stays up. Auditor's twin-download self-test goes through the admin
# router and folds into an existing slot in sensitive_bridge_auditor.py.
try:
    from app.routers.client_data_export import (
        router as client_data_export_router,
        admin_router as client_data_export_admin_router,
        _auditor_self_check as _client_data_export_self_check,
    )
    app.include_router(client_data_export_router)
    app.include_router(client_data_export_admin_router)
    _cde_check = _client_data_export_self_check()
    if not _cde_check.get("uses_canonical_pii_screen"):
        print(
            f"   ⚠️  client_data_export PII screen check FAILED: "
            f"module={_cde_check.get('pii_screen_module')}"
        )
    else:
        print(
            f"   ✅ client_data_export router mounted "
            f"(contract={_cde_check.get('contract_version')}, "
            f"ttl_days={_cde_check.get('default_ttl_days')})"
        )
except Exception as _cde_err:
    print(f"   ⚠️  client_data_export router failed: {_cde_err}")


try:
    from app.routers.intake_form_api import router as intake_form_router

    app.include_router(intake_form_router)
    print("   ✅ intake_form_api router mounted")
except Exception as _intake_err:
    print(f"   ⚠️  intake_form_api router failed: {_intake_err}")


try:
    from app.routers.therapeutic_plan_api import router as therapeutic_plan_router

    app.include_router(therapeutic_plan_router)
    print("   ✅ therapeutic_plan_api router mounted")
except Exception as _tp_err:
    print(f"   ⚠️  therapeutic_plan_api router failed: {_tp_err}")

# QUANTUM-CRYSTAL-ARCH: clinical technique directory (care plans + modality assist)
try:
    from app.routers.clinical_directory_api import router as clinical_directory_router

    app.include_router(clinical_directory_router)
    print("   ✅ clinical_directory_api router mounted")
except Exception as _cd_err:
    print(f"   ⚠️  clinical_directory_api router failed: {_cd_err}")

# QUANTUM-CRYSTAL-ARCH — Phase 5b symbolic verifier telemetry
try:
    from app.routers.symbolic_verifier_api import router as symbolic_verifier_router

    app.include_router(symbolic_verifier_router)
    print("   ✅ symbolic_verifier_api router mounted")
except Exception as _sv_err:
    print(f"   ⚠️  symbolic_verifier_api router failed: {_sv_err}")


# QUANTUM-CRYSTAL-ARCH: conditional routers — mount if dependencies are satisfied
for _rmod, _ralias in [
    ("app.routers.patient_sovereignty", "patient_sovereignty_router"),
    ("app.routers.sovereign_completions_api", "sovereign_completions_router"),
    ("app.routers.agents_api", "agents_router"),  # SOVEREIGN-VOICE — partner agentic plug-in
    ("app.routers.cli_analytics_api", "cli_analytics_router"),
    ("app.routers.ceo_dual_coo_api", "ceo_dual_coo_router"),  # QUANTUM-CRYSTAL-ARCH
    ("app.routers.six_quotient_api", "six_quotient_router"),  # QUANTUM-CRYSTAL-ARCH
    ("app.routers.principal_review_api", "principal_review_router"),  # QUANTUM-CRYSTAL-ARCH
    ("app.routers.oauth_api", "oauth_router"),
    ("app.routers.nightly_audit_api", "nightly_audit_router"),
    ("app.routers.cloudflare_realtime_api", "cf_realtime_router"),
    ("app.routers.monetization_control_api", "monetization_router"),
    ("app.routers.cycle_api", "cycle_router"),
    ("app.routers.predictive_api", "predictive_router"),
]:
    try:
        _mod = __import__(_rmod, fromlist=["router"])
        app.include_router(_mod.router)
    except Exception as _rmount_err:
        print(f"   ⚠️  {_rmod.split('.')[-1]} router failed: {_rmount_err}")


# =============================================================================
# ROOT
# =============================================================================

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Welcome to the Sanctuary",
        "api_docs": "/docs",
        "health": "/health"
    }


# =============================================================================
# RUN (for development)
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=settings.DEBUG
    )
