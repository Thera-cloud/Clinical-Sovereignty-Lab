"""
LITTLE NATE — FastAPI REST API Server
Version: 1.0
Date: January 21, 2026

This wraps the existing bridge_server_hybrid.py functionality with a REST API
while maintaining backward compatibility with WebSocket clients.

Run with: uvicorn api_server:app --reload --port 8000
"""

from fastapi import FastAPI, HTTPException, Depends, status, Request, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum
import asyncio
import asyncpg
import json
import os
import secrets
import hashlib
from pathlib import Path

# =============================================================================
# CONFIGURATION
# =============================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/little_nate")
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is required — generate with: openssl rand -hex 32")
JWT_EXPIRY_HOURS = 24
REQUIRED_CONSENT_VERSION = "v12.6_2026_FINAL"

# Legacy support - load from existing paths
MASTER_PATH = Path(__file__).resolve().parent
VAULT_ROOT = MASTER_PATH / "Vaults"
REGISTRY_FILE = MASTER_PATH / "user_registry.json"

# =============================================================================
# FASTAPI APP SETUP
# =============================================================================

app = FastAPI(
    title="Little Nate API",
    description="REST API for Little Nate AI Therapy Platform",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip() for o in os.getenv(
            "CORS_ORIGINS",
            "https://app.sovereignsanctuary.net,https://coach.sovereignsanctuary.net,https://command.sovereignsanctuary.net,https://api.sovereignsanctuary.net"
        ).split(",") if o.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()

# =============================================================================
# DATABASE CONNECTION
# =============================================================================

class Database:
    pool: asyncpg.Pool = None

db = Database()

@app.on_event("startup")
async def startup():
    """Initialize database connection pool"""
    try:
        db.pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=5,
            max_size=20,
            command_timeout=60
        )
        print(f"✅ Database connected: {DATABASE_URL}")
    except Exception as e:
        print(f"⚠️ Database connection failed: {e}")
        print("   Falling back to JSON file storage")
        db.pool = None

    # Register Sovereign Vault API (requires db pool)
    if db.pool:
        try:
            from app.routers.vault_api import create_vault_router
            vault_router = create_vault_router(db.pool)
            app.include_router(vault_router)
            print("✅ Sovereign Vault API registered")
        except Exception as e:
            print(f"⚠️ Sovereign Vault API failed: {e}")

@app.on_event("shutdown")
async def shutdown():
    """Close database connections"""
    if db.pool:
        await db.pool.close()

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class UserRole(str, Enum):
    CLIENT = "CLIENT"
    COACH = "COACH"
    ADMIN = "ADMIN"
    RESEARCHER = "RESEARCHER"

class UserTier(str, Enum):
    MASTER = "MASTER"
    SUPERVISOR = "SUPERVISOR"
    TOP = "TOP"
    STANDARD = "STANDARD"
    TRIAL = "TRIAL"
    DEPENDENT = "DEPENDENT"

class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRIAL_ACTIVE = "TRIAL_ACTIVE"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    FAMILY_PLAN_ACTIVE = "FAMILY_PLAN_ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"

# --- Auth Models ---

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=3)
    expected_role: Optional[UserRole] = None

class LoginResponse(BaseModel):
    type: str = "login_success"
    token: str
    profile: Dict[str, Any]

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6)
    name: str = Field(..., min_length=1, max_length=100)
    role: UserRole = UserRole.CLIENT
    dob: Optional[str] = None  # YYYY-MM-DD
    consent_agreed: bool = True
    consent_version: str = REQUIRED_CONSENT_VERSION
    modality: str = "General"
    parent_username: Optional[str] = None  # For dependent accounts
    
    @validator('dob')
    def validate_dob(cls, v):
        if v:
            try:
                datetime.strptime(v, '%Y-%m-%d')
            except ValueError:
                raise ValueError('DOB must be in YYYY-MM-DD format')
        return v

class RegisterResponse(BaseModel):
    type: str = "register_success"
    message: str
    user_id: str

# --- User Models ---

class UserProfile(BaseModel):
    id: str
    username: str
    name: str
    role: UserRole
    tier: UserTier
    family_id: Optional[str]
    is_minor: bool = False
    consent_version: Optional[str]
    subscription_status: SubscriptionStatus

class UserUpdate(BaseModel):
    name: Optional[str]
    tier: Optional[UserTier]
    subscription_status: Optional[SubscriptionStatus]

# --- Session Models ---

