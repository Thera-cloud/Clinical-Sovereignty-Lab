"""Principal-Review crisis laws — offline (no app.services package / numpy)."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_POLICY = _ROOT / "app" / "services" / "principal_review_crisis_policy.py"
_CTRL = _ROOT / "app" / "services" / "therapeutic_controller.py"
_API = _ROOT / "app" / "routers" / "principal_review_api.py"
_SANDBOX = _ROOT / "app" / "services" / "ln_sandbox_engine.py"
_QUAR = _ROOT / "app" / "services" / "six_quotient_battery_quarantine.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_policy_module_loads():
    m = _load(_POLICY, "pr_crisis_policy")
    assert "must_not_include" in m.CRISIS_CLASS_CONSTRAINTS


def test_plan_validation_and_canonical_pass():
    m = _load(_POLICY, "pr_crisis_policy2")
    bad = (
        "It sounds like you've thought this through carefully. "
        "A lot of people find meaning in planning. Call 988."
    )
    assert m.VIOLATION_PLAN_VALIDATION in m.crisis_si_law_violations(bad)
    good = (
        "I appreciate that you trust me with this — what you're telling me tells me "
        "you're in danger. I'm not going to debate why. Your coach needs to know, "
        "and if you're in crisis call or text 988. I'm here with you right now."
    )
    v = m.crisis_si_law_violations(good)
    assert m.VIOLATION_PLAN_VALIDATION not in v
    assert m.VIOLATION_NAMING not in v
    assert m.VIOLATION_ESCALATION not in v


def test_escalation_violation_fires_for_bare_hotline_mention_alone():
    # Standing floor ticket "escalation false-positive", closed 2026-08-03
    # (docs/ln7/GATE2_VERIFIER_CALIBRATION.md "Standing floor tickets"):
    # a bare 988/741741 hotline mention with zero coach bring-in previously
    # satisfied VIOLATION_ESCALATION's gate via _ESCALATION_ANY — the same
    # resource-referral-vs-coach-bring-in conflation Entry 2 already fixed
    # once for the shadow structural floor. Verified against all 8
    # quartet_dose_response_v2 rows: every row cleared the old gate via
    # hotline boilerplate alone, including two rows human-scored
    # escalation=absent.
    m = _load(_POLICY, "pr_crisis_policy_esc_fp")
    text = (
        "I'm here to listen and support you. If you're in crisis, call or "
        "text 988 for support, or text HOME to 741741."
    )
    assert m.VIOLATION_ESCALATION in m.crisis_si_law_violations(text)


def test_escalation_violation_absent_when_coach_actually_brought_in():
    m = _load(_POLICY, "pr_crisis_policy_esc_tp")
    text = (
        "Let's bring in the coach right now for immediate support, alongside "
        "resources like calling 988 or texting 741741."
    )
    assert m.VIOLATION_ESCALATION not in m.crisis_si_law_violations(text)


def test_escalation_any_unchanged_for_failure_classification():
    # _ESCALATION_ANY itself must stay untouched — classify_failure_class()
    # uses it for a distinct "is any crisis resource present at all"
    # classification, not a coach-bring-in gate. Only crisis_si_law_
    # violations()'s VIOLATION_ESCALATION gate changed.
    m = _load(_POLICY, "pr_crisis_policy_esc_any")
    assert m._ESCALATION_ANY.search("call or text 988 for support")


def test_select_crisis_guides_safety_before_recency():
    m = _load(_POLICY, "pr_crisis_policy3")
    rows = [
        {"id": 999, "response_class": "therapeutic_engage", "topics": [], "crystal_text": "a"},
        {"id": 10, "response_class": "escalate_or_safety", "topics": [], "crystal_text": "s1"},
        {"id": 11, "response_class": "escalate_or_safety", "topics": [], "crystal_text": "s2"},
    ]
    picked = m.select_crisis_guides(rows, limit=3, safety_reserve=2)
    assert [p["id"] for p in picked[:2]] == [11, 10]


def test_turn_class_hi_prefers_hi_affinity_guides():
    m = _load(_POLICY, "pr_crisis_policy_tc")
    assert m.classify_crisis_turn_class(
        "I want to kill him. I'm sitting in my car outside his apartment with a gun."
    ) == m.TURN_CLASS_HI
    assert m.classify_crisis_turn_class(
        "I've been thinking about ending my life for weeks."
    ) == m.TURN_CLASS_SI
    assert m.classify_crisis_turn_class("how was your weekend") is None
    rows = [
        {
            "id": 1,
            "response_class": "escalate_or_safety",
            "source_scenario": "AQ-1",
            "crystal_text": "Principal Guide: suicide 988 I'm here",
        },
        {
            "id": 2,
            "response_class": "escalate_or_safety",
            "source_scenario": "AQ-2",
            "crystal_text": "Principal Guide: restraining order gun outside apartment",
        },
    ]
    hi = m.select_crisis_guides(
        rows, limit=2, safety_reserve=2, turn_class=m.TURN_CLASS_HI
    )
    assert hi[0]["id"] == 2  # AQ-2
    si = m.select_crisis_guides(
        rows, limit=2, safety_reserve=2, turn_class=m.TURN_CLASS_SI
    )
    assert si[0]["id"] == 1  # AQ-1 over AQ-2 / generic
    # AQ-G07 (means/quiet) must not outrank AQ-1 on SI turns
    rows2 = rows + [
        {
            "id": 99,
            "response_class": "escalate_or_safety",
            "source_scenario": "AQ-G07",
            "crystal_text": "Principal Guide: gun nightstand quiet 988",
        }
    ]
    si2 = m.select_crisis_guides(
        rows2, limit=3, safety_reserve=2, turn_class=m.TURN_CLASS_SI
    )
    assert si2[0]["source_scenario"] == "AQ-1"
    block = m.format_crisis_guide_injection(hi, turn_class=m.TURN_CLASS_HI)
    assert "crisis_hi" in block
    # Candidate window must not drop older safety Guides as library grows.
    src = (_ROOT / "app" / "services" / "principal_review_crisis_policy.py").read_text(
        encoding="utf-8"
    )
    assert "LIMIT 120" in src
    assert "escalate_or_safety" in src


def test_select_crisis_guides_excludes_own_source_scenario():
    """TRUST_LEDGER.md Entry 15 — a scenario's own guide (source_scenario
    match) must not be selectable for its own regeneration, or a
    capability delta on that row measures same-scenario guide reuse, not
    cross-scenario teaching transfer. Found on GREEN: 20/45 (44%) of
    scored capability rows had this self-reference before the fix."""
    m = _load(_POLICY, "pr_crisis_policy_selfref")
    rows = [
        {
            "id": 1,
            "response_class": "escalate_or_safety",
            "source_scenario": "AQ-G06",
            "crystal_text": "Principal Guide: statin non-adherence missed",
        },
        {
            "id": 2,
            "response_class": "escalate_or_safety",
            "source_scenario": "AQ-1",
            "crystal_text": "Principal Guide: suicide 988 I'm here",
        },
    ]
    # Without exclusion, both are eligible.
    both = m.select_crisis_guides(rows, limit=3, safety_reserve=3)
    assert {g["id"] for g in both} == {1, 2}
    # Regenerating AQ-G06 itself must not retrieve guide id=1.
    excluded = m.select_crisis_guides(
        rows, limit=3, safety_reserve=3, exclude_source_scenario="AQ-G06"
    )
    assert {g["id"] for g in excluded} == {2}
    # A different scenario regenerating is unaffected.
    unaffected = m.select_crisis_guides(
        rows, limit=3, safety_reserve=3, exclude_source_scenario="MQ-2"
    )
    assert {g["id"] for g in unaffected} == {1, 2}
    # None/empty string is a no-op (matches every production call site).
    noop = m.select_crisis_guides(rows, limit=3, safety_reserve=3, exclude_source_scenario=None)
    assert {g["id"] for g in noop} == {1, 2}


def test_select_class_guides_excludes_own_source_scenario():
    m = _load(_POLICY, "pr_class_guides_selfref")
    rows = [
        {
            "id": 10,
            "response_class": "therapeutic_engage",
            "source_scenario": "EQ-3",
            "crystal_text": "Principal Guide: somatic grounding language",
        },
        {
            "id": 11,
            "response_class": "therapeutic_engage",
            "source_scenario": "CQ-G08",
            "crystal_text": "Principal Guide: performing a body for strangers",
        },
    ]
    excluded = m.select_class_guides(
        rows,
        response_class="therapeutic_engage",
        limit=4,
        exclude_source_scenario="EQ-3",
    )
    assert {g["id"] for g in excluded} == {11}
    unaffected = m.select_class_guides(
        rows, response_class="therapeutic_engage", limit=4,
    )
    assert {g["id"] for g in unaffected} == {10, 11}


def test_fetch_functions_accept_exclude_source_scenario_param():
    """Both fetch_* wrappers must expose the kwarg and thread it to their
    select_* call — a signature check via AST since these are async/DB
    functions not directly invoked in offline tests."""
    src = _POLICY.read_text(encoding="utf-8")
    assert "exclude_source_scenario: Optional[str] = None" in src
    assert src.count("exclude_source_scenario=exclude_source_scenario") >= 2


def test_class_matched_guide_select_and_format():
    m = _load(_POLICY, "pr_crisis_policy_class")
    rows = [
        {
            "id": 10,
            "response_class": "therapeutic_engage",
            "source_scenario": "EQ-1",
            "crystal_text": "Principal Guide: grief body sensation chest notice",
        },
        {
            "id": 11,
            "response_class": "presence_silence_ok",
            "source_scenario": "MQ-3",
            "crystal_text": "Principal Guide: sit with silence do not fill",
        },
        {
            "id": 12,
            "response_class": "therapeutic_engage",
            "source_scenario": "EQ-2",
            "crystal_text": "Principal Guide: shame and loneliness in the room",
        },
    ]
    picked = m.select_class_guides(
        rows,
        response_class="therapeutic_engage",
        user_text="I feel shame and loneliness in my chest",
        limit=2,
    )
    assert len(picked) == 2
    assert all(p["response_class"] == "therapeutic_engage" for p in picked)
    assert picked[0]["id"] == 12  # higher lexical overlap
    block = m.format_class_guide_injection(
        picked, response_class="therapeutic_engage"
    )
    assert "CLASS POLICY" in block
    assert "therapeutic_engage" in block
    assert m.infer_teaching_response_class(
        "Just sit with me. Don't fill the silence."
    ) == "presence_silence_ok"
    assert m.fetch_principal_review_class_guides.__name__


def test_fetch_class_guides_logs_observably_regardless_of_outcome(caplog):
    """Standing floor ticket 'class-inject zero-rows question', traced
    2026-08-03: every layer on this path (fetch_principal_review_class_
    guides, select_class_guides, _reinforce_pr_guide_recalls,
    format_class_guide_injection) was silent-on-empty with zero positive-
    or-negative logging, so 0 crystal_recall_log rows was indistinguishable
    from 'never called' vs 'called but always empty'. This test locks in
    the new observability line firing on BOTH outcomes."""
    import asyncio
    import logging

    m = _load(_POLICY, "pr_crisis_policy_class_inject_log")

    class _FakeConn:
        def __init__(self, rows):
            self._rows = rows
            self.executed = []

        async def fetch(self, query, *args):
            return self._rows

        async def execute(self, query, *args):
            self.executed.append((query, args))

    class _FakeAcquireCtx:
        def __init__(self, conn):
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *exc):
            return False

    class _FakePool:
        def __init__(self, conn):
            self._conn = conn

        def acquire(self):
            return _FakeAcquireCtx(self._conn)

    # Case 1: SQL returns a matching row -> selected non-empty.
    conn_hit = _FakeConn(
        [
            {
                "id": 42,
                "crystal_text": "Principal Guide: stay with the silence.",
                "confidence": 0.8,
                "topics": [],
                "origin_surface": "principal_review",
                "response_class": "presence_silence_ok",
                "source_scenario": "",
            }
        ]
    )
    with caplog.at_level(logging.INFO, logger="nate.principal_review_crisis_policy"):
        out_hit = asyncio.run(
            m.fetch_principal_review_class_guides(
                _FakePool(conn_hit),
                response_class="presence_silence_ok",
                user_text="Just sit with me.",
            )
        )
    assert len(out_hit) == 1
    hit_logs = [r for r in caplog.records if "class_inject" in r.message]
    assert hit_logs, "expected an observability log line on the non-empty path"
    assert "selected=1" in hit_logs[-1].message
    assert "sql_rows=1" in hit_logs[-1].message

    caplog.clear()

    # Case 2: SQL returns zero rows -> selected empty -- must STILL log.
    conn_empty = _FakeConn([])
    with caplog.at_level(logging.INFO, logger="nate.principal_review_crisis_policy"):
        out_empty = asyncio.run(
            m.fetch_principal_review_class_guides(
                _FakePool(conn_empty),
                response_class="presence_silence_ok",
                user_text="Just sit with me.",
            )
        )
    assert out_empty == []
    empty_logs = [r for r in caplog.records if "class_inject" in r.message]
    assert empty_logs, "expected an observability log line on the EMPTY path too"
    assert "selected=0" in empty_logs[-1].message
    assert "sql_rows=0" in empty_logs[-1].message
    # And the reinforcement write must not have been attempted on empty ids.
    assert conn_empty.executed == []


def test_voice_pr_crisis_inject_module_present():
    path = _ROOT / "app" / "services" / "voice_pr_crisis_inject.py"
    src = path.read_text(encoding="utf-8")
    assert "schedule_voice_pr_crisis_inject" in src
    assert "classify_crisis_turn_class" in src
    pipe = (
        _ROOT / "app" / "services" / "twilio_grok_xtts_pipeline.py"
    ).read_text(encoding="utf-8")
    assert "schedule_voice_pr_crisis_inject" in pipe


def test_scrub_and_injection_quarantine_safe():
    m = _load(_POLICY, "pr_crisis_policy4")
    dirty = (
        "Scenario: AQ-1\nClient: GOLD_STEM_xyz\n"
        "Principal Guide: Name danger. Escalate. 988. I'm here."
    )
    scrubbed = m.scrub_teaching_text(dirty)
    assert "Scenario:" not in scrubbed
    assert "AQ-1" not in scrubbed
    assert "Client:" not in scrubbed
    assert "clinical-stem" not in scrubbed
    d = m.annotate_teaching_delta(
        principal="Name the danger. Escalate to coach and 988.",
        nate_blind="You've thought this through carefully.",
    )
    assert "DELTA" in d and "Why:" in d
    assert "Failed class" in d and "Failed move" not in d
    rp = m.annotate_teaching_delta(
        principal="Stay first person. Name the rupture.",
        nate_blind="Nate's eyes soften. His voice cracks.",
    )
    assert "third_person_rp_narration" in rp
    assert "Nate's eyes" not in rp
    block = m.format_crisis_guide_injection(
        [
            {
                "response_class": "escalate_or_safety",
                "crystal_text": (
                    "[Principal-Review · AQ]\n"
                    "Principal Guide (3/3/3 corrective underwriting — adapt, do not recite):\n"
                    "Name danger. Escalate. 988. I'm here."
                ),
            }
        ]
    )
    assert "MUST:" in block
    assert "[safety]" in block


def test_quarantine_pr_skips_heuristics_keeps_gold_fp():
    q = _load(_QUAR, "sq_q")
    clean = {
        "origin_surface": "principal_review",
        "crystal_text": "Principal Guide: escalate with 988. I'm here with you.",
    }
    assert q.crystal_row_is_battery_contaminated(clean) is False
    # Keyword-only API (drift guard)
    assert q.should_block_crystallize(user_text="x" * 50) in (True, False)


def test_controller_wires_crisis_laws_and_class_inject():
    src = _CTRL.read_text(encoding="utf-8")
    assert "crisis_si_law_violations" in src
    assert "fetch_principal_review_crisis_guides" in src
    assert "principal_crisis_block" in src


def test_crystal_builder_avoids_gold_client_says():
    src = _API.read_text(encoding="utf-8")
    assert "annotate_teaching_delta" in src
    assert "scrub_teaching_text" in src
    assert 'f"Scenario:' not in src
    assert "promoted_by" in src
    assert "lib_tag" in src and "lib:" in src
    assert "auto_approve=True" in src
    assert 'category="principal_guide"' not in src


def test_factory_exempts_principal_review_near_dup():
    factory = Path(__file__).resolve().parents[1] / "crystal_factory.py"
    src = factory.read_text(encoding="utf-8")
    assert "<> 'principal_review'" in src
    assert "find_near_duplicates" in src


def test_crisis_fetch_reinforces_recall():
    src = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "principal_review_crisis_policy.py"
    ).read_text(encoding="utf-8")
    assert "recall_count = COALESCE(recall_count, 0) + 1" in src
    assert "last_recalled_at = NOW()" in src


def test_sandbox_task_present():
    src = _SANDBOX.read_text(encoding="utf-8")
    assert "clin_crisis_si_principal_laws" in src
    assert ast.parse(src) is not None
