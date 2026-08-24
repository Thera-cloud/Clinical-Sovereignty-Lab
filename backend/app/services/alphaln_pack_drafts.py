"""AlphaLN CI pack drafts — propose only; human accept materializes files.

Does not write outcome_envelope, crystals, or conversation_history.
Does not call run_fuel_volume_burst / drip.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import ast
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("nate.alphaln_pack_drafts")

PACK_PREFIX = "catalog_aln_"
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
_REL_RE = re.compile(r"^broken/[a-z][a-z0-9_]{0,30}\.py$")
_GEN_WINDOW_S = 3600
_GEN_MAX_PER_WINDOW = 8
_gen_hits: List[float] = []


def _rate_ok() -> bool:
    now = time.time()
    while _gen_hits and now - _gen_hits[0] > _GEN_WINDOW_S:
        _gen_hits.pop(0)
    return len(_gen_hits) < _GEN_MAX_PER_WINDOW


def _mark_gen() -> None:
    _gen_hits.append(time.time())


def validate_spec(raw: Any, *, reserved: Set[str]) -> Tuple[Optional[Dict[str, str]], str]:
    """Return (normalized spec, error). Rejects imports and non-self-tests."""
    if not isinstance(raw, dict):
        return None, "not_object"
    slug = str(raw.get("slug") or "").strip().lower()
    title = str(raw.get("title") or "").strip()
    rel = str(raw.get("rel") or "broken/task.py").strip()
    broken = str(raw.get("broken") or "")
    fixed = str(raw.get("fixed") or "")
    needle = str(raw.get("looks_needle") or "").strip()
    if not _SLUG_RE.match(slug):
        return None, "bad_slug"
    if slug in reserved or f"{PACK_PREFIX}{slug}" in reserved:
        return None, "slug_taken"
    if len(title) < 8 or len(title) > 120:
        return None, "bad_title"
    if not _REL_RE.match(rel):
        return None, "bad_rel"
    if "import " in broken or "import " in fixed:
        return None, "import_forbidden"
    if broken == fixed or not needle:
        return None, "no_delta"
    if needle not in fixed or needle in broken:
        return None, "needle_not_exclusive"
    try:
        ast.parse(broken)
        ast.parse(fixed)
    except SyntaxError:
        return None, "syntax"
    try:
        b_ns: Dict[str, Any] = {}
        f_ns: Dict[str, Any] = {}
        exec(compile(broken, "<broken>", "exec"), b_ns, b_ns)
        exec(compile(fixed, "<fixed>", "exec"), f_ns, f_ns)
        if "run" not in b_ns or "looks_fixed" not in b_ns:
            return None, "missing_run_or_looks_fixed"
        if not callable(b_ns["run"]) or not callable(b_ns["looks_fixed"]):
            return None, "not_callable"
        if b_ns["looks_fixed"](b_ns["run"]()):
            return None, "broken_already_passes"
        if not f_ns["looks_fixed"](f_ns["run"]()):
            return None, "fixed_fails_looks"
    except Exception as e:
        return None, f"exec:{type(e).__name__}"
    prompt = (
        f"{rel} has a real incident bug. Change only what looks_fixed checks. "
        f"Return ONLY a unified diff for {rel}. No markdown fences."
    )
    return {
        "slug": slug,
        "title": title,
        "rel": rel,
        "broken": broken if broken.endswith("\n") else broken + "\n",
        "fixed": fixed if fixed.endswith("\n") else fixed + "\n",
        "looks_needle": needle,
        "prompt": prompt,
    }, ""


def _extract_json_array(text: str) -> List[Any]:
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _reserved_from_disk() -> Set[str]:
    names: Set[str] = set()
    try:
        from app.services.ln7_fuel_pack_catalog import catalog_pack_names, catalog_specs

        names.update(catalog_pack_names())
        names.update(s.slug for s in catalog_specs())
    except Exception:
        pass
    try:
        from app.services.ln_sandbox_engineering_ci import list_pack_names

        names.update(list_pack_names())
    except Exception:
        pass
    return names


async def _reserved(db_pool) -> Set[str]:
    names = _reserved_from_disk()
    if db_pool:
        try:
            from app.services.ln7_fuel_volume import existing_ci_pack_names

            names.update(await existing_ci_pack_names(db_pool))
        except Exception as e:
            logger.warning("alphaln drafts: used packs: %s", e)
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT slug, pack_name FROM alphaln_pack_drafts
                       WHERE status IN ('draft', 'accepted')"""
                )
            for r in rows:
                names.add(str(r["slug"]))
                if r["pack_name"]:
                    names.add(str(r["pack_name"]))
        except Exception as e:
            logger.warning("alphaln drafts: reserved db: %s", e)
    return names


