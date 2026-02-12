"""
Billing & Subscription API Routes
Handles Stripe integration, subscription management, and payment processing
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timedelta
import os
import json
import secrets
from pathlib import Path

router = APIRouter(prefix="/api/billing", tags=["billing"])

# Configuration
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))

# Plan Details
PLAN_DETAILS = {
    "TRIAL": {"name": "Trial", "tokens": 10000, "coach_sessions": 0, "price_monthly": 0},
    "STANDARD": {"name": "Standard", "tokens": 50000, "coach_sessions": 0, "price_monthly": 29},
    "TOP_TIER": {"name": "Top Tier", "tokens": 200000, "coach_sessions": 4, "price_monthly": 199},
    "FAMILY": {"name": "Family", "tokens": 300000, "coach_sessions": 6, "price_monthly": 299}
}

# Models
class SubscriptionRequest(BaseModel):
    user_id: str
    plan: str
    billing_cycle: str = "monthly"

class UsageRequest(BaseModel):
    user_id: str
    tokens: int

# Helper functions
def load_json(filepath: Path, default=None):
    if default is None: default = {}
    if not filepath.exists(): return default
    try:
        with open(filepath, 'r') as f: return json.load(f)
    except: return default

def save_json(filepath: Path, data):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w') as f: json.dump(data, f, indent=2, default=str)

@router.get("/plans")
async def get_plans():
    return {"plans": PLAN_DETAILS}

@router.get("/subscription/{user_id}")
async def get_subscription(user_id: str):
    billing = load_json(DATA_DIR / "billing.json")
    sub = billing.get("subscriptions", {}).get(user_id)
    if not sub:
        return {"plan": "TRIAL", "status": "TRIAL_ACTIVE", "details": PLAN_DETAILS["TRIAL"]}
    return {"subscription": sub, "details": PLAN_DETAILS.get(sub.get("plan", "STANDARD"))}

@router.post("/subscribe")
async def create_subscription(req: SubscriptionRequest):
    if req.plan not in PLAN_DETAILS:
        raise HTTPException(400, "Invalid plan")
    
    plan = PLAN_DETAILS[req.plan]
    billing = load_json(DATA_DIR / "billing.json")
    
    sub = {
        "user_id": req.user_id,
        "plan": req.plan,
        "status": "active",
        "tokens_included": plan["tokens"],
        "start_date": str(datetime.now().date()),
        "end_date": str((datetime.now() + timedelta(days=30)).date()),
        "created_at": str(datetime.now())
    }
    
    billing.setdefault("subscriptions", {})[req.user_id] = sub
    save_json(DATA_DIR / "billing.json", billing)
    
    # Update user registry
    registry = load_json(DATA_DIR / "user_registry.json")
    for k, v in registry.items():
        if v.get("profile", {}).get("hardware_id") == req.user_id:
            v["profile"]["subscription_plan"] = req.plan
            v["profile"]["subscription_status"] = "ACTIVE"
            v["profile"]["token_balance"] = plan["tokens"]
            save_json(DATA_DIR / "user_registry.json", registry)
            break
    
    return {"subscription": sub}

@router.get("/usage/{user_id}")
async def get_usage(user_id: str):
    registry = load_json(DATA_DIR / "user_registry.json")
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == user_id:
            return {
                "token_balance": p.get("token_balance", 0),
                "tokens_used_today": p.get("token_usage_today", 0),
                "tokens_used_month": p.get("token_usage_month", 0),
                "plan": p.get("subscription_plan", "TRIAL")
            }
    raise HTTPException(404, "User not found")

@router.post("/use-tokens")
async def use_tokens(req: UsageRequest):
    registry = load_json(DATA_DIR / "user_registry.json")
    for k, v in registry.items():
        p = v.get("profile", {})
        if p.get("hardware_id") == req.user_id:
            balance = p.get("token_balance", 0)
            if balance < req.tokens:
                raise HTTPException(402, "Insufficient tokens")
            p["token_balance"] = balance - req.tokens
            p["token_usage_today"] = p.get("token_usage_today", 0) + req.tokens
            p["token_usage_month"] = p.get("token_usage_month", 0) + req.tokens
            save_json(DATA_DIR / "user_registry.json", registry)
            return {"remaining": p["token_balance"]}
    raise HTTPException(404, "User not found")

@router.get("/transactions/{user_id}")
async def get_transactions(user_id: str, limit: int = 20):
    billing = load_json(DATA_DIR / "billing.json")
    txns = [t for t in billing.get("transactions", []) if t.get("user_id") == user_id]
    return {"transactions": txns[-limit:]}
