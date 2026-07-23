"""Offline tests: CLI truth-grounding (capability manifest + claim validator)."""

import os

os.environ["REDIS_URL"] = ""
os.environ["ENABLE_ASK_NATE_SYMBOLIC"] = "false"
os.environ["ENABLE_FORWARD_REASONING"] = "false"


def test_self_capabilities_in_all_modes():
    from app.websocket.cli_tools import get_tool_definitions

    for mode in ("ask", "plan", "debug", "ln_fab"):
        for cli in ("mac", "cloud"):
            names = {
                t["function"]["name"]
                for t in get_tool_definitions(mode, cli)
                if "function" in t
            }
            assert "self_capabilities" in names, f"missing in {cli}/{mode}"


def test_manifest_flags_clinical_ns_not_wired():
    from app.websocket.cli_grounding import build_capabilities_manifest

    m = build_capabilities_manifest("ask", "cloud")
    assert m["object"] == "cli.self_capabilities"
    assert m["clinical_neuro_symbolic"]["wired_into_cli_loop"] is False
    assert m["clinical_neuro_symbolic"]["ENABLE_ASK_NATE_SYMBOLIC"] is False
    assert m["providers"]["workers_ai_in_cli_loop"] is False
    assert m["mac_vs_cloud"]["mac_cloud_ln_fab_partnership"] is False
    assert "CLI neuro-symbolic formal logic / knowledge graph" in m["not_implemented"]
    assert "self_capabilities" in (m.get("tools") or [])
    assert m["label_rules"]["design"] == "[DESIGN PROPOSAL]"
    assert m["agentic_api_capabilities"].get("cli_truth_grounding") is True


def test_self_capabilities_sync_ok():
    from app.websocket.cli_tools import _self_capabilities_sync

    r = _self_capabilities_sync("ln_fab", "mac")
    assert r["status"] == "ok"
    assert "workers_ai_in_cli_loop" in r["content"]
    assert r["manifest"]["cli"] == "mac"
    assert r["manifest"]["mode"] == "ln_fab"


def test_capability_question_detection():
    from app.websocket.cli_grounding import is_capability_question, is_speculative_question

    assert is_capability_question("What is your neuro-symbolic state?")
    assert is_capability_question("review what your current state of neuro-symbolic")
    assert is_capability_question("Can CLI-Mac partner with CLI-Cloud?")
    assert is_speculative_question("What would make this better?")
    assert not is_capability_question("Read cli_tools.py and fix the timeout")


def test_roadmap_question_detection():
    from app.websocket.cli_grounding import is_roadmap_question, is_speculative_question

    assert is_roadmap_question(
        "What are the next steps to becoming a Narrow AGI in our Tier 2 development"
    )
    assert is_roadmap_question("Show me the Sovereign IDE roadmap")
    assert is_roadmap_question("what has been developed for agentic phase?")
    assert is_roadmap_question("What are the next steps for Narrow AGI?")
    assert is_speculative_question("Show me the Sovereign IDE roadmap")  # contains "roadmap"
    assert not is_roadmap_question("Read cli_tools.py line 100")


def test_roadmap_validator_requires_plan_evidence():
    from app.websocket.cli_grounding import validate_cli_response

    bad = validate_cli_response(
        "There is no Narrow AGI plan in the codebase.",
        tool_call_log=[{"name": "grep", "status": "ok", "args": {"pattern": "AGI"}}],
        user_message="What are the next steps for Narrow AGI Tier 2?",
    )
    assert bad["ok"] is False
    assert any(v["type"] == "roadmap_without_plan_evidence" for v in bad["violations"])

    good = validate_cli_response(
        "[DESIGN PROPOSAL] Next: finish Part C. "
        "[VERIFIED] See .cursor/plans/sovereign_ide_cursor_clone_3762c3a8.plan.md",
        tool_call_log=[{
            "name": "plan_index",
            "status": "ok",
            "injected": True,
            "evidence_excerpt": "IMPLEMENTATION PLANS: sovereign_ide_cursor_clone",
        }],
        user_message="What are the next steps for Narrow AGI Tier 2?",
    )
    assert good["ok"] is True


def test_plan_index_lists_priority_plans():
    from app.websocket.cli_manifest import generate_plan_index

    idx = generate_plan_index(query="Narrow AGI Tier 2", max_chars=8000)
    assert "IMPLEMENTATION PLANS" in idx
    assert ".cursor/plans/" in idx
    # Prefer sovereign / agentic docs when present on disk
    assert "PRIORITY" in idx or "AGI" in idx.upper() or "docs/" in idx


def test_git_tools_in_ask_cloud():
    from app.websocket.cli_tools import get_tool_definitions

    names = {
        t["function"]["name"]
        for t in get_tool_definitions("ask", "cloud")
        if "function" in t
    }
    assert "read_git_status" in names
    assert "git_log" in names
    assert "shell" not in names


def test_read_git_status_and_log_sync():
    from app.websocket.cli_tools import _git_log_sync, _read_git_status_sync

    st = _read_git_status_sync()
    assert st["status"] in ("ok", "error")
    if st["status"] == "ok":
        assert "READ-ONLY GIT STATUS" in (st.get("content") or "")
    lg = _git_log_sync(max_count=5)
    assert lg["status"] in ("ok", "error")
    if lg["status"] == "ok":
        assert "READ-ONLY GIT LOG" in (lg.get("content") or "")


def test_accuracy_contract_mentions_category_separation():
    from app.websocket.cli_chat_handler import _build_system_prompt

    p = _build_system_prompt("ask", "cloud")
    assert "CATEGORY SEPARATION" in p or "Clinical ENABLE_" in p
    assert "read_git_status" in p or "git_log" in p
    assert "IMPLEMENTATION PLANS" in p or ".cursor/plans" in p


