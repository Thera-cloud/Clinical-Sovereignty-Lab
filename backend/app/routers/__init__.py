# Little Nate API Routers
# Each router handles a specific domain of the API

from fastapi import APIRouter

# Stub routers - these will be populated with actual code
# For now, they're empty to allow the app to start

auth = APIRouter(prefix="/api/auth", tags=["auth"])
users = APIRouter(prefix="/api/users", tags=["users"])
sessions = APIRouter(prefix="/api/sessions", tags=["sessions"])
admin = APIRouter(prefix="/api/admin", tags=["admin"])
coach = APIRouter(prefix="/api/coach", tags=["coach"])
billing = APIRouter(prefix="/api/billing", tags=["billing"])
nevedal = APIRouter(prefix="/api/nevedal", tags=["nevedal"])
night_school = APIRouter(prefix="/api/night-school", tags=["night_school"])


# Placeholder endpoints for each router
@auth.post("/login")
async def login():
    return {"message": "Login endpoint - implement me"}

@auth.post("/register")
async def register():
    return {"message": "Register endpoint - implement me"}

@users.get("/")
async def list_users():
    return {"message": "List users endpoint - implement me"}

@sessions.get("/")
async def list_sessions():
    return {"message": "List sessions endpoint - implement me"}

@admin.get("/dashboard")
async def admin_dashboard():
    return {"message": "Admin dashboard endpoint - implement me"}

@coach.get("/clients")
async def coach_clients():
    return {"message": "Coach clients endpoint - implement me"}

@billing.get("/subscription")
async def get_subscription():
    return {"message": "Billing subscription endpoint - implement me"}

@nevedal.get("/status")
async def nevedal_status():
    return {"message": "Nevedal status endpoint - implement me"}

@night_school.get("/versions")
async def night_school_versions():
    return {"message": "Night School versions endpoint - implement me"}
