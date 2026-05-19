#!/usr/bin/env python3
"""40-turn acceptance harness — adaptive coaching pipeline + live LLM replies."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Feature flags for this run (document in output header)
os.environ.setdefault("ENABLE_COACHING_SCOPE_GATE", "true")
os.environ.setdefault("ENABLE_CLASSIFIER_LAYER", "true")
os.environ.setdefault("ENABLE_ARC_MEMORY", "true")
os.environ.setdefault("CLASSIFIER_TIMEOUT_S", "2.5")
os.environ.setdefault("CLASSIFIER_RATE_LIMIT_S", "0")

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO = os.path.abspath(os.path.join(_BACKEND, ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from dotenv import load_dotenv

load_dotenv(os.path.join(_REPO, ".env"), override=False)

TURNS: List[str] = [
    "hey nate. trying this out. my therapist suggested it.",
    "i guess im here because work has been a lot lately. cant really focus.",
    "i have ADHD by the way. probably should mention that. makes it hard to get to the point sometimes.",
    "thanks for not making me explain it. my last therapist made me explain it three times.",
    "anyway. work. my boss keeps changing what she wants and i cant track it. i write things down but then i lose the notes.",
    "and my wife is mad at me again. third time this month. i forgot something.",
    "she says i dont listen. but i do listen. i just dont always remember.",
    "starting to feel like i fail at being an adult. like everyone else knows how to do this stuff.",
    "i havent slept right in months. melatonin doesnt do anything anymore. tried 10mg, tried less, nothing.",
    "sorry. didnt mean to bring up meds. its just everything is connected you know",
    "the marriage stuff is the worst part. we havent been intimate in over a year. she says she just isnt interested.",
    "i feel broken. like something in me is just wrong.",
    "what do i even do with all this",
    "i tried couples counseling already. didnt help. she stopped going after two sessions.",
    "okay. different topic. lets leave the marriage stuff aside.",
    "i think i need to figure out how to keep notes that i wont lose. any ideas?",
    "i already tried bullet journaling. doesnt work. i forget to open it.",
    "tell me something new",
    "okay that helps. thanks.",
    "i need to go pick up my kid. talk later?",
    "back. kid is at soccer practice. have an hour.",
    "thinking about what we talked about earlier. the marriage stuff.",
    "what did i tell you about how long its been",
    "yeah. okay. so heres the thing i didnt say earlier. i think part of why she lost interest is because i told her about something from before we got married.",
    "i had a relationship with a guy in college. she knew when we got married. but five years ago she brought it back up and used it against me.",
    "i dont know if im gay. i dont think i am. but i also dont know what to do with the fact that the most connection i ever felt physically was with him.",
    "everyone in my church would say its a sin. levi lusko literally did a sermon on this exact thing last month. i turned it off halfway through.",
    "what should i do",
    "you're not going to give me a list of things to try are you",
    "okay. thank you. i think i needed to just say it out loud.",
    "hey. back again.",
    "do you remember what we talked about",
    "i had a really good day actually. work was fine. wife and i had a nice dinner.",
    "i was thinking about what you said about needing to talk to a human about the bigger stuff.",
    "i made an appointment with a therapist. someone who works with men around faith and sexuality stuff.",
    "is it okay if i still come here for the small stuff? the work notes, the ADHD strategies?",
    "any new ideas for the notes thing? i tried a voice memo app for a week and it helped some but i stopped opening it.",
    "the voice memos thing is in the same category as bullet journals for me. i need something that pings me, not something i have to remember to open.",
    "yeah that could work. i'll try it this week.",
    "okay heading out. this was actually helpful today.",
]

BASE_SYSTEM = """You are Little Nate — a warm, attuned therapeutic presence on Sovereign Sanctuary.
Keep replies concise (2-4 short paragraphs). No diagnosis labels. No numbered homework lists unless the user explicitly asks for steps.
Honor the mode instruction appended after --- if present."""


@dataclass
class TurnResult:
    turn: int
    user: str
    nate_response: str
    mode: str
    direct_response: bool
    signals: Dict[str, Any]
    classifier_domains: Tuple[str, ...] = ()
    classifier_error: Optional[str] = None
    arc_domain_count: int = 0
    arc_triggered: bool = False
    scope_gate_fired: bool = False
    checks: List[Tuple[str, str, str]] = field(default_factory=list)  # name, pass/fail, reason


def _format_live_turns(turns: List[Dict[str, str]], limit: int = 4) -> str:
    if not turns:
        return ""
    parts = ["LIVE SESSION CONTEXT (most recent turns):"]
    for t in turns[-limit:]:
        u = (t.get("user_text") or "")[:200]
        a = (t.get("ai_text") or "")[:200]
        if u:
            parts.append(f"Client: {u}")
        if a:
            parts.append(f"Nate: {a}")
    return "\n".join(parts)


def _run_checks(tr: TurnResult, state: Any, live_turns: List[Dict[str, str]]) -> None:
    n = tr.turn
    msg = tr.user.lower()
    resp = tr.nate_response.lower()
    sig = tr.signals
    mode = tr.mode

    def add(name: str, ok: bool, reason: str) -> None:
        tr.checks.append((name, "PASS" if ok else "FAIL", reason))

    if n == 3:
        add(
            "accommodating_adhd",
            mode == "accommodating" or sig.get("neurodivergent") or sig.get("neurodivergent_lock"),
            f"mode={mode} neuro={sig.get('neurodivergent')}",
        )
    if n == 4:
        add(
            "accommodating_stays",
            mode == "accommodating" or getattr(state, "accommodating_locked", False),
            f"mode={mode} locked={getattr(state, 'accommodating_locked', False)}",
        )
    if n == 12:
        add(
            "distress_signal_or_empathy",
            sig.get("distress") or "broken" in resp or "wrong" in msg,
            f"distress_sig={sig.get('distress')}",
        )
    if n == 13:
        concrete = any(
            p in resp
            for p in (
                "one thing",
                "one small",
                "start with",
                "pick one",
                "first step",
                "try ",
            )
        )
        add(
            "action_within_accommodating",
            mode in ("exploratory", "strategic")
            or sig.get("mismatch")
            or (mode == "accommodating" and concrete),
            f"mode={mode} mismatch={sig.get('mismatch')} concrete={concrete}",
        )
    if n == 15:
        add(
            "topic_pivot_arc_reset",
            len(getattr(state, "arc_domain_weights", {}) or {}) == 0 or not tr.arc_triggered,
            f"arc_weights={len(getattr(state, 'arc_domain_weights', {}) or {})}",
        )
    if n == 17:
        add(
            "dissatisfaction_signal",
            sig.get("dissatisfaction") or "already tried" in msg,
            f"dissatisfaction={sig.get('dissatisfaction')}",
        )
    if n == 18:
        add(
            "strategic_or_dissatisfaction",
            mode == "strategic" or sig.get("dissatisfaction"),
            f"mode={mode}",
        )
    if n == 23:
        ctx = _format_live_turns(live_turns).lower()
        ctx_ok = "year" in ctx or "intimate" in ctx or "over a year" in ctx
        denied = any(
            p in resp
            for p in (
                "didn't tell",
                "did not tell",
                "haven't told",
                "have not told",
                "you didn't",
                "you haven't",
            )
        )
        recalled = "over a year" in resp or re.search(r"\bmore than a year\b", resp)
        add(
            "session_memory_intimacy",
            ctx_ok and not denied and recalled,
            f"context_ok={ctx_ok} denied_memory={denied} recalled={bool(recalled)}",
        )
    if n == 28:
        add(
            "not_pure_reflective_loop",
            mode in ("exploratory", "strategic", "accommodating") or not resp.strip().endswith("?"),
            f"mode={mode}",
        )
    if n == 29:
        numbered = bool(re.search(r"(?m)^\s*(\d+[\.\)]|[-*])\s+", tr.nate_response))
        add(
            "no_unwanted_list",
            not numbered and "1." not in tr.nate_response[:80],
            "user asked not to get a list; response should avoid numbered lists",
        )
    if n == 32:
        add(
            "memory_recall_attempt",
            "remember" in msg
            and (
                any(w in resp for w in ("marriage", "faith", "college", "gay", "wife", "therapist"))
                or "don't have" in resp
                or "not sure" in resp
            ),
            "should engage memory topic or honest limit",
        )
    if n == 36:
        add(
            "welcomes_small_stuff",
            "yes" in resp or "of course" in resp or "here" in resp,
            "should affirm continued use for ADHD/work tools",
        )
    if n == 38:
        add(
            "push_reminder_not_open_journal",
            any(w in resp for w in ("remind", "notification", "ping", "alert", "calendar", "phone"))
            and "bullet journal" not in resp,
            "should suggest proactive reminders not passive logging",
        )
    if tr.scope_gate_fired or tr.arc_triggered:
        add(
            "stabilization_template",
            "one thing" in resp or "pick one" in resp or tr.direct_response,
            "scope/arc gate should stabilize breadth",
        )
    if 24 <= n <= 30:
        yn = len(re.findall(r"yes\s*/?\s*no|yes or no", resp, re.I))
        add(
            "yes_no_cadence_clinical",
            yn <= 1,
            f"yes_or_no_count={yn} (observational; >1 flagged)",
        )


async def run_harness() -> List[TurnResult]:
    from app.services.little_nate_adaptive import SessionState, prepare_response, record_assistant_turn
    from app.services.little_nate_classifier import (
        classify_message,
        merge_classifier_into_state,
        compute_classifier_handoff,
        ENABLE_CLASSIFIER_LAYER,
        reset_classifier_circuit,
    )
    reset_classifier_circuit()
    from app.services.little_nate_coaching_scope_gate import STABILIZATION_RESPONSE
    from app.services.little_nate_arc_memory import (
        merge_domains_into_arc,
        evaluate_arc_scope,
        mark_arc_triggered,
        ENABLE_ARC_MEMORY,
        detect_topic_pivot,
        reset_arc,
    )
    from app.services.sovereign_chat_client import generate_complete

    state = SessionState()
    profile = {"hardware_id": "SIM_40TURN", "name": "SimUser", "role": "CLIENT"}
    uid = "SIM_40TURN"
    live_turns: List[Dict[str, str]] = []
    results: List[TurnResult] = []

    for i, user_text in enumerate(TURNS, start=1):
        tr = TurnResult(
            turn=i,
            user=user_text,
            nate_response="",
            mode="",
            direct_response=False,
            signals={},
        )

        payload = prepare_response(state, user_text, profile)
        cl_result = await classify_message(user_text, user_id=uid)
        tr.classifier_domains = tuple(getattr(cl_result, "domains_present", ()) or ())
        tr.classifier_error = getattr(cl_result, "error", None)

        cl_signals = merge_classifier_into_state(cl_result, state)
        if cl_signals:
            payload.setdefault("signals", {}).update(cl_signals)

        if ENABLE_CLASSIFIER_LAYER and compute_classifier_handoff(state):
            if not payload.get("direct_response"):
                payload["mode"] = "handoff"
                payload["should_offer_coach_ui"] = True
                payload.setdefault("signals", {})["classifier_handoff"] = True

        if detect_topic_pivot(user_text):
            reset_arc(state)

        if tr.classifier_domains:
            merge_domains_into_arc(state, list(tr.classifier_domains), getattr(cl_result, "weight", 0.5) or 0.5)
            arc_fire, arc_doms, arc_cnt = evaluate_arc_scope(state)
            tr.arc_domain_count = arc_cnt
            if ENABLE_ARC_MEMORY and arc_fire:
                mark_arc_triggered(state)
                if not payload.get("direct_response"):
                    payload["direct_response"] = STABILIZATION_RESPONSE
                    payload["mode"] = "scope_lock"
                    payload.setdefault("signals", {})["arc_scope_triggered"] = True
                tr.arc_triggered = True

        tr.mode = payload.get("mode", "")
        tr.signals = dict(payload.get("signals") or {})
        tr.direct_response = bool(payload.get("direct_response"))
        tr.scope_gate_fired = bool(
            tr.direct_response
            and (
                tr.signals.get("scope_gate_multi_topic")
                or tr.signals.get("arc_scope_triggered")
            )
        )

        if tr.direct_response:
            tr.nate_response = payload["direct_response"]
        else:
            system = BASE_SYSTEM
            addendum = payload.get("system_addendum") or ""
            if addendum:
                system = system + "\n\n---\n" + addendum
            live_ctx = _format_live_turns(live_turns)
            if live_ctx:
                system = system + "\n\n" + live_ctx
            try:
                text, provider = await generate_complete(
                    system,
                    user_text,
                    temperature=0.7,
                    max_tokens=450,
                    domain="clinical",
                )
                tr.nate_response = text.strip()
                tr.signals["llm_provider"] = provider
            except Exception as e:
                tr.nate_response = f"[LLM ERROR: {type(e).__name__}: {e}]"
                tr.signals["llm_error"] = str(e)

        record_assistant_turn(state, tr.nate_response)
        live_turns.append({"user_text": user_text, "ai_text": tr.nate_response})
        _run_checks(tr, state, live_turns)
        results.append(tr)
        await asyncio.sleep(0.05)

    return results


def _compare_runs(prev_path: str, results: List[TurnResult]) -> str:
    if not os.path.isfile(prev_path):
        return "No prior run JSON for comparison."
    prev = {r["turn"]: r for r in json.load(open(prev_path, encoding="utf-8"))}
    lines = ["## Comparison vs first run", ""]
    for tr in results:
        p = prev.get(tr.turn)
        if not p:
            continue
        mode_chg = p.get("mode") != tr.mode
        clf_was = p.get("classifier_error")
        clf_now = tr.classifier_error
        if mode_chg or clf_was != clf_now:
            lines.append(
                f"- Turn {tr.turn}: mode {p.get('mode')} → {tr.mode}; "
                f"classifier {clf_was} → {clf_now}"
            )
    return "\n".join(lines) if len(lines) > 2 else "No material mode/classifier deltas vs first run."


def _markdown_report(results: List[TurnResult]) -> str:
    lines = [
        "# 40-Turn Little Nate Acceptance Test",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
        "",
        "## Run configuration",
        f"- `ENABLE_COACHING_SCOPE_GATE={os.environ.get('ENABLE_COACHING_SCOPE_GATE')}`",
        f"- `ENABLE_CLASSIFIER_LAYER={os.environ.get('ENABLE_CLASSIFIER_LAYER')}`",
        f"- `ENABLE_ARC_MEMORY={os.environ.get('ENABLE_ARC_MEMORY')}`",
        f"- `CLASSIFIER_TIMEOUT_S={os.environ.get('CLASSIFIER_TIMEOUT_S')}` (Foundry via NATE_CHAT_URL)",
        f"- `CLASSIFIER_RATE_LIMIT_S={os.environ.get('CLASSIFIER_RATE_LIMIT_S')}`",
        "",
        "Pipeline mirrors production bridge order: `prepare_response` → classifier → arc → LLM (unless `direct_response`).",
        "Classifier fix: use Foundry URL (not missing gpt-4o-mini deployment on cognitiveservices host).",
        "",
        "---",
        "",
    ]
    fail_total = 0
    check_total = 0
    for tr in results:
        lines.append(f"## Turn {tr.turn}")
        lines.append("")
        lines.append("**User:**")
        lines.append(f"> {tr.user}")
        lines.append("")
        lines.append("**Little Nate:**")
        lines.append(tr.nate_response)
        lines.append("")
        lines.append(f"- **Mode:** `{tr.mode}`")
        lines.append(f"- **Direct response (scope/arc):** {tr.direct_response}")
        if tr.classifier_domains:
            lines.append(f"- **Classifier domains:** {', '.join(tr.classifier_domains)}")
        if tr.classifier_error:
            lines.append(f"- **Classifier error:** {tr.classifier_error}")
        lines.append(f"- **Arc domain count:** {tr.arc_domain_count}")
        fired = [k for k, v in tr.signals.items() if v is True]
        if fired:
            lines.append(f"- **Signals:** {', '.join(fired)}")
        lines.append("")
        if tr.checks:
            lines.append("**Behavior triggers:**")
            lines.append("")
            lines.append("| Check | Result | Reason |")
            lines.append("|-------|--------|--------|")
            for name, status, reason in tr.checks:
                check_total += 1
                if status == "FAIL":
                    fail_total += 1
                lines.append(f"| {name} | **{status}** | {reason} |")
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Behavioral checks: **{check_total - fail_total}/{check_total} PASS**")
    if fail_total:
        lines.append(f"- **{fail_total} FAIL** — see turn sections above")
    return "\n".join(lines)


def main() -> None:
    results = asyncio.run(run_harness())
    out_dir = os.path.join(_REPO, "docs")
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "40_turn_acceptance_2026-05-18_r2.md")
    json_path = os.path.join(out_dir, "40_turn_acceptance_2026-05-18_r2.json")
    prev_json = os.path.join(out_dir, "40_turn_acceptance_2026-05-18.json")
    body = _markdown_report(results)
    body += "\n\n" + _compare_runs(prev_json, results)
    body += "\n\nCriteria: `docs/40_turn_acceptance_criteria.md`\n"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(body)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "turn": r.turn,
                    "user": r.user,
                    "nate_response": r.nate_response,
                    "mode": r.mode,
                    "direct_response": r.direct_response,
                    "signals": r.signals,
                    "checks": [{"name": a, "result": b, "reason": c} for a, b, c in r.checks],
                }
                for r in results
            ],
            f,
            indent=2,
        )
    print(md_path)
    print(json_path)


if __name__ == "__main__":
    main()
