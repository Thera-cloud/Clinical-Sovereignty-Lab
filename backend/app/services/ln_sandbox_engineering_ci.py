"""LN Sandbox Engineering CI DOJO — disposable pack → patch → pytest.

QUANTUM-CRYSTAL-ARCH

Runs ONLY on copies under /tmp/ln_sandbox_ci/ (or LN_SANDBOX_CI_WORKDIR).
Never mutates GREEN prod tree, vaults, or docker-compose sources.

Flags:
  LN_SANDBOX_ENGINEERING_CI=true  (or ENABLE_ENGINEERING_DOJO=1)
  LN_SANDBOX_CI_USE_GOLDEN=true   — apply golden.patch (offline / smoke)
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("sovereign.ln_sandbox_engineering_ci")

PACKS_REL = Path("data") / "ln_sandbox_ci_packs"
DEFAULT_WORK_ROOT = Path(os.getenv("LN_SANDBOX_CI_WORKDIR", "/tmp/ln_sandbox_ci"))


def ci_mode_on() -> bool:
    for name in ("LN_SANDBOX_ENGINEERING_CI", "ENABLE_ENGINEERING_DOJO"):
        if os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on"):
            return True
    return False


def use_golden() -> bool:
    return os.getenv("LN_SANDBOX_CI_USE_GOLDEN", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _pack_roots() -> List[Path]:
    here = Path(__file__).resolve().parents[1] / PACKS_REL
    docker = Path("/app/app") / PACKS_REL
    return [here, docker]


def packs_dir() -> Optional[Path]:
    for root in _pack_roots():
        idx = root / "packs_index.json"
        if idx.is_file():
            return root
    return None


def list_pack_names() -> List[str]:
    root = packs_dir()
    if not root:
        return []
    try:
        data = json.loads((root / "packs_index.json").read_text(encoding="utf-8"))
        names = list(data.get("packs") or [])
        return [n for n in names if (root / n / "task.json").is_file()]
    except Exception as e:
        logger.warning("ln_sandbox_ci: index load failed: %s", e)
        return []


def load_pack(name: str) -> Optional[Dict[str, Any]]:
    root = packs_dir()
    if not root:
        return None
    pack = root / name
    task_path = pack / "task.json"
    if not task_path.is_file():
        return None
    try:
        task = json.loads(task_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("ln_sandbox_ci: task.json %s: %s", name, e)
        return None
    task["_pack_dir"] = str(pack)
    task["_pack_name"] = name
    return task


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:diff|patch|unified)?\s*\n?", "", t)
        t = re.sub(r"\n?```\s*$", "", t)
    return t.strip()


def _extract_unified_diff(text: str) -> str:
    t = _strip_fences(text)
    m = re.search(r"(?m)^---\s+", t)
    if m:
        t = t[m.start() :]
    return t.strip()


def apply_unified_diff(workdir: Path, diff_text: str) -> Tuple[bool, str]:
    """Minimal unified diff applier (no external patch binary)."""
    diff = _extract_unified_diff(diff_text)
    if not diff or "@@" not in diff:
        return False, "no_unified_diff"
    return _apply_unified_diff_impl(workdir, diff)


def _apply_unified_diff_impl(workdir: Path, diff: str) -> Tuple[bool, str]:
    file_chunks = re.split(r"(?m)(?=^---\s)", diff)
    applied = 0
    notes: List[str] = []

    for chunk in file_chunks:
        chunk = chunk.strip()
        if not chunk.startswith("---"):
            continue
        lines = chunk.splitlines()
        old_spec = lines[0][4:].strip().split("\t")[0]
        new_spec = ""
        body_start = 1
        if len(lines) > 1 and lines[1].startswith("+++"):
            new_spec = lines[1][4:].strip().split("\t")[0]
            body_start = 2
        rel = new_spec or old_spec
        if rel.startswith("a/") or rel.startswith("b/"):
            rel = rel[2:]
        if not rel or rel == "/dev/null":
            notes.append("skip_null")
            continue
        target = (workdir / rel).resolve()
        try:
            target.relative_to(workdir.resolve())
        except ValueError:
            notes.append(f"escape:{rel}")
            continue
        if not target.is_file():
            notes.append(f"missing:{rel}")
            continue

        original = target.read_text(encoding="utf-8").splitlines(keepends=True)
        # Normalize to lines preserving newline style
        src = target.read_text(encoding="utf-8").splitlines()
        out: List[str] = []
        src_i = 0
        ok = True
        i = body_start
        while i < len(lines):
            line = lines[i]
            if line.startswith("@@"):
                m = re.match(
                    r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@",
                    line,
                )
                if not m:
                    ok = False
                    notes.append("bad_hunk_header")
                    break
                old_start = int(m.group(1)) - 1  # 0-based
                # QUANTUM-CRYSTAL-ARCH — fuzzy reposition when model line numbers drift
                peek = i + 1
                anchor = None
                while peek < len(lines) and lines[peek][:1] in (" ", "-", "+"):
                    if lines[peek].startswith("-") or lines[peek].startswith(" "):
                        anchor = lines[peek][1:].rstrip()
                        break
                    peek += 1
                if anchor:
                    window = src[max(0, old_start - 8): min(len(src), old_start + 24)]
                    for off, row in enumerate(window):
                        if row.rstrip() == anchor:
                            old_start = max(0, old_start - 8) + off
                            break
                # copy unchanged prefix
                if old_start < src_i:
                    # allow rewind only within same file when fuzzy moved up
                    if old_start >= 0 and not out:
                        src_i = 0
                        out = []
                    else:
                        ok = False
                        notes.append("hunk_order")
                        break
                out.extend(src[src_i:old_start])
                src_i = old_start
                i += 1
                while i < len(lines) and not lines[i].startswith("@@") and not lines[i].startswith("---"):
                    hl = lines[i]
                    if hl.startswith("\\"):  # "\ No newline at end of file"
                        i += 1
                        continue
                    if not hl:
                        # empty context line rare
                        if src_i >= len(src):
                            ok = False
                            break
                        out.append(src[src_i])
                        src_i += 1
                        i += 1
                        continue
                    tag, payload = hl[0], hl[1:]
                    if tag == " ":
                        if src_i >= len(src) or src[src_i] != payload:
                            # soft match: allow if strip equal
                            if src_i >= len(src) or src[src_i].rstrip() != payload.rstrip():
                                # skip one source line if next matches (model dropped a blank)
                                if (
                                    src_i + 1 < len(src)
                                    and src[src_i + 1].rstrip() == payload.rstrip()
                                ):
                                    out.append(src[src_i])
                                    src_i += 1
                                else:
                                    ok = False
                                    notes.append(f"ctx_mismatch@{src_i+1}")
                                    break
                        out.append(src[src_i])
                        src_i += 1
                    elif tag == "-":
                        if src_i >= len(src) or (
                            src[src_i] != payload
                            and src[src_i].rstrip() != payload.rstrip()
                        ):
                            # search forward a few lines for the delete target
                            found = None
                            for j in range(src_i, min(len(src), src_i + 6)):
                                if src[j] == payload or src[j].rstrip() == payload.rstrip():
                                    found = j
                                    break
                            if found is None:
                                ok = False
                                notes.append(f"del_mismatch@{src_i+1}")
                                break
                            out.extend(src[src_i:found])
                            src_i = found
                        src_i += 1
                    elif tag == "+":
                        out.append(payload)
                    else:
                        # treat as context without tag (some models omit)
                        if src_i < len(src) and (
                            src[src_i] == hl or src[src_i].rstrip() == hl.rstrip()
                        ):
                            out.append(src[src_i])
                            src_i += 1
                        else:
                            ok = False
                            notes.append("unknown_hunk_line")
                            break
                    i += 1
                if not ok:
                    break
                continue
            i += 1

        if not ok:
            continue
        out.extend(src[src_i:])
        # Preserve trailing newline if original had one
        text = "\n".join(out)
        if original and original[-1].endswith("\n"):
            text += "\n"
        target.write_text(text, encoding="utf-8")
        applied += 1
        notes.append(f"ok:{rel}")

    if applied == 0:
        return False, ";".join(notes) or "apply_failed"
    return True, ";".join(notes)


def run_pytest(workdir: Path, test_path: str, timeout_s: float = 30.0) -> Dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(workdir) + os.pathsep + env.get("PYTHONPATH", "")
    # Offline pack tests must not need DB/Redis
    env.setdefault("DATABASE_URL", "")
    env.setdefault("REDIS_URL", "")
    cmd = [
        os.environ.get("LN_SANDBOX_CI_PYTHON", "python3"),
        "-m",
        "pytest",
        test_path,
        "-q",
        "--tb=short",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workdir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return {
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "log": out[-4000:],
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "passed": False, "log": "pytest_timeout"}
    except FileNotFoundError:
        return {"exit_code": -2, "passed": False, "log": "python_or_pytest_missing"}
    except Exception as e:
        return {"exit_code": -3, "passed": False, "log": f"pytest_error:{e}"}


def materialize_pack(pack_name: str, work_root: Optional[Path] = None) -> Tuple[Optional[Path], Optional[Dict[str, Any]], str]:
    task = load_pack(pack_name)
    if not task:
        return None, None, "pack_missing"
    src = Path(task["_pack_dir"])
    root = Path(work_root or DEFAULT_WORK_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    # Safety: refuse if somehow pointed at prod vaults
    resolved = root.resolve()
    forbidden = ("/opt/clinical-sovereignty-lab/data", "/Vaults", "Vaults/Clients")
    for f in forbidden:
        if f in str(resolved):
            return None, None, "forbidden_workdir"
    dest = root / f"{pack_name}_{uuid.uuid4().hex[:10]}"
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dest, task, "ok"


def score_from_pytest(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("passed"):
        return {"passed": True, "score": 1.0, "notes": "pytest_pass"}
    log = result.get("log") or ""
    # Partial credit: collected but failed
    if "failed" in log.lower() or "FAILED" in log:
        return {"passed": False, "score": 0.25, "notes": "pytest_fail"}
    return {"passed": False, "score": 0.1, "notes": "pytest_error"}


async def run_ci_pack_cycle(engine: Any, pack_name: Optional[str] = None) -> Dict[str, Any]:
    """Full CI cycle using LNSandboxEngine helpers for session/corpus."""
    names = list_pack_names()
    if not names:
        return {"ok": False, "error": "no_ci_packs", "mode": "engineering_ci"}
    name = pack_name or random.choice(names)
    workdir, task, mat_note = materialize_pack(name)
    if not workdir or not task:
        return {"ok": False, "error": mat_note or "materialize_failed", "mode": "engineering_ci"}

    session_id = await engine._open_session(
        track="engineering",
        task_key=task.get("task_key") or name,
        trigger_reason="engineering_ci",
        target_user_id=None,
    )
    best_score = 0.0
    passed = False
    last_diff = ""
    last_notes = ""
    last_log = ""
    n = 0
    had_real = False

    try:
        for n in range(1, 3):  # max 2 attempts
            if use_golden() and n == 1:
                golden = workdir / "golden.patch"
                if golden.is_file():
                    last_diff = golden.read_text(encoding="utf-8")
                    had_real = True
                else:
                    last_diff = ""
                    last_notes = "golden_missing"
            else:
                # Build prompt with file contents
                parts = [task.get("prompt") or "Fix the broken pack so pytest passes."]
                for rel in task.get("target_files") or []:
                    fp = workdir / rel
                    if fp.is_file():
                        parts.append(f"\n--- FILE {rel} ---\n{fp.read_text(encoding='utf-8')}")
                if last_log and n > 1:
                    parts.append(
                        f"\nPrior pytest log (fix this):\n{last_log[-1500:]}\n"
                        "Return a corrected unified diff only."
                    )
                prompt = "\n".join(parts)
                text = await engine._generate(prompt, domain=task.get("domain") or "coding")
                if text.startswith("[SANDBOX_FALLBACK]"):
                    last_notes = "fallback_no_diff"
                    await engine._record_attempt(
                        session_id,
                        attempt_n=n,
                        prompt_excerpt=prompt[:500],
                        response_text=text[:2000],
                        score=0.0,
                        passed=False,
                        failure_notes=last_notes,
                        judge_meta={"mode": "engineering_ci", "notes": last_notes},
                    )
                    continue
                had_real = True
                last_diff = _extract_unified_diff(text)

            ok_apply, apply_notes = apply_unified_diff(workdir, last_diff)
            if not ok_apply:
                last_notes = f"apply_fail:{apply_notes}"
                await engine._record_attempt(
                    session_id,
                    attempt_n=n,
                    prompt_excerpt=(task.get("prompt") or "")[:500],
                    response_text=last_diff[:4000],
                    score=0.05,
                    passed=False,
                    failure_notes=last_notes,
                    judge_meta={"mode": "engineering_ci", "apply": apply_notes},
                )
                # Rematerialize clean tree for retry
                shutil.rmtree(workdir, ignore_errors=True)
                workdir, task, _ = materialize_pack(name)
                if not workdir:
                    break
                continue

            py = run_pytest(workdir, task.get("test_path") or "tests")
            last_log = py.get("log") or ""
            judged = score_from_pytest(py)
            best_score = max(best_score, float(judged["score"]))
            last_notes = judged.get("notes") or ""
            await engine._record_attempt(
                session_id,
                attempt_n=n,
                prompt_excerpt=(task.get("prompt") or "")[:500],
                response_text=(last_diff or "")[:4000],
                score=judged["score"],
                passed=bool(judged["passed"]),
                failure_notes=(last_notes + ";" + (last_log[:500] if not judged["passed"] else ""))[:1000],
                judge_meta={
                    "mode": "engineering_ci",
                    "pack": name,
                    "pytest_exit": py.get("exit_code"),
                    "apply": apply_notes,
                },
            )
            if judged["passed"]:
                passed = True
                break
            # Reset pack for next attempt
            shutil.rmtree(workdir, ignore_errors=True)
            workdir, task, _ = materialize_pack(name)
            if not workdir:
                break
    finally:
        try:
            await engine._close_session(
                session_id, attempts=n, best_score=best_score, ok=passed
            )
        except Exception as e:
            logger.warning("ln_sandbox_ci close session: %s", e)
        try:
            if workdir and workdir.exists():
                shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass

    if not had_real and not passed:
        return {
            "ok": True,
            "mode": "engineering_ci",
            "pack": name,
            "session_id": session_id,
            "passed": False,
            "best_score": best_score,
            "corpus_id": None,
            "skipped_corpus": "fallback_only",
        }

    kind = "success_pattern" if passed else "failure_lesson"
    title = task.get("title") if task else name
    body = (
        f"Sandbox engineering CI ({'PASS' if passed else 'FAIL'}, "
        f"score={best_score:.2f}).\n"
        f"Pack: {name}\n"
        f"Diff:\n{(last_diff or '')[:2500]}\n"
        f"Pytest: {last_notes}\n{(last_log or '')[:1200]}"
    )
    corpus_id = await engine._write_corpus(
        track="engineering",
        kind=kind,
        title=f"{'[CI PASS] ' if passed else '[CI LEARN] '}{title}"[:200],
        body=body,
        score=best_score,
        confidence=0.70 if passed else 0.40,
        target_user_id=None,
        session_id=session_id,
        scope="admin_only",
        tags=["engineering", "engineering_ci", kind, task.get("task_key") if task else name],
        metadata={
            "task_key": task.get("task_key") if task else name,
            "pack": name,
            "mode": "engineering_ci",
            "passed": passed,
            "origin_surface_hint": "engineering_dojo",
        },
    )

    if passed and best_score >= 0.85 and corpus_id and had_real:
        try:
            from app.services.ln_sandbox_promotion import enqueue_promotion

            await enqueue_promotion(
                engine.db_pool, corpus_id, requested_by="ln_sandbox_engineering_ci"
            )
        except Exception as e:
            logger.warning("ln_sandbox_ci auto-queue failed: %s", e)

    return {
        "ok": True,
        "mode": "engineering_ci",
        "pack": name,
        "session_id": session_id,
        "passed": passed,
        "best_score": best_score,
        "corpus_id": corpus_id,
        "task_key": task.get("task_key") if task else name,
    }