class SessionType(str, Enum):
    AI = "AI"
    COACH = "COACH"
    FAMILY = "FAMILY"
    GROUP = "GROUP"

class SessionCreate(BaseModel):
    user_id: str
    coach_id: Optional[str]
    session_type: SessionType
    platform: Optional[str]
    scheduled_at: Optional[datetime]

class SessionResponse(BaseModel):
    id: str
    user_id: str
    coach_id: Optional[str]
    session_type: SessionType
    status: str
    started_at: Optional[datetime]
    duration_seconds: Optional[int]

# --- Nevedal Models ---

class NevedalMetrics(BaseModel):
    c_emo: float = Field(..., ge=0, le=1)
    p_ent: float = Field(..., ge=0, le=1)
    t_tunnel: float = Field(..., ge=0, le=1)
    gamma_env: float = Field(..., ge=0, le=1)
    e_g_joint: float = Field(..., ge=0, le=1)
    cee_window: bool = False
    biometrics: Optional[Dict[str, Any]] = None

class NevedalResponse(BaseModel):
    user_id: str
    metrics: NevedalMetrics
    recorded_at: datetime
    interpretation: Optional[str]

# --- Coach Models ---

class CoachDashboard(BaseModel):
    clients: List[Dict[str, Any]]
    schedule: List[Dict[str, Any]]
    pending_notes: int
    upcoming_sessions: int

class CoachNoteSubmit(BaseModel):
    client_id: str
    session_id: Optional[str]
    content: str

# --- Admin Models ---

class DashboardStats(BaseModel):
    total_clients: int
    total_coaches: int
    live_sessions: int
    critical_alerts: int
    pending_notes: int
    today_spend_cents: int

class AuditLogEntry(BaseModel):
    id: int
    logged_at: datetime
    admin_username: str
    action_type: str
    target_type: Optional[str]
    target_name: Optional[str]
    description: str

# =============================================================================
# SECURITY UTILITIES
# =============================================================================

def hash_password(password: str) -> str:
    """Hash password using PBKDF2"""
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return f"{salt}${hashed.hex()}"

def verify_password(password: str, stored: str) -> bool:
    """Verify password against stored hash"""
    try:
        if '$' not in stored:
            return password == stored  # Legacy plain-text support
        salt, hashed = stored.split('$', 1)
        check = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return check.hex() == hashed
    except Exception:
        return False

_auth_redis = None
_REDIS_URL_SNAPSHOT = os.getenv("REDIS_URL", "")
_REDIS_PW_SNAPSHOT = os.getenv("REDIS_PASSWORD", "")

async def _get_auth_redis():
    """Lazy-connect to Redis for token validation (matches bridge's token store).
    Uses REDIS_URL captured at import time to avoid load_dotenv(override=True) clobbering."""
    global _auth_redis
    if _auth_redis is not None:
        try:
            await _auth_redis.ping()
            return _auth_redis
        except Exception:
            _auth_redis = None
    try:
        import redis.asyncio as aioredis
        if _REDIS_URL_SNAPSHOT:
            _auth_redis = aioredis.from_url(
                _REDIS_URL_SNAPSHOT, decode_responses=True, socket_connect_timeout=5,
            )
        else:
            _auth_redis = aioredis.Redis(
                host="redis", port=6379,
                password=_REDIS_PW_SNAPSHOT or None,
                decode_responses=True, socket_connect_timeout=5,
            )
        await _auth_redis.ping()
    except Exception as e:
        print(f"[AUTH] Redis connection failed: {e}")
        _auth_redis = None
    return _auth_redis


