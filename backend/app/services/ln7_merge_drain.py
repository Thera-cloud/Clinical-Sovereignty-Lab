"""Stage 4 dare_ties merge drain with abort gate (Phase C).

Abort = authority: beat LN7-fast-baseline AND every contributor on held-out.

No `target_model:`; do not relist base under `models:`; pin mergekit;
materialize PEFT -> HF; >=120 GB free; prefer L40S; ~15 GB WG to ORANGE.
On accept: GGUF for ORANGE Ollama; prune micros only after pass.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_merge_drain")

REPO_ROOT = Path(__file__).resolve().parents[3]

PINNED_MERGEKIT = "mergekit==0.0.5.1"  # pin; update only via weld
MIN_FREE_GB = 120.0
BASE_MODEL = "Qwen/Qwen2.5-Coder-7B-Instruct"


async def abort_gate(
    db_pool,
    *,
    merge_revision_id: str,
    contributor_ids: List[str],
    incumbent_id: str = "LN7-fast-baseline",
) -> Dict[str, Any]:
    """Return accept=True only if merge beats incumbent and all contributors."""
    if not db_pool:
        return {"accept": False, "reason": "no_db"}

    async def heldout_rate(rev: str) -> Optional[float]:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)::float AS n,
                    SUM(CASE WHEN o.passed THEN 1 ELSE 0 END)::float AS wins
                FROM ln7_coding_outcomes o
                JOIN ln7_tasks t ON t.task_id = o.task_id
                WHERE o.revision_id = $1 AND t.split = 'heldout'
                """,
                rev,
            )
        if not row or float(row["n"] or 0) < 1:
            return None
        return float(row["wins"] or 0) / float(row["n"])

    merge_rate = await heldout_rate(merge_revision_id)
    if merge_rate is None:
        return {"accept": False, "reason": "merge_no_heldout"}

    inc_rate = await heldout_rate(incumbent_id)
    if inc_rate is not None and merge_rate <= inc_rate:
        return {
            "accept": False,
            "reason": "below_incumbent",
            "merge_rate": merge_rate,
            "incumbent_rate": inc_rate,
        }

    for cid in contributor_ids:
        cr = await heldout_rate(cid)
        if cr is not None and merge_rate <= cr:
            return {
                "accept": False,
                "reason": "below_contributor",
                "contributor": cid,
                "merge_rate": merge_rate,
                "contributor_rate": cr,
            }

    return {
        "accept": True,
        "merge_rate": merge_rate,
        "incumbent_rate": inc_rate,
        "mergekit_pin": PINNED_MERGEKIT,
    }


def mergekit_yaml_dare_ties(
    contributors: List[Dict[str, Any]],
    *,
    density: float = 0.6,
) -> str:
    """Build dare_ties YAML. No target_model; do not relist base under models."""
    lines = [
        "merge_method: dare_ties",
        "base_model: Qwen/Qwen2.5-Coder-7B-Instruct",
        "parameters:",
        f"  density: {density}",
        "  weight: 1.0",
        "dtype: bfloat16",
        "models:",
    ]
    for c in contributors:
        path = c.get("path") or c.get("adapter_uri") or ""
        w = float(c.get("weight", 1.0))
        lines.append(f"  - model: {path}")
        lines.append("    parameters:")
        lines.append(f"      weight: {w}")
        lines.append(f"      density: {density}")
    return "\n".join(lines) + "\n"


def check_disk_space(path: Optional[str] = None, *, min_gb: float = MIN_FREE_GB) -> Dict[str, Any]:
    """Preflight: >=120 GB free before merge (mergekit + PEFT-to-HF materialize)."""
    target = Path(path or os.getenv("LN7_MERGE_WORKDIR", str(REPO_ROOT / ".ln7-merge")))
    try:
        target.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(str(target))
        free_gb = usage.free / (1024 ** 3)
        return {"ok": free_gb >= min_gb, "free_gb": round(free_gb, 1), "min_gb": min_gb, "path": str(target)}
    except Exception as e:
        return {"ok": False, "error": str(e), "path": str(target)}


def _merge_workdir(merge_revision_id: str) -> Path:
    root = Path(os.getenv("LN7_MERGE_WORKDIR", str(REPO_ROOT / ".ln7-merge")))
    return root / merge_revision_id


