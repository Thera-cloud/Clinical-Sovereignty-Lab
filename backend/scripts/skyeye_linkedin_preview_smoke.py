#!/usr/bin/env python3
"""Preview: LinkedIn post text (SkyEye generator) + Gemini image — no publish."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_root / "backend"))


async def main() -> int:
    out_dir = Path(os.getenv("PREVIEW_OUT_DIR", "/tmp/linkedin_preview"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        print("FAIL: DATABASE_URL required", file=sys.stderr)
        return 1

    os.environ.setdefault("ENABLE_SKYEYE_LINKEDIN_IMAGES", "true")

    import asyncpg
    from app.services.skyeye_content_generator import SkyEyeContentGenerator
    from app.services.skyeye_gemini_image import close_session
    from app.services.skyeye_linkedin_image import try_generate_linkedin_image

    topic = (
        "LinkedIn campaign preview — ORIG lane thought leadership.\n"
        "Theme: Leadership as presence in uncertainty — showing up without pretending "
        "to have all the answers.\n"
        "2–3 sentence takeaway plus brief commentary. Plain text, no markdown.\n"
        "REQUIRED: Naturally disclose that Little Nate is an AI companion.\n"
        "End with: Nathaniel reviewed + approved — Little Nate, your AI companion"
    )

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    meta: dict = {"stamp": stamp, "lane": "ORIG", "posted": False}
    try:
        gen = SkyEyeContentGenerator(pool)
        result = await gen.generate_post(
            "linkedin", topic, context={"lane": "ORIG", "preview": True}
        )
        text = (result.get("content") or "").strip()
        meta["text"] = text
        meta["safe"] = result.get("safe", False)
        meta["generator"] = "SkyEyeContentGenerator.generate_post"

        if not text:
            meta["error"] = result.get("error", "empty content")
            print(json.dumps(meta, indent=2))
            return 1

        image_bytes = await try_generate_linkedin_image(
            text, lane="ORIG", slot_key=f"preview_{stamp}"
        )
        if image_bytes:
            img_path = out_dir / f"{stamp}_linkedin_preview.jpg"
            img_path.write_bytes(image_bytes)
            meta["image_path"] = str(img_path)
            meta["image_bytes"] = len(image_bytes)
            meta["image_provider"] = "gemini"
        else:
            meta["image_path"] = None
            meta["image_note"] = "Gemini skipped or failed — text-only preview"

        meta_path = out_dir / f"{stamp}_linkedin_preview.json"
        meta_path.write_text(json.dumps(meta, indent=2))
        print("=== LINKEDIN POST TEXT (not published) ===")
        print(text)
        print("=== META ===")
        print(json.dumps({k: v for k, v in meta.items() if k != "text"}, indent=2))
        return 0 if text else 1
    finally:
        await pool.close()
        await close_session()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
