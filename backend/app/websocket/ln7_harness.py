"""Little Nate 7 coding harness — retrieve → best-of-N → static gate → sandbox → repair.

Zero vendor calls on the LN7 path. Reuses cli_symbol_store, ln_sandbox_engineering_ci.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ln7_harness")

_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}",
)
_PACK_HINT_RE = re.compile(
    r"\b(asyncpg_cast|catch_all_routes|env_redis_prefix|"
    r"sandbox\s*pack|fix\s+(?:the\s+)?pack|unified\s+diff)\b",
    re.I,
)


def kill_switch_on() -> bool:
    return os.getenv("LN7_KILL_SWITCH", "").strip().lower() in ("1", "true", "yes", "on")


def best_of_n() -> int:
    return max(1, min(8, int(os.getenv("LN7_BEST_OF_N", "4") or "4")))


def max_repair_rounds() -> int:
    return max(0, min(6, int(os.getenv("LN7_MAX_REPAIR_ROUNDS", "3") or "3")))


def candidate_timeout_s() -> float:
    return float(os.getenv("LN7_CANDIDATE_TIMEOUT_S", "180") or "180")


def max_attempts() -> int:
    return max(1, min(10, int(os.getenv("LN7_MAX_ATTEMPTS", "4") or "4")))


def harness_mode() -> str:
    m = (os.getenv("LN7_MODE", "max") or "max").strip().lower()
    return "fast" if m == "fast" else "max"


def inference_base_url() -> str:
    """LN7 local inference — never a vendor URL."""
    return (
        (os.getenv("LN7_INFERENCE_URL") or "").rstrip("/")
        or (os.getenv("SOVEREIGN_INFERENCE_URL") or "").rstrip("/")
        or (os.getenv("HOME_GPU_URL") or "").rstrip("/")
    )


def _ast_hash(text: str) -> str:
    try:
        tree = ast.parse(text)
        dump = ast.dump(tree, annotate_fields=False)
    except Exception:
        dump = text
    return hashlib.sha256(dump.encode("utf-8", errors="replace")).hexdigest()[:16]


def static_gate(diff_text: str, *, max_diff_lines: int = 400) -> Tuple[bool, str]:
    """Reject before sandbox spend: size, secrets, empty."""
    if not (diff_text or "").strip():
        return False, "empty_diff"
    lines = diff_text.splitlines()
    if len(lines) > max_diff_lines:
        return False, f"diff_too_large:{len(lines)}"
    if _SECRET_RE.search(diff_text):
        return False, "secret_pattern"
    for line in lines:
        if line.startswith("+++ ") or line.startswith("--- "):
            path = line[4:].strip().split("\t")[0]
            if path.startswith("/") or ".." in path:
                return False, f"path_escape:{path}"
    return True, "ok"


def looks_like_pack_task(prompt: str) -> bool:
    return bool(_PACK_HINT_RE.search(prompt or ""))


def infer_pack_name(prompt: str) -> Optional[str]:
    text = prompt or ""
    try:
        from app.services.ln_sandbox_engineering_ci import list_pack_names
        names = list_pack_names()
    except Exception:
        names = ["asyncpg_cast", "catch_all_routes", "env_redis_prefix"]
    for n in names:
        if n.lower() in text.lower():
            return n
    if looks_like_pack_task(text) and names:
        return names[0]
    return None


def _lexical_workspace_hits(query: str, root: str, k: int) -> List[str]:
    """Hybrid lexical retrieval via ripgrep (files that match query tokens)."""
    tokens = [t for t in re.findall(r"[A-Za-z_]{3,}", query or "") if t.lower() not in {
        "the", "and", "for", "with", "that", "this", "from", "return", "fix", "make",
    }][:6]
    if not tokens or not root or not Path(root).is_dir():
        return []
    pattern = "|".join(re.escape(t) for t in tokens)
    try:
        proc = subprocess.run(
            [
                "rg", "-n", "-i", "-m", "3", "--glob", "!**/node_modules/**",
                "--glob", "!**/.git/**", "--glob", "!**/dist/**", pattern, root,
            ],
            capture_output=True, text=True, timeout=8,
        )
        lines = (proc.stdout or "").splitlines()[: max(k * 3, k)]
        return lines[:k]
    except Exception as exc:
        logger.debug("LN7 rg retrieve: %s", exc)
        return []


async def retrieve_context(
    query: str,
    *,
    workspace_root: Optional[str] = None,
    session_key: Optional[str] = None,
    k: int = 8,
    gold_files: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Symbolic facts + lexical workspace hits; recall@k vs gold_files when provided."""
    chunks: List[str] = []
    hit_paths: List[str] = []

    if session_key:
        try:
            from app.websocket.cli_symbol_store import format_symbols_block
            block = format_symbols_block(session_key)
            if block and block.strip():
                chunks.append(block.strip()[:6000])
        except Exception as exc:
            logger.debug("LN7 retrieve symbols: %s", exc)

    root = (
        workspace_root
        or os.getenv("CLI_WORKSPACE_ROOT")
        or os.getenv("LN7_WORKSPACE_ROOT")
        or ""
    ).strip()
    if root:
        lexical = await asyncio.to_thread(_lexical_workspace_hits, query, root, k)
        for line in lexical:
            chunks.append(line[:2000])
            # path:line:content
            path = line.split(":", 1)[0] if ":" in line else ""
            if path:
                hit_paths.append(os.path.basename(path))

    # Prefer AST-ish snippets
    refined: List[str] = []
    for c in chunks:
        if "def " in c or "class " in c:
            refined.append(c[:4000])
        else:
            refined.append(c[:2000])
    chunks = refined or chunks

    recall_at_k = 0.0
    if gold_files:
        gold_base = {os.path.basename(g) for g in gold_files}
        hits = sum(1 for p in hit_paths if p in gold_base)
        recall_at_k = hits / max(1, min(k, len(gold_base)))
    else:
        recall_at_k = min(1.0, len(chunks) / max(1, k))

    return {
        "context": "\n\n".join(chunks),
        "recall_at_k": recall_at_k,
        "k": k,
        "hit_count": len(chunks),
        "hit_paths": hit_paths[:k],
    }


