"""IANA timezone resolution, display rendering, and phone normalization for user-local times."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

_logger = logging.getLogger(__name__)

# Support-facing emails (Stripe notices to support@): single display zone until ops configures otherwise.
SUPPORT_DISPLAY_TIMEZONE = os.getenv("SUPPORT_DISPLAY_TIMEZONE", "America/Los_Angeles")


def normalize_phone_e164(phone_raw: str, default_region: str = "US") -> Optional[str]:
    """Return E.164 phone or None if empty/invalid."""
    if not phone_raw or not str(phone_raw).strip():
        return None
    try:
        import phonenumbers
        from phonenumbers import NumberParseException

        raw = str(phone_raw).strip()
        try:
            parsed = phonenumbers.parse(raw, default_region if not raw.startswith("+") else None)
        except NumberParseException:
            digits = "".join(c for c in raw if c.isdigit())
            if len(digits) == 10:
                parsed = phonenumbers.parse(digits, default_region)
            elif len(digits) >= 11:
                parsed = phonenumbers.parse("+" + digits, None)
            else:
                return None
        if not phonenumbers.is_valid_number(parsed):
            return None
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception as e:
        _logger.debug("normalize_phone_e164: %s", e)
        return None


def resolve_user_timezone(
    explicit_setting: Optional[str] = None,
    browser_tz: Optional[str] = None,
    phone_number: Optional[str] = None,
    address_country: Optional[str] = None,
    address_postal: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Cascading timezone resolution. Returns (iana_timezone_string, source_label).

    Priority: user_explicit > browser > phone > address > ip > default_utc
    """
    if explicit_setting and _is_valid_iana(explicit_setting):
        return explicit_setting.strip(), "user_explicit"

    if browser_tz and _is_valid_iana(browser_tz):
        return browser_tz.strip(), "browser"

    if phone_number:
        tz = _phone_to_timezone(phone_number)
        if tz:
            return tz, "phone"

    if address_country:
        tz = _country_to_timezone(address_country, address_postal)
        if tz:
            return tz, "address"

    if ip_address:
        tz = _ip_to_timezone(ip_address)
        if tz:
            return tz, "ip"

    return "UTC", "default_utc"


def render_user_time(
    utc_dt: datetime,
    user_timezone: str,
    fmt: str = "%I:%M %p %Z on %B %d, %Y",
) -> str:
    """Render a UTC-aware datetime in the user's local timezone."""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo((user_timezone or "UTC").strip())
    except Exception:
        tz = ZoneInfo("UTC")
    local_dt = utc_dt.astimezone(tz)
    return local_dt.strftime(fmt)


def build_llm_time_context(profile: Dict[str, Any]) -> str:
    """Block injected at top of therapy / chat system prompts when profile is available."""
    now_utc = datetime.now(timezone.utc)
    user_tz = (profile.get("timezone") or "UTC").strip()
    try:
        local_date = render_user_time(now_utc, user_tz, "%A, %B %d, %Y")
        local_time = render_user_time(now_utc, user_tz, "%I:%M %p %Z")
    except Exception:
        local_date = now_utc.astimezone(ZoneInfo("UTC")).strftime("%A, %B %d, %Y")
        local_time = now_utc.astimezone(ZoneInfo("UTC")).strftime("%I:%M %p %Z")
    return (
        "CURRENT TIME CONTEXT:\n"
        f"- Server UTC time: {now_utc.isoformat()}\n"
        f"- User local time: {local_time}\n"
        f"- User timezone: {user_tz}\n"
        f"- User local date: {local_date}\n"
        "\n"
        'When the user asks about time, dates, or "when" anything happened or will happen, '
        "use the values above. Do NOT use training data cutoff dates as \"today.\" "
        f"The current local date for this user is {local_date}."
    )


def is_valid_iana_timezone(tz_string: str) -> bool:
    """True if tz_string is a valid IANA zone name."""
    return _is_valid_iana(tz_string)


def _is_valid_iana(tz_string: str) -> bool:
    if not tz_string or not str(tz_string).strip():
        return False
    try:
        ZoneInfo(str(tz_string).strip())
        return True
    except Exception:
        return False


def _phone_to_timezone(phone: str) -> Optional[str]:
    try:
        import phonenumbers
        from phonenumbers import timezone as ph_tz

        parsed = phonenumbers.parse(phone, None)
        tzs = ph_tz.time_zones_for_number(parsed)
        if tzs and tzs[0] != "Etc/Unknown":
            return tzs[0]
    except Exception as e:
        _logger.debug("phone_to_timezone failed: %s", e)

    if not phone.startswith("+"):
        return None
    _country_default_tz = {
        "+1": "America/New_York",
        "+44": "Europe/London",
        "+46": "Europe/Stockholm",
        "+33": "Europe/Paris",
        "+49": "Europe/Berlin",
        "+34": "Europe/Madrid",
        "+39": "Europe/Rome",
        "+31": "Europe/Amsterdam",
        "+61": "Australia/Sydney",
        "+81": "Asia/Tokyo",
        "+86": "Asia/Shanghai",
        "+91": "Asia/Kolkata",
        "+52": "America/Mexico_City",
        "+55": "America/Sao_Paulo",
    }
    for prefix, tz in _country_default_tz.items():
        if phone.startswith(prefix):
            return tz
    return None


def _country_to_timezone(country: str, postal: Optional[str] = None) -> Optional[str]:
    del postal  # reserved for future postal → TZ refinement
    _country_default_tz = {
        "US": "America/New_York",
        "GB": "Europe/London",
        "SE": "Europe/Stockholm",
        "FR": "Europe/Paris",
        "DE": "Europe/Berlin",
        "ES": "Europe/Madrid",
        "IT": "Europe/Rome",
        "NL": "Europe/Amsterdam",
        "AU": "Australia/Sydney",
        "JP": "Asia/Tokyo",
        "CN": "Asia/Shanghai",
        "IN": "Asia/Kolkata",
        "MX": "America/Mexico_City",
        "BR": "America/Sao_Paulo",
        "CA": "America/Toronto",
    }
    return _country_default_tz.get((country or "").upper())


def _ip_to_timezone(ip: str) -> Optional[str]:
    """
    Optional GeoIP — requires GeoLite2-City.mmdb at GEOIP2_CITY_DB_PATH.
    Until provisioned, returns None (cascade continues).
    """
    db_path = os.getenv("GEOIP2_CITY_DB_PATH", "/data/GeoLite2-City.mmdb")
    try:
        import geoip2.database
    except ImportError:
        return None
    if not ip or not os.path.isfile(db_path):
        return None
    try:
        with geoip2.database.Reader(db_path) as reader:
            response = reader.city(ip)
            return response.location.time_zone
    except Exception:
        return None