def _system_prompt(reserved: Set[str]) -> str:
    avoid = ", ".join(sorted(list(reserved))[:40])
    return (
        "You author unique Python CI incident packs for Little Nate fuel. "
        "Each pack is one real production bug class (deploy, SQL, auth, nginx, "
        "env, auditor). Not a clone of an existing slug. "
        f"Already used (do not repeat): {avoid}. "
        "Return ONLY a JSON array. Each object: slug, title, rel "
        "(broken/<name>.py), broken (full .py), fixed (full .py), looks_needle. "
        "Both files MUST define run() and looks_fixed(value). "
        "looks_fixed(run()) is False on broken and True on fixed. "
        "looks_needle appears in fixed only. No import statements. "
        "Keep each file under 25 lines."
    )


async def generate_drafts(
    db_pool,
    app_state,
    admin_user: str,
    count: int = 3,
) -> Dict[str, Any]:
    if db_pool is None:
        return {"ok": False, "reason": "no_db"}
    if not _rate_ok():
        return {"ok": False, "reason": "rate_limited"}
    count = max(1, min(int(count or 3), 4))
    reserved = await _reserved(db_pool)
    from app.services.nate_inference_router import NateInferenceRouter, TIER_CODING

    try:
        out = await NateInferenceRouter(app_state=app_state).generate(
            prompt=f"Write {count} new unique packs as a JSON array.",
            system=_system_prompt(reserved),
            tier=TIER_CODING,
            domain="coding",
            max_tokens=2200,
            temperature=0.4,
        )
        text = (out.get("text") or "").strip()
        provider = str(out.get("provider") or "router")
    except Exception as e:
        logger.warning("alphaln pack draft inference: %s", e)
        return {"ok": False, "reason": "inference_failed"}

    raw_items = _extract_json_array(text)
    saved: List[Dict[str, Any]] = []
    rejected: List[str] = []
    for item in raw_items:
        spec, err = validate_spec(item, reserved=reserved)
        if not spec:
            rejected.append(err)
            continue
        reserved.add(spec["slug"])
        reserved.add(f"{PACK_PREFIX}{spec['slug']}")
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """INSERT INTO alphaln_pack_drafts
                           (created_by, slug, title, spec_json, metadata)
                         VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
                         RETURNING id, created_at, status""",
                    admin_user,
                    spec["slug"],
                    spec["title"],
                    json.dumps(spec),
                    json.dumps({"provider": provider}),
                )
            saved.append(
                {
                    "id": int(row["id"]),
                    "slug": spec["slug"],
                    "title": spec["title"],
                    "status": row["status"],
                    "created_at": row["created_at"].isoformat(),
                }
            )
        except Exception as e:
            rejected.append(f"db:{type(e).__name__}")
            logger.warning("alphaln pack draft insert: %s", e)
    _mark_gen()
    return {
        "ok": True,
        "drafted": len(saved),
        "drafts": saved,
        "rejected": rejected[:12],
        "provider": provider,
        "note": "Drafts are not fuel. Accept in the AlphaLN console to publish.",
    }


