"""
Shared registration finalizer — callable from Stripe webhook and bridge WS.
Extracts core user-creation logic from bridge_server.register_new_user().
"""
import datetime
import json
import logging
import os
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


# ---------------------------------------------------------------------------
# Dependent signup — Sovereign Circle family plan
#
# Pricing model (matches stripe_integration.family_tier_price_cents):
#   - 1st dependent of any age: FREE  (rides on parent's Sovereign Circle plan)
#   - 2nd dependent: $75/mo via STRIPE_PRICE_FAMILY_TIER_1
#   - 3rd dependent: $60/mo via STRIPE_PRICE_FAMILY_TIER_2
#   - 4th dependent: $45/mo via STRIPE_PRICE_FAMILY_TIER_3
#   - 5th+ dependent: $30/mo via STRIPE_PRICE_FAMILY_TIER_4
#
# `finalize_dependent_signup` is called at *prepare* time. It only finalizes
# the FREE case directly. For paid slots it returns DEPENDENT_REQUIRES_PAYMENT
# so the caller can route through Stripe Checkout. After Stripe completes,
# `finalize_paid_dependent_signup` is called from the webhook to materialize
# the user.
# ---------------------------------------------------------------------------

# Parent must be on one of these tiers for any dependent linkage.
DEPENDENT_ELIGIBLE_PARENT_TIERS = {"TOP_TIER", "TOP", "SOVEREIGN_CIRCLE"}
DEPENDENT_ELIGIBLE_PARENT_STATUSES = {"ACTIVE", "FAMILY_PLAN_ACTIVE", "TRIAL_ACTIVE"}

# Cents per family-tier slot (1-indexed among PAID dependents, 4+ all == 3000).
# Mirrors stripe_integration.FAMILY_TIER_PRICES so the disclosed cost matches
# what the webhook handler will actually charge.
FAMILY_TIER_PRICE_CENTS = {1: 7500, 2: 6000, 3: 4500}
FAMILY_TIER_PRICE_DEFAULT_CENTS = 3000  # 4th+ paid slot


def _family_tier_price_cents(paid_ordinal: int) -> int:
    return FAMILY_TIER_PRICE_CENTS.get(paid_ordinal, FAMILY_TIER_PRICE_DEFAULT_CENTS)


def _family_tier_env_key(paid_ordinal: int) -> str:
    """Stripe price env var name for a given paid ordinal (1..4)."""
    capped = max(1, min(paid_ordinal, 4))
    return f"STRIPE_PRICE_FAMILY_TIER_{capped}"


async def _validate_parent_for_dependent(conn, parent_username: str):
    """Look up the parent and verify they can sponsor a dependent.

    Returns (parent_row, error_reason). On success error_reason is None.
    """
    parent = await conn.fetchrow(
        """
        SELECT id, family_id, tier, subscription_status, name,
               profile_data->>'stripe_customer_id' AS stripe_customer_id,
               profile_data->>'stripe_subscription_id' AS stripe_subscription_id
        FROM users
        WHERE LOWER(username) = LOWER($1) AND role = 'CLIENT'
        """,
        parent_username,
    )
    if not parent:
        return None, "PARENT_NOT_FOUND"

    parent_tier = (parent["tier"] or "").upper()
    parent_status = (parent["subscription_status"] or "").upper()
    if parent_tier not in DEPENDENT_ELIGIBLE_PARENT_TIERS:
        return parent, "PARENT_NOT_SOVEREIGN_CIRCLE"
    if parent_status not in DEPENDENT_ELIGIBLE_PARENT_STATUSES:
        return parent, "PARENT_SUBSCRIPTION_INACTIVE"
    return parent, None


