"""Regression tests for the 2026-11-05 duplicate session charge (Blake Barnes).

A Zoom-repair upsert reset payment_status paid→pending every 30 min and the
payment agent re-charged on each cycle. These tests pin every layer of the fix
and run fully offline (no DB, no Stripe network).
"""

import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import pg_data_helpers
from app.services import session_charge_guard as guard
from app.services.session_payment_agent import SessionPaymentAgent
from app.services.session_zoom_repair import session_dict_from_row


# ── Layer 0: the dict handed to the upsert carries billing state ──────────────

def test_session_dict_from_row_carries_billing_columns():
    row = {
        "session_id": "SES_X", "client_id": "C", "coach_id": "K",
        "scheduled_start": datetime(2026, 11, 9, 14, tzinfo=timezone.utc),
        "payment_status": "paid", "price_cents": 9000,
        "stripe_payment_intent_id": "pi_legit",
        "session_data": {"billing_obligation": "collected"},
    }
    d = session_dict_from_row(row)
    assert d["payment_status"] == "paid"
    assert d["price_cents"] == 9000
    assert d["stripe_payment_intent_id"] == "pi_legit"


def test_session_dict_from_row_omits_missing_billing_columns():
    d = session_dict_from_row({"session_id": "SES_Y", "status": "scheduled"})
    assert "payment_status" not in d
    assert "price_cents" not in d


# ── Layer 1: upsert never downgrades money states, never self-nests ───────────

class _AsyncCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        return False


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _AsyncCtx(self._conn)


@pytest.mark.asyncio
async def test_upsert_sql_has_never_downgrade_guard_and_flattens_session_data():
    conn = AsyncMock()
    nested = {"billing_obligation": "collected", "session_data": {"deep": 1, "session_data": {"deeper": 2}}}
    ok = await pg_data_helpers.upsert_session_pg(
        _Pool(conn),
        {
            "session_id": "SES_GUARD", "client_id": "C", "coach_id": "K",
            "scheduled_start": "2026-11-09T14:00:00+00:00", "status": "scheduled",
            "session_data": nested,  # caller echoes row.session_data back
        },
    )
    assert ok is True
    sql = conn.execute.await_args_list[0].args[0]
    args = conn.execute.await_args_list[0].args
    assert "LOWER(COALESCE(coaching_sessions.payment_status, '')) IN ('paid','refunded','partially_refunded')" in sql
    assert "THEN coaching_sessions.payment_status" in sql
    assert "payment_status = EXCLUDED.payment_status," not in sql  # old unconditional overwrite is gone
    assert "'billing_obligation', 'collected'" in sql  # re-asserted after merge
    import json
    extra = json.loads(args[30])  # args[0]=sql, $30 session_data json -> args[30]; $31 created_at -> args[31]
    assert "session_data" not in extra
    assert extra["billing_obligation"] == "collected"
    assert extra["deep"] == 1 and extra["deeper"] == 2
    assert "charge_claim_at" not in extra


def test_flatten_session_data_extra_lifts_nested_levels():
    out = guard.flatten_session_data_extra(
        {"a": 1, "session_data": '{"b": 2, "session_data": {"c": 3, "a": 99}}'}
    )
    assert out == {"a": 1, "b": 2, "c": 3}  # explicit top-level wins


# ── Layer 2: collected_reason stops every "already paid" shape ────────────────

@pytest.mark.parametrize("state,expect", [
    ({"payment_status": "paid"}, "payment_status=paid"),
    ({"payment_status": "refunded"}, "payment_status=refunded"),
    ({"payment_status": "pending", "stripe_payment_intent_id": "pi_1"}, "stripe_payment_intent_id"),
    ({"payment_status": "pending", "billing_obligation": "collected"}, "billing_obligation"),
    ({"payment_status": "pending", "charges": 1}, "charge_succeeded"),
    ({"payment_status": "cancelled"}, "not pending"),
    (None, "not found"),
])
def test_collected_reason_blocks(state, expect):
    reason = guard.collected_reason(state)
    assert reason and expect in reason


def test_collected_reason_allows_clean_pending():
    assert guard.collected_reason(
        {"payment_status": "pending", "stripe_payment_intent_id": "", "billing_obligation": None, "charges": 0}
    ) is None


def test_idempotency_key_stable_and_distinct():
    k1 = guard.idempotency_key("u-1", 9000, "pm_a")
    assert k1 == guard.idempotency_key("u-1", 9000, "pm_a")
    assert k1 != guard.idempotency_key("u-1", 9000, "pm_b")
    assert k1 != guard.idempotency_key("u-1", 3000, "pm_a")


def test_amount_ceiling():
    assert guard.amount_within_ceiling(9000)
    assert not guard.amount_within_ceiling(0)
    assert not guard.amount_within_ceiling(guard.MAX_SESSION_CHARGE_CENTS + 1)