def materialize_peft_to_hf(
    adapter_dir: str,
    out_dir: str,
    *,
    base_model: str = BASE_MODEL,
    dry_run: bool = True,
    timeout_s: int = 1800,
) -> Dict[str, Any]:
    """Merge a PEFT/LoRA adapter into a full HuggingFace checkpoint (merge_and_unload).

    Runs an inline python -c snippet so no extra script file is needed on disk.
    Gated by dry_run — caller decides based on GPU/toolchain availability.
    """
    script = (
        "import sys\n"
        "from peft import PeftModel\n"
        "from transformers import AutoModelForCausalLM, AutoTokenizer\n"
        "base_id, adapter_dir, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]\n"
        "base = AutoModelForCausalLM.from_pretrained(base_id, torch_dtype='auto')\n"
        "tok = AutoTokenizer.from_pretrained(base_id)\n"
        "merged = PeftModel.from_pretrained(base, adapter_dir).merge_and_unload()\n"
        "merged.save_pretrained(out_dir)\n"
        "tok.save_pretrained(out_dir)\n"
    )
    cmd = ["python3", "-c", script, base_model, adapter_dir, out_dir]
    if dry_run:
        return {"ok": True, "dry_run": True, "cmd": cmd, "out_dir": out_dir}
    try:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout_s
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
            "out_dir": out_dir,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "out_dir": out_dir}


def run_mergekit(
    yaml_text: str,
    out_dir: str,
    *,
    dry_run: bool = True,
    timeout_s: int = 3600,
) -> Dict[str, Any]:
    """Write dare_ties config and invoke `mergekit-yaml`. Pinned via PINNED_MERGEKIT."""
    workdir = Path(out_dir).parent
    workdir.mkdir(parents=True, exist_ok=True)
    yaml_path = workdir / "mergekit.yaml"
    try:
        yaml_path.write_text(yaml_text, encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"yaml_write_failed: {e}"}
    cmd = ["mergekit-yaml", str(yaml_path), out_dir, "--out-shard-size", "5B", "--lazy-unpickle"]
    if dry_run:
        return {"ok": True, "dry_run": True, "cmd": cmd, "yaml_path": str(yaml_path), "out_dir": out_dir}
    try:
        proc = subprocess.run(
            cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout_s
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
            "yaml_path": str(yaml_path),
            "out_dir": out_dir,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "yaml_path": str(yaml_path), "out_dir": out_dir}


def convert_to_gguf(
    hf_dir: str,
    out_gguf: str,
    *,
    quantization: str = "q5_K_M",
    dry_run: bool = True,
    timeout_s: int = 3600,
) -> Dict[str, Any]:
    """Convert merged HF checkpoint to GGUF for ORANGE Ollama (llama.cpp toolchain)."""
    llamacpp = os.getenv("LN7_LLAMACPP_DIR", str(REPO_ROOT.parent / "llama.cpp"))
    convert_py = str(Path(llamacpp) / "convert_hf_to_gguf.py")
    quantize_bin = str(Path(llamacpp) / "llama-quantize")
    fp16_out = str(Path(out_gguf).with_suffix(".fp16.gguf"))
    convert_cmd = ["python3", convert_py, hf_dir, "--outfile", fp16_out, "--outtype", "f16"]
    quantize_cmd = [quantize_bin, fp16_out, out_gguf, quantization]
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "convert_cmd": convert_cmd,
            "quantize_cmd": quantize_cmd,
            "out_gguf": out_gguf,
        }
    try:
        Path(out_gguf).parent.mkdir(parents=True, exist_ok=True)
        p1 = subprocess.run(convert_cmd, capture_output=True, text=True, timeout=timeout_s)
        if p1.returncode != 0:
            return {
                "ok": False, "stage": "convert", "returncode": p1.returncode,
                "stderr_tail": (p1.stderr or "")[-2000:],
            }
        p2 = subprocess.run(quantize_cmd, capture_output=True, text=True, timeout=timeout_s)
        return {
            "ok": p2.returncode == 0,
            "returncode": p2.returncode,
            "stderr_tail": (p2.stderr or "")[-2000:],
            "out_gguf": out_gguf,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "out_gguf": out_gguf}