_REDIS_KEY_PREFIX = os.environ.get("REDIS_KEY_PREFIX", "nate")
_REDIS_KEY_ENV = os.environ.get("ENVIRONMENT", "production")

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict[str, Any]:
    """Validate bridge token against Redis (shared with bridge container)."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    token = credentials.credentials

    # === AUDIT TOKEN BYPASS ===
    # Trust auditors probe every protected endpoint via SKYEYE_AUDIT_TOKEN.
    # This MUST be checked FIRST — before any Redis/JWT/DB lookup that can
    # 401 — so newly-added auth middleware never silently drops audit traffic.
    # Adding new endpoints requires zero per-route bypass logic.
    audit_token = os.environ.get("SKYEYE_AUDIT_TOKEN")
    if audit_token and token == audit_token:
        return {
            "user_id": "AUDIT_SYSTEM",
            "id": "AUDIT_SYSTEM",
            "hardware_id": "AUDIT_SYSTEM",
            "username": "audit_system",
            "name": "Audit System",
            "role": "ADMIN",
            "tier": "TOP_TIER",
            "is_audit": True,
        }

    # Primary path: Redis token store (written by bridge on login)
    # Key format must match bridge: {prefix}:{env}:auth:{token}
    r = await _get_auth_redis()
    if r:
        try:
            token_key = f"{_REDIS_KEY_PREFIX}:{_REDIS_KEY_ENV}:auth:{token}"
            raw = await r.get(token_key)
            if raw:
                profile = json.loads(raw)
                profile.pop("password_hash", None)
                profile.pop("password", None)
                creds = profile.get("credentials")
                if isinstance(creds, dict):
                    creds.pop("password", None)
                return profile
        except Exception:
            pass

    # Fallback: PostgreSQL active_tokens table
    if db.pool:
        try:
            async with db.pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT u.id, u.username, u.name, u.role, u.tier,
                           u.hardware_id, u.family_id, u.company_id,
                           u.subscription_status, u.profile_data,
                           u.created_at, u.updated_at
                    FROM users u
                    JOIN active_tokens t ON t.user_id = u.id
                    WHERE t.token = $1 AND t.is_valid = TRUE
                      AND t.expires_at > NOW()
                """, token)
                if row:
                    return dict(row)
        except Exception:
            pass

    raise HTTPException(status_code=401, detail="Invalid or expired token")

async def require_admin(user: Dict = Depends(get_current_user)) -> Dict:
    """Require admin role"""
    if user.get('is_audit'):
        return user
    if user.get('role') != 'ADMIN':
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

async def require_corp_admin(user: Dict = Depends(get_current_user)) -> Dict:
    """Require corporate admin or full admin role"""
    if user.get('is_audit'):
        return user
    if user.get('role') not in ['CORP_ADMIN', 'ADMIN']:
        raise HTTPException(status_code=403, detail="Corporate admin access required")
    return user

async def require_coach(user: Dict = Depends(get_current_user)) -> Dict:
    """Require coach or admin role"""
    if user.get('is_audit'):
        return user
    if user.get('role') not in ['COACH', 'ADMIN']:
        raise HTTPException(status_code=403, detail="Coach access required")
    return user

# =============================================================================
# AUDIT LOGGING
# =============================================================================

async def log_audit(
    admin_id: str,
    admin_username: str,
    action_type: str,
    description: str,
    target_type: str = None,
    target_id: str = None,
    target_name: str = None,
    old_value: Dict = None,
    new_value: Dict = None,
    request: Request = None
):
    """Log administrative action to audit trail"""
    if db.pool:
        async with db.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO audit_log (
                    admin_id, admin_username, admin_role, ip_address, user_agent,
                    action_type, target_type, target_id, target_name,
                    description, old_value, new_value
                ) VALUES ($1, $2, 'ADMIN', $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
                admin_id,
                admin_username,
                str(request.client.host) if request else None,
                request.headers.get('user-agent') if request else None,
                action_type,
                target_type,
                target_id,
                target_name,
                description,
                json.dumps(old_value) if old_value else None,
                json.dumps(new_value) if new_value else None
            )

# =============================================================================
# AUTH ENDPOINTS
# =============================================================================

@app.post("/api/auth/login", response_model=LoginResponse, tags=["Auth"])
async def login(data: LoginRequest):
    """
    Authenticate user and return JWT token.
    Compatible with existing bridge_server_hybrid.py login_request handler.
    """
    if db.pool:
        # PostgreSQL auth
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE username = $1 AND deleted_at IS NULL",
                data.username
            )
            
            if not row:
                raise HTTPException(status_code=401, detail="USER_NOT_FOUND")
            
            if not verify_password(data.password, row['password_hash']):
                raise HTTPException(status_code=401, detail="INVALID_PASSWORD")
            
            user = dict(row)
            
            # Check consent
            if user.get('consent_version') != REQUIRED_CONSENT_VERSION:
                raise HTTPException(status_code=403, detail="LEGAL_UPDATE_REQUIRED")
            
            # Check subscription
            if user.get('subscription_status') == 'PENDING_VERIFICATION':
                raise HTTPException(status_code=403, detail="ACCOUNT_PENDING_APPROVAL")
            
            # Check role if specified
            if data.expected_role and user['role'] != 'ADMIN' and user['role'] != data.expected_role:
                raise HTTPException(status_code=403, detail="WRONG_PORTAL")
            
            # Generate token
            token = secrets.token_hex(32)
            expires_at = datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
            
            await conn.execute("""
                INSERT INTO active_tokens (token, user_id, expires_at)
                VALUES ($1, $2, $3)
            """, token, user['id'], expires_at)
            
            # Build profile response (matching existing format)
            profile = {
                "id": str(user['id']),
                "username": user['username'],
                "name": user['name'],
                "role": user['role'],
                "tier": user['tier'],
                "family_id": str(user['family_id']) if user['family_id'] else None,
                "hardware_id": user['hardware_id'],
                "consent_version": user['consent_version'],
                "subscription_status": user['subscription_status']
            }
            
            return LoginResponse(token=token, profile=profile)
    
    else:
        # Fallback to JSON file (existing bridge_server logic)
        from bridge_server_hybrid import authenticate_user
        token, result = authenticate_user(data.username, data.password, data.expected_role)
        
        if token is None:
            raise HTTPException(status_code=401, detail=result)
        
        return LoginResponse(token=token, profile=result)