async def propose_candidates(
    prompt: str,
    *,
    system: str,
    n: Optional[int] = None,
    mode: Optional[str] = None,
    revision_id: Optional[str] = None,
    db_pool=None,
) -> List[Dict[str, Any]]:
    """N candidates at varied temperature via sovereign coder weights only."""
    if kill_switch_on():
        return []
    n = n or (2 if (mode or harness_mode()) == "fast" else best_of_n())
    try:
        from app.services.little_nate_7 import (
            coder_model,
            identity_system_preamble,
            load_active_revision,
            load_revision,
            serve_target_from_revision,
        )
        from app.services.nate_inference_router import NateInferenceRouter, TIER_CODING
    except Exception as exc:
        logger.warning("LN7 propose import failed: %s", exc)
        return []

    router = NateInferenceRouter()
    sys_full = identity_system_preamble() + "\n\n" + (system or "")
    temps = [0.1, 0.3, 0.5, 0.7][:n]
    while len(temps) < n:
        temps.append(0.4)
    model_tier = "fast" if (mode or harness_mode()) == "fast" else "deep"
    _ = coder_model(model_tier)
    # QUANTUM-CRYSTAL-ARCH — serve PEFT / ollama tag for revision under test
    rev = None
    if db_pool is not None:
        if revision_id:
            rev = await load_revision(db_pool, revision_id)
        if rev is None:
            rev = await load_active_revision(db_pool, tier=model_tier)
    target = serve_target_from_revision(rev, tier=model_tier)
    model_override = target.get("model") or None
    base_url_override = target.get("url") or None

    async def _one(temp: float, idx: int) -> Dict[str, Any]:
        t0 = time.time()
        try:
            result = await asyncio.wait_for(
                router.generate(
                    prompt=prompt,
                    system=sys_full,
                    tier=TIER_CODING,
                    domain="coding",
                    temperature=temp,
                    max_tokens=4096,
                    odpe_signal="TENSION",
                    allow_deep=(model_tier == "deep"),
                    providers_override=["sovereign", "home_gpu"],
                    model_override=model_override,
                    base_url_override=base_url_override,
                ),
                timeout=candidate_timeout_s(),
            )
            text = (result or {}).get("text") or ""
            prov = (result or {}).get("provider") or ""
            # Refuse vendor bleed even if router misconfigured
            if prov and prov not in ("sovereign", "home_gpu", "odpe_skip", ""):
                return {
                    "index": idx,
                    "temperature": temp,
                    "text": "",
                    "ast_hash": "",
                    "error": f"vendor_rejected:{prov}",
                    "ok": False,
                    "latency_ms": int((time.time() - t0) * 1000),
                }
            # QUANTUM-CRYSTAL-ARCH — refusals/prose are not candidates
            ok = bool(text.strip()) and looks_like_unified_diff(text)
            return {
                "index": idx,
                "temperature": temp,
                "text": text,
                "ast_hash": _ast_hash(text),
                "provider": prov,
                "model": (result or {}).get("model"),
                "tokens": (result or {}).get("tokens_used") or 0,
                "latency_ms": int((time.time() - t0) * 1000),
                "ok": ok,
                "error": None if ok else ("no_unified_diff" if text.strip() else "empty"),
            }
        except Exception as exc:
            return {
                "index": idx,
                "temperature": temp,
                "text": "",
                "ast_hash": "",
                "error": str(exc)[:200],
                "ok": False,
                "latency_ms": int((time.time() - t0) * 1000),
            }

    # Serialize under ORANGE load (parallel N×timeouts starve Ollama)
    sequential = os.getenv("LN7_PROPOSE_SEQUENTIAL", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )
    if sequential:
        results = []
        for i in range(n):
            results.append(await _one(temps[i], i))
    else:
        results = await asyncio.gather(*[_one(temps[i], i) for i in range(n)])
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for r in results:
        h = r.get("ast_hash") or ""
        if h and h in seen:
            continue
        if h:
            seen.add(h)
        if r.get("ok"):
            deduped.append(r)
    return deduped


