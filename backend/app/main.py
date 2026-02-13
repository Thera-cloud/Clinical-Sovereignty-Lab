"""
LITTLE NATE — Main API Server Entry Point
Clinical Sovereignty Lab
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncpg

from app.config import settings
# NOTE:
# - `app/routers/__init__.py` contains legacy "stub" routers for auth/users.
# - Real routers live in `app/routers/*.py` and expose `router`.
# Import them explicitly to avoid name collisions with the stubs.
from app.routers import auth, users  # legacy stubs (kept for now)
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
    if getattr(settings, "ENABLE_SOVEREIGN_SWARM", False):
        try:
            from app.services.identity_chain import IdentityChainService
            from app.services.wisdom_mesh import WisdomMeshService
            from app.services.sovereign_immunity import SovereignImmunityService
            from app.services.fibre_manager import FibreManager
            from app.fibres import FIBRE_REGISTRY
            from app.models.fibre import FibreType

            # Identity Chain
            identity_service = IdentityChainService()
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

            # Wisdom Mesh
            wisdom_mesh = WisdomMeshService(db_pool=db_pool)
            try:
                await wisdom_mesh.connect(settings.redis_url)
            except Exception as e:
                print(f"   ⚠️  Wisdom Mesh Redis connection failed: {e}")
            app.state.wisdom_mesh = wisdom_mesh

            # Sovereign Immunity
            immunity = SovereignImmunityService(
                db_pool=db_pool, identity_service=identity_service
            )
            app.state.sovereign_immunity = immunity

            # Fibre Manager
            fibre_manager = FibreManager(
                db_pool=db_pool,
                identity_service=identity_service,
                wisdom_mesh=wisdom_mesh,
            )
            # Register all Fibre types
            for type_name, fibre_cls in FIBRE_REGISTRY.items():
                try:
                    fibre_type = FibreType(type_name)
                    fibre_manager.register_fibre_type(fibre_type, fibre_cls)
                except ValueError:
                    pass
            app.state.fibre_manager = fibre_manager

            print(f"   ✅ Sovereign Swarm initialized "
                  f"({len(FIBRE_REGISTRY)} Fibre types registered)")
        except Exception as e:
            print(f"   ⚠️  Sovereign Swarm failed to start: {e}")
    
    yield
    
    # Shutdown
    print("👋 Shutting down...")
    if skyeye_engine:
        try:
            await skyeye_engine.stop()
        except Exception:
            pass
    if drip_scheduler:
        drip_scheduler.shutdown()
    # Disconnect Wisdom Mesh (Redis cleanup)
    wisdom_mesh = getattr(app.state, "wisdom_mesh", None)
    if wisdom_mesh:
        try:
            await wisdom_mesh.disconnect()
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
