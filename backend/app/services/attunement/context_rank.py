"""Prompt layer rank: live → session → query crystals → PG → story background.

QUANTUM-CRYSTAL-ARCH — clinical. SOVEREIGN-STANDARD.
CEO: Nathaniel James Nevedal. Risk: RED.
"""

from __future__ import annotations

from typing import Tuple

from app.services.attunement import flags

_BG = (
    "BACKGROUND FILE (do not lead with this; use only if the live turn is silent):\n"
)


def rank(
    live: str,
    session: str,
    crystals: str,
    pg: str,
    story: str,
) -> Tuple[str, str, str, str, str]:
    if not flags.context_rank():
        return live, session, crystals, pg, story
    story2 = story
    if story2 and not story2.startswith("BACKGROUND FILE"):
        story2 = _BG + story2
    return live or "", session or "", crystals or "", pg or "", story2
