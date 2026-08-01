#!/usr/bin/env python3
"""
One-time scrub + re-fingerprint pass — contaminated principal_review crystals.

Context: verify_fuel_cycle.py Stage 3 flags live nate_intelligence_crystals rows
(origin_surface='principal_review', superseded_by IS NULL) whose crystal_text
still contains battery metadata ("Scenario:" headers, stem ids like AQ-1/MQ-G05)
or verbatim roleplay-mode-leakage narration ("blind Nate", "eyes are cast", ...).

Root cause was two-fold, both now fixed going forward:
  1) backend/scripts/backfill_principal_review_notes_learning.py built crystal_text
     by hand instead of calling the production scrubber.
  2) app.services.principal_review_crisis_policy.scrub_teaching_text did not
     redact literal stage-direction narration a Principal's own analysis quotes
     when describing *why* a blind failed.

This script does NOT touch (1) or (2) — those are already fixed in code. It
repairs the crystals that were written *before* the fix, by re-deriving each
one from its source principal_review_library row using the current (fixed)
_build_principal_crystal_text(), then superseding the old crystal the same way
_promote_library_item() already does for any other re-promotion.

Read path: nate_intelligence_crystals + principal_review_library (SELECT only).
Write path: INSERT a new crystal + UPDATE the old crystal's superseded_by/scope
+ UPDATE principal_review_library.promoted_crystal_id — mirrors
_promote_library_item() in app/routers/principal_review_api.py exactly, so this
script produces output indistinguishable from a normal re-promotion.

Nothing is ever deleted. Old crystal rows are archived (scope='archived',
superseded_by=<new id>), never dropped — same invariant as
crystal-intelligence-integrity.mdc Rule 8.

Usage:
  # Dry run (default) — reports what would change, writes nothing:
  DATABASE_URL=postgresql://... python backend/scripts/scrub_contaminated_principal_crystals.py

  # Apply the fix:
  DATABASE_URL=... python backend/scripts/scrub_contaminated_principal_crystals.py --apply

Exit codes:
  0 = clean run (dry-run report, or --apply with 0 remaining contamination)
  1 = --apply run left contamination behind (re-scrub still matched — needs a
      manual look, script refuses to loop/guess further)
  2 = could not connect to the database
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
from typing import Any, Optional

CRYSTAL_TABLE = "nate_intelligence_crystals"
LIBRARY_TABLE = "principal_review_library"

# Same patterns verify_fuel_cycle.py Stage 3 checks — keep these two in sync.
_CONTAM_STEM_ID_RE = re.compile(r"[A-Z]{2}-G?\d")


def _is_contaminated(text: str) -> bool:
    t = text or ""
    low = t.lower()
    return (
        "scenario:" in low
        or bool(_CONTAM_STEM_ID_RE.search(t))
        or "blind nate" in low
        or "eyes are cast" in low
    )


async def _run(apply: bool) -> int:
    try:
        import asyncpg
    except ImportError:
        print("ERROR: asyncpg not installed", file=sys.stderr)
        return 2

    dsn = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN")
    if not dsn:
        print("ERROR: DATABASE_URL/POSTGRES_DSN not set — refusing to guess a prod DSN")
        return 2

    try:
        conn = await asyncpg.connect(dsn)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: could not connect to database: {e}")
        return 2

    # Repo-root import so this survives being run from anywhere.
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    try:
        from app.services.principal_review_crisis_policy import (  # type: ignore
            annotate_teaching_delta,
            classify_failure_class,
            scrub_teaching_text,
        )
    except Exception as e:  # noqa: BLE001
        await conn.close()
        print(f"ERROR: could not import scrub_teaching_text (schema/import drift?): {e}")
        return 2

    _ANTI_VERBATIM_RULE = (
        "TEACHING RULE: Absorb principles, stance, safety moves, and clinical intent "
        "from Principal Guide. Never recite Guide text verbatim in client replies — "
        "paraphrase naturally for the live moment. Verbatim reuse lowers naturalness "
        "and other scores."
    )

    def _build_principal_crystal_text(row: Any) -> str:
        """Verbatim copy of principal_review_api._build_principal_crystal_text()
        so this one-time script has no import dependency on the router module
        (routers pull in FastAPI/require_admin — heavier than a migration script
        needs) while staying byte-for-byte identical to the production builder."""
        principal = scrub_teaching_text(row["principal_response"] or "")
        nate = scrub_teaching_text(row["nate_response"] or "")
        if not (principal or nate):
            return ""
        section = str(row["section"] or "clinical")[:40]
        try:
            lib_tag = str(row["id"] or "").replace("-", "")[:12]
        except (KeyError, IndexError, TypeError):
            lib_tag = ""
        header = (
            f"[Principal-Review · {section} · lib:{lib_tag}]"
            if lib_tag
            else f"[Principal-Review · {section}]"
        )
        parts = [header, _ANTI_VERBATIM_RULE]
        try:
            delta = annotate_teaching_delta(principal=principal, nate_blind=nate)
            if delta:
                parts.append(delta)
        except Exception:
            if principal and nate:
                parts.append(
                    "DELTA (near-miss → correction):\n"
                    f"- Failed class (do not reproduce): {classify_failure_class(nate)}\n"
                    f"- Corrected move (Principal Guide — adapt, do not recite): "
                    f"{principal[:1200]}\n"
                    "- Why: never quote failed blinds in teaching; failure classes only."
                )
        if principal:
            parts.append(
                "Principal Guide (3/3/3 corrective underwriting — adapt, do not recite):\n"
                f"{principal[:2500]}"
            )
        elif nate:
            parts.append(f"Guide: {nate[:2500]}")
        return scrub_teaching_text("\n".join(parts))

    print(f"scrub_contaminated_principal_crystals — mode={'APPLY' if apply else 'DRY-RUN'}")
    print()

    try:
        contaminated = await conn.fetch(
            f"""SELECT id, crystal_text, topics, source_count, confidence
                FROM {CRYSTAL_TABLE}
                WHERE origin_surface = 'principal_review'
                  AND superseded_by IS NULL
                  AND (
                    crystal_text ILIKE '%scenario:%'
                    OR crystal_text ~ '[A-Z]{{2}}-G?\\d'
                    OR crystal_text ILIKE '%blind Nate%'
                    OR crystal_text ILIKE '%eyes are cast%'
                  )"""
        )
    except Exception as e:  # noqa: BLE001
        await conn.close()
        print(f"ERROR: could not query {CRYSTAL_TABLE}: {e}")
        return 2

    if not contaminated:
        print("No live contaminated principal_review crystals found. Nothing to do.")
        await conn.close()
        return 0

    print(f"Found {len(contaminated)} live contaminated crystal(s):")
    fixed = 0
    skipped_no_lib_row = 0
    skipped_still_dirty = 0
    for crow in contaminated:
        crystal_id = crow["id"]
        try:
            lib_row = await conn.fetchrow(
                f"""SELECT * FROM {LIBRARY_TABLE}
                    WHERE promoted_crystal_id = $1""",
                str(crystal_id),
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [{crystal_id}] ERROR looking up {LIBRARY_TABLE}: {e}")
            continue

        if not lib_row:
            skipped_no_lib_row += 1
            print(
                f"  [{crystal_id}] SKIP — no {LIBRARY_TABLE} row has "
                f"promoted_crystal_id={crystal_id} (orphaned crystal, nothing to "
                f"re-derive from; requires manual review)"
            )
            continue

        new_text = _build_principal_crystal_text(lib_row)
        if not new_text:
            skipped_no_lib_row += 1
            print(
                f"  [{crystal_id}] SKIP — lib row {lib_row['id']} has no "
                f"principal_response/nate_response to rebuild from"
            )
            continue

        if _is_contaminated(new_text):
            skipped_still_dirty += 1
            print(
                f"  [{crystal_id}] SKIP — re-derived text is STILL contaminated "
                f"after scrub_teaching_text; scrub_teaching_text needs another "
                f"pattern, not this script. lib={lib_row['id']}"
            )
            continue

        new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
        old_snippet = (crow["crystal_text"] or "")[:100].replace("\n", " ")
        new_snippet = new_text[:100].replace("\n", " ")
        print(f"  [{crystal_id}] lib={lib_row['id']}")
        print(f"      before: {old_snippet}...")
        print(f"      after : {new_snippet}...")

        if not apply:
            fixed += 1
            continue

        async with conn.transaction():
            new_id = await conn.fetchval(
                f"""INSERT INTO {CRYSTAL_TABLE}
                    (crystal_text, domain, scope, topics, source_count,
                     confidence, content_hash, origin_surface)
                    VALUES ($1, 'clinical', 'global', $2, $3, $4, $5, 'principal_review')
                    ON CONFLICT (content_hash) DO NOTHING
                    RETURNING id""",
                new_text[:8000],
                crow["topics"],
                crow["source_count"] or 1,
                crow["confidence"] or 0.72,
                new_hash,
            )
            if not new_id:
                new_id = await conn.fetchval(
                    f"SELECT id FROM {CRYSTAL_TABLE} WHERE content_hash = $1 LIMIT 1",
                    new_hash,
                )
            if new_id and int(new_id) != int(crystal_id):
                await conn.execute(
                    f"""UPDATE {CRYSTAL_TABLE}
                        SET superseded_by = $2, scope = 'archived', updated_at = NOW()
                        WHERE id = $1
                          AND origin_surface = 'principal_review'
                          AND superseded_by IS NULL""",
                    crystal_id,
                    new_id,
                )
                await conn.execute(
                    f"""UPDATE {LIBRARY_TABLE}
                        SET promoted_crystal_id = $2, updated_at = NOW()
                        WHERE id = $1""",
                    lib_row["id"],
                    str(new_id),
                )
                print(f"      APPLIED — superseded {crystal_id} -> {new_id}")
            else:
                print(f"      NOTE — new text hashed identical to {crystal_id}, no-op")
        fixed += 1

    print()
    print(
        f"Summary: {fixed} rebuilt clean, {skipped_no_lib_row} skipped (no source row), "
        f"{skipped_still_dirty} skipped (still dirty after scrub)"
    )

    if apply:
        remaining = await conn.fetchval(
            f"""SELECT COUNT(*) FROM {CRYSTAL_TABLE}
                WHERE origin_surface = 'principal_review'
                  AND superseded_by IS NULL
                  AND (
                    crystal_text ILIKE '%scenario:%'
                    OR crystal_text ~ '[A-Z]{{2}}-G?\\d'
                    OR crystal_text ILIKE '%blind Nate%'
                    OR crystal_text ILIKE '%eyes are cast%'
                  )"""
        )
        print(f"Live contaminated crystals remaining after apply: {remaining}")
        await conn.close()
        return 1 if remaining else 0

    print("Dry run only — rerun with --apply to write these changes.")
    await conn.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the fix (default is dry-run, read+report only).",
    )
    args = parser.parse_args()
    return asyncio.run(_run(apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