def test_validator_flags_ungrounded_claims():
    from app.websocket.cli_grounding import validate_cli_response

    bad = validate_cli_response(
        "I can continuously enhance code via dual-agent partnership. Phase 5b is fully implemented.",
        tool_call_log=[],
        user_message="What is your neuro-symbolic state?",
    )
    assert bad["ok"] is False
    assert bad["self_capabilities_called"] is False
    assert any(v["type"] == "capability_question_without_manifest" for v in bad["violations"])
    assert bad["rewritten_text"].startswith("[UNVERIFIED]")


def test_validator_passes_with_manifest_and_tags():
    from app.websocket.cli_grounding import validate_cli_response

    good = validate_cli_response(
        "[NOT IMPLEMENTED] Mac↔Cloud dual LN-FAB partnership. "
        "[FLAG-OFF] ENABLE_ASK_NATE_SYMBOLIC. "
        "[VERIFIED tool=self_capabilities] CLI uses Grok/Azure only.",
        tool_call_log=[{"name": "self_capabilities", "status": "ok"}],
        user_message="What can you do?",
    )
    assert good["ok"] is True
    assert good["self_capabilities_called"] is True


def test_speculation_requires_design_tag():
    from app.websocket.cli_grounding import validate_cli_response

    r = validate_cli_response(
        "I can provide a dual CLI partnership that continuously enhances code.",
        tool_call_log=[{"name": "self_capabilities", "status": "ok"}],
        user_message="What would a CLI-Mac and CLI-Cloud partnership look like?",
    )
    assert r["ok"] is False
    assert any(v["type"] == "speculation_unlabeled" for v in r["violations"])


def test_completion_claim_needs_hash_or_pending():
    from app.websocket.cli_grounding import validate_cli_response

    r = validate_cli_response(
        "The feature is deployed and fixed.",
        tool_call_log=[{"name": "self_capabilities", "status": "ok"}],
        user_message="status?",
    )
    assert r["ok"] is False
    assert any(v["type"] == "completion_claim_no_hash" for v in r["violations"])

    ok = validate_cli_response(
        "Change pending commit (uncommitted).",
        tool_call_log=[{"name": "grep", "status": "ok"}],
        user_message="did you finish?",
    )
    assert ok["ok"] is True


def test_system_prompt_contains_accuracy_contract():
    from app.websocket.cli_chat_handler import _build_system_prompt

    p = _build_system_prompt("ask", "cloud")
    assert "YOUR ACCURACY RULES" in p
    assert "self_capabilities" in p
    assert "DESIGN PROPOSAL" in p
    assert "VERIFICATION-BEFORE-CLAIM" in p


def test_apply_grounding_to_done():
    from app.websocket.cli_grounding import apply_grounding_to_done

    text, meta = apply_grounding_to_done(
        "I support neuro-symbolic Phase 5b fully.",
        [],
        "What is your neuro-symbolic level?",
    )
    assert meta["ok"] is False
    assert meta["violation_count"] >= 1
    assert text.startswith("[UNVERIFIED]")
    assert meta.get("citation_audit") is True


def test_citation_tool_missing():
    from app.websocket.cli_grounding import audit_verified_citations

    r = audit_verified_citations(
        "[VERIFIED tool=self_capabilities] CLI uses Grok only.",
        tool_call_log=[],
    )
    assert r["ok"] is False
    assert any(v["type"] == "citation_tool_missing" for v in r["violations"])


def test_citation_path_missing():
    from app.websocket.cli_grounding import audit_verified_citations

    r = audit_verified_citations(
        "[VERIFIED backend/app/websocket/cli_tools.py:12] writes are always live.",
        tool_call_log=[{"name": "grep", "status": "ok", "args": {"pattern": "foo"}, "evidence_excerpt": "no match"}],
    )
    assert r["ok"] is False
    assert any(v["type"] == "citation_path_missing" for v in r["violations"])


def test_citation_path_ok_when_in_evidence():
    from app.websocket.cli_grounding import audit_verified_citations

    r = audit_verified_citations(
        "[VERIFIED backend/app/websocket/cli_tools.py:100] sandbox writes gated.",
        tool_call_log=[{
            "name": "read_file",
            "status": "ok",
            "args": {"path": "backend/app/websocket/cli_tools.py"},
            "evidence_excerpt": "def _cloud_sandbox_active: sandbox writes gated at line 100",
        }],
    )
    assert r["ok"] is True
    assert r["checked"] == 1


def test_manifest_contradiction_caught():
    from app.websocket.cli_grounding import audit_verified_citations, apply_grounding_to_done

    evidence = (
        '{"workers_ai_in_cli_loop": false, '
        '"mac_cloud_ln_fab_partnership": false, '
        '"wired_into_cli_loop": false, '
        '"ENABLE_ASK_NATE_SYMBOLIC": false}'
    )
    log = [{"name": "self_capabilities", "status": "ok", "evidence_excerpt": evidence}]
    r = audit_verified_citations(
        "[VERIFIED tool=self_capabilities] CLI-Cloud partners with CLI-Mac in LN-FAB "
        "to continuously enhance each others code via dual-agent collaboration.",
        tool_call_log=log,
    )
    assert r["ok"] is False
    assert any(v["type"] == "manifest_contradiction" for v in r["violations"])

    text, meta = apply_grounding_to_done(
        "[VERIFIED tool=self_capabilities] Workers AI powers the CLI coding loop.",
        log,
        "What providers do you use?",
    )
    assert meta["ok"] is False
    assert text.startswith("[UNVERIFIED]")
    assert meta["citations_checked"] >= 1
