#!/usr/bin/env python3
"""Read-only Twilio A2P / SMS health check. No outbound send."""
from __future__ import annotations

import json
import os
import sys


def mask(s: str, keep: int = 6) -> str:
    s = s or ""
    if not s:
        return "(unset)"
    if len(s) <= keep:
        return "***"
    return f"{s[:keep]}…len={len(s)}"


def dump(obj) -> None:
    print(json.dumps(obj, default=str))


def main() -> int:
    keys = [
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_VERIFY_SID",
        "TWILIO_PHONE_NUMBER",
        "TWILIO_FROM_NUMBER",
        "TWILIO_MESSAGING_SERVICE_SID",
    ]
    print("=== ENV (masked) ===")
    for k in keys:
        v = os.getenv(k, "")
        if k.endswith(("NUMBER", "SID")):
            print(f"{k}={v or '(unset)'}")
        else:
            print(f"{k}={mask(v)}")

    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        print("MISSING CREDENTIALS")
        return 1

    from twilio.rest import Client

    client = Client(sid, token)

    print("\n=== ACCOUNT ===")
    acct = client.api.accounts(sid).fetch()
    dump(
        {
            "friendly_name": acct.friendly_name,
            "status": acct.status,
            "type": acct.type,
            "sid": acct.sid,
        }
    )

    print("\n=== BRANDS ===")
    try:
        brands = client.messaging.v1.brand_registrations.list(limit=20)
        if not brands:
            print("NONE")
        for b in brands:
            dump(
                {
                    "sid": b.sid,
                    "brand_type": getattr(b, "brand_type", None),
                    "status": getattr(b, "status", None),
                    "identity_status": getattr(b, "identity_status", None),
                    "tcr_id": getattr(b, "tcr_id", None),
                    "customer_profile_bundle_sid": getattr(
                        b, "customer_profile_bundle_sid", None
                    ),
                    "date_created": str(getattr(b, "date_created", "")),
                    "date_updated": str(getattr(b, "date_updated", "")),
                }
            )
    except Exception as e:
        print("brand list error:", type(e).__name__, str(e)[:300])

    print("\n=== MESSAGING SERVICES ===")
    try:
        services = list(client.messaging.v1.services.list(limit=20))
        if not services:
            print("NONE")
        for svc in services:
            dump(
                {
                    "sid": svc.sid,
                    "friendly_name": svc.friendly_name,
                    "inbound_request_url": svc.inbound_request_url,
                    "status_callback": svc.status_callback,
                    "usecase": getattr(svc, "usecase", None),
                    "sticky_sender": getattr(svc, "sticky_sender", None),
                }
            )
            try:
                campaigns = client.messaging.v1.services(svc.sid).us_app_to_person.list(
                    limit=20
                )
                if not campaigns:
                    print("  campaigns: NONE")
                for c in campaigns:
                    print(
                        "  CAMPAIGN",
                        json.dumps(
                            {
                                "sid": c.sid,
                                "campaign_status": getattr(c, "campaign_status", None),
                                "campaign_id": getattr(c, "campaign_id", None),
                                "us_app_to_person_usecase": getattr(
                                    c, "us_app_to_person_usecase", None
                                ),
                                "brand_registration_sid": getattr(
                                    c, "brand_registration_sid", None
                                ),
                                "description": (getattr(c, "description", "") or "")[:160],
                                "has_embedded_links": getattr(
                                    c, "has_embedded_links", None
                                ),
                                "has_embedded_phone": getattr(
                                    c, "has_embedded_phone", None
                                ),
                                "errors": getattr(c, "errors", None),
                            },
                            default=str,
                        ),
                    )
            except Exception as e:
                print("  campaign list error:", type(e).__name__, str(e)[:300])
            try:
                nums = client.messaging.v1.services(svc.sid).phone_numbers.list(limit=20)
                if not nums:
                    print("  numbers: NONE")
                for n in nums:
                    print("  NUMBER", n.phone_number, n.sid)
            except Exception as e:
                print("  number list error:", type(e).__name__, str(e)[:200])
    except Exception as e:
        print("service list error:", type(e).__name__, str(e)[:300])

    print("\n=== INCOMING NUMBERS ===")
    for n in client.incoming_phone_numbers.list(limit=20):
        dump(
            {
                "phone": n.phone_number,
                "friendly_name": n.friendly_name,
                "sms_url": n.sms_url,
                "sms_method": n.sms_method,
                "voice_url": n.voice_url,
                "status": getattr(n, "status", None),
                "capabilities": str(n.capabilities),
            }
        )

    print("\n=== RECENT MESSAGES (last 25) ===")
    for m in client.messages.list(limit=25):
        dump(
            {
                "sid": m.sid,
                "from": m.from_,
                "to": (m.to or "")[:6] + "…",
                "status": m.status,
                "error_code": m.error_code,
                "error_message": (m.error_message or "")[:180],
                "direction": m.direction,
                "date_sent": str(m.date_sent),
                "date_created": str(m.date_created),
                "messaging_service_sid": m.messaging_service_sid,
            }
        )

    print("\n=== VERIFY SERVICE ===")
    vsid = os.getenv("TWILIO_VERIFY_SID", "")
    if vsid:
        try:
            v = client.verify.v2.services(vsid).fetch()
            dump(
                {
                    "sid": v.sid,
                    "friendly_name": v.friendly_name,
                    "code_length": v.code_length,
                }
            )
        except Exception as e:
            print("verify fetch error:", type(e).__name__, str(e)[:300])
    else:
        print("TWILIO_VERIFY_SID unset")
    return 0


if __name__ == "__main__":
    sys.exit(main())