async def _ensure_family_row(conn, parent) -> str:
    """Make sure parent has a families row; return the family_id."""
    family_id = parent["family_id"]
    parent_username = parent.get("name") or ""
    if not family_id:
        family_code = f"FAM_{secrets.token_hex(4).upper()}"
        family_id = await conn.fetchval(
            """
            INSERT INTO families (family_code, head_of_household_id, name)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            family_code,
            parent["id"],
            f"{parent_username or 'Sovereign'} family",
        )
        await conn.execute(
            "UPDATE users SET family_id = $1 WHERE id = $2",
            family_id,
            parent["id"],
        )
    else:
        hoh = await conn.fetchval(
            "SELECT head_of_household_id FROM families WHERE id = $1",
            family_id,
        )
        if not hoh:
            await conn.execute(
                "UPDATE families SET head_of_household_id = $1 WHERE id = $2",
                parent["id"],
                family_id,
            )
    return family_id


async def _count_existing_dependents(conn, family_id) -> int:
    """Count existing dependents (excluding HOH/spouse) under this family."""
    return await conn.fetchval(
        """
        SELECT COUNT(*) FROM users
        WHERE family_id = $1
          AND tier = 'DEPENDENT'
        """,
        family_id,
    ) or 0


def _compute_is_minor(dob_str):
    """Return (dob_date_or_None, is_minor)."""
    if not dob_str:
        return None, False
    try:
        dob_date = datetime.datetime.strptime(dob_str, "%Y-%m-%d").date()
        age = (datetime.date.today() - dob_date).days // 365
        return dob_date, age < 18
    except ValueError:
        return None, False


def _build_dependent_profile(
    *,
    username: str,
    email: str,
    profile_fields: dict,
    family_id,
    parent,
    parent_username: str,
    is_minor: bool,
    paid_ordinal: int,
    monthly_cost_cents: int,
    stripe_customer_id: str = "",
    stripe_subscription_id: str = "",
) -> dict:
    """Shared profile_data dict for both free and paid dependent inserts."""
    now = datetime.datetime.now()
    today = str(now.date())
    hardware_id = f"CLIENT_{username.upper()}_ID"
    plan_label = (
        "DEPENDENT_UNDER_SOVEREIGN_CIRCLE"
        if paid_ordinal == 0
        else f"DEPENDENT_PAID_TIER_{min(paid_ordinal, 4)}"
    )

    return {
        "role": "CLIENT",
        "name": profile_fields.get("name", ""),
        "email": email,
        "phone": profile_fields.get("phone", ""),
        "hardware_id": hardware_id,
        "family_id": str(family_id),
        "joined_date": today,
        "tier": "DEPENDENT",
        "registration_type": "DEPENDENT",
        "dob": profile_fields.get("dob"),
        "is_minor": is_minor,
        "consent_version": profile_fields.get("consent_version", "v13.0_2026"),
        "timezone": profile_fields.get("timezone", "America/New_York"),
        "subscription_status": "FAMILY_PLAN_ACTIVE",
        "subscription_plan": plan_label,
        "stripe_customer_id": stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
        "subscription_start_date": today,
        "trial_end_date": "",
        "parent_username": parent_username,
        "parent_id": str(parent["id"]),
        "guardian_id": str(parent["id"]),
        "head_of_household_id": str(parent["id"]),
        # Billing audit
        "paid_slot_ordinal": paid_ordinal,  # 0 = free first dependent
        "monthly_cost_cents": monthly_cost_cents,
        "family_tier_price_key": (
            None if paid_ordinal == 0 else _family_tier_env_key(paid_ordinal)
        ),
        "total_sessions_count": 0,
        "token_balance": 50000,
        "token_usage_today": 0,
        "token_usage_month": 0,
        "last_token_reset": today,
        "can_access_nate": True,
        "coach_id": profile_fields.get("coach_id", "COACH_COACHN_ID"),
        "assigned_coach": profile_fields.get("assigned_coach", "CoachN"),
        "assigned_coach_id": profile_fields.get(
            "assigned_coach_id", "COACH_COACHN_ID"
        ),
        "created_at": str(now),
        "updated_at": str(now),
        "onboarding_completed": False,
        "discount_code": "",
    }


async def _insert_dependent_user(
    conn,
    *,
    username: str,
    password_hash: str,
    email: str,
    profile_fields: dict,
    family_id,
    parent,
    is_minor: bool,
    dob_date,
    new_profile: dict,
):
    """Common INSERT into users for both free and paid dependents."""
    return await conn.fetchval(
        """
        INSERT INTO users (
            username, role, password_hash, name, email, dob,
            tier, subscription_status, token_balance,
            family_id, guardian_id, is_minor,
            family_role, linked_by, linked_at,
            consent_version, consent_date,
            profile_data, hardware_id, intake_data
        ) VALUES (
            $1, 'CLIENT', $2, $3, $4, $5,
            'DEPENDENT', 'FAMILY_PLAN_ACTIVE', $6,
            $7, $8, $9,
            'dependent', $8, NOW(),
            $10, NOW(),
            $11::jsonb, $12, $13::jsonb
        )
        RETURNING id
        """,
        username,
        password_hash,
        profile_fields.get("name", ""),
        email or None,
        dob_date,
        50000,
        family_id,
        parent["id"],
        is_minor,
        profile_fields.get("consent_version", "v13.0_2026"),
        json.dumps(new_profile),
        f"CLIENT_{username.upper()}_ID",
        json.dumps({
            "goals": [],
            "modality": profile_fields.get("modality", "General"),
        }),
    )


async def finalize_dependent_signup(
    db_pool,
    *,
    username: str,
    password_hash: str,
    email: str,
    profile_fields: dict,
    parent_username: str,
) -> Tuple[bool, str, dict]:
    """Decide whether a dependent under `parent_username` is FREE or PAID and,
    if FREE, finalize the user immediately under the parent's Sovereign Circle
    plan with no Stripe charge.

    Outcomes:
      * (True, "DEPENDENT_REGISTRATION_SUCCESS", info) — free dep created.
      * (False, "DEPENDENT_REQUIRES_PAYMENT", info)    — caller must run
        Stripe Checkout with the price ID indicated by info["family_tier_price_key"]
        and call finalize_paid_dependent_signup() from the webhook on success.
      * (False, <error_reason>, {})                    — validation failed.
    """
    email = (email or "").strip().lower()
    parent_username = (parent_username or "").strip()

    if not parent_username:
        return False, "PARENT_USERNAME_REQUIRED", {}

    async with db_pool.acquire() as conn:
        if await conn.fetchval(
            "SELECT 1 FROM users WHERE LOWER(username) = LOWER($1)", username
        ):
            return False, "USERNAME_TAKEN", {}

        parent, err = await _validate_parent_for_dependent(conn, parent_username)
        if err:
            extra = {}
            if parent:
                extra = {"parent_tier": (parent["tier"] or "").upper(),
                         "parent_status": (parent["subscription_status"] or "").upper()}
            return False, err, extra

        family_id = await _ensure_family_row(conn, parent)
        existing_count = await _count_existing_dependents(conn, family_id)

        # 0 existing => this dep is the 1st (free). 1 existing => 1st paid. etc.
        paid_ordinal = existing_count  # 0 means free slot

        dob_date, is_minor = _compute_is_minor(profile_fields.get("dob"))

        if paid_ordinal > 0:
            # Caller must route through Stripe Checkout. Do NOT create user.
            price_cents = _family_tier_price_cents(paid_ordinal)
            tier_key = _family_tier_env_key(paid_ordinal)
            return False, "DEPENDENT_REQUIRES_PAYMENT", {
                "parent_id": str(parent["id"]),
                "parent_username": parent_username,
                "family_id": str(family_id),
                "is_minor": is_minor,
                "paid_ordinal": paid_ordinal,
                "monthly_cost_cents": price_cents,
                "family_tier_price_key": tier_key,
                "existing_dependent_count": existing_count,
            }

        # FREE path — first dependent.
        new_profile = _build_dependent_profile(
            username=username,
            email=email,
            profile_fields=profile_fields,
            family_id=family_id,
            parent=parent,
            parent_username=parent_username,
            is_minor=is_minor,
            paid_ordinal=0,
            monthly_cost_cents=0,
        )

        try:
            new_user_id = await _insert_dependent_user(
                conn,
                username=username,
                password_hash=password_hash,
                email=email,
                profile_fields=profile_fields,
                family_id=family_id,
                parent=parent,
                is_minor=is_minor,
                dob_date=dob_date,
                new_profile=new_profile,
            )
        except Exception as e:
            logger.error("finalize_dependent_signup INSERT failed for %s: %s", username, e)
            return False, f"DB_ERROR: {e}", {}

    logger.info(
        "finalize_dependent_signup: FREE dependent %s under parent %s family=%s",
        username, parent_username, family_id,
    )
    return True, "DEPENDENT_REGISTRATION_SUCCESS", {
        "user_id": str(new_user_id),
        "family_id": str(family_id),
        "parent_id": str(parent["id"]),
        "parent_username": parent_username,
        "is_minor": is_minor,
        "paid_ordinal": 0,
        "monthly_cost_cents": 0,
    }


async def finalize_paid_dependent_signup(
    db_pool,
    *,
    username: str,
    password_hash: str,
    email: str,
    profile_fields: dict,
    parent_username: str,
    paid_ordinal: int,
    monthly_cost_cents: int,
    stripe_customer_id: str,
    stripe_subscription_id: str,
    stripe_checkout_session_id: str,
) -> Tuple[bool, str, dict]:
    """Materialize a paid dependent AFTER Stripe Checkout has succeeded.

    Called from the webhook handler. We re-validate parent eligibility and
    family count to defend against tier changes between prepare and webhook.
    """
    email = (email or "").strip().lower()
    parent_username = (parent_username or "").strip()
    if not parent_username:
        return False, "PARENT_USERNAME_REQUIRED", {}

    async with db_pool.acquire() as conn:
        if await conn.fetchval(
            "SELECT 1 FROM users WHERE LOWER(username) = LOWER($1)", username
        ):
            return False, "USERNAME_TAKEN", {}

        parent, err = await _validate_parent_for_dependent(conn, parent_username)
        if err:
            return False, err, {}

        family_id = await _ensure_family_row(conn, parent)
        # Re-count: another dependent might have been added between
        # prepare-checkout and webhook completion. Recompute the ordinal so
        # the audit trail is correct, but trust the price the user already
        # paid (no double-charge / clawback here — Stripe is source of truth).
        existing_count = await _count_existing_dependents(conn, family_id)
        actual_ordinal = existing_count if existing_count > 0 else 1
        if actual_ordinal != paid_ordinal:
            logger.warning(
                "finalize_paid_dependent_signup: ordinal drift for %s — "
                "expected %d, actual %d", username, paid_ordinal, actual_ordinal,
            )

        dob_date, is_minor = _compute_is_minor(profile_fields.get("dob"))

        new_profile = _build_dependent_profile(
            username=username,
            email=email,
            profile_fields=profile_fields,
            family_id=family_id,
            parent=parent,
            parent_username=parent_username,
            is_minor=is_minor,
            paid_ordinal=actual_ordinal,
            monthly_cost_cents=monthly_cost_cents,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
        )
        new_profile["stripe_checkout_session_id"] = stripe_checkout_session_id

        try:
            new_user_id = await _insert_dependent_user(
                conn,
                username=username,
                password_hash=password_hash,
                email=email,
                profile_fields=profile_fields,
                family_id=family_id,
                parent=parent,
                is_minor=is_minor,
                dob_date=dob_date,
                new_profile=new_profile,
            )
        except Exception as e:
            logger.error(
                "finalize_paid_dependent_signup INSERT failed for %s: %s",
                username, e,
            )
            return False, f"DB_ERROR: {e}", {}

    logger.info(
        "finalize_paid_dependent_signup: PAID dependent %s under parent %s "
        "family=%s ordinal=%d cost=%d¢",
        username, parent_username, family_id, actual_ordinal, monthly_cost_cents,
    )
    return True, "DEPENDENT_PAID_REGISTRATION_SUCCESS", {
        "user_id": str(new_user_id),
        "family_id": str(family_id),
        "parent_id": str(parent["id"]),
        "parent_username": parent_username,
        "is_minor": is_minor,
        "paid_ordinal": actual_ordinal,
        "monthly_cost_cents": monthly_cost_cents,
    }


async def activate_family_member_from_stripe_checkout(db_pool, session: dict) -> None:
    """Activate an existing dependent after Checkout when metadata.type == family_member.
    Called from stripe_integration on checkout.session.completed.
    """
    import stripe

    metadata = session.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    hoh_username = (metadata.get("hoh_username") or "").strip()
    dep_username = (metadata.get("dependent_username") or "").strip()
    dep_id_str = (metadata.get("user_id") or "").strip()
    try:
        ordinal = int(str(metadata.get("ordinal") or "1"))
    except (TypeError, ValueError):
        ordinal = 1
    subscription_id = session.get("subscription")
    customer_id = (session.get("customer") or "").strip()
    if not hoh_username or not subscription_id:
        logger.warning("activate_family_member: missing hoh_username or subscription id")
        return
    ocap = max(1, min(ordinal, 4))
    plan_label = f"DEPENDENT_PAID_TIER_{ocap}"
    monthly_cents = _family_tier_price_cents(ordinal)
    today = str(datetime.date.today())
    now_iso = str(datetime.datetime.now())

    try:
        async with db_pool.acquire() as conn:
            hoh = await conn.fetchrow(
                """
                SELECT id, username, family_id FROM users
                WHERE LOWER(username) = LOWER($1) AND role = 'CLIENT'
                """,
                hoh_username,
            )
            if not hoh:
                logger.error("activate_family_member: HOH not found: %s", hoh_username)
                return
            if dep_id_str:
                dep = await conn.fetchrow(
                    """
                    SELECT id, username, profile_data, family_id, guardian_id, tier, subscription_status
                    FROM users WHERE id = $1::uuid
                    """,
                    dep_id_str,
                )
            else:
                dep = await conn.fetchrow(
                    """
                    SELECT id, username, profile_data, family_id, guardian_id, tier, subscription_status
                    FROM users WHERE LOWER(username) = LOWER($1)
                    """,
                    dep_username,
                )
            if not dep:
                logger.error(
                    "activate_family_member: dependent not found user_id=%s username=%s",
                    dep_id_str, dep_username,
                )
                return
            pd = dep["profile_data"]
            if isinstance(pd, str):
                try:
                    pd = json.loads(pd)
                except Exception:
                    pd = {}
            pd = dict(pd or {})
            ok_link = False
            if dep.get("guardian_id") == hoh["id"]:
                ok_link = True
            elif str(pd.get("head_of_household_id") or "") == str(hoh["id"]):
                ok_link = True
            elif (pd.get("parent_username") or "").lower() == hoh_username.lower():
                ok_link = True
            if not ok_link and dep.get("family_id") and hoh.get("family_id"):
                if str(dep["family_id"]) == str(hoh["family_id"]):
                    ok_link = True
            if not ok_link:
                logger.error(
                    "activate_family_member: dependent %s not linked to HOH %s",
                    dep.get("username"), hoh_username,
                )
                return
            pd["subscription_status"] = "FAMILY_PLAN_ACTIVE"
            pd["subscription_plan"] = plan_label
            pd["paid_slot_ordinal"] = ordinal
            pd["monthly_cost_cents"] = monthly_cents
            pd["family_tier_price_key"] = _family_tier_env_key(ordinal) if ordinal > 0 else None
            pd["stripe_customer_id"] = customer_id
            pd["stripe_subscription_id"] = subscription_id
            pd["subscription_start_date"] = today
            pd["trial_end_date"] = ""
            pd["updated_at"] = now_iso
            pd["can_access_nate"] = True
            sub_obj = None
            try:
                if stripe.api_key or os.environ.get("STRIPE_SECRET_KEY"):
                    sub_obj = stripe.Subscription.retrieve(subscription_id)
            except Exception as e:
                logger.warning("activate_family_member: Subscription.retrieve failed: %s", e)
            if sub_obj:
                pd["stripe_current_period_start"] = str(sub_obj.get("current_period_start", ""))
                pd["stripe_current_period_end"] = str(sub_obj.get("current_period_end", ""))
            await conn.execute(
                """
                UPDATE users
                SET tier = 'DEPENDENT', subscription_status = 'FAMILY_PLAN_ACTIVE', profile_data = $1::jsonb
                WHERE id = $2
                """,
                json.dumps(pd), dep["id"],
            )
        uname = dep["username"]
        try:
            from app.services.api_server import _get_auth_redis
            r = await _get_auth_redis()
            if r and uname:
                await r.publish("nate:user_reload", json.dumps({"username": uname}))
        except Exception as e:
            logger.warning("activate_family_member: user_reload failed: %s", e)
        logger.info(
            "activate_family_member: activated %s ordinal=%d sub=%s",
            uname, ordinal, subscription_id,
        )
    except Exception as e:
        logger.error("activate_family_member: failed: %s", e, exc_info=True)
