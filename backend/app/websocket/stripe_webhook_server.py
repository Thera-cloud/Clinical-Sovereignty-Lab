"""
LITTLE NATE - Stripe Webhook Server
Version: 1.0
Date: January 23, 2026

FastAPI server for handling Stripe webhooks.
Run alongside the main WebSocket server on a different port.

Usage:
    uvicorn stripe_webhook_server:app --host 0.0.0.0 --port 8766
"""

import os
import json
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import asyncio

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

# Import the billing system
from stripe_billing import StripeBillingSystem

# Data directory
DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))

# Registry functions
REGISTRY_FILE = DATA_DIR / "user_registry.json"

def load_registry():
    if not REGISTRY_FILE.exists():
        return {}
    with open(REGISTRY_FILE) as f:
        return json.load(f)

def save_registry(data):
    with open(REGISTRY_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)

# Initialize billing system
billing_system = StripeBillingSystem(
    DATA_DIR,
    stripe_key=os.getenv("STRIPE_SECRET_KEY"),
    webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET"),
    registry_loader=load_registry,
    registry_saver=save_registry
)

# FastAPI app
app = FastAPI(
    title="Little Nate - Stripe Webhooks",
    description="Webhook handler for Stripe events",
    version="1.0"
)


@app.get("/")
async def root():
    return {"status": "ok", "service": "stripe-webhooks"}


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "stripe_enabled": billing_system.stripe_enabled
    }


@app.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature")
):
    """
    Handle Stripe webhook events.
    
    Configure this URL in Stripe Dashboard:
    https://yourdomain.com/webhook/stripe
    
    Events to enable:
    - checkout.session.completed
    - customer.subscription.created
    - customer.subscription.updated
    - customer.subscription.deleted
    - invoice.paid
    - invoice.payment_failed
    """
    
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
    
    # Get raw body
    payload = await request.body()
    
    # Handle webhook
    success, message = await billing_system.handle_webhook(payload, stripe_signature)
    
    if not success and "Invalid" in message:
        raise HTTPException(status_code=400, detail=message)
    
    return JSONResponse(
        status_code=200,
        content={"received": True, "message": message}
    )


@app.post("/webhook/stripe/test")
async def stripe_webhook_test(request: Request):
    """
    Test endpoint for development (no signature verification).
    DISABLE IN PRODUCTION!
    """
    if os.getenv("ENVIRONMENT", "development") == "production":
        raise HTTPException(status_code=403, detail="Test endpoint disabled in production")
    
    payload = await request.json()
    print(f">>> [WEBHOOK TEST] Received: {payload.get('type', 'unknown')}")
    
    return {"received": True, "test": True}


# =========================================================================
# MANUAL SUBSCRIPTION MANAGEMENT (Admin endpoints)
# =========================================================================

@app.post("/admin/subscription/activate")
async def manual_activate_subscription(
    user_id: str,
    plan: str,
    admin_key: str = Header(None, alias="X-Admin-Key")
):
    """
    Manually activate a subscription (for testing or manual overrides).
    Requires admin key header.
    """
    expected_key = os.getenv("ADMIN_API_KEY", "dev-admin-key")
    if admin_key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    # Get plan config
    plan_config = billing_system.PLANS.get(plan.upper())
    if not plan_config:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {plan}")
    
    # Update user
    registry = load_registry()
    updated = False
    
    for k, v in registry.items():
        if v.get("profile", {}).get("hardware_id") == user_id:
            v["profile"]["subscription_plan"] = plan.upper()
            v["profile"]["subscription_status"] = "ACTIVE"
            v["profile"]["token_balance"] = plan_config["tokens"]
            updated = True
            save_registry(registry)
            break
    
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update billing record
    billing = billing_system._load_billing()
    billing.setdefault("subscriptions", {})[user_id] = {
        "stripe_subscription_id": f"sub_manual_{user_id[:8]}",
        "plan": plan.upper(),
        "status": "active",
        "created_at": str(asyncio.get_event_loop().time()),
        "manual": True
    }
    billing_system._save_billing(billing)
    
    return {
        "success": True,
        "user_id": user_id,
        "plan": plan.upper(),
        "tokens": plan_config["tokens"]
    }


@app.get("/admin/subscriptions")
async def list_subscriptions(
    admin_key: str = Header(None, alias="X-Admin-Key")
):
    """List all subscriptions."""
    expected_key = os.getenv("ADMIN_API_KEY", "dev-admin-key")
    if admin_key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid admin key")
    
    billing = billing_system._load_billing()
    return {
        "subscriptions": billing.get("subscriptions", {}),
        "customers": billing.get("customers", {})
    }


# =========================================================================
# STARTUP
# =========================================================================

@app.on_event("startup")
async def startup():
    print(f">>> [WEBHOOK] Stripe webhook server starting...")
    print(f">>> [WEBHOOK] Data directory: {DATA_DIR}")
    print(f">>> [WEBHOOK] Stripe enabled: {billing_system.stripe_enabled}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8766)
