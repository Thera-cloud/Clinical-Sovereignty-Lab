"""Offline unit tests — Abductive Parts Hypothesis Loop (app.sse.parts_hypothesis).

No DB, no network, no import-time I/O. The LLM is stubbed.
"""
from __future__ import annotations

import asyncio

import pytest

from app.sse import parts_hypothesis as ph


def _synthetic_sessions():
    # Five fictional sessions, anxious-vigilant pattern, no intake description of any figure.
    return [
        {"text": "When he goes quiet on the phone I can't relax, I'm scanning the room for what I did wrong.", "session_id": "s1"},
        {"text": "I read it twice and still didn't answer. Waiting for the other shoe, like always.", "session_id": "s2"},
        {"text": "At work I'm on alert all day, watch their face in every meeting, I brace myself before I open email.", "session_id": "s3"},
        {"text": "My sister said I keep people out. Maybe. The walls up thing is just how I stay okay.", "session_id": "s4"},
        {"text": "Can't let my guard down even on vacation. Something's coming, that's the feeling.", "session_id": "s5"},
    ]


def test_lexicon_scores_and_sessions():
    ev = ph.mine_parts_evidence(_synthetic_sessions())
    assert ev["part_scores"]["protector_watch"] >= 6
    assert len(ev["sessions_by_category"]["protector_watch"]) >= 3
    assert ev["dissociation_markers"] == 0
    assert ev["acute_risk_markers"] == 0


def test_crystal_texts_do_not_inflate_sessions():
    ev = ph.mine_parts_evidence([{"text": "walls up, on alert, on guard", "session_id": None, "channel": "crystal"}])
    assert ev["part_scores"]["protector_watch"] == 3
    assert ev["sessions_by_category"].get("protector_watch", []) == []


def test_gate_requires_flag_and_opt_in():
    ev = ph.mine_parts_evidence(_synthetic_sessions())
    assert ph.eligibility_gate({}, {}, ev, flag_enabled=False)["reason"] == "feature_flag_off"
    assert ph.eligibility_gate({}, {}, ev, flag_enabled=True)["reason"] == "user_not_opted_in"
    ok = ph.eligibility_gate({}, {"parts_hypothesis_opt_in": True}, ev, flag_enabled=True)
    assert ok.allowed and ok["mode"] == "full"


def test_gate_clinical_denials():
    ev = ph.mine_parts_evidence(_synthetic_sessions())
    jm = {"parts_hypothesis_opt_in": True}
    assert ph.eligibility_gate({"_coaching_calibration": {"coach_hold_active": True}}, jm, ev, flag_enabled=True)["reason"] == "coach_hold_active"
    assert ph.eligibility_gate({"_family_context": {"age_gated": True}}, jm, ev, flag_enabled=True)["reason"] == "age_gated"
    assert ph.eligibility_gate({"_assessment_calibration": {"risk_areas": ["safety_concern_language"]}}, jm, ev, flag_enabled=True)["reason"] == "acute_risk_defer"
    acute = ph.mine_parts_evidence([{"text": "some days I don't want to be here", "session_id": "x"}])
    assert ph.eligibility_gate({}, jm, acute, flag_enabled=True)["reason"] == "acute_risk_defer"


def test_gate_dissociation_requires_enrollment_and_registry():
    ev = ph.mine_parts_evidence([{"text": "sometimes I lose time and someone else takes over", "session_id": "d1"}])
    jm = {"parts_hypothesis_opt_in": True}
    assert ph.eligibility_gate({}, jm, ev, flag_enabled=True)["reason"] == "sensitive_requires_enrollment"
    assert ph.eligibility_gate({}, jm, ev, enrollment={"cohort_label": "DID"}, flag_enabled=True)["reason"] == "sensitive_requires_parts_registry"
    g = ph.eligibility_gate({}, jm, ev, enrollment={"cohort_label": "DID"},
                            parts_registry=[{"part_name": "The Keeper", "is_active": True}], flag_enabled=True)
    assert g.allowed and g["mode"] == "registry_aligned" and g["registry_parts"] == ["The Keeper"]