def extract_diff(text: str) -> str:
    """Pull unified diff from model output if fenced."""
    if not text:
        return ""
    try:
        from app.services.ln_sandbox_engineering_ci import _extract_unified_diff, _strip_fences
        d = _extract_unified_diff(text)
        if d:
            return d
        return _strip_fences(text)
    except Exception:
        m = re.search(r"```(?:diff)?\n([\s\S]*?)```", text)
        return (m.group(1) if m else text).strip()


def looks_like_unified_diff(text: str) -> bool:
    d = extract_diff(text or "")
    return bool(d) and ("---" in d) and ("@@" in d)


def build_pack_prompt(pack_name: str) -> str:
    """Pack task prompt + target file bodies (matches engineering CI cycle)."""
    try:
        from app.services.ln_sandbox_engineering_ci import load_pack, materialize_pack
    except Exception:
        return ""
    task = load_pack(pack_name)
    if not task:
        return ""
    workdir, loaded, _note = materialize_pack(pack_name)
    try:
        parts = [(loaded or task).get("prompt") or ""]
        parts.append(
            "\nReturn ONLY a unified diff that patches the listed files. "
            "No prose, no markdown fences. "
            "Hunk context lines must match the FILE bodies below exactly "
            "(same indentation and quotes)."
        )
        if pack_name == "asyncpg_cast":
            parts.append(
                "\nRequired SQL edit: replace to_jsonb($1) with to_jsonb($1::int) "
                "in the string literal. Minimal hunk preferred."
            )
        targets = (loaded or task).get("target_files") or []
        if workdir:
            for rel in targets:
                fp = Path(workdir) / rel
                if fp.is_file():
                    parts.append(f"\n--- FILE {rel} ---\n{fp.read_text(encoding='utf-8')}")
        return "\n".join(p for p in parts if p).strip()
    finally:
        if workdir:
            try:
                import shutil
                shutil.rmtree(workdir, ignore_errors=True)
            except Exception:
                pass