@app.post("/api/auth/register", response_model=RegisterResponse, tags=["Auth"])
async def register(data: RegisterRequest):
    """
    Register new user account.
    Compatible with existing bridge_server_hybrid.py register_request handler.
    """
    if not data.consent_agreed:
        raise HTTPException(status_code=400, detail="CONSENT_REQUIRED")
    
    if db.pool:
        async with db.pool.acquire() as conn:
            # Check username availability
            existing = await conn.fetchval(
                "SELECT id FROM users WHERE username = $1",
                data.username
            )
            if existing:
                raise HTTPException(status_code=409, detail="USERNAME_TAKEN")
            
            # Handle family/guardian linking
            family_id = None
            guardian_id = None
            is_minor = False
            
            if data.parent_username:
                parent = await conn.fetchrow(
                    "SELECT id, family_id FROM users WHERE username = $1",
                    data.parent_username
                )
                if not parent:
                    raise HTTPException(status_code=400, detail="GUARDIAN_NOT_FOUND")
                
                guardian_id = parent['id']
                family_id = parent['family_id']
                
                # Check if minor based on DOB
                if data.dob:
                    dob = datetime.strptime(data.dob, '%Y-%m-%d')
                    age = (datetime.now() - dob).days // 365
                    is_minor = age < 18
            
            # Create family if needed and not dependent
            if not family_id and data.role == UserRole.CLIENT:
                family_code = f"FAM_{secrets.token_hex(4).upper()}"
                family_id = await conn.fetchval("""
                    INSERT INTO families (family_code) VALUES ($1) RETURNING id
                """, family_code)
            
            # Hash password
            password_hash = hash_password(data.password)
            
            # Insert user
            user_id = await conn.fetchval("""
                INSERT INTO users (
                    username, password_hash, name, role, tier,
                    dob, family_id, guardian_id, is_minor,
                    consent_version, consent_date, subscription_status,
                    intake_data
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW(), $11, $12)
                RETURNING id
            """,
                data.username,
                password_hash,
                data.name,
                data.role.value,
                'DEPENDENT' if data.parent_username else 'STANDARD',
                datetime.strptime(data.dob, '%Y-%m-%d').date() if data.dob else None,
                family_id,
                guardian_id,
                is_minor,
                data.consent_version,
                'FAMILY_PLAN_ACTIVE' if data.parent_username else 'TRIAL_ACTIVE',
                json.dumps({"goals": [], "modality": data.modality})
            )
            
            return RegisterResponse(
                message="Account created successfully",
                user_id=str(user_id)
            )
    
    else:
        # Fallback to JSON file
        from bridge_server_hybrid import register_new_user
        success, result = register_new_user(data.dict())
        
        if not success:
            raise HTTPException(status_code=400, detail=result)
        
        return RegisterResponse(message="Account created", user_id=result)

