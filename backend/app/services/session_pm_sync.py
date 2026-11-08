"""Keep users.profile_data.default_payment_method_id aligned with Stripe."""

from __future__ import annotations

import logging

logger = logging.getLogger("nate.session_pm_sync")


async def sync_default_pm_from_stripe(
    db_pool,
    *,
    user_key: str,
    customer_id: str,
) -> str:
    """Stripe customer default (then first card) wins; mirror onto the profile.

    Returns the payment_method id to charge, or "".
    """
    if not customer_id:
        return ""
    pm = ""
    try:
        from app.services.session_financial_records import resolve_charge_payment_method

        pm = (await resolve_charge_payment_method(customer_id) or "") or ""
        if not isinstance(pm, str):
            pm = getattr(pm, "id", "") or ""
    except Exception as e:
        logger.warning("sync_default_pm_from_stripe resolve: %s", e)
        pm = ""
    if pm and db_pool and user_key:
        try:
            from app.services.session_financial_records import mirror_default_payment_method

            await mirror_default_payment_method(
                db_pool,
                user_key=user_key,
                payment_method_id=pm,
                stripe_customer_id=customer_id,
            )
        except Exception as e:
            logger.warning("sync_default_pm_from_stripe mirror: %s", e)
    return (pm or "").strip()
