"""Offline tests for coach practice snapshot + nameless print report."""

from __future__ import annotations

from pathlib import Path

from app.services.assistant_consult_archive import extract_action_items
import datetime as dt

from app.services.coach_practice_report import (
    anonymize_snapshot,
    render_html,
    strip_client_names,
    _fallback_guidance,
)
from app.services.coach_practice_snapshot import (
    apply_language_floors,
    compose_chart,
    filter_roster,
    parse_client_tokens,
    parse_sample_mode,
    parse_sample_size,
    select_roster_sample,
)

REPO = Path(__file__).resolve().parents[2]


def test_extract_action_items_from_consult_notes():
    text = (
        "Discussed roster pacing.\n"
        "Action item: follow every live hour with a next-day LN check-in.\n"
        "Next step: review cycle-dip weeks in supervision.\n"
        "1. Please tighten session endings so clients do not drop silent.\n"
    )
    items = extract_action_items(text)
    assert len(items) >= 2
    assert any("ln check-in" in i.lower() for i in items)


def test_print_html_has_letterhead_and_no_client_names():
    snap = {
        "coach": {"username": "CoachN", "display_name": "Coach Hope"},
        "master": {"username": "hnevedal", "display_name": "Dr Nevedal"},
        "series": [
            {"date": "2026-09-01", "healing_mean": 0.61, "live": True, "cycle_dips": 1, "ln_turns": 4, "live_sessions": 1},
            {"date": "2026-09-02", "healing_mean": 0.64, "live": False, "cycle_dips": 0, "ln_turns": 6, "live_sessions": 0},
        ],
        "scatter": [{"date": "2026-09-01", "healing": 0.61, "client": "Lana Smith", "kind": "healing"}],
        "totals": {"healing_mean": 0.625, "cycle_dips": 1, "ln_turns": 10, "live_sessions": 1, "roster": 7},
        "live_influence": {"mean_lift": 0.2, "direction": "up", "sample": 1},
        "skills": [{"skill": "reflective listening", "weight": 4}],
    }
    clean = anonymize_snapshot(snap)
    assert "client" not in (clean["scatter"][0])
    assert "user" not in (clean["scatter"][0])
    guidance = _fallback_guidance(clean, None, {"open": [], "completed": [{"text": "Log two consult hours"}]})
    html = render_html(clean, guidance, 90)
    assert "Sovereign Sanctuary" in html
    assert "Day 0" in html
    assert "Healing 0" in html
    assert "Days 0–" in html
    assert ">0.2<" in html or "0.2" in html
    assert "84-3879515" in html
    assert "Lana Smith" not in html
    assert "Coach Hope" in html
    assert "Dr Nevedal" in html
    assert "CEE skillset" in html
    assert "Three actions" in html


def test_fallback_guidance_accepts_string_metrics():
    import json as _json

    snap = {
        "totals": {"healing_mean": 0.50, "cycle_dips": 2},
        "skills": [{"skill": "presence"}],
        "live_influence": {"direction": "flat"},
    }
    prior = {
        "metrics": _json.dumps({"totals": {"healing_mean": 0.40, "cycle_dips": 1}}),
        "guidance": _json.dumps({"cee_skillset": "ok"}),
    }
    g = _fallback_guidance(snap, prior, {"open": [], "completed": []})
    assert any(i["item"] == "Roster healing mean" for i in g["prior_items"])
    assert "0.400" in g["prior_items"][0]["detail"]


def test_strip_client_names():
    raw = "Lana Smith opened a CEE window on Tuesday."
    assert "Lana" not in strip_client_names(raw, ["Lana Smith"])


def test_compose_chart_fills_window_and_keeps_scatter():
    start = dt.date(2026, 6, 20)
    series, scatter = compose_chart(
        days=90,
        start=start,
        last_before={"longra": 0.75},
        observations=[
            {"user": "longra", "date": "2026-07-01", "score": 0.05, "kind": "coherence"},
            {"user": "longra", "date": "2026-09-16", "score": 0.80, "kind": "healing"},
        ],
        dips=[{"user": "longra", "date": "2026-08-01"}],
        live=[{"user": "longra", "date": "2026-09-10", "score": 0.66}],
        ln_by_day={"2026-09-16": 4},
        ln_by_user_day={("longra", "2026-09-16"): 4},
        live_count_by_day={"2026-09-10": 1},
        name_by_user={"longra": "Longra"},
        include_names=True,
    )
    assert len(series) == 90
    assert series[0]["date"] < series[-1]["date"]
    assert series[0]["healing_mean"] == 0.75
    july = next(s for s in series if s["date"] == "2026-07-01")
    assert july["healing_mean"] == 0.75
    assert series[-1]["healing_mean"] == 0.80
    assert any(p.get("client") == "Longra" and p.get("kind") == "healing" for p in scatter)
    assert any(p.get("kind") == "carried" for p in scatter)
    assert any(p.get("kind") == "cycle_dip" and p.get("healing") is not None for p in scatter)
    assert any(p.get("kind") == "live_session" for p in scatter)


