"""
Shared registration finalizer — callable from Stripe webhook and bridge WS.
Extracts core user-creation logic from bridge_server.register_new_user().
"""
import datetime
import json
import logging
import secrets
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

DOJO_PRICES = {
    "therapist": 175.0,
    "project_pm": 250.0,
    "business": 325.0,
    "cnc": 150.0,
    "mcat": 500.0,
    "teacher": 225.0,
    "judge": 2100.0,
    "coach_nate": 90.0,
}
DOJO_DISCOUNTS = [0, 0, 10, 15, 20, 25, 30, 35]

REQUIRED_COACH_ETHICS_VERSION = "v1.0_2026"


def _build_dojo_subscriptions(selected_dojos: list, discount_pct: int = 0) -> dict:
    today = str(datetime.datetime.now().date())
    term_end = str((datetime.datetime.now() + datetime.timedelta(days=365)).date())
    subs = {}
    for dojo_key in selected_dojos:
        effective_discount = 0 if dojo_key == "judge" else discount_pct
        subs[dojo_key] = {
            "status": "active",
            "start_date": today,
            "term_end_date": term_end,
            "cancellation_requested": None,
            "access_end_date": None,
            "monthly_rate": DOJO_PRICES.get(dojo_key, 0),
            "discount_pct": effective_discount,
        }
    return subs


def _tier_mapping(role: str, registration_type: str):
    """Return (tier, plan, sub_status, can_access_nate, token_balance, trial_end)."""
    if role == "COACH":
        return "COACH", "COACH", "PENDING_VERIFICATION", True, 50000, ""

    rt = (registration_type or "TRIAL").upper()
    if rt == "COACH_ONLY":
        return "COACH_ONLY", "COACH_ONLY", "ACTIVE", False, 0, ""
    elif rt == "STANDARD":
        return "STANDARD", "STANDARD", "ACTIVE", True, 50000, ""
    elif rt == "TOP_TIER":
        return "TOP_TIER", "TOP_TIER", "ACTIVE", True, 200000, ""
    else:
        trial_end = str((datetime.datetime.now() + datetime.timedelta(days=7)).date())
        return "STANDARD", "TRIAL", "TRIAL_ACTIVE", True, 10000, trial_end


