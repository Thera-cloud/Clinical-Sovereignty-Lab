"""Live-stack addressee integrity — perspective inversion guard."""

from __future__ import annotations

import ast
from pathlib import Path

_LIVE = Path(__file__).resolve().parents[1] / "app" / "services" / "live_stack_blinds.py"


def _load_helpers():
    # Importing live_stack_blinds pulls app stack; exec only the pure helpers.
    src = _LIVE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    wanted = {
        "wrap_client_turn_for_live",
        "looks_like_perspective_inversion",
        "_CLIENT_TURN_WRAPPER",
        "_PERSPECTIVE_INVERSION_RE",
    }
    chunks = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in wanted:
                    chunks.append(ast.get_source_segment(src, node))
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            chunks.append(ast.get_source_segment(src, node))
    ns: dict = {"re": __import__("re")}
    exec("\n\n".join(c for c in chunks if c), ns)
    return ns


def test_wrap_and_detect_cq3_inversion():
    ns = _load_helpers()
    wrap = ns["wrap_client_turn_for_live"]
    detect = ns["looks_like_perspective_inversion"]
    wrapped = wrap("My body remembers something that didn't happen to me.")
    assert wrapped.startswith("[CLIENT MESSAGE")
    assert "respond AS Little Nate" in wrapped
    inv = (
        "I notice my body tensing up when I hear loud noises. "
        "I've also caught myself stockpiling rice."
    )
    assert detect(inv)
    assert not detect(
        "Your body remembers something that didn't happen to you. "
        "I'm here with you in that."
    )