@app.post("/api/auth/logout", tags=["Auth"])
async def logout(user: Dict = Depends(get_current_user), credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Invalidate current token"""
    if db.pool:
        async with db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE active_tokens SET is_valid = FALSE WHERE token = $1",
                credentials.credentials
            )
    return {"message": "Logged out successfully"}

# =============================================================================
# USER ENDPOINTS
# =============================================================================

@app.get("/api/users", tags=["Users"])
async def list_users(
    role: Optional[UserRole] = None,
    family_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    admin: Dict = Depends(require_admin)
):
    """List all users (admin only)"""
    if db.pool:
        async with db.pool.acquire() as conn:
            query = "SELECT * FROM users WHERE deleted_at IS NULL"
            params = []
            
            if role:
                params.append(role.value)
                query += f" AND role = ${len(params)}"
            
            if family_id:
                params.append(family_id)
                query += f" AND family_id = ${len(params)}"
            
            query += f" ORDER BY created_at DESC LIMIT {limit} OFFSET {offset}"
            
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
    
    else:
        # JSON fallback
        with open(REGISTRY_FILE) as f:
            registry = json.load(f)
        
        users = []
        for key, val in registry.items():
            profile = val.get('profile', {})
            if role and profile.get('role') != role.value:
                continue
            if family_id and profile.get('family_id') != family_id:
                continue
            users.append(profile)
        
        return users[offset:offset+limit]

@app.get("/api/users/{user_id}", tags=["Users"])
async def get_user(user_id: str, current_user: Dict = Depends(get_current_user)):
    """Get user details"""
    if db.pool:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE id = $1 AND deleted_at IS NULL",
                user_id
            )
            if not row:
                raise HTTPException(status_code=404, detail="User not found")
            return dict(row)
    
    raise HTTPException(status_code=404, detail="User not found")

@app.get("/api/users/{user_id}/nevedal", response_model=NevedalResponse, tags=["Users"])
async def get_user_nevedal(user_id: str, current_user: Dict = Depends(get_current_user)):
    """Get user's latest Nevedal metrics"""
    if db.pool:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM nevedal_metrics 
                WHERE user_id = $1 
                ORDER BY recorded_at DESC LIMIT 1
            """, user_id)
            
            if not row:
                # Return default metrics
                return NevedalResponse(
                    user_id=user_id,
                    metrics=NevedalMetrics(
                        c_emo=0.5, p_ent=0.5, t_tunnel=0.5,
                        gamma_env=0.3, e_g_joint=0.4
                    ),
                    recorded_at=datetime.utcnow(),
                    interpretation="No metrics recorded yet"
                )
            
            # Decrypt biometric fields that may have been encrypted at rest
            biometrics_data = row['biometrics']
            if biometrics_data and isinstance(biometrics_data, dict):
                try:
                    from app.field_encryption import decrypt_fields
                    biometrics_data = decrypt_fields(biometrics_data)
                except Exception:
                    pass  # Graceful fallback
            
            return NevedalResponse(
                user_id=user_id,
                metrics=NevedalMetrics(
                    c_emo=float(row['c_emo']),
                    p_ent=float(row['p_ent']),
                    t_tunnel=float(row['t_tunnel']),
                    gamma_env=float(row['gamma_env']),
                    e_g_joint=float(row['e_g_joint']),
                    cee_window=row['cee_window'],
                    biometrics=biometrics_data
                ),
                recorded_at=row['recorded_at']
            )
    
    raise HTTPException(status_code=501, detail="Requires PostgreSQL")

@app.post("/api/users/{user_id}/reset-password", tags=["Users"])
async def reset_password(
    user_id: str,
    request: Request,
    admin: Dict = Depends(require_admin)
):
    """Reset user's password (admin only)"""
    new_password = secrets.token_urlsafe(12)
    
    if db.pool:
        async with db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET password_hash = $1 WHERE id = $2",
                hash_password(new_password),
                user_id
            )
            
            await log_audit(
                admin_id=admin['id'],
                admin_username=admin['username'],
                action_type='SECURITY',
                description=f"Reset password for user",
                target_type='user',
                target_id=user_id,
                request=request
            )
    
    return {"new_password": new_password}

@app.post("/api/users/{user_id}/wipe-memory", tags=["Users"])
async def wipe_memory(
    user_id: str,
    request: Request,
    admin: Dict = Depends(require_admin)
):
    """Wipe user's memory (RTBF compliance)"""
    if db.pool:
        async with db.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM memory_ledger WHERE user_id = $1",
                user_id
            )
            await conn.execute(
                "DELETE FROM nevedal_metrics WHERE user_id = $1",
                user_id
            )
            
            await log_audit(
                admin_id=admin['id'],
                admin_username=admin['username'],
                action_type='DELETE',
                description=f"Wiped all memory for user (RTBF)",
                target_type='user',
                target_id=user_id,
                compliance_flags=['RTBF'],
                request=request
            )
    
    return {"message": "Memory wiped successfully"}