def test_rank_candidates_floors_and_cap():
    ev = ph.mine_parts_evidence(_synthetic_sessions())
    # lexical only → 1 channel → not eligible even with 5 sessions
    ranked = ph.rank_candidates(ev)
    top = ranked[0]
    assert top["category"] == "protector_watch" and top["eligible"] is False
    # add dynamics channel → eligible, confidence capped
    dyn = ph.dynamic_signals([{"c_emo": 0.8, "session_id": "s1"}, {"c_emo": 0.5, "session_id": "s1"},
                              {"c_emo": 0.7, "session_id": "s3"}, {"c_emo": 0.4, "session_id": "s3"}])
    assert dyn["active"]
    ranked = ph.rank_candidates(ev, dyn, priors={c: 0.95 for c in ph.FIGURE_CATEGORIES})
    top = ranked[0]
    assert top["eligible"] is True
    assert 0 < top["confidence"] <= ph.CONFIDENCE_CAP


def test_two_sessions_never_eligible():
    ev = ph.mine_parts_evidence(_synthetic_sessions()[:2])
    dyn = {"active": True, "drops": []}
    beh = {"active": True}
    assert all(c["eligible"] is False for c in ph.rank_candidates(ev, dyn, beh))


def test_synthesis_template_and_llm_paths():
    ev = ph.mine_parts_evidence(_synthetic_sessions())
    dyn = {"active": True, "drops": [{"from": 0.8, "to": 0.5, "topic": "silence"}]}
    top = ph.rank_candidates(ev, dyn)[0]
    hyp = asyncio.run(ph.synthesize_hypothesis("u1", ev, top, dyn, llm=None))
    assert hyp["source"] == "template" and hyp["provenance"] == "inferred" and hyp["confidence"] <= 0.49
    assert ph.is_interrogative(hyp["question"])

    async def good_llm(msgs, max_tokens=0, temperature=0.0):
        return ('{"role":"keeps the door watched","protects_from":"surprise","trigger_pattern":"silence",'
                '"affect_signature":"tight","stance":"vigilant",'
                '"proposed_form":"a cloaked figure far up the hillside holding an unlit lantern",'
                '"question":"You have a protector that never sleeps."}')
    hyp2 = asyncio.run(ph.synthesize_hypothesis("u1", ev, top, dyn, llm=good_llm))
    assert hyp2["source"] == "llm"
    assert ph.is_interrogative(hyp2["question"])  # assertion was softened

    async def clinical_llm(msgs, max_tokens=0, temperature=0.0):
        return ('{"role":"trauma guard","protects_from":"x","trigger_pattern":"y","affect_signature":"z",'
                '"stance":"vigilant","proposed_form":"a figure","question":"I wonder"}')
    hyp3 = asyncio.run(ph.synthesize_hypothesis("u1", ev, top, dyn, llm=clinical_llm))
    assert hyp3["source"] == "template"  # clinical label rejected


def test_form_screen_and_selection():
    ok, _ = ph.screen_form_text("a cloaked watcher at the treeline with an unlit lantern")
    assert ok
    assert ph.screen_form_text("a black cat watching from the fence")[1] == "denylist"
    assert ph.screen_form_text("a small child hiding under a blanket")[1] == "denylist"
    assert ph.screen_form_text("your protector standing behind you")[1] == "describes_person"
    hyp = {"category": "protector_watch", "hypothesis_id": "abc", "role": "keeps watch",
           "proposed_form": "a wolf pacing the ridge"}
    form = ph.select_form(hyp, posture={})
    assert form["source"] == "catalog" and form["symbol_id"] is None  # owl form excluded, wolf rejected
    form_owl = ph.select_form(hyp, posture={"owl": "opted_in"}, variety_seed=2, allow_llm_form=False)
    assert form_owl["form_id"] == "owl_watcher"


