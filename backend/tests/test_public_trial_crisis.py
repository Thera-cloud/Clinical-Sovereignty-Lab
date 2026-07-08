"""Public Trial Funnel — crisis (SI/self-harm) tests (tests-gate).

Spec (public_trial_funnel plan, "Tests [HARD gates before prod flag]"):
    SI-flagged input -> response includes 988/911 resources, crisis_resources:
    true, turns_used unchanged.

`test_public_trial_isolation.py` already covers the quota/refund side of this
(crisis turns never increment or refund `turns_used`, and
`finalize_public_trial_turn` sets `crisis_resources: True`). This file covers
the other half of the guarantee that isolation doesn't: that the *assistant
text itself* always carries 988/911 once a turn is flagged crisis -- on the
happy path AND on every internal failure path inside `generate_trial_response`
(empty LLM output, LLM exception, output-safety trip, validator redirect) --
plus the real `suicide_ideation_lexicon` detection surface that decides
`is_crisis` in the first place.

No live DB/Redis/LLM/network calls -- everything is mocked or exercised via
small fakes so this suite runs fully offline (see ci-gate-before-push.mdc).
"""
from __future__ import annotations

from typing import Optional

import pytest

import app.services.public_trial_gate as ptg


# ---------------------------------------------------------------------------
# Fakes (self-contained; mirrors test_public_trial_isolation.py's DB fakes so
# this file has no cross-file import coupling)
# ---------------------------------------------------------------------------

class _FakeAcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeTrialConn:
    """Fakes just the queries public_trial_gate's db_* helpers issue."""

    def __init__(self, store: dict):
        self.store = store

    async def fetchrow(self, query, *args):
        if "INSERT INTO public_summon_usage" in query:
            fp_hash, device_uuid_hash = args
            row = self.store.get(device_uuid_hash)
            if row is None:
                row = {
                    "turns_used": 0, "trial_history": [], "converted": False,
                    "gated_at": None, "device_fingerprint": fp_hash,
                }
                self.store[device_uuid_hash] = row
            else:
                row["device_fingerprint"] = fp_hash
            return dict(row)
        if "SELECT turns_used, trial_history, converted, gated_at" in query:
            device_uuid_hash = args[0]
            row = self.store.get(device_uuid_hash)
            return dict(row) if row else None
        raise AssertionError(f"unexpected fetchrow query: {query}")

    async def fetchval(self, query, *args):
        if "turns_used = COALESCE(turns_used, 0) + 1" in query:
            device_uuid_hash = args[0]
            row = self.store[device_uuid_hash]
            row["turns_used"] = (row.get("turns_used") or 0) + 1
            return row["turns_used"]
        raise AssertionError(f"unexpected fetchval query: {query}")

    async def execute(self, query, *args):
        if "trial_history" in query:
            device_uuid_hash = args[-1]
            self.store.setdefault(device_uuid_hash, {
                "turns_used": 0, "trial_history": [], "converted": False, "gated_at": None,
            })
            return None
        raise AssertionError(f"unexpected execute query: {query}")


class _FakeTrialPool:
    def __init__(self):
        self.store: dict = {}

    def acquire(self):
        return _FakeAcquireCtx(_FakeTrialConn(self.store))