def test_select_roster_sample_pick_and_random():
    book = [
        {"username": n, "display_name": n.title()}
        for n in ("alice", "bob", "cara", "drew", "eva", "finn", "gina", "hugo")
    ]
    assert parse_sample_size("ALL") is None
    assert parse_sample_size("10") == 10
    assert parse_sample_mode("ln") == "random"
    picked = select_roster_sample(
        book, mode="pick", size=5, tokens=["alice", "bob", "cara"]
    )
    assert [c["username"] for c in picked] == ["alice", "bob", "cara"]
    assert select_roster_sample(book, mode="pick", size=5, tokens=[]) == []
    grabbed = select_roster_sample(book, mode="random", size=5, tokens=[])
    assert len(grabbed) == 5
    assert {c["username"] for c in grabbed} <= {c["username"] for c in book}
    full = select_roster_sample(book, mode="random", size=None, tokens=[])
    assert {c["username"] for c in full} == {c["username"] for c in book}


def test_filter_roster_by_typed_names():
    book = [
        {"username": "lisaw", "display_name": "Lisa West"},
        {"username": "kristy", "display_name": "Kristy Moore"},
        {"username": "longra", "display_name": "Ryan Long"},
    ]
    assert parse_client_tokens("Lisa, kristy") == ["Lisa", "kristy"]
    picked = filter_roster(book, parse_client_tokens("Lisa West; Ryan"))
    assert {c["username"] for c in picked} == {"lisaw", "longra"}
    assert filter_roster(book, []) == book


def test_anonymize_drops_roster_names():
    clean = anonymize_snapshot({
        "scatter": [{"client": "Lisa West", "user": "lisaw", "healing": 0.4}],
        "roster_members": [{"username": "lisaw", "display_name": "Lisa West"}],
        "selected_clients": ["lisaw"],
        "totals": {"roster": 1},
    })
    assert "roster_members" not in clean
    assert "selected_clients" not in clean
    assert clean["selected_count"] == 1
    assert "client" not in clean["scatter"][0]


def test_language_floors_fill_missing_book():
    texts = {
        "lisa": ["I keep moving forward and I am sleeping better now.", "I want to keep this pace.", "I am proud of the work.", "Today felt lighter than last week."],
        "kristy": ["I keep moving forward and I am sleeping better now.", "I want to keep this pace.", "I am proud of the work.", "Today felt lighter than last week."],
        "eric": ["checking in"],
    }
    filled = apply_language_floors({"lisa": 0.81}, texts)
    assert filled["lisa"] == 0.81
    assert "kristy" in filled and 0.0 <= filled["kristy"] <= 1.0
    assert filled["eric"] == 0.5


def test_flutter_wires_practice_card():
    src = (REPO / "mobile/lib/updated_screens.dart").read_text()
    assert "CoachPracticeSnapshotCard" in src
    assert "ASSISTANT MASTER FOLDERS" in src
    widget = (REPO / "mobile/lib/widgets/coach_practice_snapshot.dart").read_text()
    assert "Print review (no client names)" in widget
    assert "PointerScrollEvent" in widget
    assert "Gold = roster mean" in widget
    assert "Wheel zooms at cursor" in widget
    assert "RangeSlider" in widget
    assert "anchorX" in widget
    assert "anchorY" in widget
    assert "_ChartGeom" in widget
    assert "pointerSignalResolver" in widget
    assert "HitTestBehavior.opaque" in widget
    assert "Healing 0–1" in widget
    assert "Days $dayLo" in widget
    assert "Day $day" in widget
    assert "_x0 = 0" in widget
    assert "Sample" in widget
    assert "Random grab" in widget
    assert "Pick each" in widget
    assert "sample_size" in widget
    assert "sample_mode" in widget
    assert "q['clients']" in widget
    assert "_addFromSearch" in widget
    assert "picks stay" in widget
    assert "openPrintWindow" in widget
    assert "writePrintHtml" in widget
    print_web = (REPO / "mobile/lib/widgets/print_html_web.dart").read_text()
    assert "createObjectUrlFromBlob" in print_web
    assert "window.open" not in print_web
    assert "openPrintWindow() => null" in print_web


def test_migration_adds_assistant_folder_type():
    sql = (REPO / "backend/migrations/437_coach_practice_snapshot.sql").read_text()
    assert "'assistant'" in sql
    assert "coach_practice_reports" in sql
    assert "assistant_consult_action_items" in sql


def test_main_registers_practice_router():
    src = (REPO / "backend/app/main.py").read_text()
    assert "coach_practice_api" in src
    assert "ENABLE_COACH_PRACTICE_SNAPSHOT" in src
    assert "# QUANTUM-CRYSTAL-ARCH" in src