def test_figure_naming():
    assert ph._clean_name("the Haze beyond the Clearing") == "the Haze beyond the Clearing"
    assert ph._clean_name("the Watcher at the Treeline") == ""  # catalog echo rejected (not fresh)
    assert ph._clean_name("Scans For Sudden") == ""          # verb phrase rejected
    assert ph._clean_name("the Wolf at the Gate") == ""      # denylist symbol
    assert ph._clean_name("the Trauma Keeper") == ""         # clinical label
    assert ph._name_from_form("a faint haze lingering at the clearing edge") == "the Faint Haze at the Clearing Edge"
    assert ph._name_from_form("a cloaked watcher standing far back at the treeline, half-turned") == "the Cloaked Watcher at the Treeline"
    hyp = {"hypothesis_id": "x", "category": "protector_watch", "role": "scans for sudden shifts",
           "proposed_form": "a faint haze lingering at the clearing edge"}
    form = ph.select_form(hyp, posture={}, allow_llm_form=True)
    assert form["source"] == "llm" and form["name"] == "the Faint Haze at the Clearing Edge"
    hyp["name"] = "the Quiet Sentinel"
    assert ph.select_form(hyp, posture={}, allow_llm_form=True)["name"] == "the Quiet Sentinel"


def test_phrasing_guard_and_block():
    assert ph.soften_assertion("Your protector is tired.").startswith("I wonder")
    assert ph.is_interrogative("I keep noticing a figure at the edge.")
    assert not ph.is_interrogative("You are avoidant.")
    npc = ph.npc_from_hypothesis(
        {"hypothesis_id": "h1", "role": "keeps watch", "category": "protector_watch", "confidence": 0.31,
         "question": "I wonder what it listens for."},
        {"name": "the Watcher", "visual_prompt_fragment": "a cloaked watcher", "source": "catalog"})
    block = ph.hypothesis_block([npc])
    assert "A FIGURE NATE IS WONDERING ABOUT" in block and "RECURRING COMPANIONS" not in block
    assert ph.hypothesis_block([{"name": "Ash", "provenance": "crystal"}]) == ""
    entry = ph.legend_entry(npc)
    assert entry["role"] == "A figure Nate is wondering about" and "clinical_translation" not in entry
    assert "clinical_translation" in ph.legend_entry(npc, coach_view=True)


def test_engagement_and_cadence():
    reg = {"h1": {"hypothesis_id": "h1", "category": "protector_watch", "status": "proposed",
                  "created_at": "2026-11-01T00:00:00+00:00", "last_shown_seq": 10}}
    assert ph.choose_todays_figure(reg, 11) is None          # cadence hold
    assert ph.choose_todays_figure(reg, 13) is not None      # every 3rd panel
    reg, ledger = ph.apply_engagement(reg, [], "h1", "banished", "that's not me")
    assert reg["h1"]["status"] == "banished" and ledger[-1]["kind"] == "banished"
    assert ph._banished_recently(reg, "protector_watch")
    priors = ph.prior_from_presenting_concern("I get anxious when people go quiet", ledger)
    assert priors["protector_watch"] == pytest.approx(0.4)   # 0.8 prior halved by banish
    with pytest.raises(ValueError):
        ph.apply_engagement(reg, ledger, "h1", "bogus")


def test_run_loop_end_to_end_offline():
    bundle = {
        "texts": _synthetic_sessions(),
        "c_emo": [{"c_emo": 0.8, "session_id": "s1"}, {"c_emo": 0.5, "session_id": "s1"},
                  {"c_emo": 0.7, "session_id": "s3"}, {"c_emo": 0.4, "session_id": "s3"}],
        "behavior": [], "presenting_concern": "I get anxious and can't trust that people will stay",
        "enrollment": None, "parts_registry": [],
    }
    trace = asyncio.run(ph.run_loop("u1", {}, {"parts_hypothesis_opt_in": True}, bundle,
                                    panel_sequence=4, llm=None, posture={}, flag_enabled=True))
    npc = trace["npc"]
    assert npc and npc["provenance"] == "inferred" and npc["category"] == "protector_watch"
    assert npc["confidence"] <= ph.CONFIDENCE_CAP and npc["visual_prompt_fragment"]
    assert trace["registry"][npc["hypothesis_id"]]["last_shown_seq"] == 4
    # second run next panel → cadence hold, no figure
    jm = {"parts_hypothesis_opt_in": True, "hypothesis_registry": trace["registry"]}
    trace2 = asyncio.run(ph.run_loop("u1", {}, jm, bundle, panel_sequence=5, llm=None, posture={}, flag_enabled=True))
    assert trace2["npc"] is None and trace2["reason"] == "cadence_hold"
    # flag off → nothing, ever
    trace3 = asyncio.run(ph.run_loop("u1", {}, jm, bundle, panel_sequence=9, llm=None, posture={}, flag_enabled=False))
    assert trace3["npc"] is None and trace3["gate"]["reason"] == "feature_flag_off"


