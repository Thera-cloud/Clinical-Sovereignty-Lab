#!/usr/bin/env python3
"""Generate branded Gemini infographics for all 10 Coach Portal tabs."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_root / "backend"))

_FOOTER = (
    "Nathaniel Nevedal reviewed + approved | by Little Nate, your AI companion"
)

_TABS = (
    {
        "id": 0,
        "slug": "clients",
        "name": "CLIENTS",
        "headline": "YOUR CASELOAD. ONE COMMAND CENTER.",
        "callout_1": "Risk badges at a glance.",
        "callout_2": "Family and company grouped.",
        "sidebar": "COACH COMMAND",
        "body": (
            "See every assigned client with Nevedal coherence signals, subscription tier, "
            "and folder grouping — family, company, group, or individual. "
            "Triage who needs you first without opening ten charts."
        ),
        "takeaway": "The roster mirrors how therapists actually think about caseloads.",
    },
    {
        "id": 1,
        "slug": "schedule",
        "name": "SCHEDULE",
        "headline": "FROM AVAILABILITY TO LIVE SESSION.",
        "callout_1": "Zoom, family, group sessions.",
        "callout_2": "Session Assistant in the room.",
        "sidebar": "SESSION LIFECYCLE",
        "body": (
            "Set hours, approve bookings, start live sessions, and run the Session Assistant "
            "overlay with crisis baseline and clinical co-pilot tools — all tied to each client's ID."
        ),
        "takeaway": "One calendar for every session shape your practice runs.",
    },
    {
        "id": 2,
        "slug": "insights",
        "name": "INSIGHTS",
        "headline": "AI OVERSIGHT YOU CONTROL.",
        "callout_1": "Per-client Nate modes.",
        "callout_2": "Therapeutic overrides.",
        "sidebar": "CLINICAL OVERSIGHT",
        "body": (
            "Govern how Little Nate supports each dyad — observe, suggest, or challenge. "
            "Nevedal reports, override history, and coach-to-Nate chat for caseload thinking."
        ),
        "takeaway": "The AI answers to you — not the other way around.",
    },
    {
        "id": 3,
        "slug": "briefings",
        "name": "BRIEFINGS",
        "headline": "WALK IN ALREADY KNOWING.",
        "callout_1": "Pre-session briefings.",
        "callout_2": "Conversation memory included.",
        "sidebar": "PRE-SESSION INTEL",
        "body": (
            "View Brief pulls mood, topics, F-codes, intake, Zoom insights, and Nate's memory "
            "before the client arrives. Replace the first ten minutes of reconstruction."
        ),
        "takeaway": "Continuity starts before the session — not after.",
    },
    {
        "id": 4,
        "slug": "dojo",
        "name": "DOJO",
        "headline": "TRAIN BEFORE THE REAL ROOM.",
        "callout_1": "HOSTILE, CRISIS, SKEPTIC personas.",
        "callout_2": "Night School adversarial drills.",
        "sidebar": "NIGHT SCHOOL",
        "body": (
            "Sharpen skills on simulated clients — hostile, crisis, skeptical, and more. "
            "Case upload, secure search, and rubric-scored evaluation inside Coach Command."
        ),
        "takeaway": "Practice hard cases in simulation — protect real clients.",
    },
    {
        "id": 5,
        "slug": "classroom",
        "name": "CLASSROOM",
        "headline": "REVIEW THE SESSION. GROW THE CRAFT.",
        "callout_1": "Zoom archive or upload.",
        "callout_2": "AI presence analysis.",
        "sidebar": "SESSION REVIEW",
        "body": (
            "Upload or pull session video, run transcript analysis, and track presence scores "
            "over time. Professional development tied to each client dyad."
        ),
        "takeaway": "Objective feedback on therapist presence — not guesswork.",
    },
    {
        "id": 6,
        "slug": "training",
        "name": "TRAINING",
        "headline": "SUPERVISE WITH STRUCTURE.",
        "callout_1": "BLE coaching mesh sessions.",
        "callout_2": "21 scored DOJO methods.",
        "sidebar": "COACH DEVELOPMENT",
        "body": (
            "Master coaches launch mesh training; assistants join live. "
            "Supervised hours auto-log for licensure attestation."
        ),
        "takeaway": "Associate development with audit trails — not shadowing alone.",
    },
    {
        "id": 7,
        "slug": "financials",
        "name": "FINANCIALS",
        "headline": "PRACTICE REVENUE IN ONE PLACE.",
        "callout_1": "Stripe Connect payouts.",
        "callout_2": "Per-session fee ledger.",
        "sidebar": "PRACTICE BILLING",
        "body": (
            "Month and YTD earnings, platform fees, coaching rates, DOJO subscriptions, "
            "and W-9 tracking — aggregated from real billed sessions per client."
        ),
        "takeaway": "See what you earned without exporting spreadsheets.",
    },
    {
        "id": 8,
        "slug": "folder",
        "name": "FOLDER",
        "headline": "SECURE FILES. RIGHT CLIENT.",
        "callout_1": "Family and company folders.",
        "callout_2": "Client-initiated shares.",
        "sidebar": "FILE MANAGER",
        "body": (
            "Upload, preview, and organize documents per client, family, group, or company. "
            "Pull Zoom summaries from sessions into the correct folder automatically."
        ),
        "takeaway": "HIPAA-aligned sharing without email attachments.",
    },
    {
        "id": 9,
        "slug": "assistants",
        "name": "ASSISTANTS",
        "headline": "OVERSEE YOUR ASSOCIATES.",
        "callout_1": "Per-assistant metrics.",
        "callout_2": "Hierarchy-scoped Nate chat.",
        "sidebar": "MASTER COACH",
        "body": (
            "View assistant caseloads, 30-day session counts, and average coherence. "
            "Chat with Nate about supervision without shadowing every session."
        ),
        "takeaway": "Supervision visibility without micromanagement.",
    },
)


def _build_tab_prompt(tab: dict) -> str:
    return (
        "Create a professional LinkedIn feed infographic in EXACTLY the visual system "
        "shown in the attached style reference images. "
        f"Coach Portal tab feature graphic — {tab['name']}. "
        "LAYOUT (adapt the vertical reference to a wide 16:9 landscape canvas): "
        "dark charcoal textured background with subtle gold corner accents; "
        "large centered 3D metallic gold-and-silver intertwined S logo (match logo reference exactly); "
        "thin white/gold callout lines from the logo to short phrases; "
        "elegant gold serif headline band across the top; "
        "left text panel with gold border and white body copy with gold keyword highlights; "
        "right sidebar panel with dark frame and gold title; "
        "small tab label badge showing COACH COMMAND · {tab_name}; "
        "horizontal gold takeaway bar above the footer; "
        "footer line with small LN microchip icon. "
        "Typography must be crisp and legible. "
        f"HEADLINE: {tab['headline']} "
        f"CALLOUT 1: {tab['callout_1']} "
        f"CALLOUT 2: {tab['callout_2']} "
        f"SIDEBAR TITLE: {tab['sidebar']} "
        f"BODY: {tab['body']} "
        f"TAKEAWAY BAR: Takeaway: {tab['takeaway']} "
        f"FOOTER: {_FOOTER} "
        "Do not use banned words: liminal, threshold, aching, quantum, sentient. "
        "Premium executive aesthetic — Sovereign Sanctuary / Little Nate brand."
    ).replace("{tab_name}", tab["name"])


async def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Coach Portal tab Gemini images")
    parser.add_argument(
        "--out-dir",
        default=os.getenv("COACH_PORTAL_TAB_IMAGES_DIR", "data/coach_portal_tab_images"),
    )
    parser.add_argument("--only", default="", help="Comma-separated slugs to generate")
    args = parser.parse_args()

    from app.services.skyeye_gemini_image import close_session, generate_image
    from app.services.skyeye_linkedin_brand import load_brand_reference_images

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    only = {s.strip() for s in args.only.split(",") if s.strip()}
    refs = load_brand_reference_images()
    if not refs:
        print("WARN: no brand reference images — prompt-only generation", file=sys.stderr)

    failed = 0
    try:
        for tab in _TABS:
            if only and tab["slug"] not in only:
                continue
            prompt = _build_tab_prompt(tab)
            print(f"Generating tab {tab['id']:02d} {tab['slug']}...")
            try:
                image_bytes = await generate_image(prompt, reference_images=refs or None)
            except Exception as exc:
                print(f"FAIL {tab['slug']}: {exc}", file=sys.stderr)
                failed += 1
                continue
            out_path = out_dir / f"tab{tab['id']:02d}_{tab['slug']}.jpg"
            out_path.write_bytes(image_bytes)
            print(f"OK {out_path} ({len(image_bytes)} bytes)")
    finally:
        await close_session()

    if failed:
        print(f"DONE with {failed} failure(s)", file=sys.stderr)
        return 1
    print(f"DONE — {len(_TABS) if not only else len(only)} images in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