async def list_drafts(db_pool, status: Optional[str] = None, limit: int = 40) -> Dict[str, Any]:
    if db_pool is None:
        return {"drafts": []}
    limit = max(1, min(int(limit or 40), 100))
    async with db_pool.acquire() as conn:
        if status:
            rows = await conn.fetch(
                """SELECT id, created_at, created_by, slug, title, spec_json,
                          status, pack_name, reject_reason
                     FROM alphaln_pack_drafts
                    WHERE status = $1
                    ORDER BY created_at DESC LIMIT $2""",
                status,
                limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT id, created_at, created_by, slug, title, spec_json,
                          status, pack_name, reject_reason
                     FROM alphaln_pack_drafts
                    ORDER BY created_at DESC LIMIT $1""",
                limit,
            )
    drafts = []
    for r in rows:
        spec = r["spec_json"] or {}
        if isinstance(spec, str):
            try:
                spec = json.loads(spec)
            except Exception:
                spec = {}
        drafts.append(
            {
                "id": int(r["id"]),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "created_by": r["created_by"],
                "slug": r["slug"],
                "title": r["title"],
                "status": r["status"],
                "pack_name": r["pack_name"],
                "reject_reason": r["reject_reason"],
                "rel": spec.get("rel"),
                "looks_needle": spec.get("looks_needle"),
                "broken": spec.get("broken"),
                "fixed": spec.get("fixed"),
                "preview": build_preview(
                    spec,
                    slug=str(r["slug"]),
                    title=str(r["title"]),
                    status=str(r["status"]),
                    pack_name=r["pack_name"],
                ),
            }
        )
    return {"drafts": drafts}


def build_preview(
    spec: Dict[str, Any],
    *,
    slug: str,
    title: str,
    status: str,
    pack_name: Optional[str] = None,
) -> Dict[str, str]:
    """Three-part brief: request, after accept/reject, benefit."""
    rel = str((spec or {}).get("rel") or "broken/task.py")
    needle = str((spec or {}).get("looks_needle") or "").strip()
    name = pack_name or f"{PACK_PREFIX}{slug}"
    request = (
        f"{title}. Incident file {rel}. "
        "LN must change only what makes looks_fixed(run()) true"
        + (f" (fixed-only marker: {needle})." if needle else ".")
    )
    if status == "accepted":
        after = (
            f"Already published as {name} on the writable packs root. "
            "Nightly unused-only drip (after 06:00 UTC, limit 8) may run it "
            "as a coding shadow fork. Accept did not mint fuel rows."
        )
    elif status == "rejected":
        after = "Rejected. No pack file was written. Drip cannot see this spec."
    else:
        after = (
            f"Accept writes unused inventory {name} under "
            "DATA_DIR/ln_sandbox_ci_packs. Reject writes nothing. "
            "Neither mints outcome_envelope. Next drip after 06:00 UTC "
            "can pick unused accepted packs (limit 8)."
        )
    benefit = (
        "Grows PRE6 coding fuel (#15) when drip runs this unique pack. "
        "No replay. Does not close #9 / #16 / R4 or promote AlphaLN."
    )
    return {"request": request, "after": after, "benefit": benefit}


def materialize_aln_pack(root: Path, spec: Dict[str, str]) -> Dict[str, Any]:
    from app.services.ln7_fuel_pack_catalog import _unified

    name = f"{PACK_PREFIX}{spec['slug']}"
    pack = root / name
    broken_dir = pack / "broken"
    tests_dir = pack / "tests"
    broken_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)
    (broken_dir / "__init__.py").write_text(
        '"""Broken on purpose — AlphaLN accepted draft."""\n',
        encoding="utf-8",
    )
    target = Path(spec["rel"])
    (pack / target).parent.mkdir(parents=True, exist_ok=True)
    (pack / target).write_text(spec["broken"], encoding="utf-8")
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    mod = target.stem
    (tests_dir / "test_fix.py").write_text(
        f"from broken.{mod} import run, looks_fixed\n\n\n"
        f"def test_fixed():\n"
        f"    assert looks_fixed(run())\n",
        encoding="utf-8",
    )
    (pack / "golden.patch").write_text(
        _unified(spec["rel"], spec["broken"], spec["fixed"]), encoding="utf-8"
    )
    task = {
        "task_key": f"ci_{name}",
        "title": spec["title"],
        "prompt": spec["prompt"],
        "test_path": "tests/test_fix.py",
        "target_files": [spec["rel"]],
        "domain": "coding",
        "domain_tag": "python",
        "split": "train",
        "provenance": {"kind": "alphaln_draft", "slug": spec["slug"]},
    }
    (pack / "task.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "pack_name": name, "path": str(pack)}


async def review_draft(
    db_pool,
    draft_id: int,
    admin_user: str,
    decision: str,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    if db_pool is None:
        return {"ok": False, "reason": "no_db"}
    if decision not in ("accepted", "rejected"):
        return {"ok": False, "reason": "bad_decision"}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, slug, title, spec_json, status
                 FROM alphaln_pack_drafts WHERE id = $1""",
            int(draft_id),
        )
        if not row:
            return {"ok": False, "reason": "not_found"}
        if row["status"] != "draft":
            return {"ok": False, "reason": "not_draft", "status": row["status"]}
        if decision == "rejected":
            await conn.execute(
                """UPDATE alphaln_pack_drafts
                      SET status = 'rejected', reviewed_by = $2, reviewed_at = NOW(),
                          reject_reason = $3
                    WHERE id = $1""",
                int(draft_id),
                admin_user,
                (note or "rejected")[:400],
            )
            return {"ok": True, "id": int(draft_id), "status": "rejected"}

        spec = row["spec_json"] or {}
        if isinstance(spec, str):
            spec = json.loads(spec)
        reserved = await _reserved(db_pool)
        reserved.discard(str(row["slug"]))
        reserved.discard(f"{PACK_PREFIX}{row['slug']}")
        clean, err = validate_spec(spec, reserved=reserved)
        if not clean:
            return {"ok": False, "reason": f"invalid_spec:{err}"}

        from app.services.ln7_fuel_pack_catalog import _is_repo_tree
        from app.services.ln7_living_packs import packs_root

        root = packs_root()
        allow_repo = os.getenv("LN7_CATALOG_ALLOW_REPO", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if _is_repo_tree(root) and not allow_repo:
            return {
                "ok": False,
                "reason": "repo_tree",
                "detail": "Accept on GREEN (DATA_DIR packs root), not the RO repo tree.",
            }
        wrote = materialize_aln_pack(root, clean)
        await conn.execute(
            """UPDATE alphaln_pack_drafts
                  SET status = 'accepted', reviewed_by = $2, reviewed_at = NOW(),
                      pack_name = $3
                WHERE id = $1""",
            int(draft_id),
            admin_user,
            wrote["pack_name"],
        )
    return {
        "ok": True,
        "id": int(draft_id),
        "status": "accepted",
        "pack_name": wrote["pack_name"],
        "path": wrote["path"],
        "note": "Pack is unused inventory. Nightly drip may pick it up. No burst ran.",
    }