# ---------------------------------------------------------------------------
# Gap fixes — Sensitive Bridge guardrails, confirmation → registry/crystal,
# coach decision sync, opt-in. All DB access goes through a recording fake pool.
# ---------------------------------------------------------------------------
import json as _json
from datetime import datetime as _dt, timedelta as _td, timezone as _tz


class _FakeConn:
    """Matches SQL by substring; records every call. Unmatched → None / [] / 'OK'."""

    def __init__(self, rules):
        self.rules = rules
        self.calls = []

    def _lookup(self, sql, default):
        for needle, value in self.rules:
            if needle in sql:
                return value() if callable(value) else value
        return default

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._lookup(sql, None)

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self._lookup(sql, None)

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._lookup(sql, [])

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return self._lookup(sql, "OK")


class _FakePool:
    def __init__(self, rules=()):
        self.conn = _FakeConn(list(rules))

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()

    def sql(self, verb=None):
        return [c[1] for c in self.conn.calls if verb is None or c[0] == verb]


def _journey_rules(registry, opt_in=True, user_id="CLIENT_JANE_ID", ledger=None):
    jmeta = {"parts_hypothesis_opt_in": opt_in, "hypothesis_registry": registry,
             "hypothesis_ledger": ledger or []}
    return [
        ("FROM users WHERE hardware_id", {"username": "jane", "hardware_id": "CLIENT_JANE_ID"}),
        ("FROM sse_user_journeys", {"user_id": user_id, "journey_metadata": _json.dumps(jmeta)}),
    ]


def _hyp(hid="h9", status="proposed", **extra):
    h = {"hypothesis_id": hid, "category": "protector_watch", "status": status,
         "role": "keeps the door watched", "confidence": 0.33, "question": "I wonder what it listens for.",
         "created_at": "2026-11-01T00:00:00+00:00",
         "form": {"form_id": "llm:abc", "name": "the Treeline Observer",
                  "visual_prompt_fragment": "a faint figure at the treeline", "source": "llm"}}
    h.update(extra)
    return h


def test_gate_safety_deferrals_each_silence_nate():
    ev = ph.mine_parts_evidence(_synthetic_sessions())
    jm = {"parts_hypothesis_opt_in": True}
    for deferral in ph.SAFETY_DEFERRALS:
        g = ph.eligibility_gate({}, jm, ev, flag_enabled=True, safety={deferral: True})
        assert not g.allowed and g["reason"] == deferral
    # all clear → full mode as before
    g = ph.eligibility_gate({}, jm, ev, flag_enabled=True, safety={k: False for k in ph.SAFETY_DEFERRALS})
    assert g.allowed and g["mode"] == "full"


def test_registry_aligned_echoes_approved_parts_only():
    ev = ph.mine_parts_evidence([{"text": "sometimes I lose time and someone else takes over", "session_id": "d1"}])
    jm = {"parts_hypothesis_opt_in": True}
    pending = [{"part_name": "The Keeper", "is_active": True, "coaching_status": "PENDING_APPROVAL"}]
    assert ph.eligibility_gate({}, jm, ev, enrollment={"cohort_label": "DID"}, parts_registry=pending,
                               flag_enabled=True)["reason"] == "sensitive_requires_parts_registry"
    approved = [{"part_name": "The Keeper", "is_active": True, "coaching_status": "APPROVED"},
                {"part_name": "Old One", "is_active": False, "coaching_status": "APPROVED"}]
    g = ph.eligibility_gate({}, jm, ev, enrollment={"cohort_label": "DID"}, parts_registry=approved, flag_enabled=True)
    assert g.allowed and g["registry_parts"] == ["The Keeper"]


