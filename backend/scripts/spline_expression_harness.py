#!/usr/bin/env python3
"""Headless browser test: Spline iframe expression postMessage + visual delta check."""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

SPLINE_URL = "https://app.sovereignsanctuary.net/spline/index.html"
EXPRESSIONS = [
    "neutral",
    "sad",
    "proud",
    "empathetic",
    "warm",
    "calming",
    "curious",
]
OUT_DIR = Path(__file__).resolve().parents[2] / "backend" / "test_results" / "spline_harness"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("INSTALL: pip install playwright && playwright install chromium")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    logs: list[str] = []
    hashes: dict[str, str] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 640, "height": 480})

        def on_console(msg):
            text = msg.text
            if "[SplineAvatar]" in text or "No variable for" in text:
                logs.append(text)

        page.on("console", on_console)
        with page.expect_console_message(
            lambda m: "Ready — expression keys" in m.text, timeout=120_000
        ):
            page.goto(SPLINE_URL, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(2000)

        for expr in EXPRESSIONS:
            page.evaluate(
                """(expression) => {
                    window.postMessage({ type: 'setExpression', expression }, '*');
                }""",
                expr,
            )
            page.wait_for_timeout(2500)
            canvas = page.locator("#canvas3d")
            shot = OUT_DIR / f"{expr}.png"
            canvas.screenshot(path=str(shot))
            data = shot.read_bytes()
            hashes[expr] = hashlib.sha256(data).hexdigest()[:16]
            logs.append(f"[Harness] screenshot {expr} sha={hashes[expr]}")

        browser.close()

    unique_hashes = set(hashes.values())
    report = {
        "url": SPLINE_URL,
        "expression_hashes": hashes,
        "unique_visual_states": len(unique_hashes),
        "total_expressions": len(EXPRESSIONS),
        "console_logs": logs,
        "verdict": (
            "VISUAL_TRANSITIONS_WORKING"
            if len(unique_hashes) >= 3
            else "VISUAL_TRANSITIONS_LIKELY_BROKEN"
        ),
    }
    report_path = OUT_DIR / f"spline_harness_{int(time.time())}.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report["verdict"] == "VISUAL_TRANSITIONS_WORKING" else 1


if __name__ == "__main__":
    sys.exit(main())
