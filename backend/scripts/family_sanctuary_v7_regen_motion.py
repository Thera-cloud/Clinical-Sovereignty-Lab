#!/usr/bin/env python3
"""Family Sanctuary hero — surgical Step 5 regen for v7 (scenes 4, 8, 9).

Run inside nate_backend container (loads app.* modules):

  docker exec -w /app nate_backend env PYTHONPATH=/app python3 /tmp/regen_v7.py

Scripts under /tmp put /tmp first on sys.path — PYTHONPATH=/app (or the sys.path hook
below) is required so ``import app`` resolves to ``/app/app``.

Deploy by: scp this file → green:/tmp/regen_v7.py (or docker cp).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# nate_backend: package lives at /app/app; running from /tmp/regen_v7.py otherwise breaks imports.
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

os.environ.setdefault("FAMILY_SANCTUARY_STEP5_USE_GROK", "1")

from app.sse.trailer_generator import generate_family_sanctuary_step5_motion

SCENE_LOCKS = {
    4: (
        "Photorealistic cinematic film still, NOT animated, NOT cartoon. "
        "Black family of four reacts to portal threat. "
        "Mother: Black woman, terracotta dress with sage green inset panels and patterned woven cuff bands, hair in low bun. "
        "Daughter: ~8y Black girl, TWIN AFRO PUFFS with beads, BRIGHT YELLOW tee or dress. NOT braids. NOT cornrows. NOT pink. NOT blush. "
        "Son: ~12y Black boy, olive jacket over graphic tee. "
        "Father: Black man, NAVY HENLEY 3-button placket, dark jeans. NOT cargo pants. "
        "ONLY four family members in frame. NO extras. "
        "Subtle motion: wind in fabric, breath, slight head turn. "
        "DO NOT add or remove characters. DO NOT change wardrobe. DO NOT change hair style."
    ),
    8: (
        "Photorealistic cinematic film still, NOT animated, NOT cartoon. "
        "Father in foreground reacting in stone sanctuary chamber, mother behind him, son and daughter at sides. "
        "Portal arch behind father shows ONLY soft mist and stone — NO figures, NO humans, NO women in bodysuits, NO extras. "
        "ABSOLUTELY NO additional characters in the portal plane. ONLY the four family members exist in this image. "
        "Father: NAVY HENLEY 3-button, dark jeans. Mother: terracotta sage panel dress. "
        "Daughter: twin Afro puffs, yellow tee. Son: olive jacket. "
        "Subtle motion: father's breath, slow zoom-in on his expression, soft mist drift."
    ),
    9: (
        "PHOTOREALISTIC cinematic film still. NOT animated. NOT Pixar. NOT Disney. NOT cartoon. NOT illustrated. "
        "Photographic skin texture, photographic lighting, real fabric, real hair texture. "
        "Black family of four together — ALL FOUR present in frame. "
        "Mother: Black woman, hair in LOW BUN (NOT long loose braid), terracotta dress with sage green panels and patterned cuffs. "
        "Daughter: ~8y Black girl, TWIN AFRO PUFFS with beads, bright YELLOW tee. NOT cornrows. NOT braids. "
        "Son: ~12y Black boy, olive jacket. Father: Black man, navy henley, dark jeans. "
        "Subtle motion: family turns toward camera together, soft mist, hair moves gently. "
        "DO NOT render in animated style. DO NOT smooth skin into cartoon. DO NOT remove daughter."
    ),
}


async def main() -> None:
    result = await generate_family_sanctuary_step5_motion(
        local_dir="/tmp/family_sanctuary_step5_motion_v7",
        inter_scene_delay_seconds=8.0,
        scenes_to_regenerate=[4, 8, 9],
        per_scene_prompt_overrides=SCENE_LOCKS,
        grok_motion_strength=0.4,
    )
    print("REGEN_RESULT_JSON:")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