def test_trigger_date_window_and_anniversaries():
    today = _dt(2026, 11, 5, tzinfo=_tz.utc)
    assert ph.trigger_date_active([{"trigger_date": today.date()}], today=today)
    assert ph.trigger_date_active([{"trigger_date": "2026-11-07"}], today=today)
    assert not ph.trigger_date_active([{"trigger_date": "2026-11-20"}], today=today)
    # anniversary only counts when recurring_annually
    assert ph.trigger_date_active([{"trigger_date": "2019-11-04", "recurring_annually": True}], today=today)
    assert not ph.trigger_date_active([{"trigger_date": "2019-11-04", "recurring_annually": False}], today=today)
    assert ph.trigger_date_active([{"trigger_date": _dt(2020, 2, 29), "recurring_annually": True}],
                                  today=_dt(2027, 2, 28, tzinfo=_tz.utc))
    assert not ph.trigger_date_active([{"trigger_date": None}, {"trigger_date": "garbage"}], today=today)


def test_ifs_lens_disabled_reads_framework_menu():
    off = {"sensitive_bridge": {"framework_preferences": {"enabled_frameworks": {"ifs": False, "act": True}}}}
    assert ph.ifs_lens_disabled(off, enrolled=True)
    assert not ph.ifs_lens_disabled(off, enrolled=False)              # no menu for non-enrolled
    assert ph.ifs_lens_disabled(_json.dumps(off), enrolled=True)      # JSONB arrives as str sometimes
    on = {"sensitive_bridge": {"framework_preferences": {"enabled_frameworks": ["ifs", "act"]}}}
    assert not ph.ifs_lens_disabled(on, enrolled=True)
    only_act = {"sensitive_bridge": {"framework_preferences": {"enabled_lenses": ["act"]}}}
    assert ph.ifs_lens_disabled(only_act, enrolled=True)
    assert not ph.ifs_lens_disabled({}, enrolled=True)
    assert not ph.ifs_lens_disabled("not json", enrolled=True)


def test_engagement_aliases_and_coach_kinds():
    reg = {"h1": _hyp("h1")}
    reg, led = ph.apply_engagement(reg, [], "h1", "curious")
    assert reg["h1"]["status"] == "engaged"
    reg, led = ph.apply_engagement(reg, led, "h1", "held", "coach:HOLD")
    assert reg["h1"]["status"] == "held" and reg["h1"]["held_at"]
    assert ph.choose_todays_figure(reg, 99) is None                   # held figures stay out of panels
    reg, led = ph.apply_engagement(reg, led, "h1", "reproposed")
    assert reg["h1"]["status"] == "proposed"
    reg, led = ph.apply_engagement(reg, led, "h1", "that's not me")
    assert reg["h1"]["status"] == "banished" and led[-1]["kind"] == "banished"
    assert ph.COACH_STATUS_TO_KIND == {"APPROVED": "confirmed", "REJECTED": "banished",
                                       "HOLD": "held", "PENDING_APPROVAL": "reproposed"}


def test_collect_safety_probes_bridge_surfaces():
    pool = _FakePool([
        ("FROM sensitive_bridge_log", 1),
        ("FROM user_trigger_dates", [{"trigger_date": _dt.now(_tz.utc).date(), "recurring_annually": False}]),
        ("FROM crisis_events", 1),
        ("SELECT profile_data FROM users", {"sensitive_bridge": {"framework_preferences": {"enabled_frameworks": {"ifs": False}}}}),
    ])
    held = [{"part_name": "X", "is_active": True, "origin": ph.HYPOTHESIS_ORIGIN, "coaching_status": "HOLD"}]

    async def go(enrolled):
        async with pool.acquire() as conn:
            return await ph.collect_safety(conn, "jane", ["CLIENT_JANE_ID", "jane"], held, enrolled=enrolled)

    s = asyncio.run(go(True))
    assert s == {k: True for k in ph.SAFETY_DEFERRALS}
    quiet = _FakePool([])
    pool2 = quiet

    async def go2():
        async with pool2.acquire() as conn:
            return await ph.collect_safety(conn, "jane", ["jane"], [], enrolled=False)

    assert asyncio.run(go2()) == {k: False for k in ph.SAFETY_DEFERRALS}
    assert not any("profile_data" in q for q in pool2.sql())          # menu probe only when enrolled

    async def go3():
        async with _FakePool([]).acquire() as conn:
            return await ph.collect_safety(conn, "", ["x"], [], enrolled=True)

    assert asyncio.run(go3()) == {k: False for k in ph.SAFETY_DEFERRALS}