def test_not_collected_sql_checks_all_three_signals():
    assert "cs.stripe_payment_intent_id" in guard.NOT_COLLECTED_SQL
    assert "billing_obligation" in guard.NOT_COLLECTED_SQL
    assert "charge_succeeded" in guard.NOT_COLLECTED_SQL


# ── Layer 3: the agent never reaches Stripe for a collected session ───────────

def _fake_stripe(search_data=None, raise_on_search=None):
    mod = types.ModuleType("stripe")
    mod.api_key = "sk_test_fake"
    created = []

    class _PI:
        @staticmethod
        def search(query, limit=5):
            if raise_on_search:
                raise raise_on_search
            return SimpleNamespace(data=list(search_data or []))

        @staticmethod
        def create(**kw):
            created.append(kw)
            return SimpleNamespace(id="pi_new", status="succeeded", latest_charge="ch_new")

    class _Charge:
        @staticmethod
        def retrieve(cid):
            return SimpleNamespace(receipt_url="https://r")

    class _PM:
        @staticmethod
        def list(**kw):
            return SimpleNamespace(data=[SimpleNamespace(id="pm_card")])

    class _Customer:
        @staticmethod
        def retrieve(cid):
            return SimpleNamespace(invoice_settings={"default_payment_method": "pm_card"})

    mod.PaymentIntent = _PI
    mod.Charge = _Charge
    mod.PaymentMethod = _PM
    mod.Customer = _Customer
    mod._created = created
    return mod


def _session(**over):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "session_id_str": "SES_TEST", "coach_id": "COACH_COACHN_ID",
        "client_id": "CLIENT_X", "client_email": "x@example.com",
        "client_default_pm": "pm_card", "coach_connect_id": "", "session_data": {},
        "price_cents": 9000,
    }
    base.update(over)
    return base


def _conn_with_state(state, claim_result="UPDATE 1"):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=state)
    conn.execute = AsyncMock(return_value=claim_result)
    return conn


@pytest.mark.asyncio
async def test_charge_card_skips_when_db_says_collected(monkeypatch):
    stripe_mod = _fake_stripe()
    monkeypatch.setitem(sys.modules, "stripe", stripe_mod)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    agent = SessionPaymentAgent(db_pool=MagicMock(), app_state=None)
    conn = _conn_with_state(
        {"payment_status": "pending", "stripe_payment_intent_id": "pi_legit",
         "billing_obligation": "collected", "charge_claim_at": None, "charges": 1}
    )
    res = await agent._charge_card(conn, _session(), "cus_1", 9000)
    assert res is None
    assert stripe_mod._created == []
    # charge_skipped logged (session_payment_events: $1 session_id, $2 event_type)
    kinds = [c.args[2] for c in conn.execute.await_args_list if len(c.args) > 2]
    assert "charge_skipped" in kinds


@pytest.mark.asyncio
async def test_charge_card_reconciles_when_stripe_already_succeeded(monkeypatch):
    existing = SimpleNamespace(id="pi_prior", status="succeeded", amount=9000, latest_charge="ch_prior")
    stripe_mod = _fake_stripe(search_data=[existing])
    monkeypatch.setitem(sys.modules, "stripe", stripe_mod)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    agent = SessionPaymentAgent(db_pool=MagicMock(), app_state=None)
    conn = _conn_with_state(
        {"payment_status": "pending", "stripe_payment_intent_id": "",
         "billing_obligation": None, "charge_claim_at": None, "charges": 0}
    )
    res = await agent._charge_card(conn, _session(), "cus_1", 9000)
    assert res is None
    assert stripe_mod._created == []
    sqls = " ".join(str(c.args[0]) for c in conn.execute.await_args_list)
    assert "payment_status = 'paid'" in sqls
    assert "charge_reconciled" in " ".join(str(c.args) for c in conn.execute.await_args_list)


@pytest.mark.asyncio
async def test_charge_card_fails_closed_when_stripe_unverifiable(monkeypatch):
    stripe_mod = _fake_stripe(raise_on_search=RuntimeError("search down"))
    monkeypatch.setitem(sys.modules, "stripe", stripe_mod)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    agent = SessionPaymentAgent(db_pool=MagicMock(), app_state=None)
    conn = _conn_with_state(
        {"payment_status": "pending", "stripe_payment_intent_id": "",
         "billing_obligation": None, "charge_claim_at": None, "charges": 0}
    )
    res = await agent._charge_card(conn, _session(), "cus_1", 9000)
    assert res is None  # not False → caller sends no reminder/invoice either
    assert stripe_mod._created == []


@pytest.mark.asyncio
async def test_charge_card_skips_when_claim_not_won(monkeypatch):
    stripe_mod = _fake_stripe()
    monkeypatch.setitem(sys.modules, "stripe", stripe_mod)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    agent = SessionPaymentAgent(db_pool=MagicMock(), app_state=None)
    conn = _conn_with_state(
        {"payment_status": "pending", "stripe_payment_intent_id": "",
         "billing_obligation": None, "charge_claim_at": None, "charges": 0},
        claim_result="UPDATE 0",
    )
    res = await agent._charge_card(conn, _session(), "cus_1", 9000)
    assert res is None
    assert stripe_mod._created == []


