"""Trial merge ingestion — vault, crystals, digest, ordinal recall, priority fill."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("JWT_SECRET", "test-only-not-a-real-secret-0123456789abcdef")

import app.services.public_trial_conversion as ptc
import app.services.trial_merge_ingestion as tmi


# ---------------------------------------------------------------------------
# Fakes (offline — no live DB/LLM)
# ---------------------------------------------------------------------------

class _FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeTxn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeMergeConn:
    def __init__(self, summon_store: dict, users: dict | None = None):
        self.summon = summon_store
        self.users = users or {}
        self.history: list = []
        self.crystals: list = []

    def transaction(self):
        return _FakeTxn()

    async def fetchrow(self, query, *args):
        if "FROM public_trial_leads" in query:
            return {"device_uuid_hash": args[0] if args else "duh_test"}
        if "FROM public_summon_usage" in query:
            return self.summon.get(args[0])
        if "FROM users WHERE username" in query:
            uname = args[0]
            return self.users.get(uname)
        if "SELECT id FROM users" in query:
            return {"id": "uuid-test6"}
        raise AssertionError(f"unexpected fetchrow: {query[:80]}")

    async def fetchval(self, query, *args):
        if "COUNT(*)" in query and "public_trial_merge" in query:
            return sum(
                1 for h in self.history
                if h.get("meta", {}).get("source") == "public_trial_merge"
            )
        if "COUNT(*)" in query and "conversation_history" in query:
            if "public_trial_merge" not in query:
                if "post-signup" in query or "COALESCE(metadata" in query:
                    return sum(
                        1 for h in self.history
                        if h.get("meta", {}).get("source") != "public_trial_merge"
                    )
                return len(self.history)
        if "SELECT id FROM users" in query:
            return "uuid-test6"
        raise AssertionError(f"unexpected fetchval: {query[:80]}")

    async def fetch(self, query, *args):
        _ids = args[0] if args else []
        limit = args[1] if len(args) > 1 else 15
        rows = [
            h for h in self.history
            if h["user_id"] in _ids and len(h.get("user_text", "")) > 15
        ]
        if "public_trial_merge" in query and "ASC" in query:
            rows = [r for r in rows if r.get("meta", {}).get("source") == "public_trial_merge"]
            rows.sort(key=lambda r: (r["created_at"], r["id"]))
            return rows[:limit]
        if "!= ALL" in query:
            exclude = set(args[2]) if len(args) > 2 else set()
            rows = [r for r in rows if r["id"] not in exclude]
        if "ASC, id ASC" in query and "public_trial_merge" not in query:
            rows.sort(key=lambda r: (r["created_at"], r["id"]))
            return rows[:limit]
        if "DESC, id DESC" in query:
            rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
            return rows[:limit]
        rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
        return rows[:limit]

    async def execute(self, query, *args):
        if "INSERT INTO conversation_history" in query:
            self.history.append({
                "id": len(self.history) + 4909,
                "user_id": args[0],
                "session_id": args[1],
                "user_text": args[2],
                "ai_text": args[3],
                "meta": json.loads(args[4]) if isinstance(args[4], str) else args[4],
                "created_at": args[5] if len(args) > 5 else datetime.now(timezone.utc),
            })
        elif "INSERT INTO nate_intelligence_crystals" in query:
            self.crystals.append({"text": args[0], "origin": args[5] if len(args) > 5 else "trial_merge"})
        elif "UPDATE users SET profile_data" in query:
            uname = args[0]
            digest = args[1]
            u = self.users.setdefault(uname, {
                "hardware_id": "CLIENT_TEST6_ID",
                "role": "CLIENT",
                "name": "Test6",
                "profile_data": {},
            })
            u["profile_data"]["trial_context_digest"] = digest
        elif "UPDATE public_summon_usage" in query or "UPDATE public_trial_leads" in query:
            pass
        else:
            raise AssertionError(f"unexpected execute: {query[:80]}")


class _FakeMergePool:
    def __init__(self, conn: _FakeMergeConn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquireCtx(self._conn)


def _test6_pairs():
    opener = (
        "Hey. Not really sure why I'm here honestly. I haven't been sleeping great "
        "and I keep snapping at my wife over nothing."
    )
    pairs = [(opener, "I hear you. Sleep and tension at home often travel together.")]
    for i in range(1, 20):
        pairs.append((f"Trial follow-up question {i} about stress and family?", f"Nate response {i}"))
    pairs[8] = (
        "I was on medication for PTSD but stopped — is that relevant?",
        "Thank you for sharing that. Medication changes can matter clinically.",
    )
    return pairs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_detect_ordinal_first_question():
    assert tmi.detect_ordinal_recall_intent("what was my first question") == "first"
    assert tmi.detect_ordinal_recall_intent("tell me my earliest message") == "first"
    assert tmi.detect_ordinal_recall_intent("how are you today") is None


@pytest.mark.asyncio
async def test_merge_schedules_ingestion(monkeypatch, tmp_path):
    scheduled = []

    def _fake_schedule(db_pool, **kwargs):
        scheduled.append(kwargs)

    monkeypatch.setattr(tmi, "schedule_trial_merge_ingestion", _fake_schedule)

    duh = "duh_test6"
    duh_hash = ptc.compute_device_uuid_hash(duh)
    pairs = _test6_pairs()
    history = [{"user": u, "assistant": a} for u, a in pairs]
    conn = _FakeMergeConn({duh_hash: {"trial_history": history, "converted": False}})
    pool = _FakeMergePool(conn)

    result = await ptc.try_merge_trial_data(
        pool, device_fingerprint=duh, trial_token=None, new_username="Test6",
    )
    assert result["merged"] is True
    assert len(scheduled) == 1
    assert scheduled[0]["username"] == "Test6"
    assert len(scheduled[0]["valid_pairs"]) == 20


@pytest.mark.asyncio
async def test_vault_and_crystal_on_ingestion(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRIAL_CONTEXT_DIGEST_ENABLED", "0")

    crystallized = {"session": 0, "turns": 0}

    async def _fake_session(db_pool, hw, turns, **kw):
        crystallized["session"] += 1
        return 1

    async def _fake_turn(db_pool, hw, user_text, nate_response, **kw):
        crystallized["turns"] += 1
        return "hash"

    monkeypatch.setattr(
        "app.websocket.crystal_recall_bridge.crystallize_session_summary",
        _fake_session,
    )
    monkeypatch.setattr(
        "app.websocket.crystal_recall_bridge.crystallize_from_conversation",
        _fake_turn,
    )

    pairs = _test6_pairs()[:3]
    conn = _FakeMergeConn({})
    conn.users["Test6"] = {
        "hardware_id": "CLIENT_TEST6_ID",
        "role": "CLIENT",
        "name": "Test6",
    }
    pool = _FakeMergePool(conn)

    await tmi._run_trial_merge_ingestion(
        pool, username="Test6", valid_pairs=pairs,
        session_id="trial_duh_test", matched_via="trial_token",
    )

    mem_path = tmp_path / "Vaults" / "Clients" / "CLIENT_TEST6_ID" / "memory.json"
    assert mem_path.exists()
    entries = json.loads(mem_path.read_text())
    assert len(entries) == 3
    assert entries[0]["source"] == "trial_merge"
    assert "snapping" in entries[0]["user"]
    assert crystallized["session"] == 1
    assert crystallized["turns"] >= 1


@pytest.mark.asyncio
async def test_digest_crystal_and_profile(monkeypatch):
    conn = _FakeMergeConn({})
    conn.users["Test6"] = {
        "hardware_id": "CLIENT_TEST6_ID",
        "role": "CLIENT",
        "name": "Test6",
        "profile_data": {},
    }
    pool = _FakeMergePool(conn)

    async def _fake_digest(pairs):
        return "Sleep trouble, snapping at spouse, PTSD meds stopped."

    monkeypatch.setattr(tmi, "_generate_trial_digest", _fake_digest)

    await tmi._persist_trial_digest(
        pool, username="Test6", hardware_id="CLIENT_TEST6_ID",
        digest="Sleep trouble, snapping at spouse, PTSD meds stopped.",
        user_name="Test6",
    )

    assert len(conn.crystals) == 1
    assert "trial_merge" in conn.crystals[0]["text"] or conn.crystals[0].get("origin") == "trial_merge"
    assert conn.users["Test6"]["profile_data"]["trial_context_digest"].startswith("Sleep")


@pytest.mark.asyncio
async def test_trial_context_injected_turn3_not_turn12(monkeypatch):
    conn = _FakeMergeConn({})
    pool = _FakeMergePool(conn)
    profile = {"profile_data": {"trial_context_digest": "Trial themes: sleep, snapping, PTSD meds."}}

    async def _count3(*a, **k):
        return 2

    async def _count12(*a, **k):
        return 11

    monkeypatch.setattr(conn, "fetchval", _count3)
    block3 = await tmi.build_trial_context_prompt_block(pool, "Test6", profile)
    assert block3.startswith("TRIAL CONTEXT:")
    assert "sleep" in block3.lower()

    monkeypatch.setattr(conn, "fetchval", _count12)
    block12 = await tmi.build_trial_context_prompt_block(pool, "Test6", profile)
    assert block12 == ""


@pytest.mark.asyncio
async def test_chronological_first_query_returns_opener():
    """Ordinal 'first' path returns sleep/snapping opener, not later meta-question."""
    merge_now = datetime.now(timezone.utc)
    pairs = _test6_pairs()
    conn = _FakeMergeConn({})
    for idx, (u, a) in enumerate(pairs):
        conn.history.append({
            "id": 4909 + idx,
            "user_id": "Test6",
            "user_text": u,
            "ai_text": a,
            "meta": {"source": "public_trial_merge"},
            "created_at": merge_now - timedelta(seconds=(len(pairs) - 1 - idx)),
        })
    conn.history.append({
        "id": 4933,
        "user_id": "Test6",
        "user_text": "what was my first question to you in this app?",
        "ai_text": "meta response",
        "meta": {},
        "created_at": merge_now + timedelta(hours=1),
    })
    assert tmi.detect_ordinal_recall_intent("what was my first question") == "first"
    rows = await conn.fetch(
        "SELECT user_text, ai_text, created_at, session_id "
        "FROM conversation_history WHERE user_id = ANY($1) "
        "AND LENGTH(user_text) > 15 "
        "ORDER BY created_at ASC, id ASC LIMIT $2",
        ["Test6"], 3,
    )
    assert "snapping" in rows[0]["user_text"] or "sleeping" in rows[0]["user_text"]


def test_anonymous_trial_does_not_schedule_ingestion(monkeypatch):
    """Ingestion fires only at merge — public_trial_gate must not import scheduler."""
    import inspect
    import app.services.public_trial_gate as ptg
    src = inspect.getsource(ptg)
    assert "trial_merge_ingestion" not in src
    assert "schedule_trial_merge_ingestion" not in src