# =============================================================================
# COACH ENDPOINTS
# =============================================================================

@app.get("/api/coach/dashboard", response_model=CoachDashboard, tags=["Coach"])
async def get_coach_dashboard(coach: Dict = Depends(require_coach)):
    """Get coach dashboard data"""
    if db.pool:
        async with db.pool.acquire() as conn:
            # Get assigned clients (all clients for now, can be filtered by assignment)
            clients = await conn.fetch("""
                SELECT id, name, tier, family_id 
                FROM users 
                WHERE role = 'CLIENT' AND deleted_at IS NULL
                ORDER BY name
            """)
            
            # Get schedule
            schedule = await conn.fetch("""
                SELECT s.*, u.name as client_name
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.coach_id = $1 AND s.scheduled_at > NOW()
                ORDER BY s.scheduled_at
                LIMIT 10
            """, coach['id'])
            
            # Get pending notes count
            pending_notes = await conn.fetchval("""
                SELECT COUNT(*) FROM coach_notes 
                WHERE coach_id = $1 AND status = 'PENDING'
            """, coach['id'])
            
            return CoachDashboard(
                clients=[dict(c) for c in clients],
                schedule=[dict(s) for s in schedule],
                pending_notes=pending_notes or 0,
                upcoming_sessions=len(schedule)
            )
    
    else:
        # JSON fallback using existing CoachNexus
        from bridge_server_hybrid import CoachNexus, VAULT_ROOT
        nexus = CoachNexus(VAULT_ROOT)
        data = nexus.get_dashboard(coach)
        
        return CoachDashboard(
            clients=data.get('clients', []),
            schedule=data.get('schedule', []),
            pending_notes=0,
            upcoming_sessions=len(data.get('schedule', []))
        )

@app.post("/api/coach/notes", tags=["Coach"])
async def submit_coach_note(note: CoachNoteSubmit, coach: Dict = Depends(require_coach)):
    """Submit session notes for review"""
    if db.pool:
        async with db.pool.acquire() as conn:
            # Simple PII detection (enhance with ML in production)
            pii_detected = any(pattern in note.content.lower() for pattern in [
                'ssn', 'social security', 'credit card', 'password'
            ])
            
            note_id = await conn.fetchval("""
                INSERT INTO coach_notes (coach_id, client_id, session_id, content, pii_detected)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, coach['id'], note.client_id, note.session_id, note.content, pii_detected)
            
            return {"id": str(note_id), "pii_detected": pii_detected}
    
    else:
        # JSON fallback
        from bridge_server_hybrid import CoachNexus, VAULT_ROOT
        nexus = CoachNexus(VAULT_ROOT)
        result = nexus.save_session_note(coach, note.content)
        return {"message": result}

@app.get("/api/coach/clients/{client_id}/brief", tags=["Coach"])
async def get_presession_brief(client_id: str, coach: Dict = Depends(require_coach)):
    """Get pre-session brief for client"""
    if db.pool:
        async with db.pool.acquire() as conn:
            # Get client info
            client = await conn.fetchrow(
                "SELECT * FROM users WHERE id = $1",
                client_id
            )
            
            if not client:
                raise HTTPException(status_code=404, detail="Client not found")
            
            # Get recent memory
            memories = await conn.fetch("""
                SELECT * FROM memory_ledger 
                WHERE user_id = $1 
                ORDER BY created_at DESC LIMIT 10
            """, client_id)
            
            # Get recent metrics
            metrics = await conn.fetchrow("""
                SELECT * FROM nevedal_metrics
                WHERE user_id = $1
                ORDER BY recorded_at DESC LIMIT 1
            """, client_id)
            
            # Get family context
            family_members = []
            if client['family_id']:
                family_members = await conn.fetch("""
                    SELECT name, role FROM users 
                    WHERE family_id = $1 AND id != $2
                """, client['family_id'], client_id)
            
            return {
                "client": dict(client),
                "recent_topics": [m['content'][:100] for m in memories],
                "nevedal_state": dict(metrics) if metrics else None,
                "family_context": [dict(f) for f in family_members],
                "suggestions": [
                    "Review progress on previously discussed topics",
                    "Check in on emotional state before diving deep"
                ]
            }
    
    raise HTTPException(status_code=501, detail="Requires PostgreSQL")

# =============================================================================
# ADMIN ENDPOINTS
# =============================================================================

@app.get("/api/admin/dashboard/stats", response_model=DashboardStats, tags=["Admin"])
async def get_dashboard_stats(admin: Dict = Depends(require_admin)):
    """Get admin dashboard statistics"""
    if db.pool:
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM v_dashboard_stats")
            return DashboardStats(**dict(row))
    
    else:
        # JSON fallback
        with open(REGISTRY_FILE) as f:
            registry = json.load(f)
        
        clients = sum(1 for v in registry.values() if v['profile'].get('role') == 'CLIENT')
        coaches = sum(1 for v in registry.values() if v['profile'].get('role') == 'COACH')
        
        return DashboardStats(
            total_clients=clients,
            total_coaches=coaches,
            live_sessions=0,
            critical_alerts=0,
            pending_notes=0,
            today_spend_cents=0
        )

@app.get("/api/admin/crisis-watchlist", tags=["Admin"])
async def get_crisis_watchlist(admin: Dict = Depends(require_admin)):
    """Get active crisis watchlist"""
    if db.pool:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT cw.*, u.name as user_name, c.name as coach_name
                FROM crisis_watchlist cw
                JOIN users u ON u.id = cw.user_id
                LEFT JOIN users c ON c.id = cw.assigned_coach_id
                WHERE cw.resolved = FALSE
                ORDER BY 
                    CASE cw.severity 
                        WHEN 'CRITICAL' THEN 1 
                        WHEN 'WARNING' THEN 2 
                        ELSE 3 
                    END,
                    cw.created_at DESC
            """)
            return [dict(row) for row in rows]
    
    return []