@pytest.mark.asyncio
async def test_charge_card_happy_path_uses_idempotency_key_and_ledger(monkeypatch):
    stripe_mod = _fake_stripe()
    monkeypatch.setitem(sys.modules, "stripe", stripe_mod)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    fin = types.ModuleType("app.services.session_financial_records")
    fin.platform_fee_cents_from_session = lambda s, a: 3000
    fin.mark_coach_ledger_collected = AsyncMock()
    monkeypatch.setitem(sys.modules, "app.services.session_financial_records", fin)
    agent = SessionPaymentAgent(db_pool=MagicMock(), app_state=None)
    conn = _conn_with_state(
        {"payment_status": "pending", "stripe_payment_intent_id": "",
         "billing_obligation": None, "charge_claim_at": None, "charges": 0}
    )
    res = await agent._charge_card(conn, _session(), "cus_1", 9000)
    assert res is True
    assert len(stripe_mod._created) == 1
    kw = stripe_mod._created[0]
    assert kw["idempotency_key"] == guard.idempotency_key(_session()["id"], 9000, "pm_card")
    assert kw["metadata"]["session_uuid"] == _session()["id"]
    sqls = [str(c.args[0]) for c in conn.execute.await_args_list]
    assert any("INSERT INTO payment_history" in s for s in sqls)
    assert any("- 'charge_claim_at'" in s for s in sqls)  # claim cleared on success


# ── Layer 4: check-in agent only repairs when a reminder will actually send ──

def test_reminder_pending_for_mirrors_send_gates():
    from app.services.nate_checkin_agent import NateCheckInAgent
    agent = NateCheckInAgent.__new__(NateCheckInAgent)
    agent.notification_system = object()
    both_sent = {"client_reminded": True, "coach_reminded": True}
    none_sent = {"client_reminded": False, "coach_reminded": False}
    assert agent._reminder_pending_for(both_sent, "c@x", {}, "k@x", {}) is False
    assert agent._reminder_pending_for(none_sent, "c@x", {}, "k@x", {}) is True
    assert agent._reminder_pending_for(none_sent, "", {}, "", {}) is False
    assert agent._reminder_pending_for(
        none_sent, "c@x", {"notif_session_reminders": False}, "k@x", {"session_reminders": False}
    ) is False
    only_coach_left = {"client_reminded": True, "coach_reminded": False}
    assert agent._reminder_pending_for(only_coach_left, "c@x", {}, "k@x", {}) is True


# ── Layer 5: invoice auto-pay refuses a second collection ─────────────────────

@pytest.mark.asyncio
async def test_session_collected_elsewhere_blocks_other_pi():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "payment_status": "paid", "stripe_payment_intent_id": "pi_card", "billing_obligation": "collected",
    })
    assert await guard.session_collected_elsewhere(conn, "SES_1", "pi_invoice")
    assert await guard.session_collected_elsewhere(conn, "SES_1", "pi_card") is None  # same PI ok
    conn.fetchrow = AsyncMock(return_value={
        "payment_status": "pending", "stripe_payment_intent_id": "", "billing_obligation": None,
    })
    assert await guard.session_collected_elsewhere(conn, "SES_1", "pi_invoice") is None


@pytest.mark.asyncio
async def test_pay_or_revive_blocks_double_collection(monkeypatch):
    from app.services import session_invoice_repay as repay
    inv = SimpleNamespace(
        id="in_1", status="open", customer="cus_1", payment_intent="pi_inv",
        hosted_invoice_url="https://inv", metadata={"session_id": "SES_1", "type": "session_fee"},
        default_payment_method=None, charge=None,
    )
    stripe_mod = _fake_stripe()
    paid_calls = []
    stripe_mod.Invoice = SimpleNamespace(
        modify=lambda *a, **k: None,
        pay=lambda *a, **k: paid_calls.append(k) or inv,
        send_invoice=lambda *a, **k: None,
    )
    monkeypatch.setattr(repay, "_ensure_stripe", lambda: stripe_mod)
    monkeypatch.setattr(repay, "retrieve_invoice", lambda _id: inv)
    monkeypatch.setattr(repay, "invoice_needs_revive", lambda _inv: False)
    monkeypatch.setattr(repay, "should_skip_auto_pay", lambda _inv, _pm: False)
    # Bare connection (no .acquire) — AsyncMock would auto-create `acquire`.
    conn = SimpleNamespace(
        fetchrow=AsyncMock(return_value={
            "payment_status": "paid", "stripe_payment_intent_id": "pi_card", "billing_obligation": "collected",
        }),
        execute=AsyncMock(return_value="UPDATE 0"),
    )
    out = await repay.pay_or_revive_open_invoice(conn, invoice_id="in_1", payment_method_id="pm_1", charge=True)
    assert paid_calls == []
    assert out["double_collection_blocked"] is True
    assert out["paid"] is False