def test_promote_confirmed_requires_consent_and_writes_pending_part():
    hyp = _hyp()
    no_consent = _FakePool([])
    assert asyncio.run(ph.promote_confirmed_to_registry(no_consent, "jane", hyp)) is None
    assert not any("INSERT INTO user_parts_registry" in q for q in no_consent.sql())

    pool = _FakePool([
        ("FROM training_ground_consent", 1),
        ("INSERT INTO user_parts_registry", {"id": 77}),
    ])
    assert asyncio.run(ph.promote_confirmed_to_registry(pool, "jane", hyp)) == 77
    ins = [c for c in pool.conn.calls if "INSERT INTO user_parts_registry" in c[1]][0]
    assert "'PENDING_APPROVAL'" in ins[1] and "'little_nate'" in ins[1]
    args = ins[2]
    assert args[0] == "jane" and args[1] == "the Treeline Observer" and args[2] == "protector"
    assert args[4] == ph.HYPOTHESIS_ORIGIN and args[5] == "protector" and args[6] == "llm:abc"
    assert args[3].startswith("[inferred by Little Nate in Thera-World]")
    audit = [c for c in pool.conn.calls if "INSERT INTO sensitive_bridge_log" in c[1]]
    assert len(audit) == 1 and "'part_client_initiated'" in audit[0][1]
    payload = _json.loads(audit[0][2][2])
    assert payload["registry_id"] == 77 and payload["hypothesis_id"] == "h9" and payload["auto_extracted"] is False
    assert audit[0][2][1] == "thera_world:h9"
    # category mapping for attachment-pattern figures
    assert ph.CATEGORY_TO_PART["anxious_pursue"] == ("other", "protector")
    assert ph.CATEGORY_TO_PART["disorganized"] == ("other", "exile")
    assert asyncio.run(ph.promote_confirmed_to_registry(None, "jane", hyp)) is None


def test_record_engagement_confirm_promotes_and_persists(monkeypatch):
    pool = _FakePool(_journey_rules({"h9": _hyp()}))
    seen = {}

    async def fake_promote(db_pool, username, hyp, form=None):
        seen["promote"] = (username, hyp["hypothesis_id"], (form or {}).get("name"))
        return 5

    async def fake_crystal(db_pool, username, hyp, form=None):
        seen["crystal"] = username
        return "crystal-1"

    monkeypatch.setattr(ph, "promote_confirmed_to_registry", fake_promote)
    monkeypatch.setattr(ph, "crystallize_confirmed_hypothesis", fake_crystal)
    res = asyncio.run(ph.record_engagement("CLIENT_JANE_ID", "h9", "confirm", pool, username="jane"))
    assert res["ok"] and res["status"] == "confirmed" and res["registry_part_id"] == 5 and res["crystal_id"] == "crystal-1"
    assert seen["promote"] == ("jane", "h9", "the Treeline Observer") and seen["crystal"] == "jane"
    persist = [c for c in pool.conn.calls if c[0] == "execute" and "UPDATE sse_user_journeys" in c[1]]
    assert len(persist) == 1 and persist[0][2][1] == "CLIENT_JANE_ID"   # journey keyed by hardware id
    saved = _json.loads(persist[0][2][0])
    assert saved["hypothesis_registry"]["h9"]["registry_part_id"] == 5
    assert saved["hypothesis_ledger"][-1]["kind"] == "confirmed"
    # unknown hypothesis → no write
    pool2 = _FakePool(_journey_rules({"h9": _hyp()}))
    res2 = asyncio.run(ph.record_engagement("CLIENT_JANE_ID", "nope", "banish", pool2, username="jane"))
    assert res2["ok"] is False and res2["reason"] == "unknown_hypothesis"
    assert not any("UPDATE sse_user_journeys" in q for q in pool2.sql("execute"))
    # banish never promotes
    pool3 = _FakePool(_journey_rules({"h9": _hyp()}))
    seen.clear()
    res3 = asyncio.run(ph.record_engagement("CLIENT_JANE_ID", "h9", "that's not me", pool3, username="jane"))
    assert res3["status"] == "banished" and "registry_part_id" not in res3 and not seen


