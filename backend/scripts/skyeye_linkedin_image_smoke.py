#!/usr/bin/env python3
"""Smoke test: Gemini LinkedIn image (optional live LinkedIn upload)."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow: PYTHONPATH=backend python backend/scripts/skyeye_linkedin_image_smoke.py
if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_root / "backend"))


async def main() -> int:
    parser = argparse.ArgumentParser(description="SkyEye LinkedIn Gemini image smoke test")
    parser.add_argument(
        "--text",
        default=(
            "Leadership as presence: showing up in uncertainty without pretending "
            "to have all the answers."
        ),
        help="Sample post body for image prompt",
    )
    parser.add_argument("--lane", default="ORIG", choices=("ORIG", "PERS", "CUR"))
    parser.add_argument(
        "--out-dir",
        default=os.getenv("COMPARE_OUT_DIR", "data/image_compare"),
        help="Where to write JPEG",
    )
    parser.add_argument(
        "--linkedin-upload",
        action="store_true",
        help="Also upload to LinkedIn (requires DB + OAuth on GREEN)",
    )
    args = parser.parse_args()

    os.environ.setdefault("ENABLE_SKYEYE_LINKEDIN_IMAGES", "true")

    from app.services.skyeye_gemini_image import close_session
    from app.services.skyeye_linkedin_image import (
        build_image_prompt,
        try_generate_linkedin_image,
    )

    exit_code = 1
    try:
        prompt = build_image_prompt(args.text, lane=args.lane, slot_key="smoke_test")
        print("PROMPT:", prompt[:200], "...")

        image_bytes = await try_generate_linkedin_image(
            args.text, lane=args.lane, slot_key="smoke_test"
        )
        if not image_bytes:
            print("FAIL: no image bytes (check GEMINI_API_KEY / quota)", file=sys.stderr)
            return 1

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = out_dir / f"{stamp}_skyeye_linkedin_smoke.jpg"
        out_path.write_bytes(image_bytes)
        print(f"OK gemini: {out_path} ({len(image_bytes)} bytes)")

        if not args.linkedin_upload:
            print("Skip LinkedIn upload (pass --linkedin-upload to test native post path)")
            exit_code = 0
            return exit_code

        db_url = os.getenv("DATABASE_URL", "").strip()
        if not db_url:
            print("FAIL: DATABASE_URL required for --linkedin-upload", file=sys.stderr)
            return 1

        import asyncpg
        from app.services.platforms.linkedin import LinkedInAdapter

        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        try:
            adapter = LinkedInAdapter(pool)
            if not await adapter.authenticate():
                print("FAIL: LinkedIn adapter not authenticated", file=sys.stderr)
                return 1
            urn = await adapter._upload_image_bytes(
                image_bytes,
                adapter._person_urn,
                adapter._access_token,
            )
            if urn:
                print(f"OK linkedin upload: {urn}")
                exit_code = 0
                return exit_code
            print("FAIL: LinkedIn upload returned no URN", file=sys.stderr)
            return 1
        finally:
            await pool.close()
    finally:
        await close_session()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