def transfer_gguf_to_orange(
    local_gguf: str,
    revision_id: str,
    *,
    dry_run: bool = True,
    timeout_s: int = 1800,
) -> Dict[str, Any]:
    """~15 GB WG transfer BLUE/GREEN -> ORANGE for Ollama import (ProxyJump pattern)."""
    green = os.getenv("LN7_GREEN_HOST", "root@68.183.168.75")
    orange_ip = os.getenv("LN7_ORANGE_WG", "10.13.13.5")
    remote_dir = f"/opt/ln7/gguf/{revision_id}"
    remote_path = f"root@{orange_ip}:{remote_dir}/"
    ssh_opts = [
        "-o", "BatchMode=yes", "-o", f"ProxyJump={green}",
        "-o", "ConnectTimeout=30", "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=4",
    ]
    mkdir_cmd = ["ssh", *ssh_opts, f"root@{orange_ip}", f"mkdir -p {remote_dir}"]
    scp_cmd = ["scp", *ssh_opts, local_gguf, remote_path]
    if dry_run:
        return {"ok": True, "dry_run": True, "mkdir_cmd": mkdir_cmd, "scp_cmd": scp_cmd, "remote_path": remote_path}
    try:
        p0 = subprocess.run(mkdir_cmd, capture_output=True, text=True, timeout=60)
        if p0.returncode != 0:
            return {"ok": False, "stage": "mkdir", "stderr_tail": (p0.stderr or "")[-1000:]}
        p1 = subprocess.run(scp_cmd, capture_output=True, text=True, timeout=timeout_s)
        return {
            "ok": p1.returncode == 0,
            "returncode": p1.returncode,
            "stderr_tail": (p1.stderr or "")[-1000:],
            "remote_path": remote_path,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "remote_path": remote_path}


async def _fetch_contributor_rows(db_pool, contributor_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch adapter_uri/domain_tag/status for each contributor revision_id."""
    out: Dict[str, Dict[str, Any]] = {}
    if not db_pool or not contributor_ids:
        return out
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT revision_id, adapter_uri, domain_tag, status
            FROM ln7_revisions
            WHERE revision_id = ANY($1::text[])
            """,
            contributor_ids,
        )
    for r in rows:
        out[r["revision_id"]] = dict(r)
    return out


async def prune_micro_experts(
    db_pool,
    contributor_ids: List[str],
    *,
    merge_revision_id: str,
) -> Dict[str, Any]:
    """Mark superseded micro-experts pruned only after the merge passes abort_gate."""
    if not db_pool:
        return {"ok": False, "reason": "no_db", "pruned": []}
    pruned: List[str] = []
    async with db_pool.acquire() as conn:
        for cid in contributor_ids:
            try:
                await conn.execute(
                    """
                    UPDATE ln7_revisions
                    SET status = 'pruned', active = FALSE,
                        harness_config_json = COALESCE(harness_config_json, '{}'::jsonb)
                            || jsonb_build_object('pruned_into', $2::text)
                    WHERE revision_id = $1
                    """,
                    cid,
                    merge_revision_id,
                )
                pruned.append(cid)
            except Exception as e:
                logger.warning("prune_micro_experts: %s failed: %s", cid, e)
    return {"ok": True, "pruned": pruned}