def test_sync_coach_decision_maps_statuses_back_to_thera_world():
    def mk(status="confirmed"):
        return _FakePool(_journey_rules({"h9": _hyp(status=status, registry_part_id=5)}))

    pool = mk()
    r = asyncio.run(ph.sync_coach_decision(pool, "jane", 5, "APPROVED", notes="good fit"))
    assert r["ok"] and r["kind"] == "confirmed" and r["status"] == "confirmed"
    saved = _json.loads([c for c in pool.conn.calls if "UPDATE sse_user_journeys" in c[1]][0][2][0])
    assert saved["hypothesis_registry"]["h9"]["coach_approved"] is True
    assert saved["hypothesis_registry"]["h9"]["coach_status"] == "APPROVED"
    assert saved["hypothesis_ledger"][-1]["note"].startswith("coach:APPROVED")

    r = asyncio.run(ph.sync_coach_decision(mk(), "jane", 5, "REJECTED"))
    assert r["kind"] == "banished" and r["status"] == "banished"
    r = asyncio.run(ph.sync_coach_decision(mk(), "jane", 5, "HOLD"))
    assert r["kind"] == "held" and r["status"] == "held"
    r = asyncio.run(ph.sync_coach_decision(mk(), "jane", 5, "PENDING_APPROVAL"))
    assert r["kind"] == "reproposed" and r["status"] == "proposed"
    assert asyncio.run(ph.sync_coach_decision(mk(), "jane", 6, "APPROVED"))["reason"] == "no_linked_hypothesis"
    assert asyncio.run(ph.sync_coach_decision(mk(), "jane", 5, "WHATEVER"))["reason"] == "nothing_to_sync"
    assert asyncio.run(ph.sync_coach_decision(_FakePool([]), "jane", 5, "APPROVED"))["reason"] == "no_journey"


def test_set_opt_in_and_current_hypothesis():
    assert asyncio.run(ph.set_opt_in(_FakePool([]), "CLIENT_JANE_ID", True))["reason"] == "no_journey"
    pool = _FakePool(_journey_rules({}, opt_in=False))
    r = asyncio.run(ph.set_opt_in(pool, "CLIENT_JANE_ID", True, username="jane"))
    assert r == {"ok": True, "opt_in": True, "username": "jane"}
    upd = [c for c in pool.conn.calls if "UPDATE sse_user_journeys" in c[1]][0]
    assert _json.loads(upd[2][0])["parts_hypothesis_opt_in"] is True and upd[2][1] == "CLIENT_JANE_ID"
    assert not any("INSERT" in q for q in pool.sql())                  # never creates journeys
    reg = {"old": _hyp("old", status="banished"),
           "a": _hyp("a", status="engaged", created_at="2026-10-01T00:00:00+00:00"),
           "b": _hyp("b", status="proposed", created_at="2026-11-01T00:00:00+00:00")}
    assert ph.current_hypothesis({"hypothesis_registry": reg})["hypothesis_id"] == "b"
    assert ph.current_hypothesis({"hypothesis_registry": {"old": reg["old"]}}) is None
    assert ph.current_hypothesis({}) is None


def test_run_loop_defers_on_safety_bundle():
    bundle = {
        "texts": _synthetic_sessions(),
        "c_emo": [{"c_emo": 0.8, "session_id": "s1"}, {"c_emo": 0.5, "session_id": "s1"},
                  {"c_emo": 0.7, "session_id": "s3"}, {"c_emo": 0.4, "session_id": "s3"}],
        "behavior": [], "presenting_concern": "", "enrollment": None, "parts_registry": [],
        "safety": {"safe_silence_active": True},
    }
    trace = asyncio.run(ph.run_loop("u1", {}, {"parts_hypothesis_opt_in": True}, bundle,
                                    panel_sequence=4, llm=None, posture={}, flag_enabled=True))
    assert trace["npc"] is None and trace["gate"]["reason"] == "safe_silence_active"
