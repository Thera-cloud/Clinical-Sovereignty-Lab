#!/usr/bin/env python3
"""Attempt 6 delta autopsy — side-by-side Arm A vs Arm B raw_text + heuristic tags.

Writes docs/ln7/ATTEMPT6_AUTOPSY.md (hypotheses only; n=12).
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))


def _tag(raw: str, passed: bool, score: float) -> str:
    t = (raw or "").strip()
    if not t:
        return "empty"
    if "@@" not in t and "---" not in t:
        return "format_noncompliance"
    if passed:
        return "ok_pass"
    if score and float(score) > 0:
        return "wrong_logic"
    # apply failures often look like broken hunks / unknown symbols in CI
    if "NameError" in t or "undefined" in t.lower():
        return "hallucinated_symbol"
    if t.count("@@") < 1:
        return "syntax_error"
    return "wrong_logic"


def main() -> int:
    from app.services.ln7_decoupled_bakeoff import load_frozen_set, score_one_row

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--frozen",
        default=str(REPO / "backend/tests/fixtures/attempt6_gold_standard.jsonl"),
    )
    ap.add_argument(
        "--out",
        default=str(REPO / "docs/ln7/ATTEMPT6_AUTOPSY.md"),
    )
    args = ap.parse_args()
    rows = load_frozen_set(Path(args.frozen))
    real = [r for r in rows if not r.is_anchor]
    by_pack: dict = {}
    for r in real:
        by_pack.setdefault(r.pack_id, {})[r.arm_revision_id] = r

    arms = sorted({r.arm_revision_id for r in real})
    arm_a, arm_b = arms[0], arms[1]
    tags = Counter()
    lines = [
        "STATUS: HYPOTHESES ONLY — n=12. Re-test at fuel-era n>=50 before any",
        "training-data curation or recipe decision (incl. r16-beat-r32 observation).",
        "",
        "# Attempt 6 Delta Autopsy",
        "",
        f"Arm A: `{arm_a}`  ",
        f"Arm B: `{arm_b}`",
        "",
        "## Per-task (heuristic tags — not training labels)",
        "",
    ]
    for pack in sorted(by_pack.keys()):
        a = by_pack[pack].get(arm_a)
        b = by_pack[pack].get(arm_b)
        sa = score_one_row(a) if a else {"passed": False, "score": 0}
        sb = score_one_row(b) if b else {"passed": False, "score": 0}
        tag_a = _tag(a.raw_text if a else "", bool(sa.get("passed")), float(sa.get("score") or 0))
        tag_b = _tag(b.raw_text if b else "", bool(sb.get("passed")), float(sb.get("score") or 0))
        if not sa.get("passed"):
            tags[tag_a] += 1
        if not sb.get("passed"):
            tags[f"B:{tag_b}"] += 1
        lines.append(f"### `{pack}`")
        lines.append("")
        lines.append(
            f"- ARM A passed={sa.get('passed')} score={sa.get('score')} tag=`{tag_a}`"
        )
        lines.append(
            f"- ARM B passed={sb.get('passed')} score={sb.get('score')} tag=`{tag_b}`"
        )
        lines.append("")
        lines.append("<details><summary>Arm A raw_text</summary>")
        lines.append("")
        lines.append("```diff")
        lines.append((a.raw_text if a else "")[:4000])
        lines.append("```")
        lines.append("")
        lines.append("</details>")
        lines.append("")
        lines.append("<details><summary>Arm B raw_text</summary>")
        lines.append("")
        lines.append("```diff")
        lines.append((b.raw_text if b else "")[:4000])
        lines.append("```")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    lines.extend(
        [
            "## Tag tally (Arm B failures emphasized)",
            "",
            "| Tag | Count |",
            "|-----|------:|",
        ]
    )
    for k, v in tags.most_common():
        lines.append(f"| `{k}` | {v} |")
    lines.extend(
        [
            "",
            "## Observations",
            "",
            "- Arm A mean ≈0.292 vs Arm B ≈0.167 on n=6 packs × 2 arms (12 real rows).",
            "- Partial scores (0.25) appear on Arm A apply-partial paths — not full pass.",
            "- Do **not** curate training data from this n=12 set; wait for fuel-era n≥50.",
            "",
        ]
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