async def run_merge_drain(
    db_pool=None,
    *,
    contributor_ids: Optional[List[str]] = None,
    incumbent_id: str = "LN7-fast-baseline",
    density: float = 0.6,
    dry_run: bool = True,
    notes: str = "",
) -> Dict[str, Any]:
    """Orchestrate Stage 4 dare_ties consolidation: materialize -> merge -> abort_gate ->
    (accept: GGUF + WG transfer + prune micros) | (reject: mark rejected, no prune).

    Mirrors run_hive_burst()'s lease/watchdog/outcome_envelope pattern (W3/Phase A).
    """
    from app.services.flywheel_anomaly import notify_flywheel_anomaly
    from app.services.ln7_change_lease import acquire_lease, release_lease
    from app.services.ln7_revision import register_revision

    contributor_ids = list(contributor_ids or [])
    if len(contributor_ids) < 2:
        return {"ok": False, "error": "need_at_least_2_contributors", "contributor_ids": contributor_ids}

    disk = check_disk_space()
    if not dry_run and not disk.get("ok"):
        await notify_flywheel_anomaly("merge_disk_low", {"disk": disk}, db_pool=db_pool)
        return {"ok": False, "error": "disk_space_low", "disk": disk}

    lease = acquire_lease("merge_drain")
    if not lease:
        return {"ok": False, "error": "lease_held", "disk": disk}

    merge_revision_id = f"LN7-merge-{int(time.time())}"
    result: Dict[str, Any] = {
        "ok": False,
        "merge_revision_id": merge_revision_id,
        "contributor_ids": contributor_ids,
        "incumbent_id": incumbent_id,
        "dry_run": dry_run,
        "disk": disk,
    }
    try:
        rows = await _fetch_contributor_rows(db_pool, contributor_ids)
        workdir = _merge_workdir(merge_revision_id)
        hf_dirs: List[Dict[str, Any]] = []
        materialize_results: Dict[str, Any] = {}
        for cid in contributor_ids:
            row = rows.get(cid) or {}
            adapter_uri = str(row.get("adapter_uri") or "")
            if not adapter_uri:
                result["error"] = f"missing_adapter_uri:{cid}"
                release_lease("merge_drain", lease)
                return result
            hf_out = str(workdir / "hf" / cid)
            mres = materialize_peft_to_hf(adapter_uri, hf_out, dry_run=dry_run)
            materialize_results[cid] = mres
            if not mres.get("ok"):
                result["error"] = f"materialize_failed:{cid}"
                result["materialize"] = materialize_results
                release_lease("merge_drain", lease)
                return result
            hf_dirs.append({"path": hf_out, "weight": 1.0})
        result["materialize"] = materialize_results

        yaml_text = mergekit_yaml_dare_ties(hf_dirs, density=density)
        merged_out = str(workdir / "merged")
        mk_res = run_mergekit(yaml_text, merged_out, dry_run=dry_run)
        result["mergekit"] = mk_res
        if not mk_res.get("ok"):
            result["error"] = "mergekit_failed"
            release_lease("merge_drain", lease)
            return result

        # QUANTUM-CRYSTAL-ARCH — register_revision's ON CONFLICT overwrites
        # harness_config_json/base_checkpoint from EXCLUDED every call, so the
        # same harness_config must be replayed on every subsequent status update
        # or the merge_of/mergekit_pin provenance is silently wiped.
        harness_config = {
            "merge_of": contributor_ids,
            "merge_method": "dare_ties",
            "density": density,
            "mergekit_pin": PINNED_MERGEKIT,
        }
        await register_revision(
            db_pool,
            revision_id=merge_revision_id,
            base_checkpoint=BASE_MODEL,
            quantization="q5_K_M",
            harness_config=harness_config,
            notes=notes or f"dare_ties merge of {len(contributor_ids)} contributors",
            status="draft",
        )

        gate = await abort_gate(
            db_pool,
            merge_revision_id=merge_revision_id,
            contributor_ids=contributor_ids,
            incumbent_id=incumbent_id,
        )
        result["abort_gate"] = gate

        if gate.get("accept"):
            gguf_out = str(workdir / f"{merge_revision_id}.gguf")
            gguf_res = convert_to_gguf(merged_out, gguf_out, dry_run=dry_run)
            result["gguf"] = gguf_res
            transfer_res: Dict[str, Any] = {}
            if gguf_res.get("ok"):
                transfer_res = transfer_gguf_to_orange(gguf_out, merge_revision_id, dry_run=dry_run)
            result["transfer"] = transfer_res
            accepted = bool(gguf_res.get("ok") and (dry_run or transfer_res.get("ok")))
            if accepted:
                prune_res = await prune_micro_experts(
                    db_pool, contributor_ids, merge_revision_id=merge_revision_id
                )
                result["prune"] = prune_res
                await register_revision(
                    db_pool,
                    revision_id=merge_revision_id,
                    base_checkpoint=BASE_MODEL,
                    quantization="q5_K_M",
                    harness_config=harness_config,
                    status="active" if not dry_run else "draft",
                    notes=notes or f"dare_ties merge accepted ({len(contributor_ids)} contributors)",
                )
            result["ok"] = accepted
        else:
            await register_revision(
                db_pool,
                revision_id=merge_revision_id,
                base_checkpoint=BASE_MODEL,
                quantization="q5_K_M",
                harness_config=harness_config,
                status="rejected",
                notes=f"abort_gate rejected: {gate.get('reason')}",
            )
            result["ok"] = True  # orchestration succeeded; merge correctly rejected
            result["accepted"] = False
    except Exception as e:
        logger.exception("run_merge_drain failed: %s", e)
        result["error"] = str(e)
        await notify_flywheel_anomaly(
            "merge_drain_fail", {"merge_revision_id": merge_revision_id, "error": str(e)}, db_pool=db_pool
        )
    finally:
        release_lease("merge_drain", lease)

    if db_pool:
        try:
            from app.services.ln7_outcome_envelope import cross_loop_attribution, write_envelope

            await write_envelope(
                db_pool,
                loop_name="merge_drain",
                event_kind="merge_drain",
                revision_id=merge_revision_id,
                source_node="green",
                attribution={
                    **cross_loop_attribution(None, revision_id=merge_revision_id),
                    "contributor_ids": contributor_ids,
                    "incumbent_id": incumbent_id,
                },
                metrics={k: v for k, v in result.items() if k not in ("materialize",)},
                confounded=False,
            )
        except Exception:
            pass
    return result
