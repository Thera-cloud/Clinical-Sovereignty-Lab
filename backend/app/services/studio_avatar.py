"""S4 audio-envelope avatar — not photoreal. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import math
from typing import Any, Dict, List


def envelope_frame(level: float = 0.35) -> Dict[str, Any]:
    amp = max(0.05, min(1.0, float(level)))
    points: List[Dict[str, float]] = []
    for i in range(24):
        ang = (i / 24.0) * 2 * math.pi
        r = 40 + 28 * amp * (0.65 + 0.35 * math.sin(i * 1.7))
        points.append({"x": round(80 + r * math.cos(ang), 2), "y": round(80 + r * math.sin(ang), 2)})
    return {
        "ok": True,
        "kind": "audio_envelope",
        "photoreal": False,
        "level": amp,
        "points": points,
        "view": 160,
    }
