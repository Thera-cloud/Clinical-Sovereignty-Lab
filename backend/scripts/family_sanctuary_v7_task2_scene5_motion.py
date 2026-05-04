#!/usr/bin/env python3
"""Family Sanctuary v7 Task 2 — surgical Grok Video regen for scene 5 motion only."""

from __future__ import annotations

import asyncio
import json
import os
import sys

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

os.environ.setdefault("FAMILY_SANCTUARY_STEP5_USE_GROK", "1")

from app.sse.trailer_generator import generate_family_sanctuary_step5_motion

SCENE_5_LOCK = (
    "Photorealistic cinematic film still, NOT animated, NOT cartoon. "
    "Mother reaches toward daughter as family of four faces threat together. "
    "Mother: Black woman, terracotta dress with sage green INSET PANELS and "
    "patterned woven cuff bands, hair in low bun. NOT a wrap robe. NOT a "
    "solid earth-tone dress. "
    "Daughter MUST BE IN FRAME: ~8y Black girl, twin Afro puffs with beads, "
    "bright yellow tee. NOT cornrows. NOT pink. "
    "Son: olive jacket. Father: navy henley, dark jeans. "
    "ONLY four family members. NO extras through archway, NO background humans, "
    "NO figures in distance. "
    "Subtle motion: mother reaching, fabric movement, breath."
)


async def main() -> None:
    result = await generate_family_sanctuary_step5_motion(
        local_dir="/tmp/family_sanctuary_step5_motion_v7",
        inter_scene_delay_seconds=8.0,
        scenes_to_regenerate=[5],
        per_scene_prompt_overrides={5: SCENE_5_LOCK},
        grok_motion_strength=0.4,
    )
    print("SCENE5_MOTION_JSON:")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
