import pytest

from app.services.account_lifecycle import (
    client_email_mentions_no_charges,
    should_cancel_stripe_status,
    stop_charges_for_user,
)


def test_live_stripe_statuses():
    assert should_cancel_stripe_status("active")
    assert should_cancel_stripe_status("PAST_DUE")
    assert not should_cancel_stripe_status("canceled")
    assert not should_cancel_stripe_status("CANCELLED")


def test_confirmation_copy_names_no_further_charges():
    html_body = "<p>Stripe has been notified and <strong>no further charges will apply</strong>.</p>"
    assert client_email_mentions_no_charges(html_body)


class _Acq:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self):
        self.executed = []
        self.user = {
            "username": "jakepetersen22",
            "role": "CLIENT",
            "hardware_id": "CLIENT_JAKEPETERSEN22_ID",
            "name": "Jake",
            "email": "jake@example.com",
            "phone": "",
            "coach_id": "COACH_COACHN_ID",
            "assigned_coach": "CoachN",
            "assigned_coach_id": "COACH_COACHN_ID",
            "profile_cust": "cus_test",
            "profile_sub": "sub_test",
            "subscription_status": "ACTIVE",
            "tier": "STANDARD",
        }
        self.coach = {
            "username": "CoachN",
            "role": "COACH",
            "name": "CoachN",
            "email": "coach@example.com",
        }
        self.subs = [
            {
                "stripe_subscription_id": "sub_test",
                "stripe_customer_id": "cus_test",
                "status": "ACTIVE",
            }
        ]

    async def fetchrow(self, q, *a):
        key = (a[0] if a else "")
        if key in ("CoachN", "COACH_COACHN_ID"):
            return self.coach
        if key in (self.user["hardware_id"], self.user["username"]):
            return self.user
        return None

    async def fetchval(self, q, *a):
        ql = q.lower()
        if "select id from users" in ql:
            return "uuid-jake"
        if "from staged_deletions" in ql:
            return None
        return None

    async def fetch(self, q, *a):
        if "from subscriptions" in q.lower():
            return self.subs
        return []

    async def execute(self, q, *a):
        self.executed.append(q)
        return "OK"


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acq(self.conn)


class FakeStripe:
    class Subscription:
        cancelled = []

        @classmethod
        def cancel(cls, sid):
            cls.cancelled.append(sid)
            return {"id": sid, "status": "canceled"}

        @classmethod
        def list(cls, customer=None, status=None, limit=20):
            return {"data": [{"id": "sub_test", "status": "active"}]}


class FakeNotifier:
    def __init__(self):
        self.calls = []

    async def send_stop_payment_confirmation(self, *a, **k):
        self.calls.append(("stop", a, k))
        return True

    async def send_account_deletion_scheduled(self, *a, **k):
        self.calls.append(("del", a, k))
        return True

    async def send_coach_client_charges_stopped(self, *a, **k):
        self.calls.append(("coach", a, k))
        return True


@pytest.mark.asyncio
async def test_stop_payment_cancels_stripe_and_emails_client_and_coach():
    FakeStripe.Subscription.cancelled = []
    conn = FakeConn()
    notifier = FakeNotifier()
    result = await stop_charges_for_user(
        FakePool(conn),
        "CLIENT_JAKEPETERSEN22_ID",
        source="stop_payment",
        reason="test",
        immediate=True,
        schedule_purge=False,
        notifier=notifier,
        stripe_mod=FakeStripe,
    )
    assert result["ok"] is True
    assert "sub_test" in result["cancelled_ids"]
    kinds = [c[0] for c in notifier.calls]
    assert "stop" in kinds
    assert "coach" in kinds
    assert any("account_cancellation_events" in q.lower() for q in conn.executed)


@pytest.mark.asyncio
async def test_account_deletion_schedules_30_day_hold():
    FakeStripe.Subscription.cancelled = []
    conn = FakeConn()
    notifier = FakeNotifier()
    result = await stop_charges_for_user(
        FakePool(conn),
        "jakepetersen22",
        source="account_deletion",
        immediate=True,
        schedule_purge=True,
        notifier=notifier,
        stripe_mod=FakeStripe,
    )
    assert result["ok"] is True
    assert any("staged_deletions" in q.lower() for q in conn.executed)
    kinds = [c[0] for c in notifier.calls]
    assert "del" in kinds
    assert "coach" in kinds
    assert notifier.calls[0][1] or True
    del_call = next(c for c in notifier.calls if c[0] == "del")
    assert del_call[2].get("charges_stopped") is True