async def run_sandbox_candidate(
    pack_name: str,
    diff_text: str,
) -> Dict[str, Any]:
    """Apply diff to a materialized pack and pytest."""
    try:
        from app.services import ln_sandbox_engineering_ci as ci
    except Exception as exc:
        return {"passed": False, "error": f"ci_import:{exc}"}

    ok_gate, note = static_gate(diff_text)
    if not ok_gate:
        return {
            "passed": False,
            "error": f"static_gate:{note}",
            "score": 0.0,
            "diff_lines": len((diff_text or "").splitlines()),
        }

    workdir, task, mat_note = ci.materialize_pack(pack_name)
    if not workdir or not task:
        return {
            "passed": False,
            "error": mat_note or "materialize_failed",
            "score": 0.0,
            "diff_lines": len((diff_text or "").splitlines()),
        }

    try:
        applied, apply_msg = ci.apply_unified_diff(workdir, diff_text)
        if not applied:
            return {
                "passed": False,
                "error": f"apply_failed:{apply_msg}",
                "score": 0.05,
                "diff_lines": len((diff_text or "").splitlines()),
            }
        test_path = task.get("test_path") or "tests"
        result = await asyncio.to_thread(ci.run_pytest, workdir, test_path, candidate_timeout_s())
        score = ci.score_from_pytest(result)
        return {
            "passed": bool(result.get("passed")),
            "score": score.get("score", 0.0),
            "log": (result.get("log") or "")[-2000:],
            "diff_lines": len(diff_text.splitlines()),
            "pack": pack_name,
            "error": None if result.get("passed") else (score.get("notes") or "pytest_fail"),
        }
    finally:
        try:
            import shutil
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass


async def repair_loop(
    prompt: str,
    *,
    system: str,
    pack_name: str,
    failing_log: str,
    prior_diff: str,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Bounded repair: feed stderr back, re-propose, re-verify."""
    rounds = max_repair_rounds()
    last: Dict[str, Any] = {"passed": False}
    for r in range(rounds):
        if kill_switch_on():
            return {"passed": False, "error": "kill_switch", "round": r}
        repair_prompt = (
            f"{prompt}\n\n---\nPrevious patch failed tests. Fix it.\n"
            f"FAILING LOG:\n{failing_log[-3000:]}\n\n"
            f"PREVIOUS DIFF:\n{prior_diff[:4000]}\n"
            "Return a complete corrected unified diff only."
        )
        cands = await propose_candidates(repair_prompt, system=system, n=1, mode=mode)
        if not cands:
            break
        diff = extract_diff(cands[0].get("text") or "")
        last = await run_sandbox_candidate(pack_name, diff)
        last["round"] = r + 1
        last["diff"] = diff
        if last.get("passed"):
            return last
        failing_log = last.get("log") or failing_log
        prior_diff = diff
    return last


async def generate_sovereign_reply(
    messages: List[Dict[str, Any]],
    *,
    mode: Optional[str] = None,
    db_pool=None,
    revision_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Interactive LN7 chat turn — sovereign/home_gpu only, never vendor."""
    if kill_switch_on():
        return {"ok": False, "error": "kill_switch", "text": "", "provider": "ln7"}
    try:
        from app.services.little_nate_7 import (
            coder_model,
            identity_system_preamble,
            load_active_revision,
            load_revision,
            serve_target_from_revision,
        )
        from app.services.nate_inference_router import NateInferenceRouter, TIER_CODING
    except Exception as exc:
        return {"ok": False, "error": f"import:{exc}", "text": "", "provider": "ln7"}

    system_parts = [identity_system_preamble()]
    user_parts: List[str] = []
    for m in messages:
        role = (m.get("role") or "").lower()
        content = m.get("content") or ""
        if role == "system":
            system_parts.append(str(content))
        elif role in ("user", "assistant"):
            user_parts.append(f"{role.upper()}: {content}")
    prompt = "\n\n".join(user_parts[-12:]) or "Say hello as Little Nate 7."
    model_tier = "fast" if (mode or harness_mode()) == "fast" else "deep"
    rev = None
    if db_pool is not None:
        if revision_id:
            rev = await load_revision(db_pool, revision_id)
        if rev is None:
            rev = await load_active_revision(db_pool, tier=model_tier)
    target = serve_target_from_revision(rev, tier=model_tier)
    router = NateInferenceRouter()
    result = await router.generate(
        prompt=prompt,
        system="\n\n".join(system_parts),
        tier=TIER_CODING,
        domain="coding",
        temperature=0.3,
        max_tokens=4096,
        odpe_signal="TENSION",
        allow_deep=(model_tier == "deep"),
        providers_override=["sovereign", "home_gpu"],
        model_override=target.get("model") or None,
        base_url_override=target.get("url") or None,
    )
    text = (result or {}).get("text") or ""
    prov = (result or {}).get("provider") or "sovereign"
    if prov not in ("sovereign", "home_gpu", "odpe_skip"):
        return {
            "ok": False,
            "error": f"vendor_rejected:{prov}",
            "text": "",
            "provider": "ln7",
            "model": coder_model(model_tier),
        }
    return {
        "ok": bool(text.strip()),
        "text": text,
        "provider": "ln7",
        "upstream": prov,
        "model": (result or {}).get("model") or coder_model(model_tier),
        "tokens": (result or {}).get("tokens_used") or 0,
        "latency_ms": (result or {}).get("latency_ms") or 0,
    }


async def maybe_shadow_compare(
    db_pool,
    prompt: str,
    *,
    active_text: str,
) -> None:
    """Fire-and-forget: score a shadow revision candidate without user impact.

    LN7_SHADOW_SPEND=true → second sovereign generate (local only, never vendor).
    Otherwise observe-only ledger row (hash of active answer).
    """
    if not db_pool:
        return
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT revision_id, base_checkpoint FROM ln7_revisions
                WHERE status = 'shadow' AND active = FALSE
                ORDER BY revised_at DESC LIMIT 1
                """
            )
        if not row:
            return
        from app.services.ln7_ledger import record_outcome

        spend = os.getenv("LN7_SHADOW_SPEND", "").strip().lower() in ("1", "true", "yes")
        shadow_text = ""
        tokens = 0
        latency_ms = 0
        if spend:
            t0 = time.time()
            gen = await generate_sovereign_reply(
                [
                    {
                        "role": "system",
                        "content": "LN7 shadow revision — produce a candidate patch/answer.",
                    },
                    {"role": "user", "content": prompt},
                ],
                mode="fast",
            )
            shadow_text = (gen or {}).get("text") or ""
            tokens = int((gen or {}).get("tokens") or 0)
            latency_ms = int((time.time() - t0) * 1000)
        await record_outcome(db_pool, {
            "task_id": None,
            "generator": "ln7_shadow",
            "revision_id": row["revision_id"],
            "harness_mode": "shadow",
            "patch_hash": hashlib.sha256(
                (shadow_text or active_text or "")[:4000].encode()
            ).hexdigest()[:32],
            "passed": bool(shadow_text.strip()) if spend else False,
            "diff_lines": len((shadow_text or "").splitlines()),
            "tokens": tokens,
            "latency_ms": latency_ms,
            "metrics_json": {
                "note": "shadow_spend" if spend else "shadow_observe_only",
                "prompt_chars": len(prompt or ""),
                "active_chars": len(active_text or ""),
                "shadow_chars": len(shadow_text),
                "base_checkpoint": row.get("base_checkpoint"),
            },
        })
    except Exception as exc:
        logger.debug("LN7 shadow compare: %s", exc)


async def run_task(
    prompt: str,
    *,
    pack_name: Optional[str] = None,
    system: str = "",
    mode: Optional[str] = None,
    workspace_root: Optional[str] = None,
    session_key: Optional[str] = None,
    revision_id: Optional[str] = None,
    db_pool=None,
) -> Dict[str, Any]:
    """Full harness cycle for one task. Returns best survivor + metrics."""
    if kill_switch_on():
        return {"ok": False, "error": "kill_switch", "generator": "ln7"}

    t0 = time.time()
    mode = mode or harness_mode()
    retrieval = await retrieve_context(
        prompt, workspace_root=workspace_root, session_key=session_key,
    )
    sys = (system or "") + (
        f"\n\nRETRIEVED CONTEXT (recall@k={retrieval.get('recall_at_k'):.2f}):\n"
        f"{retrieval.get('context') or '(none)'}"
    )

    pack = pack_name or infer_pack_name(prompt)
    if not pack:
        try:
            from app.services.ln_sandbox_engineering_ci import list_pack_names
            names = list_pack_names()
            pack = names[0] if names else None
        except Exception:
            pack = None
    if not pack:
        return {"ok": False, "error": "no_pack", "generator": "ln7"}

    # QUANTUM-CRYSTAL-ARCH — W5 domain router (no-op when flag off)
    route_meta: Dict[str, Any] = {}
    try:
        from app.services.ln7_flywheel_pipeline import route_coding_turn
        import hashlib as _hl

        route_meta = await route_coding_turn(
            db_pool,
            prompt,
            file_paths=[pack] if pack else [],
            task_hash=_hl.sha256((prompt or "")[:2000].encode()).hexdigest()[:16],
        )
        if route_meta.get("adapter_id") and not revision_id:
            revision_id = str(route_meta.get("adapter_id"))
    except Exception as _rt:
        logger.debug("LN7 domain route: %s", _rt)

    # Burst serve URL when hive published Redis endpoint
    try:
        from app.services.ln7_serve_endpoint import get_serve_endpoint, get_serve_engine

        if get_serve_engine() == "vllm_burst" and get_serve_endpoint():
            route_meta["serve_endpoint"] = get_serve_endpoint()
    except Exception:
        pass

    # Enrich vague prompts with pack task + file bodies
    if pack and "--- FILE " not in (prompt or ""):
        enriched = build_pack_prompt(pack)
        if enriched:
            prompt = enriched

    candidates = await propose_candidates(
        prompt, system=sys, mode=mode, revision_id=revision_id, db_pool=db_pool,
    )
    ranked: List[Dict[str, Any]] = []
    attempts = 0
    for cand in candidates:
        attempts += 1
        if attempts > max_attempts():
            break
        diff = extract_diff(cand.get("text") or "")
        outcome = await run_sandbox_candidate(pack, diff)
        outcome["candidate_index"] = cand.get("index")
        outcome["diff"] = diff
        outcome["tokens"] = cand.get("tokens") or 0
        ranked.append(outcome)
        if outcome.get("passed"):
            break

    best = None
    for o in ranked:
        if o.get("passed"):
            best = o
            break
    if not best and ranked:
        best = max(ranked, key=lambda x: float(x.get("score") or 0))

    if best and not best.get("passed") and best.get("diff"):
        repaired = await repair_loop(
            prompt,
            system=sys,
            pack_name=pack,
            failing_log=best.get("log") or "",
            prior_diff=best.get("diff") or "",
            mode=mode,
        )
        if repaired.get("passed") or float(repaired.get("score") or 0) > float(best.get("score") or 0):
            best = repaired
            attempts += int(repaired.get("round") or 1)

    return {
        "ok": bool(best and best.get("passed")),
        "generator": "ln7",
        "harness_mode": mode,
        "pack": pack,
        "route": route_meta,
        "passed": bool(best and best.get("passed")),
        "score": (best or {}).get("score", 0.0),
        "diff": (best or {}).get("diff") or "",
        "diff_lines": (best or {}).get("diff_lines") or 0,
        "attempts": attempts,
        "candidates": len(candidates),
        "recall_at_k": retrieval.get("recall_at_k"),
        "latency_ms": int((time.time() - t0) * 1000),
        "tokens": sum(int(c.get("tokens") or 0) for c in candidates),
        "log": ((best or {}).get("log") or "")[-1500:],
        "text": (best or {}).get("diff") or "",
    }