@app.get("/api/admin/audit-log", tags=["Admin"])
async def get_audit_log(
    limit: int = 100,
    offset: int = 0,
    action_type: Optional[str] = None,
    admin: Dict = Depends(require_admin)
):
    """Get audit log entries"""
    if db.pool:
        async with db.pool.acquire() as conn:
            query = "SELECT * FROM audit_log"
            params = []
            
            if action_type:
                params.append(action_type)
                query += f" WHERE action_type = ${len(params)}"
            
            query += f" ORDER BY logged_at DESC LIMIT {limit} OFFSET {offset}"
            
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]
    
    return []

@app.get("/api/admin/night-school/pending", tags=["Admin"])
async def get_pending_notes(admin: Dict = Depends(require_admin)):
    """Get coach notes pending approval"""
    if db.pool:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT cn.*, u.name as coach_name, c.name as client_name
                FROM coach_notes cn
                JOIN users u ON u.id = cn.coach_id
                JOIN users c ON c.id = cn.client_id
                WHERE cn.status = 'PENDING'
                ORDER BY cn.created_at
            """)
            return [dict(row) for row in rows]
    
    return []

@app.post("/api/admin/night-school/notes/{note_id}/approve", tags=["Admin"])
async def approve_note(
    note_id: str,
    request: Request,
    admin: Dict = Depends(require_admin)
):
    """Approve coach note for wisdom ingestion"""
    if db.pool:
        async with db.pool.acquire() as conn:
            # Get note
            note = await conn.fetchrow(
                "SELECT * FROM coach_notes WHERE id = $1",
                note_id
            )
            
            if not note:
                raise HTTPException(status_code=404, detail="Note not found")
            
            # Update status
            await conn.execute("""
                UPDATE coach_notes 
                SET status = 'APPROVED', reviewed_by = $1, reviewed_at = NOW()
                WHERE id = $2
            """, admin['id'], note_id)
            
            # Add to wisdom
            await conn.execute("""
                INSERT INTO wisdom_entries (version, category, source, content, approved, approved_by, approved_at)
                VALUES ('current', 'coach_notes', 'coach_note', $1, TRUE, $2, NOW())
            """, note['redacted_content'] or note['content'], admin['id'])
            
            await log_audit(
                admin_id=admin['id'],
                admin_username=admin['username'],
                action_type='APPROVE',
                description=f"Approved coach note for wisdom ingestion",
                target_type='coach_note',
                target_id=note_id,
                request=request
            )
            
            return {"message": "Note approved and added to wisdom"}
    
    raise HTTPException(status_code=501, detail="Requires PostgreSQL")

# =============================================================================
# NEVEDAL ENDPOINTS
# =============================================================================

@app.post("/api/nevedal/compute", tags=["Nevedal"])
async def compute_nevedal(
    user_id: str,
    biometrics: Dict[str, Any],
    session_id: Optional[str] = None,
    dyad_partner_id: Optional[str] = None,
    current_user: Dict = Depends(get_current_user)
):
    """
    Compute Nevedal metrics from biometrics.
    
    Formula: C_emo(t) = [β · p_ent · T_tunnel] / [γ_env + E_G^(joint)/ℏ]
    """
    # Extract biometric signals
    subject_a = biometrics.get('subject_a', {})
    subject_b = biometrics.get('subject_b', {})
    synchrony = biometrics.get('synchrony', {})
    
    # Compute p_ent (entanglement) from synchrony
    hrv_sync = synchrony.get('hrv', 0.5)
    breath_sync = synchrony.get('breath', 0.5)
    gaze_sync = synchrony.get('gaze', 0.5)
    posture_sync = synchrony.get('posture', 0.5)
    p_ent = (hrv_sync + breath_sync + gaze_sync + posture_sync) / 4
    
    # Compute t_tunnel from approach behaviors
    gaze_contact = subject_a.get('gaze_contact', 0.5)
    body_lean = min(abs(subject_a.get('body_lean', 0)) / 30, 1.0)  # Normalize to 0-1
    t_tunnel = (gaze_contact + body_lean) / 2
    
    # Compute gamma_env from arousal signals
    eda_a = subject_a.get('eda', 2.0)
    eda_b = subject_b.get('eda', 2.0)
    gamma_env = min((eda_a + eda_b) / 10, 1.0)  # Normalize
    
    # Compute e_g_joint (emotional load) - simplified
    voice_stress = subject_a.get('voice_stress', 0.3)
    e_g_joint = voice_stress
    
    # Constants
    beta = 1.0
    h_bar = 1.0
    
    # Compute C_emo
    numerator = beta * p_ent * t_tunnel
    denominator = gamma_env + (e_g_joint / h_bar)
    c_emo = numerator / max(denominator, 0.01)  # Prevent division by zero
    c_emo = min(max(c_emo, 0), 1)  # Clamp to 0-1
    
    # Detect CEE window
    cee_window = p_ent > 0.7 and t_tunnel > 0.6 and gamma_env < 0.3 and e_g_joint > 0.4
    
    result = {
        "c_emo": round(c_emo, 5),
        "p_ent": round(p_ent, 5),
        "t_tunnel": round(t_tunnel, 5),
        "gamma_env": round(gamma_env, 5),
        "e_g_joint": round(e_g_joint, 5),
        "cee_window": cee_window
    }
    
    # Store in database — resolve hardware_id to UUID for FK columns
    if db.pool:
        async with db.pool.acquire() as conn:
            user_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1",
                user_id,
            )
            if user_uuid:
                import uuid as _uuid_mod
                session_uuid = None
                if session_id:
                    try:
                        parsed = _uuid_mod.UUID(str(session_id))
                        exists = await conn.fetchval("SELECT 1 FROM sessions WHERE id = $1", parsed)
                        if exists:
                            session_uuid = parsed
                    except (ValueError, AttributeError):
                        pass
                dyad_uuid = None
                if dyad_partner_id:
                    dyad_uuid = await conn.fetchval(
                        "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1",
                        dyad_partner_id,
                    )
                await conn.execute("""
                    INSERT INTO nevedal_metrics (
                        user_id, session_id, dyad_partner_id,
                        c_emo, p_ent, t_tunnel, gamma_env, e_g_joint,
                        cee_window, biometrics
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                    user_uuid, session_uuid, dyad_uuid,
                    result['c_emo'], result['p_ent'], result['t_tunnel'],
                    result['gamma_env'], result['e_g_joint'],
                    cee_window, json.dumps(biometrics)
                )
    
    return result

@app.get("/api/nevedal/history/{user_id}", tags=["Nevedal"])
async def get_nevedal_history(
    user_id: str,
    limit: int = 100,
    current_user: Dict = Depends(get_current_user)
):
    """Get historical Nevedal metrics for a user"""
    if db.pool:
        async with db.pool.acquire() as conn:
            user_uuid = await conn.fetchval(
                "SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1",
                user_id,
            )
            if not user_uuid:
                return []
            rows = await conn.fetch("""
                SELECT * FROM nevedal_metrics
                WHERE user_id = $1
                ORDER BY recorded_at DESC
                LIMIT $2
            """, user_uuid, limit)
            return [dict(row) for row in rows]
    
    return []

# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint"""
    db_status = "connected" if db.pool else "disconnected (using JSON fallback)"
    return {
        "status": "healthy",
        "database": db_status,
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
