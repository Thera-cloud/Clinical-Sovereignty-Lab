"""
LITTLE NATE — Main API Server Entry Point
Clinical Sovereignty Lab
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
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
import app.routers.skyeye_api as skyeye_api
import app.routers.marketing_api as marketing_api
import app.routers.coherence_api as coherence_api
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


# =============================================================================
# DATABASE CONNECTION POOL
# =============================================================================

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
            max_size=20
        )
    return db_pool


# =============================================================================
# LIFESPAN (Startup/Shutdown)
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown."""
    # Startup
    print(f"🚀 Starting Little Nate API Server...")
    print(f"   Environment: {settings.ENVIRONMENT}")
    print(f"   Server: {settings.SERVER_HOST}:{settings.SERVER_PORT}")
    
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
        max_size=20
    )
    print(f"   ✅ Database connected (host={_db_host})")
    
    # Store pool in app state
    app.state.db_pool = db_pool

    # Share db_pool with twilio_webhook router for approval protocol
    twilio_webhook.router._db_pool = db_pool

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
    if getattr(settings, "ENABLE_SKYEYE_SESSIONS", False):
        try:
            from app.services.skyeye_session_engine import SkyEyeSessionEngine
            skyeye_engine = SkyEyeSessionEngine(db_pool)
            await skyeye_engine.start()
            app.state.skyeye_engine = skyeye_engine
            print(f"   ✅ SkyEye session engine started")
        except Exception as e:
            print(f"   ⚠️  SkyEye session engine failed to start: {e}")
    
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
        except Exception:
            pass

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
        emotional_weather = EmotionalWeatherService(nevedal_engine=_nevedal_engine, sovereign_mind=_sovereign_mind)
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

        # ── Multi-Cloud Heritage Vault (Section 13.10.7) ──
        try:
            _heritage_vault = MultiCloudHeritageVault(db_pool)
            _heritage_status = await _heritage_vault.initialize()
            app.state.hive_v4["heritage_vault"] = _heritage_vault
            print(f"   ✅ Multi-Cloud Heritage Vault initialized: {_heritage_status}")
        except Exception as _hv_err:
            print(f"   ⚠️  Heritage Vault init failed: {_hv_err}")

        # Register Transit Inspection middleware
        from app.middleware.transit_inspection import TransitInspectionMiddleware
        app.add_middleware(TransitInspectionMiddleware, transit_guardian=app.state.hive_v4["transit_guardian"])

        # Register Pipeline Drum middleware
        from app.middleware.drum_tap import DrumTapMiddleware
        app.add_middleware(DrumTapMiddleware, pipeline_drum=_pipeline_drum)

        # Register Webhook Rate Limit middleware
        from app.middleware.webhook_rate_limit import WebhookRateLimitMiddleware
        app.add_middleware(WebhookRateLimitMiddleware, max_requests=120, window_seconds=60)

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

        print("   ✅ Hive Defense v4.0-v4.3 initialized (25 services, 8 background loops)")
        print("      All 8 Windows Closed | Billing Fortress | Guardian Fibre | Sentinel Mesh")
        print("      Pipeline Drum | HEPA Filter | Sovereign Layer | Zero Knowledge")
        print("      Upstream Canary | Webhook Rate Limit | Therapeutic Integrity | Deadman Switch")
    except Exception as v4_err:
        import traceback
        print(f"   ⚠️  Hive Defense v4.x initialization failed: {v4_err}")
        traceback.print_exc()
        app.state.hive_v4 = {}

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
        ("hot_memory", getattr(app.state, "hot_memory", None) is not None),
        ("warm_memory", getattr(app.state, "warm_memory", None) is not None),
        ("cold_memory", getattr(app.state, "cold_memory", None) is not None),
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
        from app.services.session_memory_store import SessionMemoryStore
        mem_store = SessionMemoryStore()
        mem_store._save_index()
        print("   ✅ Session memory index saved")
    except Exception as mem_err:
        print(f"   ⚠️  Session memory index save failed: {mem_err}")
    
    if skyeye_engine:
        try:
            await skyeye_engine.stop()
        except Exception:
            pass
    if drip_scheduler:
        drip_scheduler.shutdown()
    # Stop background workers
    for w in _workers:
        try:
            w.stop()
        except Exception:
            pass
    if _workers:
        print(f"   ✅ {len(_workers)} background workers stopped")
    # Stop Hive Defense workers
    for hw in _hive_workers:
        try:
            hw.stop()
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
    allow_origins=settings.CORS_ORIGINS.split(","),
    # Allow local Flutter web dev server origins (random port) to call REST endpoints.
    # WebSockets are separate; this is specifically for /api/* fetches (e.g. schedule session).
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
app.include_router(admin_api.router)
app.include_router(coach_api.router)
app.include_router(billing_api.router)
app.include_router(dojo_api.router)
app.include_router(twilio_webhook.router)

# Drip Campaign routes
app.include_router(campaign_api.router)
app.include_router(quiz_api.router)
app.include_router(prospect_api.router)
app.include_router(response_api.router)
app.include_router(golden_ticket_api.router)
app.include_router(analytics_api.router)
app.include_router(webhook_api.router)

# Zoom endpoints are additive and gated behind ENABLE_ZOOM (and missing env checks inside the router)
if settings.ENABLE_ZOOM:
    app.include_router(zoom_api.router)

# SkyEye Social Media Hub
if settings.ENABLE_SKYEYE:
    app.include_router(skyeye_api.router)

# Marketing Brain (always enabled when SkyEye is enabled)
if settings.ENABLE_SKYEYE:
    app.include_router(marketing_api.router)

# Coherence Engine (Sovereign Swarm)
app.include_router(coherence_api.router)

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