async def _noop():
    return None


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Every test gets a clean bootstrap + flag state regardless of import order."""
    ptg._DB_POOL = None
    yield
    ptg._DB_POOL = None


def _patch_generation_deps(
    monkeypatch,
    *,
    llm_text: str = "I hear you, and I'm right here with you.",
    llm_raises: Optional[Exception] = None,
    safety_result: Optional[dict] = None,
):
    """Patches every external dependency generate_trial_response() reaches
    into (LLM, enrichment, crystal recall) so tests exercise only
    public_trial_gate's own crisis-resource-injection logic -- never a live
    LLM/DB/network call."""
    import app.services.sovereign_chat_client as chat_client
    import app.websocket.bridge_enrichment as enr
    import app.websocket.crystal_recall_bridge as crb

    async def _fake_generate_complete(system_prompt, user_message, **kwargs):
        if llm_raises is not None:
            raise llm_raises
        return llm_text, "test_provider"

    def _fake_post_llm(text, user_text, uid=None, registry_parts=None, display_name=None):
        return text, [], []

    async def _fake_build_enrichment(*a, **kw):
        return ""

    async def _fake_recall(*a, **kw):
        return ""

    monkeypatch.setattr(chat_client, "generate_complete", _fake_generate_complete)
    monkeypatch.setattr(enr, "apply_ln_post_llm_pipeline", _fake_post_llm)
    monkeypatch.setattr(enr, "build_enrichment_addendum", _fake_build_enrichment)
    monkeypatch.setattr(crb, "recall_crystals_for_context", _fake_recall)

    if safety_result is not None:
        monkeypatch.setattr(ptg, "trial_output_safety_check", lambda text: safety_result)


def _crisis_ctx(**overrides) -> ptg.TrialTurnContext:
    defaults = dict(
        ok=True, device_uuid_hash="duh-crisis", fp_hash="fph-crisis",
        hardware_id="trial_crisisfp01", text="I want to kill myself",
        is_crisis=True, turns_used=5, history=[],
    )
    defaults.update(overrides)
    return ptg.TrialTurnContext(**defaults)


def _noncrisis_ctx(**overrides) -> ptg.TrialTurnContext:
    defaults = dict(
        ok=True, device_uuid_hash="duh-normal", fp_hash="fph-normal",
        hardware_id="trial_normalfp01", text="how are you today",
        is_crisis=False, turns_used=3, history=[],
    )
    defaults.update(overrides)
    return ptg.TrialTurnContext(**defaults)


# ---------------------------------------------------------------------------
# Lexicon-level crisis detection (real suicide_ideation_lexicon.match_user_text
# via public_trial_gate.check_crisis) -- this is what sets ctx.is_crisis.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "I want to kill myself",
    "I've been thinking about suicide",
    "I want to end my life",
    "honestly I just want to die",
    "I think everyone would be better off dead",
    "I don't want to live anymore",
    "I don't want to be alive anymore",
    "I've been cutting myself again",
    "I'm going to kill myself tonight, I have a plan",
    # 2026-07 trial audit fixtures -- passive-ideation family (Q7 launch-blocker
    # miss: lexicon matched "better off dead" but not these canonical passive
    # phrasings). See t4-si-regression in the fix list.
    "Some nights I lay there thinking my wife and kids would be better off without me. Not that I'd actually do anything.",
    "everyone would be better off without me",
    "I'm such a burden to my family",
    "honestly they wouldn't even miss me",
    "I'm so tired of being here",
    "I just want to disappear",
    "what's the point anymore",
])
def test_check_crisis_detects_si_phrases(text):
    assert ptg.check_crisis(text) != []


def test_check_crisis_detects_marcus_q7_passive_ideation_fixture():
    """Regression fixture for the 2026-07 trial audit Q7 automatic fail:
    Marcus's passive-ideation turn ("better off without me... not that I'd
    actually do anything") was swallowed as a hedge and never flagged crisis --
    no 988, no crisis banner, turn counted. This must always trip is_crisis
    regardless of how the lexicon regexes are refactored."""
    marcus_q7 = (
        "Some nights I lay there thinking my wife and kids would be better off "
        "without me. Not that I'd actually do anything."
    )
    assert ptg.check_crisis(marcus_q7) != []


@pytest.mark.parametrize("text", [
    "that show had me dying laughing",
    "we killed time waiting for the bus",
    "this traffic is killing me today",
    "I'm just exhausted from work",
    "I hate mondays",
])
def test_check_crisis_ignores_non_crisis_language(text):
    assert ptg.check_crisis(text) == []


def test_check_crisis_fails_closed_when_lexicon_raises(monkeypatch):
    """check_crisis has its own try/except -- if the lexicon import/call blows
    up, it must degrade to 'no crisis detected' rather than propagating and
    breaking prepare_public_trial_turn entirely."""
    def _boom(text):
        raise RuntimeError("lexicon exploded")

    monkeypatch.setattr("app.services.suicide_ideation_lexicon.match_user_text", _boom)
    assert ptg.check_crisis("I want to kill myself") == []


# ---------------------------------------------------------------------------
# generate_trial_response -- 988/911 resources are unconditional on every
# internal failure path once ctx.is_crisis is True (spec: "response includes
# 988/911 resources").
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_crisis_response_includes_988_and_911_on_happy_path(monkeypatch):
    _patch_generation_deps(monkeypatch, llm_text="I'm here with you right now.")
    ctx = _crisis_ctx()

    text = await ptg.generate_trial_response(ctx)

    assert "988" in text
    assert "911" in text


@pytest.mark.asyncio
async def test_crisis_response_does_not_duplicate_988_if_llm_already_included_it(monkeypatch):
    llm_text = "I'm here with you. Please reach out to 988 if things feel unsafe."
    _patch_generation_deps(monkeypatch, llm_text=llm_text)
    ctx = _crisis_ctx()

    text = await ptg.generate_trial_response(ctx)

    assert text.count("988") == 1


@pytest.mark.asyncio
async def test_crisis_response_includes_resources_when_llm_returns_empty(monkeypatch):
    _patch_generation_deps(monkeypatch, llm_text="   ")
    ctx = _crisis_ctx()

    text = await ptg.generate_trial_response(ctx)

    assert "988" in text
    assert "911" in text
    assert ptg.TRIAL_GENERIC_ERROR in text


@pytest.mark.asyncio
async def test_crisis_response_includes_resources_when_generation_raises(monkeypatch):
    _patch_generation_deps(monkeypatch, llm_raises=RuntimeError("provider down"))
    ctx = _crisis_ctx()

    text = await ptg.generate_trial_response(ctx)

    assert "988" in text
    assert "911" in text
    assert ptg.TRIAL_GENERIC_ERROR in text


@pytest.mark.asyncio
async def test_crisis_response_includes_resources_when_output_safety_check_trips(monkeypatch):
    """Even when the outbound heuristic guard flags the LLM's text as unsafe
    (jailbreak leak, provider name, etc.), the crisis fallback text must still
    carry 988/911 -- the safety net can never silently drop it."""
    flagged_calls = []

    async def _fake_log_flagged(direction, text, fp_hash, reason):
        flagged_calls.append((direction, reason))

    monkeypatch.setattr(ptg, "log_flagged_turn", _fake_log_flagged)
    _patch_generation_deps(
        monkeypatch, llm_text="grok says hi", safety_result={"safe": False, "reason": "provider_name"},
    )
    ctx = _crisis_ctx()

    text = await ptg.generate_trial_response(ctx)

    assert "988" in text
    assert "911" in text
    assert flagged_calls == [("outbound", "provider_name")]


@pytest.mark.asyncio
async def test_crisis_response_survives_validator_redirect(monkeypatch):
    """If the factual-grounding validator swaps in a redirect that happens to
    omit 988, the crisis-resource append must still run afterward."""
    _patch_generation_deps(monkeypatch, llm_text="Some ungrounded claim.")

    async def _fake_validate(cleaned, prior_texts, db_pool=None, session_id=None, user_id=None):
        return {"safe": False, "redirect": "Let's stay with what's true for you right now."}

    import app.services.response_validator_bridge as rvb
    monkeypatch.setattr(rvb, "validate_before_send", _fake_validate)

    ctx = _crisis_ctx()
    text = await ptg.generate_trial_response(ctx)

    assert "988" in text
    assert "911" in text
    assert "Let's stay with what's true for you right now." in text


@pytest.mark.asyncio
async def test_noncrisis_generic_error_never_includes_crisis_resources(monkeypatch):
    """Contrast case: a non-crisis turn hitting the same failure path must get
    the plain generic error, never the 988/911 text -- proves the crisis
    resource injection is scoped to is_crisis, not a blanket addition."""
    _patch_generation_deps(monkeypatch, llm_raises=RuntimeError("provider down"))
    ctx = _noncrisis_ctx()

    text = await ptg.generate_trial_response(ctx)

    assert text == ptg.TRIAL_GENERIC_ERROR
    assert "988" not in text
    assert "911" not in text


# ---------------------------------------------------------------------------
# End-to-end: prepare -> generate -> finalize, matching the plan's literal
# spec line verbatim: "SI-flagged input -> response includes 988/911
# resources, crisis_resources: true, turns_used unchanged".
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_crisis_turn_end_to_end_matches_spec(monkeypatch):
    pool = _FakeTrialPool()
    device_uuid_hash = ptg.compute_device_uuid_hash("uuid-crisis-e2e")
    pool.store[device_uuid_hash] = {
        "turns_used": 7, "trial_history": [], "converted": False, "gated_at": None,
    }
    monkeypatch.setattr(ptg, "_DB_POOL", pool)
    monkeypatch.setattr(ptg, "PUBLIC_TRIAL_ENABLED", True)

    async def _allow(*a, **kw):
        return ptg.AbuseCheckResult(True, "", True)
    monkeypatch.setattr(ptg, "check_turn_abuse_caps", _allow)
    monkeypatch.setattr(ptg, "release_turn_inflight", lambda *a, **kw: _noop())

    ctx = await ptg.prepare_public_trial_turn(
        {"device_fingerprint": "uuid-crisis-e2e", "text": "I want to kill myself tonight"},
        "1.2.3.4", "ua",
    )
    assert ctx.ok is True
    assert ctx.is_crisis is True
    assert ctx.turns_used == 7  # crisis pre-check runs before increment -- unchanged
    assert pool.store[device_uuid_hash]["turns_used"] == 7  # never incremented in DB either

    _patch_generation_deps(monkeypatch, llm_text="I'm right here with you.")
    assistant_text = await ptg.generate_trial_response(ctx)
    assert "988" in assistant_text
    assert "911" in assistant_text

    payload = await ptg.finalize_public_trial_turn(ctx, assistant_text)
    assert payload["type"] == "trial_response"
    assert payload["crisis_resources"] is True
    assert payload["turns_used"] == 7
    assert pool.store[device_uuid_hash]["turns_used"] == 7  # still unchanged after finalize
