"""Shared rules: when TokenRenewal / TokenAudit may send outbound social-token alerts.

If ops disables all social-token emails or lists a paused platform (e.g. ``x``), the
Token Renewal Agent skips SMS/email — and Token Audit must not interpret the missing
``token_renewal_notification`` row as an incident (Audit Alert — missed notification).
"""

from __future__ import annotations


def normalize_paused_platform_csv(paused_csv: str) -> frozenset[str]:
    return frozenset(p.strip().lower() for p in (paused_csv or "").split(",") if p.strip())


def social_token_outbound_alerts_allowed(
    platform: str,
    *,
    emails_enabled_globally: bool,
    paused_platform_csv: str,
) -> bool:
    if not emails_enabled_globally:
        return False
    pnorm = platform.strip().lower()
    paused = normalize_paused_platform_csv(paused_platform_csv)
    if not paused:
        return True
    if pnorm in paused:
        return False
    # Common aliases for X/Twitter adapter key vs legacy labels
    if pnorm == "x" and "x_twitter" in paused:
        return False
    if pnorm == "x_twitter" and "x" in paused:
        return False
    return True


def social_token_outbound_alerts_allowed_for_platform(platform: str) -> bool:
    from app.config import settings

    return social_token_outbound_alerts_allowed(
        platform,
        emails_enabled_globally=getattr(
            settings, "SKYEYE_SOCIAL_TOKEN_ALERT_EMAILS_ENABLED", True
        ),
        paused_platform_csv=getattr(
            settings, "SKYEYE_TOKEN_ALERT_PAUSED_PLATFORMS", ""
        )
        or "",
    )