async def finalize_signup(
    db_pool,
    *,
    role: str,
    username: str,
    password_hash: str,
    email: str,
    profile_fields: dict,
    tier: str,
    selected_dojos: list,
    discount_code: str = "",
    stripe_customer_id: str = "",
    stripe_checkout_session_id: str = "",
) -> Tuple[bool, str]:
    """Create a user from a completed Stripe checkout.

    Returns (True, "REGISTRATION_SUCCESS") or (False, reason).
    """
    email = (email or "").strip().lower()

    async with db_pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM users WHERE LOWER(username) = LOWER($1)", username
        )
        if exists:
            return False, "USERNAME_TAKEN"

        if email:
            same_role = await conn.fetchval(
                "SELECT 1 FROM users WHERE LOWER(profile_data->>'email') = LOWER($1) AND role = $2",
                email,
                role,
            )
            if same_role:
                return False, "EMAIL_TAKEN"

    registration_type = tier or profile_fields.get("registration_type", "TRIAL")
    tier_val, plan, sub_status, can_access_nate, token_balance, trial_end = _tier_mapping(
        role, registration_type
    )

    hardware_id = f"{role}_{username.upper()}_ID"
    now = datetime.datetime.now()
    today = str(now.date())

    new_profile = {
        "role": role,
        "name": profile_fields.get("name", ""),
        "email": email,
        "phone": profile_fields.get("phone", ""),
        "hardware_id": hardware_id,
        "family_id": f"FAM_{secrets.token_hex(4).upper()}",
        "joined_date": today,
        "tier": tier_val,
        "registration_type": registration_type if role == "CLIENT" else None,
        "dob": profile_fields.get("dob"),
        "consent_version": profile_fields.get("consent_version", "v13.0_2026"),
        "timezone": profile_fields.get("timezone", "America/New_York"),
        "profile_photo_url": "",
        "emergency_contact": profile_fields.get("emergency_contact", ""),
        "company_id": profile_fields.get("company_id"),
        "company_name": profile_fields.get("company_name", ""),
        "subscription_status": sub_status,
        "subscription_plan": plan,
        "stripe_customer_id": stripe_customer_id,
        "subscription_start_date": today,
        "trial_end_date": trial_end,
        "total_sessions_count": 0,
        "token_balance": token_balance,
        "token_usage_today": 0,
        "token_usage_month": 0,
        "last_token_reset": today,
        "can_access_nate": can_access_nate,
        "coach_id": profile_fields.get("coach_id", "COACH_COACHN_ID"),
        "assigned_coach": profile_fields.get("assigned_coach", "CoachN"),
        "assigned_coach_id": profile_fields.get("assigned_coach_id", "COACH_COACHN_ID"),
        "last_login": "",
        "last_activity_at": "",
        "login_count": 0,
        "created_at": str(now),
        "updated_at": str(now),
        "preferred_contact": "email",
        "onboarding_completed": False,
        "social_handle": profile_fields.get("social_handle", ""),
        "social_platform": profile_fields.get("social_platform", ""),
        "discount_code": discount_code,
    }

    if role == "COACH":
        new_profile["subscription_status"] = "PENDING_VERIFICATION"
        new_profile["assigned_clients"] = []
        new_profile["specializations"] = profile_fields.get("specializations", [])
        new_profile["certification_status"] = "PENDING"
        if profile_fields.get("coach_ethics_accepted"):
            new_profile["coach_ethics_version"] = REQUIRED_COACH_ETHICS_VERSION
            new_profile["coach_ethics_accepted_at"] = str(now)
        new_profile["hourly_rate"] = 0
        new_profile["total_sessions_conducted"] = 0
        new_profile["average_client_rating"] = 0
        new_profile["revenue_this_month"] = 0
        new_profile["zoom_link"] = profile_fields.get("zoom_link", "")
        new_profile["coaching_fee"] = float(profile_fields.get("coaching_fee", 0))
        new_profile["platform_fee_pct"] = 30
        new_profile["platform_fee_min"] = 30.00
        new_profile["payment_mode"] = "coach_handles"
        new_profile["total_earnings_ytd"] = 0.0
        new_profile["total_platform_fees_ytd"] = 0.0
        new_profile["total_sessions_billable"] = 0
        new_profile["w9_submitted"] = bool(profile_fields.get("w9_data"))
        new_profile["w9_data"] = profile_fields.get("w9_data", {})
        new_profile["requires_1099"] = False
        new_profile["address_verified"] = False
        new_profile["standardized_address"] = {}
        new_profile["tin_doc_uploaded"] = False
        new_profile["tin_doc_path"] = ""
        new_profile["tin_match_status"] = "not_submitted"
        new_profile["tin_verification_method"] = "none"
        new_profile["financial_ledger"] = []
        new_profile["selected_dojos"] = selected_dojos
        dojo_discount = profile_fields.get("dojo_discount_pct", 0)
        new_profile["dojo_discount_pct"] = dojo_discount
        new_profile["dojo_monthly_price"] = profile_fields.get("dojo_monthly_price", 0)
        new_profile["dojo_subscriptions"] = _build_dojo_subscriptions(
            selected_dojos, dojo_discount
        )
        if "judge" in [d.lower() for d in selected_dojos]:
            new_profile["judge_nate_bar_id"] = f"JNBAR-{secrets.token_hex(4).upper()}"

    profile_json = json.dumps(new_profile)

    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (
                    username, role, password_hash, tier, subscription_status,
                    token_balance, profile_data, hardware_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                ON CONFLICT (username) DO NOTHING
                """,
                username,
                role,
                password_hash,
                tier_val if tier_val in ("STANDARD", "TRIAL", "TOP_TIER") else "STANDARD",
                sub_status if sub_status in ("ACTIVE", "TRIAL_ACTIVE") else "ACTIVE",
                token_balance,
                profile_json,
                hardware_id,
            )

            inserted = await conn.fetchval(
                "SELECT 1 FROM users WHERE username = $1", username
            )
            if not inserted:
                return False, "USERNAME_TAKEN"

    except Exception as e:
        logger.error("finalize_signup INSERT failed for %s: %s", username, e)
        return False, f"DB_ERROR: {e}"

    logger.info("finalize_signup: created user %s role=%s tier=%s", username, role, tier_val)
    return True, "REGISTRATION_SUCCESS"
