#!/usr/bin/env python3
"""Attach +16562318192 to the A2P Messaging Service; optional canary SMS.

Read-only by default. Mutating flags:
  --attach   add TWILIO_PHONE_NUMBER to TWILIO_MESSAGING_SERVICE_SID if missing
  --webhook  set Messaging Service inbound_request_url to TWILIO_WEBHOOK_URL
  --canary   send one SMS to ADMIN_VERIFY_PHONE or --to E.164
"""
from __future__ import annotations

import argparse
import os
import sys
import time

DEFAULT_SERVICE = "MG17b08b844584ea171a5d019d846888fc"
DEFAULT_WEBHOOK = "https://api.sovereignsanctuary.net/webhook/twilio/incoming"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--attach", action="store_true")
    p.add_argument("--webhook", action="store_true")
    p.add_argument("--canary", action="store_true")
    p.add_argument("--to", default="")
    args = p.parse_args()

    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    phone = os.getenv("TWILIO_PHONE_NUMBER", "+16562318192")
    svc = os.getenv("TWILIO_MESSAGING_SERVICE_SID", DEFAULT_SERVICE).strip() or DEFAULT_SERVICE
    webhook = os.getenv("TWILIO_WEBHOOK_URL", DEFAULT_WEBHOOK).strip() or DEFAULT_WEBHOOK
    canary_to = (args.to or os.getenv("ADMIN_VERIFY_PHONE") or os.getenv("TWILIO_ADMIN_NUMBER") or "").strip()

    if not sid or not token:
        print("MISSING CREDENTIALS")
        return 1

    from twilio.rest import Client

    client = Client(sid, token)

    nums = list(client.messaging.v1.services(svc).phone_numbers.list(limit=20))
    attached = [n.phone_number for n in nums]
    print("service", svc)
    print("attached", attached or ["NONE"])

    pn_sid = None
    for n in client.incoming_phone_numbers.list(limit=20):
        if n.phone_number == phone:
            pn_sid = n.sid
            print("incoming", n.phone_number, "sms_url=", n.sms_url)
            break
    if not pn_sid:
        print("PHONE_NOT_IN_ACCOUNT", phone)
        return 1

    if args.attach and phone not in attached:
        client.messaging.v1.services(svc).phone_numbers.create(phone_number_sid=pn_sid)
        print("ATTACHED", phone)
    elif args.attach:
        print("ALREADY_ATTACHED", phone)

    if args.webhook:
        client.messaging.v1.services(svc).update(
            inbound_request_url=webhook,
            inbound_method="POST",
        )
        print("WEBHOOK", webhook)

    svc_obj = client.messaging.v1.services(svc).fetch()
    print(
        "inbound_request_url",
        svc_obj.inbound_request_url,
        "status_callback",
        svc_obj.status_callback,
    )

    campaigns = client.messaging.v1.services(svc).us_app_to_person.list(limit=5)
    for c in campaigns:
        print("campaign", c.sid, getattr(c, "campaign_status", None), getattr(c, "us_app_to_person_usecase", None))

    if args.canary:
        if not canary_to:
            print("NO_CANARY_DESTINATION")
            return 1
        msg = client.messages.create(
            to=canary_to,
            messaging_service_sid=svc,
            body="Sovereign Sanctuary A2P canary — pipeline check. Reply STOP to opt out.",
        )
        print("canary_sid", msg.sid, "status", msg.status)
        final = None
        for _ in range(12):
            time.sleep(2)
            fetched = client.messages(msg.sid).fetch()
            final = fetched
            print("poll", fetched.status, fetched.error_code, (fetched.error_message or "")[:120])
            if (fetched.status or "").lower() in ("delivered", "undelivered", "failed", "canceled"):
                break
        if final and (final.error_code in (30034, 30007) or (final.status or "").lower() in ("undelivered", "failed")):
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
